"""Environment configuration, with compatibility for existing config.py installs."""
import importlib
import os
from pathlib import Path

try:
    _legacy = importlib.import_module('config')
except ModuleNotFoundError as exc:
    if exc.name != 'config':
        raise
    _legacy = None


def setting(name, default='', legacy_name=None):
    return os.environ.get(name, getattr(_legacy, legacy_name or name, default))


def integer(name, default, legacy_name=None):
    try:
        value = int(setting(name, default, legacy_name))
    except (ValueError, TypeError):
        raise RuntimeError(f'{name} must be a positive integer.') from None
    if value <= 0:
        raise RuntimeError(f'{name} must be a positive integer.')
    return value


JELLYFIN_URL = setting('JELLYFIN_URL').rstrip('/')
API_KEY = setting('JELLYFIN_API_KEY', legacy_name='API_KEY')
JELLYFIN_USER_ID = setting('JELLYFIN_USER_ID')  # Blank means server-wide inventory.
CACHE_FILE = str(setting('CACHE_FILE', str(Path(__file__).with_name('cache.json'))))
PORT = integer('BACKEND_PORT', 5000, 'PORT')
CACHE_MAX_AGE = integer('CACHE_MAX_AGE', 3600)
SCAN_TIMEOUT = min(integer('SCAN_TIMEOUT', 240), 240)
MOVIES_LIBRARY_DIR = setting('MOVIES_LIBRARY_DIR')
TVSHOWS_LIBRARY_DIR = setting('TVSHOWS_LIBRARY_DIR')
JELLYFIN_MOVIES_DIR = setting('JELLYFIN_MOVIES_DIR') or MOVIES_LIBRARY_DIR
JELLYFIN_TVSHOWS_DIR = setting('JELLYFIN_TVSHOWS_DIR') or TVSHOWS_LIBRARY_DIR
ENABLE_RENAMING = str(setting('ENABLE_RENAMING', 'false')).lower() == 'true'
