#!/usr/bin/env bash
# Installe un runner GitHub Actions AUTO-HÉBERGÉ sur la VM, en service systemd.
# Le jeton d'enregistrement se récupère sur GitHub :
#   repo → Settings → Actions → Runners → New self-hosted runner (Linux x64) → "token"
#
#   sudo bash deploy/setup-runner.sh <REG_TOKEN> [REPO_URL]
#
# REPO_URL par défaut : https://github.com/BeeNooZee/JobSearchWeb
set -euo pipefail

TOKEN="${1:?Jeton d'enregistrement manquant (récupère-le dans Settings → Actions → Runners)}"
REPO_URL="${2:-https://github.com/BeeNooZee/JobSearchWeb}"
RUNNER_DIR="${RUNNER_DIR:-/opt/actions-runner}"
RUNNER_VERSION="${RUNNER_VERSION:-2.320.0}"
LABELS="alternance"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl tar rsync >/dev/null

mkdir -p "$RUNNER_DIR" && cd "$RUNNER_DIR"
if [ ! -f "./config.sh" ]; then
  echo "→ Téléchargement du runner $RUNNER_VERSION"
  curl -fsSL -o runner.tgz \
    "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
  tar xzf runner.tgz && rm -f runner.tgz
fi

# Autorise la config/exécution en root (VM dédiée homelab).
export RUNNER_ALLOW_RUNASROOT=1

if [ ! -f ".runner" ]; then
  echo "→ Enregistrement du runner auprès de $REPO_URL"
  ./config.sh --unattended --url "$REPO_URL" --token "$TOKEN" \
    --name "alternance-vm" --labels "$LABELS" --replace
fi

echo "→ Installation en service systemd"
./svc.sh install root
./svc.sh start
sleep 2
./svc.sh status || true
echo "✓ Runner installé (étiquette : $LABELS). Un push sur main déclenchera le déploiement."
