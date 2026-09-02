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
port_busy() { ss -tlnH 2>/dev/null | awk '{print $4}' | grep -qE "(:|\.)$1$"; }
pick_port() { local p=$1; while port_busy "$p"; do p=$((p+100)); done; echo "$p"; }

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

# loopback ports the host proxy will reach (skip ones already in use)
FRONTEND_PORT="$(grep -oP '^FRONTEND_PORT=\K.*' "$ENV_FILE" 2>/dev/null || true)"
BACKEND_PORT="$(grep -oP '^BACKEND_PORT=\K.*' "$ENV_FILE" 2>/dev/null || true)"
[ -n "$FRONTEND_PORT" ] || FRONTEND_PORT="$(pick_port 3000)"
[ -n "$BACKEND_PORT" ]  || BACKEND_PORT="$(pick_port 8000)"
grep -q '^FRONTEND_PORT=' "$ENV_FILE" || echo "FRONTEND_PORT=$FRONTEND_PORT" >> "$ENV_FILE"
grep -q '^BACKEND_PORT='  "$ENV_FILE" || echo "BACKEND_PORT=$BACKEND_PORT"  >> "$ENV_FILE"
echo "==> loopback ports: frontend=$FRONTEND_PORT backend=$BACKEND_PORT"

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

CADDY_SNIPPET=/etc/caddy/ai-assistant.caddy
if [ "$BUNDLED" != 1 ]; then
  # site address = whatever users type (keep the scheme so Caddy doesn't
  # try to get a cert for a bare IP)
  ADDR="$(grep '^CORS_ORIGINS=' "$ENV_FILE" | cut -d= -f2 | cut -d, -f1)"
  [ -n "$ADDR" ] || ADDR="http://$IP"
  BLOCK="$ADDR {
	encode zstd gzip
	@api path /api/*
	handle @api {
		reverse_proxy 127.0.0.1:$BACKEND_PORT {
			flush_interval -1
		}
	}
	handle {
		reverse_proxy 127.0.0.1:$FRONTEND_PORT
	}
	request_body {
		max_size 10MB
	}
}"
  printf '%s\n' "$BLOCK" > deploy/Caddyfile.snippet
  [ -n "${SUDO_USER:-}" ] && chown "$SUDO_USER":"$SUDO_USER" deploy/Caddyfile.snippet || true
  # if the host runs Caddy and we can write its config dir, wire it up
  if command -v caddy >/dev/null 2>&1 && [ -d /etc/caddy ] && [ -w /etc/caddy ]; then
    printf '%s\n' "$BLOCK" > "$CADDY_SNIPPET"
    if [ -f /etc/caddy/Caddyfile ] && ! grep -q "import $CADDY_SNIPPET" /etc/caddy/Caddyfile; then
      echo "import $CADDY_SNIPPET" >> /etc/caddy/Caddyfile
    fi
    if caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
      systemctl reload caddy && CADDY_DONE=1
    fi
  fi
fi

echo
echo "======================================================================"
if [ "$BUNDLED" = 1 ]; then
  echo " Deployed.   http://$IP"
elif [ "${CADDY_DONE:-}" = 1 ]; then
  echo " Deployed & wired into Caddy.   $ADDR"
else
  echo " Stack up on 127.0.0.1:$FRONTEND_PORT / 127.0.0.1:$BACKEND_PORT."
  echo " Add to your host proxy — generated block: deploy/Caddyfile.snippet"
  echo "   Caddy:  sudo cp deploy/Caddyfile.snippet $CADDY_SNIPPET"
  echo "           echo 'import $CADDY_SNIPPET' | sudo tee -a /etc/caddy/Caddyfile"
  echo "           sudo systemctl reload caddy"
fi
grep -E '^SEED_ADMIN_(EMAIL|PASSWORD)=' "$ENV_FILE" | sed 's/^/   /'
echo
echo " Logs:     cd deploy && $COMPOSE -p $PROJECT logs -f backend"
echo " Redeploy: git pull && sudo bash deploy/setup.sh"
echo "======================================================================"
