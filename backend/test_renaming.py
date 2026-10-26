"""Filesystem transaction tests use only disposable temporary movie folders."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import app as api
from media import normalize_items
import renaming
from renaming import MovieRenamer, RenameError

OLD = 'Pulp Fiction (1995)'
NEW = 'Pulp Fiction (1994)'
TAGS = ['Bluray-1080p-1301kbps-H.264', 'Bluray-1080p-29057kbps-H.264', 'Bluray-2160p-19857kbps-H.265', 'Bluray-2160p-6761kbps-H.265']
HEADERS = {'X-Media-Analyzer-Action': 'rename'}


class RenamingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'host/movies'
        self.folder = self.root / OLD
        self.folder.mkdir(parents=True)
        self.cache = self.base / 'state/cache.json'
        self.remote = '/home/jellyfin/media/movies'
        self.names = ['backdrop.jpg', 'folder.jpg', 'landscape.jpg', 'logo.png', 'movie.nfo']
        self.videos = []
        for index, tag in enumerate(TAGS):
            stem = f'{OLD} - [{tag}]'
            video = stem + ('.mp4' if index == 0 else '.mkv')
            self.videos.append(video)
            self.names += [video, stem + '.nfo', stem + '.eng.forced.srt', stem + '.srt']
        for index, name in enumerate(self.names):
            (self.folder / name).write_bytes(f'file contents {index}'.encode())
        item = {'Id': 'pulp', 'Name': 'Pulp Fiction', 'ProductionYear': 1994, 'Type': 'Movie', 'LocationType': 'FileSystem', 'MediaSources': [
            {'Id': str(index), 'Path': self.remote + '/' + OLD + '/' + name, 'Name': tag,
             'Size': (self.folder / name).stat().st_size} for index, (name, tag) in enumerate(zip(self.videos, TAGS))
        ]}
        self.item = item
        self.rows, _ = normalize_items([item], [(self.remote, '/movies/')])
        self.snapshot = {'data': self.rows, 'scanned_at': datetime.now(timezone.utc).isoformat(), 'revision': 'initial'}
        self.renamer = MovieRenamer(str(self.cache), str(self.root), self.remote)
        self.before = self.contents(self.folder)

    def contents(self, folder):
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir() if path.is_file()}

    def preview(self, prefix=None):
        return self.renamer.preview(self.snapshot, self.rows[0]['id'], prefix)

    def configure_api(self, enabled=True):
        config = patch.multiple(api, CACHE_FILE=str(self.cache), API_KEY='test-secret-no-exposure',
                                JELLYFIN_URL='https://jellyfin.invalid', JELLYFIN_USER_ID='',
                                MOVIES_LIBRARY_DIR=str(self.root), TVSHOWS_LIBRARY_DIR='',
                                JELLYFIN_MOVIES_DIR=self.remote, JELLYFIN_TVSHOWS_DIR='',
                                ENABLE_RENAMING=enabled, SCAN_LOCK=threading.Lock())
        config.start()
        self.addCleanup(config.stop)
        self.snapshot.update(version=api.CACHE_VERSION, identity=api.cache_identity(), skipped_records=0)
        api.write_cache(self.snapshot)
        return api.app.test_client()

    def api_preview(self, client, **fields):
        return client.post('/api/movie-renames/preview', headers=HEADERS, json={
            'row_id': self.rows[0]['id'], 'snapshot_revision': self.snapshot['revision'], **fields})

    def test_preview_covers_all_versions_and_hidden_sidecars_without_changing_files(self):
        plan = self.preview()
        self.assertEqual(plan['prefix'], NEW)
        self.assertEqual(plan['video_count'], 4)
        self.assertEqual(plan['changed_filenames'], 16)
        self.assertEqual(len(plan['files']), len(self.names))
        self.assertEqual(plan['source_directory'], str(self.folder.resolve()))
        for entry in plan['files']:
            if entry['from'].startswith(OLD):
                self.assertEqual(entry['to'], NEW + entry['from'][len(OLD):])
            else:
                self.assertEqual(entry['to'], entry['from'])
        self.assertEqual(self.contents(self.folder), self.before)
        self.assertFalse((self.root / NEW).exists())

    def test_apply_renames_entire_folder_preserves_bytes_and_updates_all_cached_paths(self):
        plan = self.preview()
        updated, result = self.renamer.apply(self.snapshot, plan['token'])
        new_folder = self.root / NEW
        self.assertFalse(self.folder.exists())
        expected = {NEW + name[len(OLD):] if name.startswith(OLD) else name: value for name, value in self.before.items()}
        self.assertEqual(self.contents(new_folder), expected)
        self.assertEqual(result['video_count'], 4)
        self.assertEqual(result['changed_filenames'], 16)
        self.assertEqual(updated['scanned_at'], self.snapshot['scanned_at'])
        self.assertNotEqual(updated['revision'], self.snapshot['revision'])
        for row in updated['data']:
            self.assertIn('/' + NEW + '/', row['path'])
            self.assertIn('Pulp%20Fiction%20%281994%29', row['download_url'])
        journal = json.loads(next(self.renamer.state.glob('*.json')).read_text())
        self.assertEqual(journal['status'], 'completed')
        self.assertEqual(journal['completed_steps'], len(journal['operations']))

    def test_manual_prefix_and_language_flags_are_preserved_exactly(self):
        custom = 'Léon: 日本語 & Friends (2001)'
        updated, _ = self.renamer.apply(self.snapshot, self.preview(custom)['token'])
        for name in self.names:
            expected = custom + name[len(OLD):] if name.startswith(OLD) else name
            self.assertTrue((self.root / custom / expected).is_file())
        self.assertEqual(len(updated['data']), 4)

    def test_generic_assets_and_nested_extras_are_not_deleted_or_rewritten(self):
        extras = self.folder / 'extras'
        extras.mkdir()
        (extras / 'Interview.txt').write_text('keep this')
        (self.folder / 'README.txt').write_text('keep too')
        self.renamer.apply(self.snapshot, self.preview()['token'])
        self.assertEqual((self.root / NEW / 'extras/Interview.txt').read_text(), 'keep this')
        self.assertEqual((self.root / NEW / 'README.txt').read_text(), 'keep too')
        self.assertTrue((self.root / NEW / 'movie.nfo').exists())

    def test_source_change_invalidates_preview(self):
        token = self.preview()['token']
        (self.folder / 'movie.nfo').write_text('updated by Jellyfin')
        with self.assertRaisesRegex(RenameError, 'changed after preview'):
            self.renamer.apply(self.snapshot, token)
        self.assertTrue(self.folder.exists())
        self.assertFalse((self.root / NEW).exists())

    def test_changed_snapshot_invalidates_preview(self):
        token = self.preview()['token']
        changed = {**self.snapshot, 'revision': 'new-scan'}
        with self.assertRaisesRegex(RenameError, 'changed after preview'):
            self.renamer.apply(changed, token)

    def test_target_collision_does_not_overwrite_even_an_empty_directory(self):
        (self.root / NEW).mkdir()
        with self.assertRaisesRegex(RenameError, 'already uses'):
            self.preview()
        self.assertEqual(self.contents(self.folder), self.before)
        self.assertEqual(list((self.root / NEW).iterdir()), [])

    def test_untagged_versions_with_colliding_names_are_blocked(self):
        (self.folder / 'Other title.mkv').write_bytes(b'other video')
        (self.folder / 'Yet another title.mkv').write_bytes(b'another video')
        with self.assertRaisesRegex(RenameError, 'Two files would have the same name'):
            self.preview()

    def test_unassociated_subtitles_block_multi_version_renames(self):
        (self.folder / 'english.srt').write_text('which version?')
        with self.assertRaisesRegex(RenameError, 'Cannot determine which movie version'):
            self.preview()
        self.assertTrue(self.folder.exists())

    def test_traversal_control_characters_and_empty_prefix_are_rejected(self):
        for prefix in ['', '.', '..', '../outside', '/tmp/other', 'bad\\name', 'bad\nname', ' leading', 'trailing ', '.media-analyzer-rename-hidden']:
            with self.subTest(prefix=prefix), self.assertRaises(RenameError):
                self.preview(prefix)
        self.assertEqual(self.contents(self.folder), self.before)

    def test_source_symlinks_and_paths_outside_library_are_rejected(self):
        (self.folder / 'linked.nfo').symlink_to(self.base / 'private')
        with self.assertRaisesRegex(RenameError, 'symlinks'):
            self.preview()
        (self.folder / 'linked.nfo').unlink()
        row = {**self.rows[0], 'path': '/etc/private/movie.mkv'}
        with self.assertRaises(RenameError):
            self.renamer.preview({**self.snapshot, 'data': [row]}, row['id'])
        real = self.root / 'real-folder'
        self.folder.rename(real)
        self.folder.symlink_to(real, target_is_directory=True)
        with self.assertRaises(OSError):
            self.preview()

    def test_library_root_and_mixed_movie_folders_cannot_be_renamed(self):
        direct = {**self.rows[0], 'path': self.remote + '/movie.mkv'}
        with self.assertRaisesRegex(RenameError, 'library root'):
            self.renamer.preview({**self.snapshot, 'data': [direct]}, direct['id'])
        different = {**self.rows[1], 'item_id': 'other', 'metadata_title': 'Different movie'}
        with self.assertRaisesRegex(RenameError, 'multiple movie identities'):
            self.renamer.preview({**self.snapshot, 'data': [self.rows[0], different]}, self.rows[0]['id'])

    def test_case_only_directory_and_prefix_rename(self):
        custom = OLD.lower()
        self.renamer.apply(self.snapshot, self.preview(custom)['token'])
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), [custom])
        self.assertTrue(all(not name.startswith(OLD) for name in self.contents(self.root / custom)))

    def test_mid_transaction_failure_rolls_back_all_names_and_contents(self):
        original = renaming.rename_noreplace
        calls = 0
        def fail_once(*args):
            nonlocal calls
            calls += 1
            if calls == 8:
                raise PermissionError('failure injected')
            return original(*args)
        token = self.preview()['token']
        with patch.object(renaming, 'rename_noreplace', side_effect=fail_once):
            with self.assertRaisesRegex(RenameError, 'was rolled back'):
                self.renamer.apply(self.snapshot, token)
        self.assertEqual(self.contents(self.folder), self.before)
        self.assertFalse((self.root / NEW).exists())
        self.assertEqual(json.loads(next(self.renamer.state.glob('*.json')).read_text())['status'], 'rolled_back')

    def test_destination_created_during_apply_is_not_overwritten(self):
        original = renaming.rename_noreplace
        def add_collision(source_fd, source, target_fd, target):
            if source.startswith(renaming.STAGE_PREFIX) and target == NEW and source_fd == target_fd:
                (self.root / NEW).mkdir()
            return original(source_fd, source, target_fd, target)
        token = self.preview()['token']
        with patch.object(renaming, 'rename_noreplace', side_effect=add_collision):
            with self.assertRaisesRegex(RenameError, 'was rolled back'):
                self.renamer.apply(self.snapshot, token)
        self.assertEqual(self.contents(self.folder), self.before)
        self.assertEqual(list((self.root / NEW).iterdir()), [])

    def test_existing_correct_folder_still_renames_its_files(self):
        self.folder.rename(self.root / NEW)
        self.folder = self.root / NEW
        for row in self.snapshot['data']:
            row['path'] = row['path'].replace('/' + OLD + '/', '/' + NEW + '/')
        plan = self.preview()
        self.assertFalse(plan['folder_changed'])
        self.assertEqual(plan['changed_filenames'], 16)
        self.renamer.apply(self.snapshot, plan['token'])
        self.assertTrue((self.folder / (NEW + ' - [' + TAGS[0] + '].mp4')).exists())

    def test_edition_suffix_is_preserved_as_a_version_tag(self):
        old_name = OLD + ' Extended.mkv'
        (self.folder / old_name).write_bytes(b'extended movie')
        (self.folder / (OLD + ' Extended.eng.srt')).write_bytes(b'English')
        plan = self.preview()
        by_old = {entry['from']: entry['to'] for entry in plan['files']}
        self.assertEqual(by_old[old_name], NEW + ' - [Extended].mkv')
        self.assertEqual(by_old[OLD + ' Extended.eng.srt'], NEW + ' - [Extended].eng.srt')

    def test_pending_journal_blocks_further_changes(self):
        self.preview()
        (self.renamer.state / 'pending.json').write_text('{"status":"pending"}')
        with self.assertRaisesRegex(RenameError, 'incomplete rename'):
            self.preview()

    def test_tampered_and_expired_preview_tokens_are_rejected(self):
        token = self.preview()['token']
        with self.assertRaises(RenameError):
            self.renamer.apply(self.snapshot, token + 'tampered')
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp', return_value=int(time.time()) + 601):
            with self.assertRaisesRegex(RenameError, 'expired'):
                self.renamer.apply(self.snapshot, token)
        self.assertEqual(self.contents(self.folder), self.before)

    def test_reconcile_handles_multiple_renames_before_jellyfin_catches_up(self):
        original = copy.deepcopy(self.snapshot)
        updated, _ = self.renamer.apply(self.snapshot, self.preview()['token'])
        next_token = self.renamer.preview(updated, updated['data'][0]['id'], 'Custom (2000)')['token']
        updated, _ = self.renamer.apply(updated, next_token)
        reconciled = self.renamer.reconcile(original)
        self.assertEqual([r['path'] for r in reconciled['data']], [r['path'] for r in updated['data']])
        self.assertNotEqual(reconciled['revision'], original['revision'])

    def test_atomic_no_overwrite_operation_rejects_an_existing_file(self):
        first, second = self.base / 'first', self.base / 'second'
        first.write_text('one')
        second.write_text('two')
        with renaming.open_directory(self.base) as fd:
            with self.assertRaises(FileExistsError):
                renaming.rename_noreplace(fd, 'first', fd, 'second')
        self.assertEqual(first.read_text(), 'one')
        self.assertEqual(second.read_text(), 'two')

    def test_api_feature_gate_and_csrf_action_check(self):
        client = self.configure_api(enabled=False)
        self.assertEqual(self.api_preview(client).status_code, 403)
        with patch.object(api, 'ENABLE_RENAMING', True):
            body = {'row_id': self.rows[0]['id'], 'snapshot_revision': 'initial'}
            self.assertEqual(client.post('/api/movie-renames/preview', json=body).status_code, 403)
            self.assertEqual(client.post('/api/movie-renames/preview', json=body, headers={**HEADERS, 'Sec-Fetch-Site': 'cross-site'}).status_code, 403)
            self.assertEqual(client.post('/api/movie-renames/preview', data='not json', headers=HEADERS).status_code, 415)
            self.assertEqual(client.post('/api/movie-renames/apply', json={}, headers=HEADERS).status_code, 400)

    def test_api_uses_host_mapping_and_reconciles_cached_and_upstream_paths(self):
        client = self.configure_api()
        preview = self.api_preview(client)
        self.assertEqual(preview.status_code, 200, preview.json)
        result = client.post('/api/movie-renames/apply', headers=HEADERS, json={'token': preview.json['token']})
        self.assertEqual(result.status_code, 200, result.json)
        media = client.get('/api/media')
        self.assertEqual(media.headers['X-Snapshot-Revision'], result.json['snapshot_revision'])
        self.assertTrue(all('/' + NEW + '/' in row['path'] for row in media.json))
        with patch.object(api, 'fetch_all_items', return_value=[self.item]):
            media = client.get('/api/media?refresh=true')
            self.assertEqual(media.status_code, 200)
            self.assertTrue(all('/' + NEW + '/' in row['path'] for row in media.json))
        report = client.get('/api/movie-paths')
        self.assertTrue(report.json['rename_enabled'])
        self.assertEqual(report.json['summary']['needs_review'], 0)
        # HTTP restrictions for NFOs do not interfere with filesystem renaming.
        self.assertEqual(client.get('/movies/' + NEW + '/movie.nfo').status_code, 404)

    def test_cache_write_failure_after_success_is_reconciled_from_receipt(self):
        client = self.configure_api()
        token = self.api_preview(client).json['token']
        with patch.object(api, 'write_cache', side_effect=OSError('fake-secret-error')):
            response = client.post('/api/movie-renames/apply', headers=HEADERS, json={'token': token})
        self.assertEqual(response.status_code, 200)
        self.assertIn('warning', response.json)
        self.assertNotIn('fake-secret-error', response.get_data(as_text=True))
        self.assertTrue(all('/' + NEW + '/' in row['path'] for row in client.get('/api/media').json))

    def test_scan_lock_blocks_renaming(self):
        client = self.configure_api()
        api.SCAN_LOCK.acquire()
        try:
            self.assertEqual(self.api_preview(client).status_code, 503)
        finally:
            api.SCAN_LOCK.release()
        self.assertEqual(self.contents(self.folder), self.before)


if __name__ == '__main__':
    unittest.main()
