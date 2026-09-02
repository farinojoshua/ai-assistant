# Deploy — Ubuntu VPS (Podman or Docker)

Everything runs in containers: 2× Postgres, backend (FastAPI), frontend
(Next.js), nginx. One command brings it up. `setup.sh` auto-detects Podman
vs Docker.

## 1. Connect + get the code

```bash
ssh ubuntu@<VPS-IP>              # you type the password
sudo apt update && sudo apt install -y git
git clone https://github.com/farinojoshua/ai-assistant.git
cd ai-assistant
```

## 2. First run — generates the env file

```bash
sudo bash deploy/setup.sh
```

Adds swap, ensures a container engine + compose, writes `deploy/.env`
with random DB passwords + JWT secret, then stops so you can fill in the rest.

## 3. Edit `deploy/.env`

```bash
nano deploy/.env
```

Set at least:
- `OLLAMA_API_KEY` — your Ollama Cloud key
- `SEED_ADMIN_EMAIL` — your login email
- (`SEED_ADMIN_PASSWORD` was auto-generated — note it or change it)
- `CORS_ORIGINS` — auto-set to `http://<VPS-IP>`; change to your domain
  later, e.g. `https://asisten.perusahaan.com` (comma-separated for several)

## 4. Deploy

```bash
sudo bash deploy/setup.sh
```

Builds and starts everything (first build ~3–6 min). Prints the URL and the
admin login. Open `http://<VPS-IP>`.

## 5. Firewall

```bash
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow OpenSSH
sudo ufw enable
```

Also open 80/443 in the VPS provider's security-group / firewall panel.

---

## Day-to-day

`setup.sh` chooses the compose command. To run it by hand, work from
`deploy/` (so `.env` is picked up):

```bash
cd ~/ai-assistant/deploy
CF="podman compose -p ai-assistant -f docker-compose.prod.yml"   # or: docker compose ...

$CF ps                    # status
$CF logs -f backend       # tail logs
$CF down                  # stop (data kept in volumes)
$CF exec backend python scripts/seed_prod.py   # re-run seed

# redeploy after a code change:
cd ~/ai-assistant && git pull && sudo bash deploy/setup.sh
```

## HTTPS (needs a domain)

Camera on phones and secure logins want HTTPS. Point a domain's A record at
the VPS IP, then:

1. In `deploy/.env`: `CORS_ORIGINS=https://your.domain`
2. In `deploy/nginx.conf`: `server_name your.domain;`
3. Issue the cert:
   ```bash
   sudo $ENGINE run --rm -p 80:80 \
     -v "$PWD/deploy/certbot/conf:/etc/letsencrypt" \
     -v "$PWD/deploy/certbot/www:/var/www/certbot" \
     docker.io/certbot/certbot certonly --standalone -d your.domain \
     --agree-tos -m you@email.com --no-eff-email
   ```
   (`$ENGINE` = `podman` or `docker`)
4. Add a `listen 443 ssl;` server block to `deploy/nginx.conf` referencing
   `/etc/letsencrypt/live/your.domain/{fullchain,privkey}.pem`
5. `$CF up -d`

Renewal: monthly cron running `certbot renew` then `$CF exec nginx nginx -s reload`.

## Point at the real company database

The sample stok/karyawan/transaksi data loads once on first boot. To use the
company's real DB instead:

1. `SEED_COMPANY_DATA=0` in `deploy/.env`
2. Change `COMPANY_DATABASE_URL` / `COMPANY_DATABASE_WRITE_URL` in
   `deploy/docker-compose.prod.yml` to the real DSNs (read-only for the
   first, INSERT/UPDATE-on-stok_barang for the second)
3. Ensure `v_stok`, `v_karyawan`, `v_transaksi` exist there
   (template: `backend/scripts/seed_company_db.sql`)
4. `$CF up -d`

## Backups

```bash
$CF exec app_db pg_dump -U app app | gzip > app-$(date +%F).sql.gz
$CF exec company_db pg_dump -U company company | gzip > company-$(date +%F).sql.gz
```

## Troubleshooting

- **rootless podman can't bind port 80** — `setup.sh` runs under `sudo`
  (rootful) so this is fine. If you run compose by hand, use `sudo`.
- **`podman compose` not found** — `setup.sh` installs `podman-compose` as a
  fallback; both are supported.
- **backend restarts / "db never came up"** — check `$CF logs app_db`; the
  entrypoint waits up to 60s for each database.
