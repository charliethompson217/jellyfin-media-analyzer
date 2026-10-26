"""Regression tests run without a live Jellyfin server or real credentials."""
import copy
from datetime import datetime, timedelta, timezone
import io
import json
import logging
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import requests
import app as api
from media import download_url, normalize_items

SECRET = 'regression-secret-DO-NOT-EXPOSE'


def response(status=200, body=None):
    result = MagicMock()
    result.__enter__.return_value = result
    result.status_code = status
    result.iter_content.return_value = [json.dumps(body if body is not None else {'Items': []}).encode()]
    return result


def movie():
    return {'Id': 'item1', 'Name': 'Movie', 'Type': 'Movie', 'LocationType': 'FileSystem',
            'RunTimeTicks': 3600 * 10_000_000, 'MediaSources': [
                {'Id': 'source1', 'Path': '/media/movies/Audit #1?.mkv', 'Size': 1024**3,
                 'RunTimeTicks': 3600 * 10_000_000,
                 'MediaStreams': [{'Type': 'Video', 'Codec': 'hevc', 'Width': 1920, 'Height': 1080},
                                  {'Type': 'Audio', 'Codec': 'aac', 'Channels': 2, 'BitRate': 128000}]}]}


class APITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name) / 'cache.json'
        self.config = patch.multiple(api, CACHE_FILE=str(self.cache), API_KEY=SECRET,
                                     JELLYFIN_URL='https://jellyfin.invalid', JELLYFIN_USER_ID='',
                                     JELLYFIN_MOVIES_DIR='/media/movies', JELLYFIN_TVSHOWS_DIR='/media/tv',
                                     SCAN_LOCK=threading.Lock())
        self.config.start()
        self.addCleanup(self.config.stop)
        self.client = api.app.test_client()
        self.logs = io.StringIO()
        handler = logging.StreamHandler(self.logs)
        api.app.logger.addHandler(handler)
        self.addCleanup(api.app.logger.removeHandler, handler)

    def scan(self, items=None):
        with patch.object(api, 'fetch_all_items', return_value=items if items is not None else [movie()]):
            return self.client.get('/api/media?refresh=true')

    def assert_secret_absent(self, result):
        self.assertNotIn(SECRET, result.get_data(as_text=True))
        self.assertNotIn(SECRET, str(result.headers))
        self.assertNotIn(SECRET, self.logs.getvalue())
        self.assertEqual(result.headers['Cache-Control'], 'no-store')

    def test_auth_failure_never_exposes_key(self):
        session = MagicMock()
        session.get.side_effect = [response(401), response(403)]
        with patch.object(api.requests, 'Session') as factory:
            factory.return_value.__enter__.return_value = session
            result = self.client.get('/api/media?refresh=true')
        self.assertEqual(result.status_code, 502)
        self.assert_secret_absent(result)
        for call in session.get.call_args_list:
            self.assertNotIn(SECRET, call.args[0])
            self.assertNotIn('api_key', call.kwargs['params'])
            self.assertFalse(call.kwargs['allow_redirects'])
            self.assertGreater(call.kwargs['timeout'][0], 0)
        self.assertIn('Authorization', session.get.call_args_list[0].kwargs['headers'])
        self.assertEqual(session.get.call_args_list[1].kwargs['headers'], {'X-Emby-Token': SECRET})

    def test_header_fallback_succeeds(self):
        session = MagicMock()
        session.get.side_effect = [response(401), response(200, {'Items': []})]
        self.assertEqual(api.jellyfin_get('Items', {}, session, time.monotonic() + 30), {'Items': []})
        self.assertEqual(session.get.call_count, 2)

    def test_transport_exceptions_are_redacted_including_nested_causes(self):
        for error in [requests.ConnectionError(f'https://example.invalid/?api_key={SECRET}'),
                      requests.Timeout(SECRET), requests.HTTPError(SECRET)]:
            with self.subTest(error=type(error).__name__), patch.object(api.requests, 'Session') as factory:
                factory.return_value.__enter__.return_value.get.side_effect = error
                result = self.client.get('/api/media?refresh=true')
                self.assertEqual(result.status_code, 502)
                self.assert_secret_absent(result)

    def test_unexpected_error_is_also_safe(self):
        with patch.object(api, 'fetch_all_items', side_effect=RuntimeError(SECRET)):
            result = self.client.get('/api/media?refresh=true')
        self.assertEqual(result.status_code, 500)
        self.assert_secret_absent(result)

    def test_redirect_is_rejected_without_following_it(self):
        session = MagicMock()
        session.get.return_value = response(302)
        with self.assertRaises(api.JellyfinError):
            api.jellyfin_get('Items', {}, session, time.monotonic() + 30)
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])

    def test_invalid_json_and_deadline_are_safe(self):
        session = MagicMock()
        session.get.return_value = response()
        session.get.return_value.iter_content.return_value = [SECRET.encode()]
        with self.assertRaises(api.JellyfinError) as error:
            api.jellyfin_get('Items', {}, session, time.monotonic() + 30)
        self.assertNotIn(SECRET, str(error.exception))
        with self.assertRaises(api.JellyfinError):
            api.jellyfin_get('Items', {}, session, time.monotonic() - 1)

    def test_pagination_and_scope(self):
        pages = [{'Items': [{'Id': str(i)} for i in range(500)]}, {'Items': [{'Id': 'last'}]}]
        with patch.object(api, 'jellyfin_get', side_effect=pages) as fetch:
            items = api.fetch_all_items(MagicMock(), time.monotonic() + 30)
            self.assertEqual(len(items), 501)
            self.assertEqual(fetch.call_args_list[1].args[1]['StartIndex'], 500)
            self.assertEqual(fetch.call_args_list[0].args[1]['Fields'], 'MediaSources,MediaStreams,Path')
            self.assertNotIn('UserId', fetch.call_args_list[0].args[1])
        with patch.object(api, 'JELLYFIN_USER_ID', 'configured-user'), patch.object(api, 'jellyfin_get', return_value={'Items': []}) as fetch:
            api.fetch_all_items(MagicMock(), time.monotonic() + 30)
            self.assertEqual(fetch.call_args.args[1]['UserId'], 'configured-user')

    def test_null_metadata_keeps_valid_files_and_counts_unusable_records(self):
        item = movie()
        source = item['MediaSources'][0]
        source.update(Path=None, RunTimeTicks=None, MediaStreams=[{'Type': 'Video', 'Codec': None},
                      {'Type': 'Audio', 'Codec': None, 'BitRate': None, 'Channels': None}])
        item['RunTimeTicks'] = None
        result = self.scan([movie(), item, {'Type': 'Movie', 'LocationType': 'FileSystem', 'MediaSources': None}])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json), 2)
        self.assertIsNone(result.json[1]['duration_min'])
        self.assertIsNone(result.json[1]['audio_bitrate_kbps'])
        self.assertEqual(result.json[1]['hdr_info'], 'Unknown')
        self.assertEqual(result.headers['X-Skipped-Records'], '1')

    def test_versions_have_their_own_runtime_and_identity(self):
        item = movie()
        second = copy.deepcopy(item['MediaSources'][0])
        second.update(Id='extended', Path='/media/movies/extended.mkv', RunTimeTicks=7200 * 10_000_000)
        item['MediaSources'].append(second)
        result = self.scan([item])
        self.assertEqual([r['duration_min'] for r in result.json], [60, 120])
        self.assertNotEqual(result.json[0]['id'], result.json[1]['id'])
        self.assertEqual(result.json[0]['download_url'], '/movies/Audit%20%231%3F.mkv')

    def test_missing_paths_are_not_deduplicated(self):
        items = [movie(), movie()]
        for i, item in enumerate(items):
            item['Id'] = str(i)
            del item['MediaSources'][0]['Path']
        rows, _ = normalize_items(items, [])
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]['download_url'])
        self.assertNotEqual(rows[0]['id'], rows[1]['id'])

    def test_corrupt_legacy_and_wrong_shape_caches_recover(self):
        for content in ['{truncated', '[]', '{"version":2,"data":{}}']:
            with self.subTest(content=content):
                self.cache.write_text(content)
                self.assertEqual(self.scan().status_code, 200)
                self.assertIsNotNone(api.read_cache())

    def test_fresh_cache_does_not_scan_and_rejects_changed_scope(self):
        self.scan()
        with patch.object(api, 'fetch_all_items') as fetch:
            result = self.client.get('/api/media')
            self.assertEqual(result.status_code, 200)
            fetch.assert_not_called()
        with patch.object(api, 'JELLYFIN_USER_ID', 'another-user'):
            self.assertIsNone(api.read_cache())
        self.assertNotIn(SECRET, self.cache.read_text())

    def test_cache_rejects_invalid_rows_and_untrusted_download_urls(self):
        self.scan()
        valid = api.read_cache()
        for key, value in [('name', {}), ('series_name', {}), ('duration_min', 'bad'), ('download_url', 'javascript:alert(1)')]:
            invalid = copy.deepcopy(valid)
            invalid['data'][0][key] = value
            api.write_cache(invalid)
            self.assertIsNone(api.read_cache())

    def test_file_lock_prevents_a_second_process_scan(self):
        self.scan()
        with open(str(self.cache) + '.lock', 'a') as handle:
            api.fcntl.flock(handle, api.fcntl.LOCK_EX | api.fcntl.LOCK_NB)
            with patch.object(api, 'fetch_all_items') as fetch:
                result = self.client.get('/api/media?refresh=true')
                self.assertEqual(result.headers['X-Scan-In-Progress'], 'true')
                fetch.assert_not_called()

    def test_health_does_not_contact_jellyfin(self):
        with patch.object(api, 'fetch_all_items') as fetch:
            self.assertEqual(self.client.get('/api/health').json, {'status': 'ok'})
            fetch.assert_not_called()

    def test_movie_path_endpoint_uses_snapshot_metadata_without_refetching(self):
        item = movie()
        item.update(Name='The Matrix', ProductionYear=1999)
        item['MediaSources'][0]['Path'] = '/media/movies/The Matrix (1999)/The Matrix (1999) - [1080p].mkv'
        scan = self.scan([item])
        self.assertEqual(scan.json[0]['production_year'], 1999)
        self.assertEqual(scan.json[0]['metadata_title'], 'The Matrix')
        with patch.object(api, 'fetch_all_items') as fetch:
            result = self.client.get('/api/movie-paths?spelling_threshold=95')
            fetch.assert_not_called()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['scanned_at'], scan.headers['X-Scanned-At'])
        self.assertEqual(result.json['spelling_threshold'], 95)
        self.assertEqual(result.json['summary']['checked'], 1)
        self.assertEqual(result.json['summary']['needs_review'], 0)
        self.assertEqual(result.json['rows'][0]['expected_component'], 'The Matrix (1999)')
        self.assert_secret_absent(result)

    def test_movie_path_endpoint_requires_snapshot_and_valid_threshold(self):
        self.assertEqual(self.client.get('/api/movie-paths').status_code, 409)
        for value in ['NaN', 'inf', '-1', '101', SECRET, '']:
            with self.subTest(value=value):
                result = self.client.get('/api/movie-paths', query_string={'spelling_threshold': value})
                self.assertEqual(result.status_code, 400)
                self.assert_secret_absent(result)

    def test_old_cache_schema_requires_refresh_for_year_metadata(self):
        self.scan()
        snapshot = api.read_cache()
        snapshot['version'] = 2
        api.write_cache(snapshot)
        self.assertEqual(self.client.get('/api/movie-paths').status_code, 409)

    def test_movie_path_check_has_no_mutation_endpoint(self):
        self.assertEqual(self.client.post('/api/movie-paths', json={'path': '/tmp/file', 'rename': 'new'}).status_code, 405)

    def test_refresh_failure_preserves_snapshot(self):
        expected = self.scan().json
        before = self.cache.read_bytes()
        with patch.object(api, 'fetch_all_items', side_effect=api.JellyfinError('Jellyfin timed out. Please try again.')):
            result = self.client.get('/api/media?refresh=true')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json, expected)
        self.assertEqual(result.headers['X-Cache-Stale'], 'true')
        self.assertIn('timed out', result.headers['X-Refresh-Error'])
        self.assertEqual(self.cache.read_bytes(), before)

    def test_expired_snapshot_triggers_scan(self):
        self.scan()
        snapshot = api.read_cache()
        snapshot['scanned_at'] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        api.write_cache(snapshot)
        with patch.object(api, 'fetch_all_items', return_value=[]) as fetch:
            self.assertEqual(self.client.get('/api/media').json, [])
            fetch.assert_called_once()

    def test_atomic_write_failure_keeps_previous_file(self):
        self.scan()
        before = self.cache.read_bytes()
        with patch.object(api.os, 'replace', side_effect=OSError(SECRET)):
            result = self.scan([])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.cache.read_bytes(), before)
        self.assert_secret_absent(result)
        self.assertEqual(sorted(p.name for p in self.cache.parent.iterdir()), ['cache.json', 'cache.json.lock'])

    def test_concurrent_scan_serves_snapshot_or_retry(self):
        api.SCAN_LOCK.acquire()
        try:
            result = self.client.get('/api/media?refresh=true')
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.headers['Retry-After'], '5')
        finally:
            api.SCAN_LOCK.release()
        self.scan()
        api.SCAN_LOCK.acquire()
        try:
            result = self.client.get('/api/media?refresh=true')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers['X-Scan-In-Progress'], 'true')
        finally:
            api.SCAN_LOCK.release()

    def test_local_download_bounds_and_special_characters(self):
        library = Path(self.directory.name) / 'movies'
        library.mkdir()
        (library / 'Audit #1?.mkv').write_bytes(b'media')
        (library / 'secret-link.mkv').symlink_to(self.cache)
        self.cache.write_text('private')
        with patch.object(api, 'MOVIES_LIBRARY_DIR', str(library)):
            with self.client.get('/movies/Audit%20%231%3F.mkv') as result:
                self.assertEqual(result.data, b'media')
            self.assertEqual(self.client.get('/movies/../cache.json').status_code, 404)
            self.assertEqual(self.client.get('/movies/secret-link.mkv').status_code, 404)
        self.assertIsNone(download_url('/media/movies-other/file.mkv', [('/media/movies', '/movies/')]))
        self.assertIsNone(download_url('/media/movies/../private.mkv', [('/media/movies', '/movies/')]))

    def test_cors_is_not_open(self):
        self.scan()
        result = self.client.get('/api/media', headers={'Origin': 'https://unrelated.invalid'})
        self.assertNotIn('Access-Control-Allow-Origin', result.headers)


if __name__ == '__main__':
    unittest.main()
