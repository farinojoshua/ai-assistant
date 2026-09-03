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

## HTTPS

Phone-camera uploads and secure logins need HTTPS. Point a subdomain's A
record at the VPS IP, then:

**Behind Caddy (host proxy)** — Caddy issues + auto-renews the cert:
```bash
cd ~/ai-assistant
sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=https://asisten.your-domain.com|' deploy/.env
sudo sed -i '1s|.*|asisten.your-domain.com {|' /etc/caddy/ai-assistant.caddy
cd deploy && sudo podman compose -p ai-assistant -f docker-compose.prod.yml down \
  && sudo podman compose -p ai-assistant -f docker-compose.prod.yml up -d
sudo systemctl reload caddy        # cert fetched in ~30s
```

**Bundled nginx** — use certbot:
```bash
sudo $ENGINE run --rm -p 80:80 \
  -v "$PWD/deploy/certbot/conf:/etc/letsencrypt" \
  -v "$PWD/deploy/certbot/www:/var/www/certbot" \
  docker.io/certbot/certbot certonly --standalone -d your.domain \
  --agree-tos -m you@email.com --no-eff-email
# add a `listen 443 ssl` block to deploy/nginx.conf, then `$CF up -d`
# renewal: monthly cron: certbot renew && $CF exec nginx nginx -s reload
```

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

## WhatsApp channel

Optional. Lets users chat with the assistant straight from WhatsApp, and/or
echoes web-chat answers to a number. Needs the site on a public HTTPS domain
(see above) — Meta only calls an HTTPS webhook.

1. **Meta setup** — App Dashboard → WhatsApp:
   - *API Setup*: note the **Phone number ID** and generate a permanent
     **System User** access token.
   - *Configuration → Webhook*: Callback URL
     `https://asisten.your-domain.com/api/wa/webhook`, Verify token = a string
     you invent. Click *Verify and save*, then **Subscribe** to the
     `messages` field.
   - *App → Settings → Basic*: copy the **App Secret**.

2. **`deploy/.env`** — fill in and redeploy (`sudo bash deploy/setup.sh`):
   ```
   WHATSAPP_TOKEN=<system user token>
   WHATSAPP_PHONE_NUMBER_ID=<phone number id>
   WHATSAPP_TO=<default number for the web echo toggle, digits only>
   WHATSAPP_VERIFY_TOKEN=<same string you gave Meta>
   WHATSAPP_APP_SECRET=<app secret>
   ```

3. **Whitelist numbers** — each inbound number must be linked to a user:
   ```bash
   $CF exec backend python scripts/link_wa.py --phone 6281385226502 --email admin@demo.test
   $CF exec backend python scripts/link_wa.py --list
   $CF exec backend python scripts/link_wa.py --phone 6281385226502 --disable
   ```
   Unlisted numbers get a "not registered" reply and are ignored.

Notes: outbound free-form messages only work within 24h of the user's last
message (Meta rule); the webhook acks instantly and runs the agent in the
background so replies arrive a few seconds later.

### Forwarder path (n8n etc.) — when Meta's webhook is already taken

Meta allows one callback URL per number. If it already points at another
system, forward from there (or n8n) to `POST /api/wa/relay` instead — no Meta
signature needed, just a shared secret:

```
WHATSAPP_RELAY_TOKEN=<invent a long random string>   # in deploy/.env
```

```bash
curl -X POST https://asisten.your-domain.com/api/wa/relay \
  -H 'content-type: application/json' \
  -H 'X-Relay-Token: <the same string>' \
  -d '{"from":"6281385226502","text":"total stok flashdisk","message_id":"wamid.optional"}'
```

`from` = sender's number (digits), `text` = message body, `message_id`
optional (dedup). The number still has to be linked with `link_wa.py`.

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
