#!/usr/bin/env bash
# One-shot deploy for a fresh Ubuntu VPS. Run from the repo root:
#   sudo bash deploy/setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
ENV_FILE="deploy/.env.prod"

echo "==> AI Assistant deploy"

# ---- 1. swap (Next build is memory-hungry on small VPS) --------------------
if [ "$(free -m | awk '/^Swap:/ {print $2}')" -lt 1024 ]; then
  echo "==> creating 2G swapfile"
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---- 2. docker -----------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "==> installing docker"
  curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin missing — install docker-compose-plugin" >&2
  exit 1
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
  IP="$(curl -fsS4 ifconfig.me || echo localhost)"
  sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=[\"http://$IP\"]|" "$ENV_FILE"
  echo
  echo "  >>> EDIT $ENV_FILE and set OLLAMA_API_KEY (and SEED_ADMIN_EMAIL), then re-run this script."
  echo
  exit 0
fi

if ! grep -q '^OLLAMA_API_KEY=.\+' "$ENV_FILE"; then
  echo "OLLAMA_API_KEY is empty in $ENV_FILE — set it and re-run." >&2
  exit 1
fi

# ---- 4. build + start -------------------------------------------------
echo "==> building & starting containers (first run takes a few minutes)"
docker compose -f deploy/docker-compose.prod.yml --env-file "$ENV_FILE" up -d --build

echo "==> waiting for backend..."
for i in $(seq 1 60); do
  if docker compose -f deploy/docker-compose.prod.yml exec -T backend \
       python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" \
       >/dev/null 2>&1; then
    echo "==> backend healthy"
    break
  fi
  sleep 3
done

echo
echo "======================================================================"
echo " Deployed.  Open  http://$(curl -fsS4 ifconfig.me 2>/dev/null || echo '<vps-ip>')"
echo " Admin login:"
grep -E '^SEED_ADMIN_(EMAIL|PASSWORD)=' "$ENV_FILE" | sed 's/^/   /'
echo
echo " Logs:    docker compose -f deploy/docker-compose.prod.yml logs -f"
echo " HTTPS:   see deploy/DEPLOY.md (needs a domain)"
echo "======================================================================"
