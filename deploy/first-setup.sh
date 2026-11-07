#!/usr/bin/env bash
# Provisionne une VM Debian NEUVE pour héberger le site (à lancer en root,
# depuis un clone du repo). Idempotent : ne réécrit ni .env ni les clés si présents.
#   sudo bash deploy/first-setup.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/alternance}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE="${SERVICE:-alternance}"

echo "→ Paquets système"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip git rsync curl >/dev/null

echo "→ Code vers $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --exclude venv --exclude .env --exclude '*.db' --exclude uploads \
  --exclude keys --exclude .git --exclude __pycache__ "$SRC"/ "$APP_DIR"/

echo "→ venv + dépendances"
[ -x "$APP_DIR/venv/bin/python" ] || python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "→ Clés VAPID (Web Push)"
mkdir -p "$APP_DIR/keys"
if [ ! -f "$APP_DIR/keys/private_key.pem" ]; then
  ( cd "$APP_DIR/keys" && "$APP_DIR/venv/bin/vapid" --gen >/dev/null 2>&1 )
fi
PUBKEY="$("$APP_DIR/venv/bin/vapid" --applicationServerKey 2>/dev/null | sed -n 's/.*Key *= *//p')"

echo "→ Fichier .env"
if [ ! -f "$APP_DIR/.env" ]; then
  SECRET="$("$APP_DIR/venv/bin/python" -c 'import secrets;print(secrets.token_urlsafe(48))')"
  cat > "$APP_DIR/.env" <<ENV
APP_NAME=Ma recherche d'alternance
SECRET_KEY=$SECRET
PUBLIC_URL=http://192.168.1.58:8000
TZ=Europe/Paris
DB_PATH=$APP_DIR/alternance.db
UPLOAD_DIR=$APP_DIR/uploads
VAPID_PUBLIC_KEY=$PUBKEY
VAPID_PRIVATE_KEY_FILE=$APP_DIR/keys/private_key.pem
VAPID_SUBJECT=mailto:l.dalet4@gmail.com
ENV
  chmod 600 "$APP_DIR/.env"
  echo "  .env créé (pense à passer PUBLIC_URL en https:// une fois le domaine prêt)"
else
  echo "  .env déjà présent — conservé"
fi

echo "→ Service systemd"
cat > /etc/systemd/system/$SERVICE.service <<UNIT
[Unit]
Description=Ma recherche d'alternance
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now $SERVICE >/dev/null 2>&1
sleep 3
systemctl is-active --quiet $SERVICE && echo "✓ Service actif sur :8000" || { echo "✗ échec"; journalctl -u $SERVICE -n 20 --no-pager; exit 1; }
