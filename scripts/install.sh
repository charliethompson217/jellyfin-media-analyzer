#!/bin/bash

set -e  # Exit on error

REPO_DIR=$(dirname "$(realpath "$0")")/..

ENV_FILE="$REPO_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "create and fill $ENV_FILE from .env.example!" >&2
    exit 1
fi
source "$ENV_FILE"

# Required env vars
REQUIRED_VARS="JELLYFIN_URL JELLYFIN_API_KEY BACKEND_DIR SERVER_NAME SSL_CERT_PATH SSL_KEY_PATH FRONTEND_DIR BACKEND_PORT MOVIES_LIBRARY_DIR TVSHOWS_LIBRARY_DIR SERVICE_USER HTPASSWD_FILE HT_USERNAME HT_PASSWORD NGINX_USER"
for var in $REQUIRED_VARS; do
    if [ -z "${!var}" ]; then
        echo "Error: $var environment variable is not set." >&2
        exit 1
    fi
done

for var in $REQUIRED_VARS; do
    export "$var"
done

htpasswd -b -c $HTPASSWD_FILE "$HT_USERNAME" "$HT_PASSWORD" || { echo "htpasswd failed, install apache2-utils"; exit 1; }
chown root:$NGINX_GROUP $HTPASSWD_FILE
chmod 640 $HTPASSWD_FILE

# Dirs
BACKEND_TARGET=$BACKEND_DIR
FRONTEND_TARGET=$FRONTEND_DIR

# Copy backend
mkdir -p $BACKEND_TARGET
cp -r backend/* $BACKEND_TARGET/

# Render config.py
envsubst '${JELLYFIN_URL} ${JELLYFIN_API_KEY} ${BACKEND_DIR} ${BACKEND_PORT}' < $REPO_DIR/backend/config.py.template > $BACKEND_TARGET/config.py

if ! id -u "$SERVICE_USER" > /dev/null 2>&1; then
    useradd -r -s /bin/false "$SERVICE_USER"
    echo "Created user $SERVICE_USER."
fi

# Venv setup
rm -rf $BACKEND_TARGET/venv
python3 -m venv $BACKEND_TARGET/venv
source $BACKEND_TARGET/venv/bin/activate
pip install -r $BACKEND_TARGET/requirements.txt
deactivate

chown -R $SERVICE_USER:$SERVICE_USER $BACKEND_TARGET

# Build & copy frontend
cd $REPO_DIR/frontend
npm i
npm run build
mkdir -p $FRONTEND_TARGET
cp -r dist/* $FRONTEND_TARGET/

chown -R $NGINX_USER:$NGINX_USER $FRONTEND_TARGET

# Render infra
envsubst '${SERVER_NAME} ${SSL_CERT_PATH} ${SSL_KEY_PATH} ${HTPASSWD_FILE} ${FRONTEND_DIR} ${BACKEND_PORT} ${MOVIES_LIBRARY_DIR} ${TVSHOWS_LIBRARY_DIR}' < $REPO_DIR/infra/media-analyzer.conf.template > /etc/nginx/sites-available/media-analyzer.conf
ln -sf /etc/nginx/sites-available/media-analyzer.conf /etc/nginx/sites-enabled/media-analyzer.conf

envsubst '${SERVICE_USER} ${BACKEND_DIR} ${BACKEND_PORT}' < $REPO_DIR/infra/media-analyzer.service.template > /etc/systemd/system/media-analyzer.service

# Reload systemd
systemctl daemon-reload

# Start/enable service
systemctl enable media-analyzer.service
systemctl restart media-analyzer.service

# Test & reload nginx
nginx -t || { echo "Nginx config is invalid, fix your templates"; exit 1; }
systemctl reload nginx

echo "Deployed. Check logs: journalctl -u media-analyzer"