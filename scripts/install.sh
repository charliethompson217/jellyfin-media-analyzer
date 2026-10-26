#!/usr/bin/env bash
# Build immutable releases, validate before activation, and restore on failure.
set -Eeuo pipefail
umask 022
REPO_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ $EUID -eq 0 ]] || { echo 'Run this installer with sudo.' >&2; exit 1; }
[[ -f "$REPO_DIR/.env" ]] || { echo 'Create .env from .env.example first.' >&2; exit 1; }
set -a
source "$REPO_DIR/.env"
set +a

required=(JELLYFIN_URL JELLYFIN_API_KEY BACKEND_DIR SERVER_NAME SSL_CERT_PATH SSL_KEY_PATH FRONTEND_DIR BACKEND_PORT MOVIES_LIBRARY_DIR TVSHOWS_LIBRARY_DIR SERVICE_USER HTPASSWD_FILE HT_USERNAME HT_PASSWORD NGINX_USER NGINX_GROUP)
for name in "${required[@]}"; do
    [[ -n ${!name:-} ]] || { echo "Missing configuration: $name" >&2; exit 1; }
done
ENABLE_FANCYINDEX=${ENABLE_FANCYINDEX:-false}
case "$ENABLE_FANCYINDEX" in
    true)
        MEDIA_INDEX_DIRECTIVES='autoindex off;
        fancyindex on;
        fancyindex_name_length 255;
        fancyindex_ignore "\.nfo$" "\.jpg$" "\.png$" "\.trickplay$";'
        ;;
    false)
        MEDIA_INDEX_DIRECTIVES='autoindex on;
        autoindex_exact_size off;'
        ;;
    *)
        echo 'ENABLE_FANCYINDEX must be true or false.' >&2
        exit 1
        ;;
esac
export MEDIA_INDEX_DIRECTIVES
for command in python3 npm nginx systemctl htpasswd envsubst runuser curl useradd getent realpath; do
    command -v "$command" >/dev/null || { echo "Missing prerequisite: $command" >&2; exit 1; }
done
[[ $BACKEND_PORT =~ ^[0-9]+$ && $BACKEND_PORT -gt 0 && $BACKEND_PORT -lt 65536 ]] || { echo 'Invalid BACKEND_PORT.' >&2; exit 1; }
[[ $SERVER_NAME =~ ^[a-zA-Z0-9.-]+$ ]] || { echo 'Invalid SERVER_NAME.' >&2; exit 1; }
[[ $SERVICE_USER =~ ^[a-z_][a-z0-9_-]*$ && $SERVICE_USER != root ]] || { echo 'SERVICE_USER must be a non-root system account.' >&2; exit 1; }
for name in BACKEND_DIR FRONTEND_DIR MOVIES_LIBRARY_DIR TVSHOWS_LIBRARY_DIR SSL_CERT_PATH SSL_KEY_PATH HTPASSWD_FILE; do
    value=${!name}
    # These values enter Nginx/systemd configuration as quoted paths.
    [[ $value == /* && $value != / && $value != *['"\$%;{}']* && $value != *$'\n'* && $value != *$'\r'* ]] || { echo "Invalid absolute path: $name" >&2; exit 1; }
    printf -v "$name" '%s' "$(realpath -ms -- "$value")"
done
for value in "$BACKEND_DIR" "$FRONTEND_DIR"; do
    case "${value%/}" in /etc|/usr|/var|/opt|/srv|/srv/http|/home|/root|/tmp|/bin|/sbin|/lib|/lib64)
        echo 'Deployment directories must be dedicated app directories.' >&2; exit 1;;
    esac
done
[[ $BACKEND_DIR != "$FRONTEND_DIR" && $BACKEND_DIR != "$FRONTEND_DIR/"* && $FRONTEND_DIR != "$BACKEND_DIR/"* ]] || { echo 'Backend and frontend directories must be separate.' >&2; exit 1; }
[[ -f "$SSL_CERT_PATH" && -f "$SSL_KEY_PATH" ]] || { echo 'SSL certificate or key is missing.' >&2; exit 1; }
[[ -d "$MOVIES_LIBRARY_DIR" && -d "$TVSHOWS_LIBRARY_DIR" ]] || { echo 'Media library directories are missing.' >&2; exit 1; }
getent passwd "$NGINX_USER" >/dev/null
getent group "$NGINX_GROUP" >/dev/null
# This script manages a site include, not the server's main configuration.
nginx_dump=$(nginx -T 2>&1) || { echo 'The existing Nginx configuration must pass nginx -t first.' >&2; exit 1; }
[[ $nginx_dump =~ include[[:space:]]+[^\;]*sites-enabled/ ]] || { echo 'Add include /etc/nginx/sites-enabled/*; inside the Nginx http block first.' >&2; exit 1; }
unset nginx_dump
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /nonexistent --shell /usr/bin/nologin "$SERVICE_USER"
fi
BUILD_USER=${BUILD_USER:-${SUDO_USER:-$SERVICE_USER}}
[[ $BUILD_USER != root ]] || BUILD_USER=$SERVICE_USER
id -u "$BUILD_USER" >/dev/null
CACHE_FILE=${CACHE_FILE:-${BACKEND_DIR}.state/cache.json}
[[ $CACHE_FILE == /* ]] || { echo 'CACHE_FILE must be an absolute path.' >&2; exit 1; }
CACHE_FILE=$(realpath -ms -- "$CACHE_FILE")
[[ $CACHE_FILE != "$BACKEND_DIR/"* && $CACHE_FILE != "$FRONTEND_DIR/"* && $CACHE_FILE != "${BACKEND_DIR}.releases/"* && $CACHE_FILE != "${FRONTEND_DIR}.releases/"* ]] || { echo 'CACHE_FILE must be outside release directories.' >&2; exit 1; }
STATE_DIR=$(dirname -- "$CACHE_FILE")
case "$STATE_DIR" in /|/etc|/usr|/var|/var/cache|/var/lib|/opt|/srv|/srv/http|/home|/root|/tmp|/bin|/sbin|/lib|/lib64)
    echo 'CACHE_FILE must use a dedicated state directory.' >&2; exit 1;;
esac
JELLYFIN_MOVIES_DIR=${JELLYFIN_MOVIES_DIR:-$MOVIES_LIBRARY_DIR}
JELLYFIN_TVSHOWS_DIR=${JELLYFIN_TVSHOWS_DIR:-$TVSHOWS_LIBRARY_DIR}
export CACHE_FILE JELLYFIN_MOVIES_DIR JELLYFIN_TVSHOWS_DIR

TAG=$(date -u +%Y%m%dT%H%M%SZ)-$$
BACKEND_RELEASE=${BACKEND_DIR}.releases/$TAG
FRONTEND_RELEASE=${FRONTEND_DIR}.releases/$TAG
BUILD_DIR=$(mktemp -d)
BACKUP_DIR=$(mktemp -d)
NGINX_CONFIG=/etc/nginx/sites-available/media-analyzer.conf
NGINX_LINK=/etc/nginx/sites-enabled/media-analyzer.conf
SERVICE_FILE=/etc/systemd/system/media-analyzer.service
OLD_BACKEND=''
OLD_FRONTEND=''
CONFIG_CHANGED=false
BACKEND_CHANGED=false
FRONTEND_CHANGED=false
BACKEND_RESTARTED=false

backup_file() {
    if [[ -e $1 || -L $1 ]]; then cp -a -- "$1" "$BACKUP_DIR/$2"; fi
}
restore_file() {
    if [[ -e "$BACKUP_DIR/$2" || -L "$BACKUP_DIR/$2" ]]; then
        cp -a --remove-destination -- "$BACKUP_DIR/$2" "$1"
    else
        rm -f -- "$1"
    fi
}
point_release() {
    ln -s -- "$2" "$1.next.$$"
    mv -Tf -- "$1.next.$$" "$1"
}
finish() {
    status=$1
    trap - EXIT
    set +e
    if [[ $status -ne 0 ]]; then
        echo 'Installation failed; restoring the previous configuration and releases.' >&2
        if $BACKEND_CHANGED; then
            if [[ -n $OLD_BACKEND ]]; then point_release "$BACKEND_DIR" "$OLD_BACKEND"; else rm -f -- "$BACKEND_DIR"; fi
        fi
        if $FRONTEND_CHANGED; then
            if [[ -n $OLD_FRONTEND ]]; then point_release "$FRONTEND_DIR" "$OLD_FRONTEND"; else rm -f -- "$FRONTEND_DIR"; fi
        fi
        if $CONFIG_CHANGED; then
            restore_file "$NGINX_CONFIG" nginx.conf
            restore_file "$NGINX_LINK" nginx.link
            restore_file "$SERVICE_FILE" service
            restore_file "$HTPASSWD_FILE" htpasswd
            systemctl daemon-reload
            if $BACKEND_RESTARTED; then
                if [[ -n $OLD_BACKEND ]]; then systemctl restart media-analyzer.service; else systemctl stop media-analyzer.service; fi
            fi
            if nginx -t; then systemctl reload nginx; fi
        fi
    fi
    rm -rf -- "$BUILD_DIR" "$BACKUP_DIR"
    exit "$status"
}
trap 'finish "$?"' EXIT

as_builder() {
    # Dependency code must not inherit server credentials from the installer's .env.
    runuser -u "$BUILD_USER" -- env -i PATH="$PATH" LANG=C.UTF-8 "$@"
}

mkdir -p -- "${BACKEND_DIR}.releases" "${FRONTEND_DIR}.releases" "$BACKEND_RELEASE" "$FRONTEND_RELEASE" "$BUILD_DIR/frontend"
cp -- "$REPO_DIR"/backend/{app.py,media.py,settings.py,requirements.txt,test_app.py} "$BACKEND_RELEASE/"
cp -- "$REPO_DIR"/frontend/{package.json,package-lock.json,vite.config.js,eslint.config.js,index.html} "$BUILD_DIR/frontend/"
cp -R -- "$REPO_DIR/frontend/src" "$BUILD_DIR/frontend/"
chown -R "$BUILD_USER" -- "$BACKEND_RELEASE" "$BUILD_DIR"
chmod 755 "$BUILD_DIR"
cd "$BUILD_DIR"
# All package installation and build/test execution happens without root.
as_builder python3 -m venv "$BACKEND_RELEASE/venv"
as_builder "$BACKEND_RELEASE/venv/bin/pip" install --only-binary=:all: --no-cache-dir -r "$BACKEND_RELEASE/requirements.txt"
as_builder "$BACKEND_RELEASE/venv/bin/python" -m unittest discover -s "$BACKEND_RELEASE" -v
as_builder npm --prefix "$BUILD_DIR/frontend" ci --ignore-scripts --no-audit --no-fund --cache "$BUILD_DIR/npm-cache"
as_builder npm --prefix "$BUILD_DIR/frontend" run lint
as_builder npm --prefix "$BUILD_DIR/frontend" test
as_builder npm --prefix "$BUILD_DIR/frontend" run build
cp -R -- "$BUILD_DIR/frontend/dist/." "$FRONTEND_RELEASE/"

# Serialize secrets as Python literals instead of interpolating source code.
chown -hR root:"$SERVICE_USER" -- "$BACKEND_RELEASE"
chmod -R go-w "$BACKEND_RELEASE"
rm -f -- "$BACKEND_RELEASE/config.py"
python3 - "$BACKEND_RELEASE/config.py" <<'PY'
import json
import os
import sys
names = {'JELLYFIN_URL': 'JELLYFIN_URL', 'API_KEY': 'JELLYFIN_API_KEY',
         'CACHE_FILE': 'CACHE_FILE', 'PORT': 'BACKEND_PORT',
         'JELLYFIN_USER_ID': 'JELLYFIN_USER_ID', 'CACHE_MAX_AGE': 'CACHE_MAX_AGE',
         'SCAN_TIMEOUT': 'SCAN_TIMEOUT', 'MOVIES_LIBRARY_DIR': 'MOVIES_LIBRARY_DIR',
         'TVSHOWS_LIBRARY_DIR': 'TVSHOWS_LIBRARY_DIR', 'JELLYFIN_MOVIES_DIR': 'JELLYFIN_MOVIES_DIR',
         'JELLYFIN_TVSHOWS_DIR': 'JELLYFIN_TVSHOWS_DIR'}
defaults = {'JELLYFIN_USER_ID': '', 'CACHE_MAX_AGE': '3600', 'SCAN_TIMEOUT': '240'}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    for key, env in names.items():
        value = os.environ.get(env, defaults.get(env, ''))
        if key in ('PORT', 'CACHE_MAX_AGE', 'SCAN_TIMEOUT'):
            value = int(value)
            if value <= 0 or (key == 'SCAN_TIMEOUT' and value > 240):
                raise SystemExit('Invalid timeout/port configuration.')
        handle.write(f'{key} = {value!r}\n')
PY
chown root:"$SERVICE_USER" "$BACKEND_RELEASE/config.py"
chmod 640 "$BACKEND_RELEASE/config.py"
chown -R root:"$NGINX_GROUP" -- "$FRONTEND_RELEASE"
if [[ -d $STATE_DIR ]]; then
    runuser -u "$SERVICE_USER" -- env -i PATH="$PATH" test -w "$STATE_DIR" || { echo 'The service account cannot write to the existing state directory.' >&2; exit 1; }
else
    install -d -m 700 -o "$SERVICE_USER" -g "$SERVICE_USER" -- "$STATE_DIR"
fi
# Password changes are staged and preserve other users. The password stays off argv.
if [[ -f $HTPASSWD_FILE ]]; then
    cp -- "$HTPASSWD_FILE" "$BACKUP_DIR/staged-htpasswd"
    printf '%s\n' "$HT_PASSWORD" | htpasswd -iB "$BACKUP_DIR/staged-htpasswd" "$HT_USERNAME" >/dev/null
else
    printf '%s\n' "$HT_PASSWORD" | htpasswd -iBc "$BACKUP_DIR/staged-htpasswd" "$HT_USERNAME" >/dev/null
fi
unset HT_PASSWORD
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
backup_file "$NGINX_CONFIG" nginx.conf
backup_file "$NGINX_LINK" nginx.link
backup_file "$SERVICE_FILE" service
backup_file "$HTPASSWD_FILE" htpasswd
CONFIG_CHANGED=true
install -m 640 -o root -g "$NGINX_GROUP" "$BACKUP_DIR/staged-htpasswd" "$HTPASSWD_FILE"
envsubst '${SERVER_NAME} ${SSL_CERT_PATH} ${SSL_KEY_PATH} ${HTPASSWD_FILE} ${FRONTEND_DIR} ${BACKEND_PORT} ${MOVIES_LIBRARY_DIR} ${TVSHOWS_LIBRARY_DIR} ${MEDIA_INDEX_DIRECTIVES}' < "$REPO_DIR/infra/media-analyzer.conf.template" > "$NGINX_CONFIG"
ln -sfn -- "$NGINX_CONFIG" "$NGINX_LINK"
envsubst '${SERVICE_USER} ${BACKEND_DIR} ${BACKEND_PORT}' < "$REPO_DIR/infra/media-analyzer.service.template" > "$SERVICE_FILE"
# Validate candidate config while the running app and Nginx are still untouched.
nginx -t

if [[ -L $BACKEND_DIR ]]; then OLD_BACKEND=$(readlink -f -- "$BACKEND_DIR");
elif [[ -e $BACKEND_DIR ]]; then
    OLD_BACKEND=${BACKEND_DIR}.releases/legacy-$TAG
    mv -- "$BACKEND_DIR" "$OLD_BACKEND"
fi
BACKEND_CHANGED=true
point_release "$BACKEND_DIR" "$BACKEND_RELEASE"
if [[ -L $FRONTEND_DIR ]]; then OLD_FRONTEND=$(readlink -f -- "$FRONTEND_DIR");
elif [[ -e $FRONTEND_DIR ]]; then
    OLD_FRONTEND=${FRONTEND_DIR}.releases/legacy-$TAG
    mv -- "$FRONTEND_DIR" "$OLD_FRONTEND"
fi
FRONTEND_CHANGED=true
point_release "$FRONTEND_DIR" "$FRONTEND_RELEASE"
systemctl daemon-reload
BACKEND_RESTARTED=true
systemctl restart media-analyzer.service
healthy=false
for attempt in {1..20}; do
    if curl --fail --silent --max-time 2 "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null; then healthy=true; break; fi
    sleep 0.5
done
$healthy || { echo 'The new backend did not become healthy.' >&2; exit 1; }
systemctl reload nginx
systemctl enable media-analyzer.service
echo 'Deployed and health-checked. Previous releases are retained for rollback.'
