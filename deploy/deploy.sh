#!/usr/bin/env bash
# Déploie le code sur /opt/alternance SANS toucher aux données d'exécution
# (.env, base SQLite, clés VAPID, documents envoyés). Idempotent.
# Usage : bash deploy/deploy.sh [dossier_source]   (défaut : dossier courant)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/alternance}"
SRC="${1:-$(pwd)}"
SERVICE="${SERVICE:-alternance}"

echo "→ Déploiement depuis $SRC vers $APP_DIR"
mkdir -p "$APP_DIR"

# Synchronise uniquement le code applicatif ; préserve les données d'exécution.
rsync -a --delete \
  --exclude 'venv' \
  --exclude '.env' \
  --exclude '*.db' \
  --exclude 'uploads' \
  --exclude 'keys' \
  --exclude '.git' \
  --exclude '__pycache__' \
  "$SRC"/ "$APP_DIR"/

# Environnement Python + dépendances.
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
  echo "→ Création du venv"
  python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# Redémarrage + vérification.
systemctl restart "$SERVICE"
sleep 3
systemctl is-active --quiet "$SERVICE" || { echo "✗ service inactif"; journalctl -u "$SERVICE" -n 30 --no-pager; exit 1; }
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/healthz || true)
[ "$code" = "200" ] && echo "✓ Déploiement OK (healthz 200)" || { echo "✗ healthz=$code"; exit 1; }
