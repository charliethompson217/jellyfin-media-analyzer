# Media Analyzer

A fullstack app for displaying video file information such as codec, resolution, framerate, etc for all your jellyfin media.

## Prerequisites

- Linux server (I use Arch btw).
- Git, Python 3.12+, Node.js 20+, npm, Nginx, systemd.
- apache2-utils (for htpasswd).
- mkcert for self-signed SSL (gen certs manual: `mkcert ${SERVER_NAME}`).
- Jellyfin server running with API key.
- Sudo for install (dirs like /etc/, /opt/).

## Installation

1. Clone repo: `git clone repo-url && cd media-analyzer`.

2. Copy `.env.example` to `.env` and fill your secrets/values (don't commit .env):
   ```
   JELLYFIN_URL=https://your-jellyfin.example
   JELLYFIN_API_KEY=your-secret-key
   BACKEND_DIR=/opt/media-analyzer
   SERVER_NAME=media-analyzer.local
   SSL_CERT_PATH=/etc/ssl/media-analyzer/media-analyzer.local.pem
   SSL_KEY_PATH=/etc/ssl/media-analyzer/media-analyzer.local-key.pem
   FRONTEND_DIR=/srv/http/media-analyzer
   BACKEND_PORT=5000
   MOVIES_LIBRARY_DIR=/path/to/movies
   TVSHOWS_LIBRARY_DIR=/path/to/tvshows
   SERVICE_USER=media-analyzer  # System user for backend—script creates if missing
   NGINX_USER=http  # Nginx runs as this user (e.g., http on Arch)
   NGINX_GROUP=http  # Nginx group
   HTPASSWD_FILE=/etc/nginx/media-analyzer.htpasswd
   HT_USERNAME=your-web-user
   HT_PASSWORD=your-web-password
   ```

3. Run install: `sudo ./scripts/install.sh`.
   - Copies/renders templates to system paths.
   - Sets up venv, installs deps.
   - Builds/copies frontend dist.
   - Creates .htpasswd for basic auth.
   - Starts/enables systemd service.
   - Reloads Nginx.

4. Verify:
   - `systemctl status media-analyzer` (backend).
   - `journalctl -u media-analyzer -f` (logs).
   - `nginx -t && curl -u $HT_USERNAME:$HT_PASSWORD https://${SERVER_NAME}` (frontend).
   - API: `curl -u $HT_USERNAME:$HT_PASSWORD https://${SERVER_NAME}/api/media`.

5. Update: Git pull, re-run install.sh (overwrites configs safely).

**Warnings**: Backup /etc/nginx/* first if customizing.

## Development Setup

1. Clone as above.

2. **Backend**:
   - `cd backend`.
   - `python3 -m venv venv && source venv/bin/activate`.
   - `pip install -r requirements.txt`.
   - Copy config.py.template to config.py, fill JELLYFIN_URL/API_KEY (or use env: script renders, but manual for dev).
   - Run: `flask run --port=5000` (or gunicorn for prod-like).
   - Test: `curl http://localhost:5000/api/media`.

3. **Frontend**:
   - `cd frontend`.
   - `npm ci`.
   - Add export: `VITE_PROXY_TARGET=http://localhost:5000` (proxies /api, /movies, /tv_shows to backend).
   - Run: `npm run dev`.
   - Open http://localhost:5173 (Vite default).

4. Full dev stack:
   - Run backend first.
   - Frontend proxies to it.

5. Build frontend: `npm run build` (outputs dist/).


## License

MIT
