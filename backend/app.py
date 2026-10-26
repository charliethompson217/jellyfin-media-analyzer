import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from datetime import datetime, timezone

import requests
from flask import Flask, abort, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from media import download_url, normalize_items, number
from settings import (
    API_KEY, CACHE_FILE, CACHE_MAX_AGE, JELLYFIN_MOVIES_DIR, JELLYFIN_TVSHOWS_DIR,
    JELLYFIN_URL, JELLYFIN_USER_ID, MOVIES_LIBRARY_DIR, PORT, SCAN_TIMEOUT, TVSHOWS_LIBRARY_DIR,
)

app = Flask(__name__)
SCAN_LOCK = threading.Lock()
CACHE_VERSION = 2
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class JellyfinError(Exception):
    """Intentionally contains only safe, fixed public messages."""


def jellyfin_get(path, params, session, deadline):
    """Use header-only credentials; never follow redirects with a server token."""
    headers = [{'Authorization': f'MediaBrowser Token="{API_KEY}"'}, {'X-Emby-Token': API_KEY}]
    try:
        for index, auth in enumerate(headers):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JellyfinError('The Jellyfin scan exceeded its time limit. Please try again.')
            with session.get(
                f'{JELLYFIN_URL}/{path}', params=params, headers=auth,
                timeout=(min(5, remaining), min(30, remaining)),
                allow_redirects=False, stream=True,
            ) as response:
                if response.status_code == 401 and index == 0:
                    continue
                if response.status_code in (401, 403):
                    raise JellyfinError('Jellyfin rejected authentication. Check the server API key and permissions.')
                if not 200 <= response.status_code < 300:
                    raise JellyfinError('Jellyfin could not complete the request. Check the server and try again.')
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    if time.monotonic() >= deadline:
                        raise JellyfinError('The Jellyfin scan exceeded its time limit. Please try again.')
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise JellyfinError('Jellyfin returned an unexpectedly large response.')
                    chunks.append(chunk)
                return json.loads(b''.join(chunks))
    except requests.Timeout:
        raise JellyfinError('Jellyfin timed out. Please try again.') from None
    except requests.RequestException:
        # Exception text can include URLs, query credentials, and response details.
        raise JellyfinError('Unable to connect to Jellyfin. Check the server configuration.') from None
    except (ValueError, UnicodeError):
        raise JellyfinError('Jellyfin returned an invalid response.') from None


def fetch_all_items(session, deadline):
    items, start_index = [], 0
    while True:
        params = {
            'IncludeItemTypes': 'Movie,Episode', 'Recursive': 'true',
            'Fields': 'MediaSources,MediaStreams,Path,SeriesName,SeasonName,IndexNumber',
            'CollapseBoxSetItems': 'false', 'SortBy': 'SortName', 'SortOrder': 'Ascending',
            'StartIndex': start_index, 'Limit': 500,
        }
        if JELLYFIN_USER_ID:
            params['UserId'] = JELLYFIN_USER_ID
        result = jellyfin_get('Items', params, session, deadline)
        if not isinstance(result, dict) or not isinstance(result.get('Items'), list):
            raise JellyfinError('Jellyfin returned an invalid media list.')
        page = result['Items']
        items.extend(page)
        if len(page) < 500:
            return items
        start_index += len(page)


def cache_identity():
    scope = [JELLYFIN_URL, API_KEY, JELLYFIN_USER_ID, JELLYFIN_MOVIES_DIR, JELLYFIN_TVSHOWS_DIR]
    return hashlib.sha256(json.dumps(scope).encode()).hexdigest()


def read_cache():
    try:
        snapshot = json.loads(Path(CACHE_FILE).read_text(encoding='utf-8'))
        if not isinstance(snapshot, dict) or snapshot.get('version') != CACHE_VERSION:
            return None
        if snapshot.get('identity') != cache_identity() or not isinstance(snapshot.get('data'), list):
            return None
        if not isinstance(snapshot.get('skipped_records'), int) or snapshot['skipped_records'] < 0:
            return None
        scanned_at = datetime.fromisoformat(snapshot['scanned_at'])
        if scanned_at.tzinfo is None:
            return None
        for row in snapshot['data']:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str):
                return None
            if not all(key in row for key in ('name', 'type', 'path', 'video_codec', 'resolution', 'size_mb', 'duration_min')):
                return None
            for key in ('name', 'type', 'video_codec', 'resolution', 'container', 'hdr_info', 'audio_codec',
                        'series_name', 'season_name', 'version_name', 'scan_type', 'color_gamut', 'item_id', 'source_id'):
                if not isinstance(row.get(key), str):
                    return None
            for key in ('size_mb', 'duration_min', 'size_bytes', 'duration_sec', 'frame_rate', 'audio_channels',
                        'video_bitrate_kbps', 'audio_bitrate_kbps', 'audio_sample_rate', 'efficiency_mb_per_hour',
                        'audio_track_count', 'episode_number'):
                if key not in row or (row[key] is not None and number(row[key]) is None):
                    return None
            if row['path'] is not None and not isinstance(row['path'], str):
                return None
            expected_url = download_url(row['path'], [(JELLYFIN_MOVIES_DIR, '/movies/'), (JELLYFIN_TVSHOWS_DIR, '/tv_shows/')])
            if row.get('download_url') != expected_url:
                return None
        return snapshot
    except (OSError, ValueError, TypeError, KeyError):
        return None


def write_cache(snapshot):
    destination = Path(CACHE_FILE)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(snapshot, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def snapshot_response(snapshot, *, stale=False, in_progress=False, error=None):
    response = jsonify(snapshot['data'])  # Keep the existing array API contract.
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Scanned-At'] = snapshot['scanned_at']
    response.headers['X-Cache-Stale'] = str(stale).lower()
    response.headers['X-Scan-In-Progress'] = str(in_progress).lower()
    response.headers['X-Skipped-Records'] = str(snapshot['skipped_records'])
    if error:
        response.headers['X-Refresh-Error'] = error
    return response


@app.after_request
def private_api(response):
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.errorhandler(Exception)
def safe_error(error):
    if isinstance(error, HTTPException):
        return jsonify({'error': error.name}), error.code
    # No exception text or traceback: nested exceptions may hold credentials.
    app.logger.error('An unexpected media API error occurred.')
    return jsonify({'error': 'Unable to complete the request. Please try again.'}), 500


@app.route('/api/media')
def get_media():
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    snapshot = read_cache()
    if snapshot:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(snapshot['scanned_at'])).total_seconds()
        if not refresh and 0 <= age < CACHE_MAX_AGE:
            return snapshot_response(snapshot)
    if not SCAN_LOCK.acquire(blocking=False):
        if snapshot:
            return snapshot_response(snapshot, stale=True, in_progress=True)
        return jsonify({'error': 'A media scan is already running. Please retry shortly.'}), 503, {'Retry-After': '5'}
    lock_handle = None
    try:
        # Protect the snapshot across Gunicorn processes as well as threads.
        Path(CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
        lock_handle = open(f'{CACHE_FILE}.lock', 'a')
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if snapshot:
                return snapshot_response(snapshot, stale=True, in_progress=True)
            return jsonify({'error': 'A media scan is already running. Please retry shortly.'}), 503, {'Retry-After': '5'}
        if not JELLYFIN_URL or not API_KEY:
            raise JellyfinError('Configure the Jellyfin server URL and API key before scanning.')
        with requests.Session() as session:
            items = fetch_all_items(session, time.monotonic() + SCAN_TIMEOUT)
        data, skipped = normalize_items(items, [(JELLYFIN_MOVIES_DIR, '/movies/'), (JELLYFIN_TVSHOWS_DIR, '/tv_shows/')])
        fresh = {
            'version': CACHE_VERSION, 'identity': cache_identity(), 'data': data,
            'scanned_at': datetime.now(timezone.utc).isoformat(), 'skipped_records': skipped,
        }
        try:
            write_cache(fresh)
        except OSError:
            app.logger.warning('Unable to save the media snapshot.')
            return snapshot_response(fresh, error='Results loaded, but the snapshot could not be saved.')
        return snapshot_response(fresh)
    except JellyfinError as error:
        if snapshot:
            return snapshot_response(snapshot, stale=True, error=str(error))
        return jsonify({'error': str(error)}), 502
    except OSError:
        if snapshot:
            return snapshot_response(snapshot, stale=True, error='Unable to access the snapshot storage. Check server permissions.')
        return jsonify({'error': 'Unable to access the snapshot storage. Check server permissions.'}), 500
    finally:
        if lock_handle:
            lock_handle.close()
        SCAN_LOCK.release()


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


def local_download(directory, filename):
    """Development equivalent of the authenticated Nginx media aliases."""
    if not directory:
        abort(404)
    root = Path(directory).resolve()
    target = (root / filename).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        abort(404)
    if target.suffix.lower() in ('.nfo', '.jpg', '.png', '.trickplay'):
        abort(404)
    return send_file(target, as_attachment=True, conditional=True)


@app.route('/movies/<path:filename>')
def movie_download(filename):
    return local_download(MOVIES_LIBRARY_DIR, filename)


@app.route('/tv_shows/<path:filename>')
def episode_download(filename):
    return local_download(TVSHOWS_LIBRARY_DIR, filename)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=PORT, debug=False)
