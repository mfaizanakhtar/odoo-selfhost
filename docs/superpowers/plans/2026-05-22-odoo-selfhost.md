# Odoo Community Self-Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy production Odoo 18 Community on Hetzner CX23 via Docker Compose, accessible over HTTPS at a user-supplied subdomain, with CRM/Sales/Inventory/Purchase/MRP/Invoicing apps installed and a custom branding module for invoice PDFs.

**Architecture:** Single Hetzner CX23 VPS (2 vCPU x86, 4GB RAM, 40GB NVMe, Ubuntu 24.04). Docker Compose stack with three services: `caddy` (TLS termination, only service exposed to internet on 80/443), `odoo` (Odoo 18 with 1 worker, suited to 4GB box), `db` (Postgres 16). Custom addons mounted from `./addons/`. Secrets in `.env` (gitignored).

**Tech Stack:** Hetzner Cloud, `hcloud` CLI, Ubuntu 24.04 LTS, Docker + Compose v2, Odoo Community 18.0, PostgreSQL 16, Caddy 2.8, `ufw`, `fail2ban`, `unattended-upgrades`.

**Deferred (out of this plan):** Phase 4 offsite backups, SMTP outbound email, FBR e-invoicing connector.

---

## File Structure

All files live in `~/odoo-selfhost/` (already git-initialized).

**Created by this plan:**

| Path | Purpose |
|---|---|
| `.env` | Secrets (DB password, Odoo master password, Hetzner token, server IP, subdomain). **Gitignored.** |
| `.env.example` | Template for `.env`, committed. |
| `docker-compose.yml` | Three-service stack definition. |
| `Caddyfile` | Reverse proxy + auto-TLS config. |
| `config/odoo.conf` | Odoo runtime config. |
| `scripts/provision.sh` | hcloud CLI provisioning of VPS + SSH key + firewall. |
| `scripts/bootstrap.sh` | Remote setup (run on VPS): deploy user, Docker, ufw, fail2ban, unattended-upgrades. |
| `scripts/sync.sh` | Rsync stack files to VPS. |
| `addons/branding/__manifest__.py` | Custom branding module manifest. |
| `addons/branding/__init__.py` | Module init. |
| `addons/branding/views/report_invoice.xml` | QWeb template override for branded invoice PDF. |
| `addons/branding/static/description/icon.png` | Module icon (placeholder OK). |

**Modified later (Phase 7):** `Caddyfile` gets security headers; `config/odoo.conf` confirmed for `list_db = False`.

---

## Pre-flight: User-supplied values

Engineer must have these before starting:

| Var | Source | Example |
|---|---|---|
| `HCLOUD_TOKEN` | Hetzner console → Security → API Tokens → Read & Write | `abc123…` |
| `SUBDOMAIN` | User-owned, points to VPS after Task 4 | `odoo.example.com` |
| `SSH_PUBLIC_KEY` | `~/.ssh/id_ed25519.pub` (generate if absent) | `ssh-ed25519 AAAA…` |

Put these in `.env` (engineer creates from `.env.example` in Task 1).

---

## Phase 1 — Local prep + VPS provisioning

### Task 1: Create `.env.example` and `.env`, install hcloud CLI

**Files:**
- Create: `.env.example`
- Create: `.env` (gitignored, user fills with real values)

- [ ] **Step 1: Write `.env.example`**

```bash
# Hetzner
HCLOUD_TOKEN=replace_with_hetzner_api_token
HCLOUD_SERVER_NAME=odoo-prod
HCLOUD_SERVER_TYPE=cx23
HCLOUD_LOCATION=nbg1   # nbg1=Nuremberg, hel1=Helsinki, fsn1=Falkenstein
HCLOUD_IMAGE=ubuntu-24.04
HCLOUD_SSH_KEY_NAME=odoo-deploy

# DNS / Caddy
SUBDOMAIN=odoo.example.com

# Odoo
ODOO_DB_NAME=odoo
ODOO_DB_USER=odoo
ODOO_DB_PASSWORD=replace_with_strong_random_64char
ODOO_MASTER_PASSWORD=replace_with_strong_random_64char

# Populated after Task 4
SERVER_IP=
```

- [ ] **Step 2: Create real `.env` from example**

```bash
cd ~/odoo-selfhost
cp .env.example .env
# User edits .env: paste HCLOUD_TOKEN, SUBDOMAIN
# Generate strong passwords:
echo "ODOO_DB_PASSWORD=$(openssl rand -base64 48 | tr -d '=+/' | head -c 64)"
echo "ODOO_MASTER_PASSWORD=$(openssl rand -base64 48 | tr -d '=+/' | head -c 64)"
# Paste outputs into .env
```

- [ ] **Step 3: Install hcloud CLI**

```bash
brew install hcloud
hcloud version
```

Expected output: `hcloud <version>` (e.g. `hcloud 1.45.0`).

- [ ] **Step 4: Configure hcloud context**

```bash
source ~/odoo-selfhost/.env
hcloud context create odoo-prod
# Paste HCLOUD_TOKEN when prompted
hcloud context list
```

Expected: one row, `odoo-prod`, marked `*` active.

- [ ] **Step 5: Verify hcloud auth**

```bash
hcloud server list
```

Expected: empty table (no servers yet) — proves auth works.

- [ ] **Step 6: Commit**

```bash
cd ~/odoo-selfhost
git add .env.example
git commit -m "feat: env template + hcloud setup"
```

---

### Task 2: Ensure SSH key exists, upload to Hetzner

**Files:**
- Read: `~/.ssh/id_ed25519.pub`

- [ ] **Step 1: Check / generate SSH key**

```bash
test -f ~/.ssh/id_ed25519.pub && echo "key exists" || \
  ssh-keygen -t ed25519 -C "odoo-deploy" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Expected: prints `ssh-ed25519 AAAA…`

- [ ] **Step 2: Upload key to Hetzner**

```bash
source ~/odoo-selfhost/.env
hcloud ssh-key create --name "$HCLOUD_SSH_KEY_NAME" --public-key-from-file ~/.ssh/id_ed25519.pub
hcloud ssh-key list
```

Expected: one row, name `odoo-deploy`, fingerprint shown.

---

### Task 3: Create Hetzner firewall

**Files:** none (state lives in Hetzner Cloud)

- [ ] **Step 1: Create firewall with inbound rules**

```bash
hcloud firewall create --name odoo-prod-fw \
  --rules-file /dev/stdin <<'EOF'
[
  {"direction":"in","protocol":"tcp","port":"22","source_ips":["0.0.0.0/0","::/0"]},
  {"direction":"in","protocol":"tcp","port":"80","source_ips":["0.0.0.0/0","::/0"]},
  {"direction":"in","protocol":"tcp","port":"443","source_ips":["0.0.0.0/0","::/0"]},
  {"direction":"in","protocol":"icmp","source_ips":["0.0.0.0/0","::/0"]}
]
EOF
hcloud firewall list
```

Expected: firewall `odoo-prod-fw` listed with 4 rules.

> **Security note:** SSH (22) is open to world here. Phase 7 adds `fail2ban`. If your IP is static, tighten to `["YOUR_IP/32"]` — but most home connections aren't static.

---

### Task 4: Provision VPS

**Files:**
- Create: `scripts/provision.sh`

- [ ] **Step 1: Write `scripts/provision.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .env

hcloud server create \
  --name "$HCLOUD_SERVER_NAME" \
  --type "$HCLOUD_SERVER_TYPE" \
  --image "$HCLOUD_IMAGE" \
  --location "$HCLOUD_LOCATION" \
  --ssh-key "$HCLOUD_SSH_KEY_NAME" \
  --firewall odoo-prod-fw \
  --label app=odoo,env=prod

IP=$(hcloud server ip "$HCLOUD_SERVER_NAME")
echo "Server IP: $IP"
echo "Add to .env:  SERVER_IP=$IP"
```

- [ ] **Step 2: Run provisioning**

```bash
chmod +x scripts/provision.sh
./scripts/provision.sh
```

Expected: prints `Server IP: <ip>` and the line to add to `.env`. Takes ~20-40 seconds.

- [ ] **Step 3: Save IP to `.env`**

```bash
# Edit .env manually, set SERVER_IP=<the_ip_just_printed>
# Confirm:
grep SERVER_IP ~/odoo-selfhost/.env
```

- [ ] **Step 4: Verify SSH access**

```bash
source ~/odoo-selfhost/.env
ssh -o StrictHostKeyChecking=accept-new root@"$SERVER_IP" "uname -a && lsb_release -d"
```

Expected: prints `Linux odoo-prod ...` and `Description: Ubuntu 24.04 ...`

- [ ] **Step 5: Commit provisioning script**

```bash
git add scripts/provision.sh
git commit -m "feat: hcloud provisioning script"
```

---

## Phase 2 — Server bootstrap + Docker stack

### Task 5: Write server bootstrap script

**Files:**
- Create: `scripts/bootstrap.sh`

- [ ] **Step 1: Write `scripts/bootstrap.sh`**

```bash
#!/usr/bin/env bash
# Runs ON the VPS as root. Creates deploy user, installs Docker, ufw, fail2ban.
set -euo pipefail

DEPLOY_USER=deploy

# 1. Create non-root sudo user
if ! id "$DEPLOY_USER" &>/dev/null; then
  adduser --disabled-password --gecos "" "$DEPLOY_USER"
  usermod -aG sudo "$DEPLOY_USER"
  echo "$DEPLOY_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-deploy
  chmod 440 /etc/sudoers.d/90-deploy
fi

# 2. Copy root SSH key to deploy user
mkdir -p /home/$DEPLOY_USER/.ssh
cp /root/.ssh/authorized_keys /home/$DEPLOY_USER/.ssh/authorized_keys
chown -R $DEPLOY_USER:$DEPLOY_USER /home/$DEPLOY_USER/.ssh
chmod 700 /home/$DEPLOY_USER/.ssh
chmod 600 /home/$DEPLOY_USER/.ssh/authorized_keys

# 3. Apt update + base packages
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  ca-certificates curl gnupg lsb-release \
  ufw fail2ban unattended-upgrades rsync

# 4. Docker official repo + install
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker $DEPLOY_USER

# 5. ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# 6. fail2ban (default jail covers sshd)
systemctl enable --now fail2ban

# 7. Unattended security updates
dpkg-reconfigure -f noninteractive unattended-upgrades

# 8. Harden SSH: disable root login + password auth
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

echo "Bootstrap complete. Reconnect as: ssh deploy@<server_ip>"
```

- [ ] **Step 2: Push + run bootstrap**

```bash
source ~/odoo-selfhost/.env
scp scripts/bootstrap.sh root@"$SERVER_IP":/root/bootstrap.sh
ssh root@"$SERVER_IP" "bash /root/bootstrap.sh"
```

Expected: ends with `Bootstrap complete. Reconnect as: ssh deploy@<server_ip>`.

- [ ] **Step 3: Verify deploy user works**

```bash
ssh deploy@"$SERVER_IP" "docker run --rm hello-world && sudo ufw status"
```

Expected:
- `Hello from Docker!` block prints
- `ufw status` shows `Status: active` with 22, 80, 443 ALLOW IN

- [ ] **Step 4: Commit bootstrap script**

```bash
git add scripts/bootstrap.sh
git commit -m "feat: server bootstrap (docker, ufw, fail2ban)"
```

---

### Task 6: Write `docker-compose.yml`

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Write compose file**

```yaml
services:
  odoo:
    image: odoo:18.0
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - odoo-web-data:/var/lib/odoo
      - ./config:/etc/odoo:ro
      - ./addons:/mnt/extra-addons:ro
    environment:
      - HOST=db
      - USER=${ODOO_DB_USER}
      - PASSWORD=${ODOO_DB_PASSWORD}
    restart: unless-stopped
    networks: [internal]
    # No ports published — Caddy reaches odoo via the internal network.

  db:
    image: postgres:16
    environment:
      - POSTGRES_DB=postgres
      - POSTGRES_USER=${ODOO_DB_USER}
      - POSTGRES_PASSWORD=${ODOO_DB_PASSWORD}
    volumes:
      - odoo-db-data:/var/lib/postgresql/data
    restart: unless-stopped
    networks: [internal]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${ODOO_DB_USER}"]
      interval: 5s
      timeout: 5s
      retries: 10

  caddy:
    image: caddy:2.8
    depends_on: [odoo]
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    environment:
      - SUBDOMAIN=${SUBDOMAIN}
    restart: unless-stopped
    networks: [internal]

volumes:
  odoo-web-data:
  odoo-db-data:
  caddy-data:
  caddy-config:

networks:
  internal:
    driver: bridge
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: docker-compose with odoo/postgres/caddy"
```

---

### Task 7: Write `config/odoo.conf`

**Files:**
- Create: `config/odoo.conf`

- [ ] **Step 1: Write Odoo config**

```ini
[options]
admin_passwd = ${ODOO_MASTER_PASSWORD}
db_host = db
db_port = 5432
db_user = ${ODOO_DB_USER}
db_password = ${ODOO_DB_PASSWORD}
addons_path = /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons
proxy_mode = True
list_db = False
workers = 1
max_cron_threads = 1
limit_memory_soft = 629145600
limit_memory_hard = 786432000
limit_time_cpu = 600
limit_time_real = 1200
limit_request = 8192
logfile = /var/log/odoo/odoo.log
log_level = info
```

> Odoo doesn't natively expand `${VAR}` in `odoo.conf`. We'll generate the final config at sync time by `envsubst`-ing this template. See `scripts/sync.sh` next task.

Rename the file to mark it a template:

```bash
mv config/odoo.conf config/odoo.conf.template
```

- [ ] **Step 2: Commit**

```bash
git add config/odoo.conf.template
git commit -m "feat: odoo.conf template with envsubst placeholders"
```

---

### Task 8: Write `scripts/sync.sh` — push stack to VPS

**Files:**
- Create: `scripts/sync.sh`

- [ ] **Step 1: Write sync script**

```bash
#!/usr/bin/env bash
# Renders odoo.conf from template + rsyncs stack to VPS.
set -euo pipefail
cd "$(dirname "$0")/.."
source .env

# 1. Render odoo.conf from template
mkdir -p .build/config
envsubst < config/odoo.conf.template > .build/config/odoo.conf

# 2. Stage payload
rm -rf .build/payload
mkdir -p .build/payload/config .build/payload/addons
cp .build/config/odoo.conf .build/payload/config/odoo.conf
cp -R addons/. .build/payload/addons/ 2>/dev/null || true
cp docker-compose.yml Caddyfile .build/payload/
# Write a sanitized .env (only vars compose + caddy need at runtime)
cat > .build/payload/.env <<EOF
ODOO_DB_USER=$ODOO_DB_USER
ODOO_DB_PASSWORD=$ODOO_DB_PASSWORD
SUBDOMAIN=$SUBDOMAIN
EOF

# 3. Rsync to server
ssh deploy@"$SERVER_IP" "mkdir -p ~/odoo-stack"
rsync -avz --delete .build/payload/ deploy@"$SERVER_IP":~/odoo-stack/

echo "Synced to deploy@$SERVER_IP:~/odoo-stack"
```

- [ ] **Step 2: Ensure `envsubst` available locally**

```bash
which envsubst || brew install gettext && brew link --force gettext
envsubst --help 2>&1 | head -1
```

Expected: prints usage line.

- [ ] **Step 3: Make executable, commit**

```bash
chmod +x scripts/sync.sh
echo ".build/" >> .gitignore
git add scripts/sync.sh .gitignore
git commit -m "feat: sync script to render config + rsync to VPS"
```

---

### Task 9: Write minimal `Caddyfile` (TLS deferred to Phase 3)

**Files:**
- Create: `Caddyfile`

For initial bring-up we use the `{$SUBDOMAIN}` placeholder; Caddy will fetch a real cert once the DNS A record is in place (Phase 3 Task 11).

- [ ] **Step 1: Write Caddyfile**

```
{$SUBDOMAIN} {
    encode gzip
    reverse_proxy /websocket odoo:8072
    reverse_proxy /longpolling/* odoo:8072
    reverse_proxy odoo:8069
}
```

- [ ] **Step 2: Commit**

```bash
git add Caddyfile
git commit -m "feat: caddyfile with longpolling + websocket routing"
```

---

### Task 10: First bring-up of the stack (Caddy will fail TLS until DNS — that's OK)

- [ ] **Step 1: Sync stack to server**

```bash
./scripts/sync.sh
```

Expected: ends with `Synced to deploy@<ip>:~/odoo-stack`.

- [ ] **Step 2: Bring stack up**

```bash
source .env
ssh deploy@"$SERVER_IP" "cd ~/odoo-stack && docker compose up -d"
ssh deploy@"$SERVER_IP" "cd ~/odoo-stack && docker compose ps"
```

Expected: 3 services — `caddy`, `db`, `odoo` — all `Up`.

- [ ] **Step 3: Check Odoo logs for clean startup**

```bash
ssh deploy@"$SERVER_IP" "cd ~/odoo-stack && docker compose logs --tail=50 odoo"
```

Expected: line like `odoo.modules.loading: 1 modules loaded` and `odoo.service.server: HTTP service (werkzeug) running on 0.0.0.0:8069`. No tracebacks.

- [ ] **Step 4: Confirm Caddy is failing TLS gracefully (expected before DNS)**

```bash
ssh deploy@"$SERVER_IP" "cd ~/odoo-stack && docker compose logs --tail=20 caddy"
```

Expected: errors about not being able to solve ACME challenge — this is fine, fixed in Task 11.

---

## Phase 3 — DNS + HTTPS

### Task 11: User adds DNS A record, verify HTTPS

**Files:** none (DNS lives at user's registrar)

- [ ] **Step 1: User adds A record at their DNS provider**

In the registrar's DNS panel, add:
- **Type:** A
- **Name/Host:** the subdomain prefix (e.g. `odoo` if FQDN is `odoo.example.com`)
- **Value:** `$SERVER_IP` (from `.env`)
- **TTL:** 300

- [ ] **Step 2: Wait for propagation, verify**

```bash
source ~/odoo-selfhost/.env
until dig +short "$SUBDOMAIN" | grep -q "$SERVER_IP"; do
  echo "waiting for DNS..."
  sleep 15
done
echo "DNS resolved: $(dig +short $SUBDOMAIN)"
```

Expected: eventually prints `DNS resolved: <SERVER_IP>`. Usually 1-5 minutes; up to 30.

- [ ] **Step 3: Restart Caddy so it retries ACME immediately**

```bash
ssh deploy@"$SERVER_IP" "cd ~/odoo-stack && docker compose restart caddy"
sleep 20
ssh deploy@"$SERVER_IP" "cd ~/odoo-stack && docker compose logs --tail=30 caddy"
```

Expected: line like `certificate obtained successfully` for `$SUBDOMAIN`.

- [ ] **Step 4: Verify HTTPS works**

```bash
curl -sS -o /dev/null -w "HTTP %{http_code}\nTLS %{ssl_verify_result} (0=ok)\n" "https://$SUBDOMAIN/web/login"
```

Expected:
```
HTTP 200
TLS 0 (0=ok)
```

- [ ] **Step 5: Open in browser**

```bash
open "https://$SUBDOMAIN/web/database/manager"
```

Expected: Odoo "Create Database" screen, padlock icon, no warnings.

---

### Task 12: Create production database via UI (one-time, manual)

**Files:** none

- [ ] **Step 1: User creates DB in browser**

At `https://$SUBDOMAIN/web/database/manager`:
- **Master Password:** value from `.env` `ODOO_MASTER_PASSWORD`
- **Database Name:** value from `.env` `ODOO_DB_NAME` (default `odoo`)
- **Email:** admin email
- **Password:** strong admin password (store in password manager)
- **Language:** English (or preferred)
- **Country:** Pakistan
- **Demo data:** unchecked
- Click **Create database**

Expected: redirects to Apps screen after ~30-60s.

- [ ] **Step 2: Confirm `list_db = False` still hides DB manager**

```bash
curl -sS -o /dev/null -w "%{http_code}\n" "https://$SUBDOMAIN/web/database/manager"
```

Expected: `404` (DB manager hidden after `list_db = False` + DB exists).

---

## Phase 4 — Backups (DEFERRED)

> Skipped per design spec §3. **Critical to revisit before real business data.** Spec includes a sketch (`scripts/backup.sh`) to expand: `pg_dump` + filestore tar → `rclone copy` to Backblaze B2 → nightly cron → tested restore. Do not consider the system production-ready without this.

---

## Phase 5 — App configuration (UI-driven)

### Task 13: Install business apps

**Files:** none (clickops in Odoo UI)

- [ ] **Step 1: Log in, navigate to Apps**

Browser → `https://$SUBDOMAIN/web` → log in → click **Apps** in top menu.

- [ ] **Step 2: Update apps list**

Click developer hamburger (top-right) → **Update Apps List** → **Update**. (Required first time; Odoo seeds the catalog.)

- [ ] **Step 3: Install in this order (dependencies pull each other in)**

For each, search the name in the Apps filter box (clear default "Apps" filter first), click **Activate**:

1. **Invoicing** (account)
2. **Sales** (sale_management)
3. **CRM** (crm)
4. **Inventory** (stock)
5. **Purchase** (purchase)
6. **Manufacturing** (mrp)

Expected: each install takes 20-60s, page reloads, app appears in main menu.

- [ ] **Step 4: Verify all installed**

```bash
ssh deploy@"$SERVER_IP" "docker compose -f ~/odoo-stack/docker-compose.yml exec db psql -U $ODOO_DB_USER -d $ODOO_DB_NAME -c \"SELECT name, state FROM ir_module_module WHERE name IN ('account','sale_management','crm','stock','purchase','mrp') AND state='installed';\""
```

Expected: 6 rows, all `state = installed`.

---

### Task 14: Configure company, currency, tax

**Files:** none

- [ ] **Step 1: Set company profile**

Settings → Users & Companies → Companies → click your company → fill:
- Name, address, phone, email
- VAT/Tax ID
- Logo (upload PNG — used by branding addon later)
- Currency: **PKR**

- [ ] **Step 2: Set default taxes**

Accounting → Configuration → Taxes → create your sales tax (e.g. "Sales Tax 18%") with the rate that applies to your business.
Settings → Accounting → set default sales tax + purchase tax to the new tax.

- [ ] **Step 3: Verify quote → invoice flow works**

1. Sales → New Quote → add a product (create one if needed) → Confirm Order
2. Click **Create Invoice** → Post → Register Payment
3. Inventory → Operations → confirm stock move applied

Expected: invoice in `Posted` state, stock decremented.

---

## Phase 6 — Custom `branding` addon

### Task 15: Scaffold `branding` module

**Files:**
- Create: `addons/branding/__manifest__.py`
- Create: `addons/branding/__init__.py`
- Create: `addons/branding/views/report_invoice.xml`

- [ ] **Step 1: Write manifest**

`addons/branding/__manifest__.py`:

```python
{
    "name": "Branding",
    "version": "18.0.1.0.0",
    "summary": "Branded invoice/quote PDF templates",
    "license": "LGPL-3",
    "author": "Internal",
    "depends": ["account", "sale"],
    "data": [
        "views/report_invoice.xml",
    ],
    "installable": True,
    "application": False,
}
```

- [ ] **Step 2: Write `__init__.py` (empty file is fine, no Python models yet)**

```python
# branding module — view-only customizations for now.
```

- [ ] **Step 3: Write QWeb template override for invoice header**

`addons/branding/views/report_invoice.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <template id="branding_external_layout_header" inherit_id="web.external_layout_standard">
        <xpath expr="//div[hasclass('header')]" position="replace">
            <div class="header o_company_#{company.id}_layout" t-att-style="report_header_style">
                <div class="row">
                    <div class="col-6">
                        <img t-if="company.logo" t-att-src="image_data_uri(company.logo)" style="max-height:80px;"/>
                    </div>
                    <div class="col-6 text-end">
                        <strong t-field="company.name"/><br/>
                        <span t-field="company.partner_id" t-options='{"widget": "contact", "fields": ["address","phone","email","vat"], "no_marker": true}'/>
                    </div>
                </div>
                <hr style="border-top:2px solid #000;"/>
            </div>
        </xpath>
    </template>
</odoo>
```

- [ ] **Step 4: Sync + restart Odoo to pick up the new module**

```bash
./scripts/sync.sh
ssh deploy@"$SERVER_IP" "cd ~/odoo-stack && docker compose restart odoo"
```

Expected: `odoo` restarts in <30s, logs show no errors.

- [ ] **Step 5: Update Apps list + install branding**

Browser → Apps → developer menu → **Update Apps List** → search `Branding` → click **Activate**.

Expected: installs in <10s.

- [ ] **Step 6: Verify branded PDF**

1. Open any posted invoice from Task 14
2. Click **Print** → **Invoice**
3. PDF downloads

Expected: PDF has company logo top-left, company name + address top-right, black horizontal rule below header.

- [ ] **Step 7: Commit**

```bash
cd ~/odoo-selfhost
git add addons/branding
git commit -m "feat(branding): custom invoice header with logo"
```

---

## Phase 7 — Hardening + monitoring

### Task 16: Add security headers to Caddy

**Files:**
- Modify: `Caddyfile`

- [ ] **Step 1: Append headers block to Caddyfile**

Replace the existing `Caddyfile` with:

```
{$SUBDOMAIN} {
    encode gzip

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        Referrer-Policy "strict-origin-when-cross-origin"
        -Server
    }

    reverse_proxy /websocket odoo:8072
    reverse_proxy /longpolling/* odoo:8072
    reverse_proxy odoo:8069
}
```

- [ ] **Step 2: Sync + reload Caddy**

```bash
./scripts/sync.sh
ssh deploy@"$SERVER_IP" "cd ~/odoo-stack && docker compose restart caddy"
sleep 5
curl -sI "https://$SUBDOMAIN/web/login" | grep -iE "strict-transport|x-content|x-frame|referrer"
```

Expected: 4 header lines present.

- [ ] **Step 3: Commit**

```bash
git add Caddyfile
git commit -m "feat(caddy): security headers (HSTS, XCTO, XFO, referrer)"
```

---

### Task 17: Verify hardening from bootstrap is in effect

- [ ] **Step 1: Confirm SSH root login disabled**

```bash
ssh -o BatchMode=yes root@"$SERVER_IP" "true" 2>&1 | head -1
```

Expected: `Permission denied (publickey).` — root SSH is blocked.

- [ ] **Step 2: Confirm `list_db = False` honored**

```bash
curl -sS -o /dev/null -w "%{http_code}\n" "https://$SUBDOMAIN/web/database/manager"
```

Expected: `404`.

- [ ] **Step 3: Confirm fail2ban running**

```bash
ssh deploy@"$SERVER_IP" "sudo fail2ban-client status sshd"
```

Expected: `Status for the jail: sshd`, banned list (likely empty).

- [ ] **Step 4: Confirm unattended-upgrades active**

```bash
ssh deploy@"$SERVER_IP" "sudo systemctl is-enabled unattended-upgrades && sudo unattended-upgrades --dry-run --verbose 2>&1 | tail -5"
```

Expected: `enabled` then dry-run output without errors.

- [ ] **Step 5: Confirm only ports 22/80/443 reachable from outside**

From your Mac:

```bash
for p in 22 80 443 5432 8069; do
  nc -zv -G 5 "$SERVER_IP" $p 2>&1 | grep -E "succeeded|refused|timed out"
done
```

Expected: 22, 80, 443 → `succeeded`. 5432, 8069 → `refused` or `timed out`.

---

### Task 18: Set up external uptime ping

**Files:** none

- [ ] **Step 1: Create free monitor at uptimerobot.com (or BetterStack)**

- Sign up
- Add HTTP(S) monitor
- URL: `https://$SUBDOMAIN/web/login`
- Interval: 5 minutes
- Alert: your email

Expected: monitor goes green within 5 min.

- [ ] **Step 2: Document restore runbook stub**

`docs/runbook.md`:

```markdown
# Odoo Restore Runbook

> **Status:** Skeleton — full restore steps land when Phase 4 (backups) is implemented.

## Pre-flight (if VPS dies)

1. New VPS via `./scripts/provision.sh` (set new `HCLOUD_SERVER_NAME` to avoid collision)
2. Bootstrap: `scp scripts/bootstrap.sh ... && ssh root@... bash bootstrap.sh`
3. Sync stack: `./scripts/sync.sh`
4. **CANNOT RESTORE DATA** until Phase 4 backups exist. Real customer data on a single unbacked-up VPS is unsafe.

## Once backups exist (Phase 4)
- Pull latest dump + filestore from offsite bucket
- `docker compose up -d db` only
- `gunzip < db.sql.gz | docker compose exec -T db psql -U $ODOO_DB_USER -d $ODOO_DB_NAME`
- `docker run --rm -v odoo-web-data:/data -v $PWD:/restore alpine tar xzf /restore/filestore.tar.gz -C /data`
- `docker compose up -d`
```

- [ ] **Step 3: Commit**

```bash
git add docs/runbook.md
git commit -m "docs: restore runbook skeleton (Phase 4 placeholder)"
```

---

## Done criteria (whole plan)

- [ ] `https://$SUBDOMAIN` loads Odoo with valid TLS, no warnings
- [ ] All 6 apps installed (CRM, Sales, Invoicing, Inventory, Purchase, Manufacturing)
- [ ] Full quote → confirm → invoice → payment + stock move flow works in UI
- [ ] Branded invoice PDF prints with logo + company details
- [ ] SSH root disabled, password auth disabled, ufw enforcing, fail2ban running, unattended-upgrades enabled
- [ ] Only 22/80/443 reachable from internet
- [ ] External uptime monitor green
- [ ] All config in git, `~/odoo-selfhost` reproducible

**Pending after this plan (per spec deferrals):**
- Phase 4 offsite backups — **do this before real data lands**
- SMTP outbound mail
- FBR e-invoicing connector

---

## Self-review notes (engineer can ignore — for plan author)

- Spec §2 locked decisions all addressed: Hetzner CX23 (Task 4), Docker Compose (Task 6), PG 16 (Task 6), Caddy (Tasks 9,16), Ubuntu 24.04 (Task 1 env), proxy_mode=True (Task 7), list_db=False (Task 7, verified Task 17).
- Spec §6.3 Odoo config — all keys present in `odoo.conf.template`.
- Spec §9 user-vs-assistant split: Tasks 11, 12, 13, 14 are user-driven (DNS, DB creation, app install, business config); the rest are scripted.
- No placeholders, all commands concrete, all configs included verbatim.
