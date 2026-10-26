import fcntl
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone

import requests
from flask import Flask, abort, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from media import download_url, normalize_items, number
from movie_paths import analyze_movies, DEFAULT_SPELLING_THRESHOLD
from renaming import MovieRenamer, RenameError, revision
from settings import (
    API_KEY, CACHE_FILE, CACHE_MAX_AGE, JELLYFIN_MOVIES_DIR, JELLYFIN_TVSHOWS_DIR,
    JELLYFIN_URL, JELLYFIN_USER_ID, MOVIES_LIBRARY_DIR, PORT, SCAN_TIMEOUT, TVSHOWS_LIBRARY_DIR, ENABLE_RENAMING,
)

app = Flask(__name__)
SCAN_LOCK = threading.Lock()
CACHE_VERSION = 3
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
            # Title, year and episode names are normal DTO properties, not ItemFields.
            # https://typescript-sdk.jellyfin.org/variables/generated-client.ItemFields.html
            'Fields': 'MediaSources,MediaStreams,Path',
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
    scope = [JELLYFIN_URL, API_KEY, JELLYFIN_USER_ID, JELLYFIN_MOVIES_DIR, JELLYFIN_TVSHOWS_DIR, MOVIES_LIBRARY_DIR, TVSHOWS_LIBRARY_DIR]
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
            if 'metadata_title' not in row or (row['metadata_title'] is not None and not isinstance(row['metadata_title'], str)):
                return None
            year = row.get('production_year')
            if 'production_year' not in row or (year is not None and (type(year) is not int or not 1000 <= year <= 9999)):
                return None
            expected_url = download_url(row['path'], [(JELLYFIN_MOVIES_DIR, '/movies/'), (JELLYFIN_TVSHOWS_DIR, '/tv_shows/')])
            if row.get('download_url') != expected_url:
                return None
        return reconcile_renames(snapshot)
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


def reconcile_renames(snapshot):
    if MOVIES_LIBRARY_DIR and JELLYFIN_MOVIES_DIR:
        try:
            return MovieRenamer(CACHE_FILE, MOVIES_LIBRARY_DIR, JELLYFIN_MOVIES_DIR).reconcile(snapshot)
        except (RenameError, OSError, ValueError, KeyError, TypeError):
            app.logger.warning('Unable to reconcile prior movie renames; serving the saved snapshot.')
    return snapshot


@contextmanager
def snapshot_edit_lock():
    if not SCAN_LOCK.acquire(blocking=False):
        raise RenameError('A library scan or rename is running. Please retry shortly.', 503)
    handle = None
    try:
        Path(CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
        handle = open(f'{CACHE_FILE}.lock', 'a')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RenameError('A library scan or rename is running. Please retry shortly.', 503) from None
        yield
    finally:
        if handle:
            handle.close()
        SCAN_LOCK.release()


def snapshot_response(snapshot, *, stale=False, in_progress=False, error=None):
    response = jsonify(snapshot['data'])  # Keep the existing array API contract.
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Scanned-At'] = snapshot['scanned_at']
    response.headers['X-Snapshot-Revision'] = revision(snapshot)
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


@app.errorhandler(RenameError)
def rename_error(error):
    return jsonify({'error': str(error)}), error.status


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
            'revision': uuid.uuid4().hex,
        }
        fresh = reconcile_renames(fresh)
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


@app.get('/api/movie-paths')
def check_movie_paths():
    try:
        threshold = float(request.args.get('spelling_threshold', DEFAULT_SPELLING_THRESHOLD))
    except (ValueError, TypeError):
        return jsonify({'error': 'Spelling threshold must be a number from 0 to 100.'}), 400
    if not math.isfinite(threshold) or not 0 <= threshold <= 100:
        return jsonify({'error': 'Spelling threshold must be a number from 0 to 100.'}), 400
    snapshot = read_cache()
    if snapshot is None:
        return jsonify({'error': 'Reload the media library before running a movie path check.'}), 409
    report = analyze_movies(snapshot['data'], threshold)
    report['scanned_at'] = snapshot['scanned_at']
    report['snapshot_revision'] = revision(snapshot)
    report['rename_enabled'] = ENABLE_RENAMING
    return jsonify(report)


def rename_payload():
    if not ENABLE_RENAMING:
        raise RenameError('Movie renaming is disabled. Set ENABLE_RENAMING=true on the server to enable it.', 403)
    if request.headers.get('X-Media-Analyzer-Action') != 'rename' or request.headers.get('Sec-Fetch-Site') == 'cross-site':
        raise RenameError('The rename request did not pass the same-origin action check.', 403)
    request.max_content_length = 16384
    if not request.is_json:
        raise RenameError('Rename requests must use JSON.', 415)
    body = request.get_json()
    if not isinstance(body, dict):
        raise RenameError('Invalid rename request.', 400)
    return body


@app.post('/api/movie-renames/preview')
def preview_movie_rename():
    body = rename_payload()
    if not isinstance(body.get('row_id'), str):
        raise RenameError('Select a movie from the path report.', 400)
    try:
        with snapshot_edit_lock():
            snapshot = read_cache()
            if snapshot is None or body.get('snapshot_revision') != revision(snapshot):
                raise RenameError('The library changed. Refresh the path report before previewing a rename.')
            return jsonify(MovieRenamer(CACHE_FILE, MOVIES_LIBRARY_DIR, JELLYFIN_MOVIES_DIR).preview(snapshot, body['row_id'], body.get('prefix')))
    except PermissionError:
        raise RenameError('The service account cannot read the movie folder or rename state. Check host directory permissions.', 403) from None
    except OSError:
        raise RenameError('The movie folder is unavailable. Check the host path mapping and filesystem permissions.') from None


@app.post('/api/movie-renames/apply')
def apply_movie_rename():
    body = rename_payload()
    if not isinstance(body.get('token'), str):
        raise RenameError('Preview the rename before applying it.', 400)
    try:
        with snapshot_edit_lock():
            snapshot = read_cache()
            if snapshot is None:
                raise RenameError('Reload the library and preview the rename again.')
            updated, result = MovieRenamer(CACHE_FILE, MOVIES_LIBRARY_DIR, JELLYFIN_MOVIES_DIR).apply(snapshot, body['token'])
            try:
                write_cache(updated)
            except OSError:
                result['warning'] = 'The files were renamed, but the snapshot could not be saved. Reload the library to reconcile its paths.'
            result['snapshot_revision'] = revision(updated)
            return jsonify(result)
    except PermissionError:
        raise RenameError('The service account needs write access to the movie folder and its parent directory.', 403) from None
    except OSError:
        raise RenameError('Unable to start the rename. Check filesystem access and preview again.') from None


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
