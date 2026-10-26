"""Exercise installer activation/rollback using isolated files and mocked OS commands.

This does not run systemd, Nginx, package managers, or privileged operations.
"""
import ast
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, re, shutil, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ['INSTALL_TEST_ROOT'])
with (root / 'events.jsonl').open('a') as log:
    log.write(json.dumps([name, args]) + '\n')
if name == 'nginx':
    if '-T' in args: print('include /etc/nginx/sites-enabled/*;')
    if '-t' in args and os.environ.get('FAIL_NGINX_TEST') == '1': sys.exit(1)
elif name == 'curl':
    sys.exit(1 if os.environ.get('FAIL_HEALTH') == '1' else 0)
elif name == 'systemctl':
    if args == ['reload', 'nginx'] and os.environ.get('FAIL_RELOAD') == '1': sys.exit(1)
elif name == 'id': print('1001')
elif name == 'runuser':
    command = args[args.index('--') + 1:]
    assert command[:2] == ['env', '-i'], 'build must clear inherited credentials'
    command = command[2:]
    while command and '=' in command[0]: command.pop(0)
    assert not any('JELLYFIN_API_KEY=' in arg or 'HT_PASSWORD=' in arg for arg in command)
    if command[:3] == ['python3', '-m', 'venv']:
        pathlib.Path(command[3], 'bin').mkdir(parents=True)
    if command and command[0] == 'npm' and command[-2:] == ['run', 'build']:
        dist = pathlib.Path(command[command.index('--prefix') + 1], 'dist')
        dist.mkdir()
        (dist / 'index.html').write_text('new frontend')
    if os.environ.get('FAIL_BUILD') == '1': sys.exit(1)
elif name == 'htpasswd':
    password = sys.stdin.read()
    assert password, 'password must come from stdin'
    path = pathlib.Path(args[-2])
    content = path.read_text() if path.exists() else ''
    user = args[-1]
    path.write_text(''.join(line + '\n' for line in content.splitlines() if not line.startswith(user + ':')) + user + ':test-hash\n')
elif name == 'install':
    if '-d' in args: pathlib.Path(args[-1]).mkdir(parents=True, exist_ok=True)
    else: shutil.copyfile(args[-2], args[-1])
elif name == 'cp':
    recursive = '-R' in args or '-a' in args
    positional = [a for a in args if not a.startswith('-')]
    destination = pathlib.Path(positional[-1])
    for source in positional[:-1]:
        path = pathlib.Path(source)
        target = destination / path.name if destination.is_dir() else destination
        if path.is_symlink():
            if target.is_symlink() or target.exists(): target.unlink()
            target.symlink_to(os.readlink(path))
        elif path.is_dir():
            assert recursive
            if source.endswith('/.'):
                for child in path.iterdir():
                    if child.is_dir(): shutil.copytree(child, destination / child.name, dirs_exist_ok=True)
                    else: shutil.copyfile(child, destination / child.name)
            else: shutil.copytree(path, target, dirs_exist_ok=True)
        else:
            if target.is_symlink(): target.unlink()
            shutil.copyfile(path, target)
elif name == 'mv':
    positional = [a for a in args if not a.startswith('-')]
    if '-Tf' in args: os.replace(*positional)
    else: shutil.move(*positional)
elif name == 'readlink': print(pathlib.Path(args[-1]).resolve())
elif name == 'realpath': print(os.path.normpath(args[-1]))
elif name == 'envsubst':
    allowed = set(re.findall(r'\$\{(\w+)\}', args[0]))
    print(re.sub(r'\$\{(\w+)\}', lambda m: os.environ.get(m[1], '') if m[1] in allowed else m[0], sys.stdin.read()), end='')
'''


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        for name in ('backend', 'frontend', 'infra', 'scripts'):
            (self.repo / name).mkdir()
        for name in ('app.py', 'media.py', 'settings.py', 'requirements.txt', 'test_app.py'):
            shutil.copyfile(ROOT / 'backend' / name, self.repo / 'backend' / name)
        for name in ('package.json', 'package-lock.json', 'vite.config.js', 'eslint.config.js', 'index.html'):
            shutil.copyfile(ROOT / 'frontend' / name, self.repo / 'frontend' / name)
        (self.repo / 'frontend/src').mkdir()
        for path in (ROOT / 'infra').iterdir():
            if path.is_file(): shutil.copyfile(path, self.repo / 'infra' / path.name)
        script = (ROOT / 'scripts/install.sh').read_text()
        guard = "[[ $EUID -eq 0 ]] || { echo 'Run this installer with sudo.' >&2; exit 1; }"
        self.assertIn(guard, script)
        script = script.replace(guard, ': # Root check bypassed only in isolated test copy.')
        script = script.replace('/etc/nginx', str(self.root / 'nginx')).replace('/etc/systemd/system', str(self.root / 'units'))
        (self.repo / 'scripts/install.sh').write_text(script)
        self.backend = self.root / 'backend'
        self.frontend = self.root / 'frontend'
        self.backend.mkdir()
        self.frontend.mkdir()
        (self.backend / 'old.txt').write_text('old backend')
        (self.frontend / 'index.html').write_text('old frontend')
        self.config = self.root / 'nginx/sites-available/media-analyzer.conf'
        self.config.parent.mkdir(parents=True)
        self.config.write_text('old nginx')
        links = self.root / 'nginx/sites-enabled'
        links.mkdir()
        (links / 'media-analyzer.conf').symlink_to(self.config)
        (self.root / 'units').mkdir()
        (self.root / 'units/media-analyzer.service').write_text('old service')
        self.password = self.root / 'passwords'
        self.password.write_text('other:preserved-hash\nweb:old-hash\n')
        self.secret = 'fake-key-with-"quotes-and-$symbols'
        values = {'JELLYFIN_URL': 'http://jellyfin.invalid', 'JELLYFIN_API_KEY': self.secret,
                  'BACKEND_DIR': str(self.backend), 'FRONTEND_DIR': str(self.frontend), 'BACKEND_PORT': '5000',
                  'SERVER_NAME': 'media.local', 'SSL_CERT_PATH': str(self.password), 'SSL_KEY_PATH': str(self.password),
                  'MOVIES_LIBRARY_DIR': str(self.root), 'TVSHOWS_LIBRARY_DIR': str(self.root),
                  'SERVICE_USER': 'media-analyzer', 'NGINX_USER': 'nginx', 'NGINX_GROUP': 'nginx',
                  'HTPASSWD_FILE': str(self.password), 'HT_USERNAME': 'web', 'HT_PASSWORD': 'fake-password', 'BUILD_USER': 'builder'}
        (self.repo / '.env').write_text(''.join(key + '=' + shlex.quote(value) + '\n' for key, value in values.items()))
        binaries = self.root / 'bin'
        binaries.mkdir()
        for name in ('nginx', 'systemctl', 'htpasswd', 'envsubst', 'runuser', 'curl', 'useradd', 'getent', 'id', 'chown', 'install', 'cp', 'mv', 'readlink', 'realpath', 'sleep'):
            executable = binaries / name
            executable.write_text(MOCK)
            executable.chmod(0o755)
        self.environment = {**os.environ, 'PATH': str(binaries) + os.pathsep + os.environ['PATH'], 'INSTALL_TEST_ROOT': str(self.root)}

    def run_installer(self, **flags):
        result = subprocess.run(['bash', str(self.repo / 'scripts/install.sh')], cwd=self.root,
                                env={**self.environment, **flags}, capture_output=True, text=True, timeout=30)
        self.assertNotIn(self.secret, result.stdout + result.stderr)
        return result

    def assert_restored(self):
        self.assertEqual((self.backend / 'old.txt').read_text(), 'old backend')
        self.assertEqual((self.frontend / 'index.html').read_text(), 'old frontend')
        self.assertEqual(self.config.read_text(), 'old nginx')
        self.assertEqual((self.root / 'units/media-analyzer.service').read_text(), 'old service')
        self.assertEqual(self.password.read_text(), 'other:preserved-hash\nweb:old-hash\n')

    def test_success_migrates_directory_install_preserves_users_and_safely_serializes_key(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.backend.is_symlink())
        self.assertTrue(self.frontend.is_symlink())
        self.assertEqual((self.frontend / 'index.html').read_text(), 'new frontend')
        config = ast.parse((self.backend / 'config.py').read_text())
        settings = {node.targets[0].id: ast.literal_eval(node.value) for node in config.body}
        self.assertEqual(settings['API_KEY'], self.secret)
        self.assertIn('other:preserved-hash', self.password.read_text())
        # A second update must also work when deployment paths are symlinks.
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_build_failure_leaves_live_directories_untouched(self):
        self.assertNotEqual(self.run_installer(FAIL_BUILD='1').returncode, 0)
        self.assert_restored()
        self.assertFalse(self.backend.is_symlink())

    def test_shared_state_directory_is_rejected_without_changing_it(self):
        with (self.repo / '.env').open('a') as handle:
            handle.write('CACHE_FILE=/tmp/cache.json\n')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dedicated state directory', result.stderr)
        self.assert_restored()

    def test_invalid_nginx_restores_config_before_release_activation(self):
        self.assertNotEqual(self.run_installer(FAIL_NGINX_TEST='1').returncode, 0)
        self.assert_restored()
        self.assertFalse(self.backend.is_symlink())

    def test_backend_health_failure_restores_previous_release(self):
        self.assertNotEqual(self.run_installer(FAIL_HEALTH='1').returncode, 0)
        self.assert_restored()

    def test_nginx_reload_failure_restores_previous_release(self):
        self.assertNotEqual(self.run_installer(FAIL_RELOAD='1').returncode, 0)
        self.assert_restored()


if __name__ == '__main__':
    unittest.main()
