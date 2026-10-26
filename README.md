# Media Analyzer

A Flask/React application for inspecting the files and versions in a Jellyfin library: codecs, resolution, frame rates, HDR, audio, storage, duration, charts, and CSV export.

## Requirements

- Production: Linux with systemd, Python 3.12+, Node 22.12+ (or Node 20.19+), npm, Nginx, `envsubst` (gettext), `htpasswd`, `curl`, and `runuser`. Fancyindex is optional.
- A running Jellyfin server and an API key with permission to list the intended media.
- An SSL certificate/key and Nginx access to the media directories.

## Install or update

1. Copy `.env.example` to `.env` and set the server, credentials, directories, service account, and Nginx account/group. This is a shell configuration file; quote values containing spaces or shell characters. Never commit it.
2. Configure Nginx to include `/etc/nginx/sites-enabled/*` inside its `http` block. [infra/nginx.conf.example](infra/nginx.conf.example) shows the structure. The site defines its own rate-limit zone. Directory listings use Nginx's built-in autoindex by default. Set `ENABLE_FANCYINDEX=true` only if the Fancyindex module is installed and loaded in Nginx. The existing Nginx configuration must pass `nginx -t` before installation.
3. Run `sudo ./scripts/install.sh` from any directory. Back up custom server configuration before the first upgrade.
4. Check `systemctl status media-analyzer`, `journalctl -u media-analyzer -f`, and your HTTPS site. The local health check is `http://127.0.0.1:5000/api/health` (adjust for `BACKEND_PORT`).

The installer builds and tests as a non-root user without passing server credentials to dependency code. It stages immutable backend/frontend releases, validates Nginx before switching the running app, checks backend health, and restores the previous release/configuration if activation fails. Existing password-file users are preserved. Previous releases remain under `<BACKEND_DIR>.releases` and `<FRONTEND_DIR>.releases`; the configured app directories become symlinks. Existing directory installs are retained as `legacy-*` releases on first migration.

`CACHE_FILE` must be an absolute path outside both app directories, such as `/opt/media-analyzer.state/cache.json`. The state directory is writable by the service; when renaming is enabled, the service also needs write access to movie folders and their parent directories. Avoid placing unrelated files in the state directory. Keep deployment directories separate and dedicated to this app. The installer is intended for GNU/Linux; macOS is supported for local application development, not system deployment.

The installer does not edit Nginx's main configuration or install missing OS packages. Certificate/key and media directories must already exist. Failed builds leave the current application untouched; failed activations restore the previous app/configuration. Staged release directories are retained for diagnosis and can be removed after verifying they are not an active/previous release.

## Configuration and downloads

Environment variables take precedence over optional `backend/config.py` settings. For local file configuration, copy `backend/config.py.template` to `backend/config.py` and fill the values. The installer generates the production file with restricted permissions.

- `JELLYFIN_URL`, `JELLYFIN_API_KEY`: server URL and key. Both modern and legacy authentication use headers, with no key in URL parameters. Redirects are rejected; use the final server URL.
- `JELLYFIN_USER_ID`: blank for a server-wide inventory; set an ID for an explicit user scope. The app no longer chooses whichever user happens to appear first.
- `CACHE_FILE`, `CACHE_MAX_AGE`: snapshot location and freshness in seconds (default 3600). Legacy caches are rescanned automatically. Cache identity includes server/scope/configuration, so changing them requires a fresh scan.
- `SCAN_TIMEOUT`: scan deadline in seconds, default/max 240 for the supplied production proxy/worker timeouts.
- `MOVIES_LIBRARY_DIR`, `TVSHOWS_LIBRARY_DIR`: local directories served by Nginx in production and Flask in development.
- `JELLYFIN_MOVIES_DIR`, `JELLYFIN_TVSHOWS_DIR`: optional corresponding paths returned by Jellyfin, if it runs inside a container or uses different mount points. They default to the local library paths.
- `ENABLE_FANCYINDEX`: `false` (default) uses built-in directory listings without requiring the Fancyindex module. Set `true` to render Fancyindex directives; install/load the module first. Both modes preserve media aliases, authentication, and the existing sidecar access restrictions. Basic listings can show sidecar names even though those files remain inaccessible.
- `ENABLE_RENAMING`: `false` (default) keeps the movie path checker read-only. Set `true` to show the folder rename action. The installer does not change media ownership or permissions; grant the configured `SERVICE_USER` write and search access to movie folders and their parent directories using your existing group or ACL setup. Everyone who can authenticate to this app can then rename movie folders.

Only recognized library paths become download links; filenames are URL-encoded, and unmapped/unknown paths remain text. Nginx provides HTTPS Basic Auth for the site, API, and downloads. The backend is deliberately bound to loopback and has no independent login; keep it behind that proxy in production.

An expired snapshot triggers a refresh. Other requests can use the last snapshot while that scan runs. A failed refresh preserves the snapshot and shows a safe warning. The UI displays the last successful scan time and skipped records. Unknown metadata remains unknown; unavailable size/runtime values do not participate in bitrate calculations. Each file/version is counted separately, and the storage-rate summary is the mean per file with known data.

## Movie path checks

Open **Movie Path Check**, then choose **Run Path Check**. This compares every movie file/version in the library snapshot against its Jellyfin title and production year. Overview filters do not limit the check, and TV episodes are excluded. The check compares paths reported by Jellyfin without inspecting the host filesystem; container/host path differences need no additional checker configuration.

The checker groups results into exact, case/symbol, year, spelling, and possible-misidentification categories. Matching supports accent folding, Roman/Arabic numerals, `&`/`and`, colon subtitle variants, and misplaced edition/version tags. The spelling threshold defaults to 92% and can be changed before each run. A filename's trailing ` - [Version]` tag is ignored for title/year comparison.

The overall category follows the **better-matching folder or filename**. A good folder can therefore give an overall exact match even when the filename is wrong; folder/file differences and version-tag problems remain independently flagged. Rows are grouped by category, with higher title similarity first within each group. **Only show issues** is selected initially; clear it to include clean matches.

Use search, category, and flag filters to narrow the report. **View details** shows both component comparisons, year differences, matching variants, misplaced version tags, and the original Jellyfin path. **Export Path CSV** exports every filtered result across all pages, including detailed fields and spreadsheet-safe text. Missing titles, production years, or usable paths appear as **Not checked** with a reason rather than being classified as misidentified.

Checks reuse the saved library snapshot and do not make additional Jellyfin requests. Reload the library when metadata changes, then rerun the check; existing reports show a notice when the library snapshot changes. This update adds production years to the snapshot schema, so older snapshots are automatically refreshed after deployment.

### Rename a movie folder

With `ENABLE_RENAMING=true`, select **Rename folder & files** on a movie row. The preview shows every top-level entry in the host folder before anything changes. **Use checker suggestion** uses Jellyfin's title and production year; you can also enter the exact shared prefix you want and choose **Preview changes**. The backend derives the host folder from the saved Jellyfin path using `JELLYFIN_MOVIES_DIR` and `MOVIES_LIBRARY_DIR`, so for example `/home/jellyfin/media/movies` can map to `/srv/jellyfin/media/movies`. The browser never supplies a host path.

Applying a preview renames the containing folder, all video versions, and the sidecar files associated with each video's full stem. Version tags, language/forced subtitle suffixes, extensions, and file bytes are preserved. Shared artwork such as `folder.jpg` and `backdrop.jpg`, plus `movie.nfo`, keep their names and move with the folder. Other files and nested extras directories move with the folder unchanged; names *inside* nested directories are not rewritten. Ambiguous sidecar ownership, name collisions, top-level symlinks, and changed top-level entries block the rename. The app uses atomic operations that refuse to overwrite a destination, records a private transaction journal under the cache state directory, and attempts to roll back a failed batch. If a journal reports `needs_recovery` or remains `pending` after a crash, review the journal and folder contents before further renames; the app blocks them in the meantime.

The backend accesses sidecars on the host filesystem. Nginx's existing `.nfo`/sidecar download restrictions stay in effect, and these files do not need public URLs. After applying a rename, run a Jellyfin library scan so Jellyfin updates its paths. The app updates its own cached links immediately and reconciles known paths while Jellyfin still reports the old ones.

## Development

From the repository root, create `.env` from `.env.example`, then load it into your shell with `set -a`, `source .env`, and `set +a`. For development, set a local writable `CACHE_FILE`, for example `/tmp/media-analyzer-dev/cache.json`. Alternatively use `backend/config.py` as described above.

Backend:

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd backend
../.venv/bin/flask --app app run --host 127.0.0.1 --port 5000
```

In a second terminal:

```sh
cd frontend
npm ci --ignore-scripts
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`). API and media downloads are proxied to `http://localhost:5000`; set `VITE_PROXY_TARGET` for a different backend address. To download real media in development, the local library directories must be accessible to the backend, with Jellyfin-to-local mappings configured if needed. The API/frontend timeouts allow a scan to finish without the previous 30-second development proxy cutoff.

## Checks

From the repository root with backend requirements installed:

```sh
python -m unittest discover -s backend -v
python -m unittest discover -s scripts -p 'test_*.py' -v
bash -n scripts/install.sh
```

From `frontend`:

```sh
npm run lint
npm test
npm run build
```

GitHub Actions runs regression tests, lint, and the build. Backend tests use synthetic data and fake credentials, never a live Jellyfin server. Installer tests use an isolated filesystem and mock system commands; a real Linux/Nginx deployment rehearsal is still needed before relying on a new host configuration.

The original [October 2026 audit](docs/audits/2026-10-26/README.md) and its characterization scripts record pre-fix behavior at commit `b971214`. Those historical scripts are not the current regression suite.

## License

MIT
