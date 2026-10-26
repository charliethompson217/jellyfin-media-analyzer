"""Preview and apply a movie-folder rename without overwrites or media-content edits."""
from contextlib import contextmanager
import copy
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import sys
import tempfile
import uuid

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from media import download_url
from movie_paths import parse_title_year, strip_incorrect_version_tags, VERSION_TAG_RE

VIDEO_EXTENSIONS = {'.avi', '.mkv', '.mp4', '.mov', '.wmv', '.webm', '.flv', '.mts', '.m2ts', '.m4v', '.m4p', '.mpg', '.mpeg', '.mpg2', '.ts', '.vob', '.iso', '.ogv'}
SIDECAR_EXTENSIONS = {'.nfo', '.srt', '.ass', '.ssa', '.sub', '.idx', '.vtt', '.sup', '.smi', '.ttml'}
GENERIC_ASSET_RE = re.compile(r'^(?:(?:backdrop|fanart)\d*|folder|poster|landscape|logo|clearlogo|banner|thumb|disc|clearart)\.(?:jpg|jpeg|png|webp)$', re.I)
STAGE_PREFIX = '.media-analyzer-rename-'
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class RenameError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def revision(snapshot):
    return snapshot.get('revision', snapshot['scanned_at'])


def file_identity(info):
    return [info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)]


def fingerprint(info):
    return file_identity(info) + [info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def validate_name(name):
    if not isinstance(name, str) or not name or name != name.strip() or name in ('.', '..'):
        raise RenameError('Enter a non-empty shared prefix without leading or trailing whitespace.', 400)
    if re.search(r'[/\\\x00-\x1f\x7f]', name) or name.startswith(STAGE_PREFIX):
        raise RenameError('The shared prefix cannot contain path separators, control characters, or a reserved staging name.', 400)
    return name


def suggested_prefix(row):
    title, year = row.get('metadata_title'), row.get('production_year')
    if not title or year is None:
        return None
    title = re.sub(r'[/\\\x00-\x1f\x7f]+', ' - ', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return f'{title} ({year})' if title else None


def video_suffix(stem):
    match = VERSION_TAG_RE.search(stem)
    base = stem[:match.start()] if match else stem
    title, _ = parse_title_year(base)
    _, _, editions = strip_incorrect_version_tags(title)
    tag = stem[match.start():] if match else ''
    if editions:
        # Keep unbracketed edition information while moving it into a valid tag.
        content = tag[tag.index('[') + 1:-1] if tag else ''
        tag = ' - [' + '-'.join(editions + ([content] if content else [])) + ']'
    return tag


@contextmanager
def open_directory(root, parts=()):
    """Pin each directory by fd; refuse symlinks below the configured root."""
    fd = os.open(str(root), DIR_FLAGS)
    try:
        for part in parts:
            if part in ('', '.', '..') or '/' in part:
                raise RenameError('The source path is outside the configured movie library.', 400)
            next_fd = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def lstat_at(fd, name):
    return os.stat(name, dir_fd=fd, follow_symlinks=False)


def inventory(fd):
    result = []
    for name in sorted(os.listdir(fd)):
        if name.startswith(STAGE_PREFIX):
            raise RenameError('A temporary rename entry exists in this folder. Review its rename journal before continuing.')
        info = lstat_at(fd, name)
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise RenameError('This folder contains symlinks or special files. Renaming is blocked.')
        result.append({'name': name, 'fingerprint': fingerprint(info), 'directory': stat.S_ISDIR(info.st_mode)})
    return result


def rename_noreplace(source_fd, source, destination_fd, destination):
    """Atomic exclusion on Linux/macOS; never fall back to overwriting rename()."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'linux' and hasattr(libc, 'renameat2'):
        function, flags = libc.renameat2, 1  # RENAME_NOREPLACE
    elif sys.platform == 'darwin' and hasattr(libc, 'renameatx_np'):
        function, flags = libc.renameatx_np, 4  # RENAME_EXCL
    else:
        raise RenameError('This platform does not support atomic renaming without overwrites.', 503)
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(source_fd, os.fsencode(source), destination_fd, os.fsencode(destination), flags) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def atomic_json(destination, value):
    destination = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(value, handle, ensure_ascii=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        with open_directory(destination.parent) as fd:
            os.fsync(fd)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class MovieRenamer:
    def __init__(self, cache_file, local_root, jellyfin_root):
        if not local_root or not jellyfin_root:
            raise RenameError('Configure both the host and Jellyfin movie library directories before renaming.', 400)
        self.root = Path(local_root).resolve()
        self.remote = PurePosixPath(jellyfin_root)
        if not self.remote.is_absolute() or '..' in self.remote.parts:
            raise RenameError('The Jellyfin movie library directory must be an absolute path.', 400)
        self.state = Path(cache_file).parent / 'rename-history'
        self.scope = digest([str(self.root), str(self.remote)])

    def _prepare_state(self):
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.state.is_symlink():
            raise RenameError('Rename history must be a private local directory.', 503)
        if stat.S_IMODE(self.state.stat().st_mode) & 0o077:
            raise RenameError('Rename history permissions must be restricted to the service account.', 503)

    def _signer(self):
        self._prepare_state()
        key_path = self.state / 'signing-key'
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(secrets.token_bytes(32))
                handle.flush()
                os.fsync(handle.fileno())
        fd = os.open(key_path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as handle:
            key = handle.read(33)
        if len(key) != 32:
            raise RenameError('The rename signing key is unavailable. Review the state directory.', 503)
        return URLSafeTimedSerializer(key, salt='movie-folder-rename-v1')

    def _check_pending(self):
        self._prepare_state()
        for path in self.state.glob('*.json'):
            try:
                receipt = json.loads(path.read_text())
            except (OSError, ValueError):
                raise RenameError('Rename history is unreadable. Review the state directory before continuing.', 503) from None
            if receipt.get('status') not in ('completed', 'rolled_back'):
                raise RenameError('An incomplete rename needs recovery. Review its journal in the rename-history directory before continuing.', 503)

    def _relative(self, path):
        if not isinstance(path, str) or '..' in PurePosixPath(path).parts:
            raise RenameError('The selected file has no safe movie-library path.', 400)
        try:
            relative = PurePosixPath(path).relative_to(self.remote)
        except ValueError:
            raise RenameError('The selected path does not belong to the configured movie library.', 400) from None
        if len(relative.parts) < 2:
            raise RenameError('Select a movie inside its own folder; the movie library root cannot be renamed.', 400)
        return relative

    def _plan(self, snapshot, row_id, prefix):
        row = next((item for item in snapshot['data'] if item['id'] == row_id and item.get('type') == 'Movie'), None)
        if row is None:
            raise RenameError('This movie is no longer in the snapshot. Refresh the report and try again.')
        relative = self._relative(row.get('path'))
        folder, parent_parts = relative.parts[-2], relative.parts[:-2]
        old_remote_folder = self.remote.joinpath(*parent_parts, folder)
        group = []
        for item in snapshot['data']:
            path = item.get('path')
            if path and PurePosixPath(path).is_relative_to(old_remote_folder):
                if item.get('type') != 'Movie' or PurePosixPath(path).parent != old_remote_folder:
                    raise RenameError('This directory contains nested or non-movie library items. A folder rename is ambiguous.')
                same_item = row.get('item_id') and item.get('item_id') == row['item_id']
                same_metadata = row.get('metadata_title') and (item.get('metadata_title'), item.get('production_year')) == (row.get('metadata_title'), row.get('production_year'))
                if not (same_item or same_metadata or item['id'] == row_id):
                    raise RenameError('This directory contains multiple movie identities. A folder rename is ambiguous.')
                group.append(item)
        suggestion = suggested_prefix(row)
        prefix = validate_name(prefix if prefix is not None else suggestion or folder)
        with open_directory(self.root, parent_parts) as parent_fd:
            with open_directory(self.root, (*parent_parts, folder)) as folder_fd:
                folder_info = os.fstat(folder_fd)
                entries = inventory(folder_fd)
                limit = os.fpathconf(folder_fd, 'PC_NAME_MAX')
                if len(os.fsencode(prefix)) > limit:
                    raise RenameError('The shared prefix exceeds the filesystem filename length limit.', 400)
                try:
                    target = lstat_at(parent_fd, prefix)
                except FileNotFoundError:
                    target = None
                if prefix != folder and target is not None and file_identity(target) != file_identity(folder_info):
                    raise RenameError('A different directory already uses that name. Nothing will be overwritten.')
                if any(name != folder and name.casefold() == prefix.casefold() for name in os.listdir(parent_fd)):
                    raise RenameError('A different directory already uses that name or a case variant. Nothing will be overwritten.')
                entries_by_name = {entry['name']: entry for entry in entries}
                for item in group:
                    name = PurePosixPath(item['path']).name
                    entry = entries_by_name.get(name)
                    if not entry or entry['directory']:
                        raise RenameError('A movie file is missing from the host folder. Check the path mapping and refresh Jellyfin.')
                    if Path(name).suffix.lower() not in VIDEO_EXTENSIONS:
                        raise RenameError('The selected directory contains an unsupported movie file type.', 400)
                    expected_size = item.get('size_bytes')
                    if expected_size is not None and expected_size != entry['fingerprint'][3]:
                        raise RenameError('A movie file no longer matches the saved snapshot size. Refresh the library before renaming.')
                videos = [entry for entry in entries if not entry['directory'] and Path(entry['name']).suffix.lower() in VIDEO_EXTENSIONS]
                if not videos:
                    raise RenameError('No supported movie files were found in this folder.')
                video_names = {entry['name']: prefix + video_suffix(Path(entry['name']).stem) + Path(entry['name']).suffix for entry in videos}
                bases = {Path(name).stem: Path(new_name).stem for name, new_name in video_names.items()}
                changes = []
                for entry in entries:
                    name, new_name, reason = entry['name'], entry['name'], 'Kept with the folder'
                    if name in video_names:
                        new_name, reason = video_names[name], 'Movie version'
                    elif name.lower() == 'movie.nfo' or GENERIC_ASSET_RE.fullmatch(name):
                        reason = 'Shared metadata / artwork; basename retained'
                    else:
                        matches = [base for base in bases if name.startswith(base) and name[len(base):len(base) + 1] in ('.', '-')]
                        if matches:
                            base = max(matches, key=len)
                            new_name, reason = bases[base] + name[len(base):], 'Associated file / artwork'
                        elif name.startswith((folder + '.', folder + '-')) and Path(name).suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.nfo'}:
                            new_name, reason = prefix + name[len(folder):], 'Shared folder metadata / artwork'
                        elif not entry['directory'] and Path(name).suffix.lower() in SIDECAR_EXTENSIONS:
                            if len(videos) == 1 and name.startswith(folder + '.'):
                                new_name, reason = next(iter(bases.values())) + name[len(folder):], 'Associated file'
                            else:
                                raise RenameError(f'Cannot determine which movie version owns this subtitle or metadata file: {name}. Rename or associate it first.')
                    if len(os.fsencode(new_name)) > limit:
                        raise RenameError('A resulting filename exceeds the filesystem length limit. Use a shorter shared prefix.', 400)
                    changes.append({**entry, 'new_name': new_name, 'reason': reason, 'renamed': new_name != name})
                targets = {}
                for change in changes:
                    key = change['new_name'].casefold()
                    if key in targets and targets[key] != change['name']:
                        raise RenameError('Two files would have the same name. Give the movie versions distinct tags before renaming.')
                    targets[key] = change['name']
                affected = []
                for item in group:
                    old_name = PurePosixPath(item['path']).name
                    new_path = str(self.remote.joinpath(*parent_parts, prefix, video_names[old_name]))
                    affected.append({'old_path': item['path'], 'new_path': new_path,
                                     'new_url': download_url(new_path, [(str(self.remote), '/movies/')]),
                                     'identity': entries_by_name[old_name]['fingerprint'][:3]})
                return {
                    'scope': self.scope, 'row_id': row_id, 'snapshot_revision': revision(snapshot),
                    'prefix': prefix, 'suggested_prefix': suggestion, 'old_folder': folder,
                    'parent_parts': list(parent_parts), 'folder_identity': file_identity(folder_info),
                    'inventory_digest': digest(entries), 'entries': changes, 'affected_media': affected,
                    'source_directory': str(self.root.joinpath(*parent_parts, folder)),
                    'destination_directory': str(self.root.joinpath(*parent_parts, prefix)),
                    'video_count': len(videos), 'changed_filenames': sum(change['renamed'] for change in changes),
                    'folder_changed': prefix != folder,
                }

    def preview(self, snapshot, row_id, prefix=None):
        self._check_pending()
        plan = self._plan(snapshot, row_id, prefix)
        token = self._signer().dumps({'row_id': row_id, 'prefix': plan['prefix'], 'digest': digest(plan)})
        return {key: value for key, value in plan.items() if key in (
            'row_id', 'prefix', 'suggested_prefix', 'source_directory', 'destination_directory', 'video_count', 'changed_filenames', 'folder_changed'
        )} | {
            'token': token, 'can_apply': bool(plan['folder_changed'] or plan['changed_filenames']),
            'files': [{'from': item['name'], 'to': item['new_name'], 'renamed': item['renamed'],
                       'directory': item['directory'], 'reason': item['reason']} for item in plan['entries']],
        }

    def apply(self, snapshot, token):
        self._check_pending()
        try:
            approved = self._signer().loads(token, max_age=600)
        except (BadSignature, SignatureExpired, TypeError):
            raise RenameError('This preview expired or is invalid. Preview the rename again.') from None
        plan = self._plan(snapshot, approved.get('row_id'), approved.get('prefix'))
        if digest(plan) != approved.get('digest'):
            raise RenameError('The snapshot or folder changed after preview. Preview the rename again.')
        if not (plan['folder_changed'] or plan['changed_filenames']):
            raise RenameError('The folder and files already use this prefix.', 400)
        transaction = uuid.uuid4().hex
        stage_folder = STAGE_PREFIX + transaction
        journal_path = self.state / (transaction + '.json')
        journal = {'id': transaction, 'status': 'pending', 'scope': self.scope,
                   'created_at': datetime.now(timezone.utc).isoformat(), 'plan': plan, 'operations': [], 'completed_steps': 0}
        snapshot_copy = copy.deepcopy(snapshot)
        # Build the new snapshot before changing the filesystem.
        update_snapshot(snapshot_copy, plan['affected_media'], transaction)
        with open_directory(self.root, plan['parent_parts']) as parent_fd:
            with open_directory(self.root, (*plan['parent_parts'], plan['old_folder'])) as folder_fd:
                if file_identity(os.fstat(folder_fd)) != plan['folder_identity'] or digest(inventory(folder_fd)) != plan['inventory_digest']:
                    raise RenameError('The source folder changed. Preview the rename again.')
                operations = [('parent', plan['old_folder'], stage_folder, plan['folder_identity'])]
                for index, item in enumerate(plan['entries']):
                    if item['renamed']:
                        temporary = f'{STAGE_PREFIX}{transaction}-{index}'
                        operations.append(('folder', item['name'], temporary, item['fingerprint'][:3]))
                for index, item in enumerate(plan['entries']):
                    if item['renamed']:
                        operations.append(('folder', f'{STAGE_PREFIX}{transaction}-{index}', item['new_name'], item['fingerprint'][:3]))
                operations.append(('parent', stage_folder, plan['prefix'], plan['folder_identity']))
                journal['operations'] = operations
                atomic_json(journal_path, journal)
                completed = []
                try:
                    for area, source, target, identity in operations:
                        fd = parent_fd if area == 'parent' else folder_fd
                        if file_identity(lstat_at(fd, source)) != identity:
                            raise RenameError('A source entry changed during the rename.')
                        rename_noreplace(fd, source, fd, target)
                        completed.append((area, source, target, identity))
                        if file_identity(lstat_at(fd, target)) != identity:
                            raise RenameError('A source entry changed during the rename.')
                        os.fsync(fd)
                        journal['completed_steps'] = len(completed)
                        atomic_json(journal_path, journal)
                    journal['status'] = 'completed'
                    journal['revision'] = transaction
                    atomic_json(journal_path, journal)
                except Exception:
                    restored = True
                    for area, source, target, identity in reversed(completed):
                        fd = parent_fd if area == 'parent' else folder_fd
                        try:
                            if file_identity(lstat_at(fd, target)) != identity:
                                raise OSError('changed entry')
                            rename_noreplace(fd, target, fd, source)
                            os.fsync(fd)
                        except Exception:
                            restored = False
                            break
                    journal['status'] = 'rolled_back' if restored else 'needs_recovery'
                    try:
                        atomic_json(journal_path, journal)
                    except OSError:
                        pass
                    if not restored:
                        raise RenameError('The rename could not be fully rolled back. Further renames are blocked; review its rename-history journal.', 503) from None
                    raise RenameError('The rename failed and was rolled back. No files were overwritten; check filesystem permissions and retry.') from None
        return snapshot_copy, {'transaction_id': transaction, 'destination_directory': plan['destination_directory'],
                               'changed_filenames': plan['changed_filenames'], 'video_count': plan['video_count']}

    def reconcile(self, snapshot):
        """Keep known renamed paths usable until Jellyfin's next library scan."""
        if not self.state.exists():
            return snapshot
        receipts = []
        for path in self.state.glob('*.json'):
            try:
                receipt = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if receipt.get('status') == 'completed' and receipt.get('scope') == self.scope:
                receipts.append(receipt)
        if not receipts:
            return snapshot
        snapshot = copy.deepcopy(snapshot)
        ordered = sorted(receipts, key=lambda item: item['created_at'])
        by_path = {alias['old_path']: alias for receipt in ordered for alias in receipt['plan']['affected_media']}
        aliases = []
        for original, first in by_path.items():
            alias = dict(first)
            visited = {original}
            while alias['new_path'] in by_path and alias['new_path'] not in visited:
                visited.add(alias['new_path'])
                next_alias = by_path[alias['new_path']]
                if next_alias['identity'] != alias['identity']:
                    break
                alias = {**next_alias, 'old_path': original}
            try:
                old_relative = self._relative(alias['old_path'])
                new_relative = self._relative(alias['new_path'])
                try:
                    with open_directory(self.root, old_relative.parts[:-1]) as fd:
                        lstat_at(fd, old_relative.name)
                except FileNotFoundError:
                    pass
                else:
                    continue
                with open_directory(self.root, new_relative.parts[:-1]) as fd:
                    if file_identity(lstat_at(fd, new_relative.name)) == alias['identity']:
                        aliases.append(alias)
            except (OSError, RenameError):
                continue
        update_snapshot(snapshot, aliases, digest([revision(snapshot), ordered[-1]['revision']]))
        return snapshot


def update_snapshot(snapshot, aliases, new_revision):
    by_path = {alias['old_path']: alias for alias in aliases}
    changed = False
    for row in snapshot['data']:
        if row.get('path') in by_path:
            alias = by_path[row['path']]
            row['path'] = alias['new_path']
            row['download_url'] = alias['new_url']
            row['id'] = hashlib.sha256(repr(('path', row['path'])).encode()).hexdigest()
            # A rename does not change metadata or the original scan timestamp.
            changed = True
    if changed:
        snapshot['revision'] = new_revision
    return changed
