# Deploy — Ubuntu VPS

Everything runs in Docker: 2× Postgres, backend (FastAPI), frontend
(Next.js), nginx. One command brings it up.

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

It installs Docker, adds swap, then writes `deploy/.env.prod` with random
DB passwords + JWT secret and stops so you can fill in the rest.

## 3. Edit `deploy/.env.prod`

```bash
nano deploy/.env.prod
```

Set at least:
- `OLLAMA_API_KEY` — your Ollama Cloud key
- `SEED_ADMIN_EMAIL` — your login email
- (`SEED_ADMIN_PASSWORD` was auto-generated; change it if you like)
- `CORS_ORIGINS` — auto-set to `["http://<VPS-IP>"]`; change to your domain
  later, e.g. `["https://asisten.perusahaan.com"]`

## 4. Deploy

```bash
sudo bash deploy/setup.sh
```

Builds and starts everything (first build ~3–6 min). When it finishes it
prints the URL and the admin login. Open `http://<VPS-IP>`.

## 5. Open the firewall

```bash
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow OpenSSH
sudo ufw enable
```

Also open ports 80/443 in the VPS provider's security group / firewall panel.

---

## HTTPS (needs a domain)

Camera on phones and secure logins want HTTPS. Point a domain's A record at
the VPS IP, then:

```bash
# 1. put the domain in deploy/.env.prod -> CORS_ORIGINS=["https://your.domain"]
# 2. add the domain to deploy/nginx.conf: server_name your.domain;
# 3. issue the cert
sudo docker run --rm -v "$PWD/deploy/certbot/conf:/etc/letsencrypt" \
  -v "$PWD/deploy/certbot/www:/var/www/certbot" \
  -p 80:80 certbot/certbot certonly --standalone -d your.domain \
  --agree-tos -m you@email.com --no-eff-email
# 4. add the TLS server block to deploy/nginx.conf (listen 443 ssl; ssl_certificate ...)
# 5. restart
sudo docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod up -d
```

(Renewal: a monthly cron running `certbot renew` + `nginx -s reload`.)

---

## Day-to-day

```bash
CF="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod"

$CF ps                    # status
$CF logs -f backend       # tail logs
$CF up -d --build         # redeploy after `git pull`
$CF down                  # stop (data kept in volumes)
$CF exec backend python scripts/seed_prod.py   # re-run seed
```

### Point at the real company database

The sample stok/karyawan/transaksi data is loaded once on first boot. To use
the company's real DB instead:

1. `SEED_COMPANY_DATA=0` in `deploy/.env.prod`
2. Change `COMPANY_DATABASE_URL` / `COMPANY_DATABASE_WRITE_URL` in
   `deploy/docker-compose.prod.yml` to the real (read-only / scoped) DSNs
3. Make sure `v_stok`, `v_karyawan`, `v_transaksi` views exist there
   (template: `backend/scripts/seed_company_db.sql`)
4. `$CF up -d`

## Backups

```bash
$CF exec app_db pg_dump -U app app | gzip > app-$(date +%F).sql.gz
$CF exec company_db pg_dump -U company company | gzip > company-$(date +%F).sql.gz
```
