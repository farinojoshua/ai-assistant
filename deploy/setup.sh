#!/usr/bin/env bash
# One-shot deploy for a fresh Ubuntu VPS (Podman or Docker).
#   sudo bash deploy/setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.prod"
COMPOSE_FILE="deploy/docker-compose.prod.yml"
PROJECT="ai-assistant"

echo "==> AI Assistant deploy"

# ---- 1. swap (image builds are memory-hungry on small VPS) -----------------
if [ "$(free -m | awk '/^Swap:/ {print $2}')" -lt 1024 ]; then
  echo "==> creating 2G swapfile"
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---- 2. container engine + compose ----------------------------------------
if command -v podman >/dev/null 2>&1; then
  ENGINE=podman
elif command -v docker >/dev/null 2>&1; then
  ENGINE=docker
else
  echo "==> installing podman"
  apt-get update && apt-get install -y podman
  ENGINE=podman
fi

if $ENGINE compose version >/dev/null 2>&1; then
  COMPOSE="$ENGINE compose -p $PROJECT"
elif command -v podman-compose >/dev/null 2>&1; then
  COMPOSE="podman-compose -p $PROJECT"
else
  echo "==> installing podman-compose"
  apt-get update && apt-get install -y podman-compose \
    || (apt-get install -y python3-pip && pip3 install podman-compose)
  COMPOSE="podman-compose -p $PROJECT"
fi
echo "==> engine: $ENGINE   compose: $COMPOSE"

# keep containers alive across reboot (rootful podman)
if [ "$ENGINE" = podman ]; then
  systemctl enable --now podman-restart.service 2>/dev/null || true
fi

# ---- 3. env file --------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  echo "==> generating $ENV_FILE"
  cp deploy/.env.prod.example "$ENV_FILE"
  gen() { openssl rand -hex 24; }
  sed -i "s|^POSTGRES_PASSWORD_APP=.*|POSTGRES_PASSWORD_APP=$(gen)|" "$ENV_FILE"
  sed -i "s|^POSTGRES_PASSWORD_COMPANY=.*|POSTGRES_PASSWORD_COMPANY=$(gen)|" "$ENV_FILE"
  sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(gen)|" "$ENV_FILE"
  sed -i "s|^SEED_ADMIN_PASSWORD=.*|SEED_ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=')|" "$ENV_FILE"
  IP="$(curl -fsS4 ifconfig.me 2>/dev/null || echo localhost)"
  sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=[\"http://$IP\"]|" "$ENV_FILE"
  echo
  echo "  >>> EDIT $ENV_FILE — set OLLAMA_API_KEY and SEED_ADMIN_EMAIL — then re-run this script."
  echo
  exit 0
fi

if ! grep -q '^OLLAMA_API_KEY=.\+' "$ENV_FILE"; then
  echo "OLLAMA_API_KEY is empty in $ENV_FILE — set it and re-run." >&2
  exit 1
fi

# ---- 4. build + start -------------------------------------------------
mkdir -p deploy/certbot/www deploy/certbot/conf
echo "==> building & starting (first run takes a few minutes)"
$COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

echo "==> waiting for backend..."
for _ in $(seq 1 60); do
  if $COMPOSE -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T backend \
       python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" \
       >/dev/null 2>&1; then
    echo "==> backend healthy"; break
  fi
  sleep 3
done

IP="$(curl -fsS4 ifconfig.me 2>/dev/null || echo '<vps-ip>')"
echo
echo "======================================================================"
echo " Deployed.  Open  http://$IP"
grep -E '^SEED_ADMIN_(EMAIL|PASSWORD)=' "$ENV_FILE" | sed 's/^/   /'
echo
echo " Logs:     $COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE logs -f"
echo " Redeploy: git pull && sudo bash deploy/setup.sh"
echo " HTTPS:    see deploy/DEPLOY.md (needs a domain)"
echo "======================================================================"
