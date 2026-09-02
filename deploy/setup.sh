#!/usr/bin/env bash
# One-shot deploy for a fresh Ubuntu VPS (Podman or Docker).
#   sudo bash deploy/setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
ENV_FILE="deploy/.env"
COMPOSE_FILE="docker-compose.prod.yml"   # run from inside deploy/
PROJECT="ai-assistant"

echo "==> AI Assistant deploy"

# ---- 1. swap ------------------------------------------------------------
if [ "$(free -m | awk '/^Swap:/ {print $2}')" -lt 1024 ]; then
  echo "==> creating 2G swapfile"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---- 2. engine + compose --------------------------------------------
if command -v podman >/dev/null 2>&1; then ENGINE=podman
elif command -v docker >/dev/null 2>&1; then ENGINE=docker
else echo "==> installing podman"; apt-get update -qq && apt-get install -y -qq podman; ENGINE=podman
fi

if $ENGINE compose version >/dev/null 2>&1; then
  COMPOSE="$ENGINE compose"
elif command -v podman-compose >/dev/null 2>&1; then
  COMPOSE="podman-compose"
else
  echo "==> installing podman-compose"
  apt-get update -qq && apt-get install -y -qq podman-compose \
    || { apt-get install -y -qq python3-pip && pip3 install -q podman-compose; }
  COMPOSE="podman-compose"
fi
echo "==> engine=$ENGINE  compose=$COMPOSE"

[ "$ENGINE" = podman ] && systemctl enable --now podman-restart.service 2>/dev/null || true

# ---- 3. env file ---------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  echo "==> generating $ENV_FILE"
  cp deploy/.env.example "$ENV_FILE"
  gen() { openssl rand -hex 24; }
  sed -i "s|^POSTGRES_PASSWORD_APP=.*|POSTGRES_PASSWORD_APP=$(gen)|" "$ENV_FILE"
  sed -i "s|^POSTGRES_PASSWORD_COMPANY=.*|POSTGRES_PASSWORD_COMPANY=$(gen)|" "$ENV_FILE"
  sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(gen)|" "$ENV_FILE"
  sed -i "s|^SEED_ADMIN_PASSWORD=.*|SEED_ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -dc 'A-Za-z0-9')|" "$ENV_FILE"
  IP="$(curl -fsS4 ifconfig.me 2>/dev/null || echo localhost)"
  sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=http://$IP|" "$ENV_FILE"
  [ -n "${SUDO_USER:-}" ] && chown "$SUDO_USER":"$SUDO_USER" "$ENV_FILE" || true
  chmod 600 "$ENV_FILE"
  echo
  echo "  >>> EDIT $ENV_FILE  (set OLLAMA_API_KEY and SEED_ADMIN_EMAIL)  then re-run this script."
  echo
  exit 0
fi

grep -q '^OLLAMA_API_KEY=.\+' "$ENV_FILE" || { echo "OLLAMA_API_KEY is empty in $ENV_FILE" >&2; exit 1; }

# ---- 4. bundled proxy or host proxy? ----------------------------
PORT80_LINE="$(ss -tlnpH 2>/dev/null | awk '$4 ~ /(:|\.)80$/' | head -1)"
FILES="-f $COMPOSE_FILE"
if [ -z "$PORT80_LINE" ]; then
  echo "==> port 80 free — using the bundled nginx"
  FILES="$FILES -f proxy.yml"
  BUNDLED=1
else
  NAME="$(printf '%s' "$PORT80_LINE" | grep -oE '"[^"]+"' | head -1 | tr -d '\"')"
  echo "==> port 80 is served by '${NAME:-another process}' — running behind it"
  BUNDLED=0
fi

# ---- 5. build + start -------------------------------------------
mkdir -p deploy/certbot/www deploy/certbot/conf
cd deploy
echo "==> stopping any previous stack"
$COMPOSE -p "$PROJECT" $FILES down --remove-orphans 2>/dev/null || true
echo "==> building & starting (first run: a few minutes)"
$COMPOSE -p "$PROJECT" $FILES up -d --build
cd "$REPO"

echo "==> waiting for backend (migrations + seed can take ~1 min)..."
BE="$($ENGINE ps --format '{{.Names}}' | grep -E "${PROJECT}[-_]backend[-_]1" | head -1)"
for _ in $(seq 1 60); do
  if [ -n "$BE" ] && $ENGINE exec "$BE" python -c \
       "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" \
       >/dev/null 2>&1; then
    echo "==> backend healthy"; break
  fi
  sleep 3
done

IP="$(curl -fsS4 ifconfig.me 2>/dev/null || echo '<vps-ip>')"

if [ "$BUNDLED" != 1 ]; then
  SITE="$(grep '^CORS_ORIGINS=' "$ENV_FILE" | cut -d= -f2 | cut -d, -f1)"
  case "$SITE" in http*) ADDR="${SITE#http://}"; ADDR="${ADDR#https://}";; *) ADDR=":80";; esac
  cat > deploy/Caddyfile.snippet <<EOF
$ADDR {
	encode zstd gzip
	@api path /api/*
	handle @api {
		reverse_proxy 127.0.0.1:8000 {
			flush_interval -1
		}
	}
	handle {
		reverse_proxy 127.0.0.1:3000
	}
	request_body {
		max_size 10MB
	}
}
EOF
  [ -n "${SUDO_USER:-}" ] && chown "$SUDO_USER":"$SUDO_USER" deploy/Caddyfile.snippet || true
fi

echo
echo "======================================================================"
if [ "$BUNDLED" = 1 ]; then
  echo " Deployed.   http://$IP"
else
  echo " Stack up on 127.0.0.1:3000 / 127.0.0.1:8000."
  echo
  echo " 1. add this line to /etc/caddy/Caddyfile:"
  echo "      import $REPO/deploy/Caddyfile.snippet"
  echo " 2. sudo systemctl reload caddy"
  echo
  echo " (generated block: deploy/Caddyfile.snippet — for site '$ADDR')"
fi
grep -E '^SEED_ADMIN_(EMAIL|PASSWORD)=' "$ENV_FILE" | sed 's/^/   /'
echo
echo " Logs:     cd deploy && $COMPOSE -p $PROJECT logs -f backend"
echo " Redeploy: git pull && sudo bash deploy/setup.sh"
echo "======================================================================"
