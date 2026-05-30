# Self-Hosted Odoo ERP — Project Plan & Build Brief

> **Purpose of this file:** A planning + context document to hand to Claude Code. Save it in your project repo (e.g. as `PLAN.md` or `CLAUDE.md`) and have Claude Code work through it phase by phase. It captures the decisions already made, the architecture, the build steps, and the open questions, so Claude Code has full context without re-deriving everything.

---

## 1. Goal

Stand up a self-hosted **Odoo Community Edition** ERP for a very small team, running in Docker on a cheap VPS, serving normal business operations: **CRM/Sales, Invoicing, Inventory, Purchase, and basic Manufacturing** — all integrated. Cheap to run, reliable enough for real business data, and extensible with custom modules over time.

Success = a team member can log in over HTTPS, manage the full quote → sale → delivery → invoice flow against live inventory, and the data is safely backed up off the server every night.

---

## 2. Key decisions (already made — treat as locked unless flagged)

| Decision | Choice | Why |
|---|---|---|
| ERP platform | **Odoo Community Edition** (open source, LGPLv3) | Free license; strong CRM/sales/inventory/manufacturing; large module ecosystem |
| Edition | Community, **not** Enterprise | No subscription; dev work (with Claude Code) covers the gap |
| Deployment | **Self-hosted via Docker** | Cheap, portable, full control; same setup on any host |
| Database | **PostgreSQL** (containerized) | Odoo's required DB |
| Reverse proxy / TLS | **Caddy** | Automatic HTTPS with near-zero config |
| Hosting | **Cheap VPS** — leading candidate **Contabo Cloud VPS 10/20** (Singapore region for PK latency); alternatives: Oracle Cloud Always Free (\$0, ARM), Hetzner CX22, LightNode (PK-local) | ~\$5–8/mo, 8–12 GB RAM, plenty for a small deployment |
| Region | Prefer **Asia (Singapore) or PK-local** | Lower latency to Pakistan than EU |

---

## 3. Out of scope (for now)

- **FBR e-invoicing integration is intentionally NOT being built right now.** (User decision.)
  - ⚠️ Compliance note for future awareness: Pakistan requires sales-tax-registered businesses dealing in goods to issue digital invoices integrated with FBR in real time via a licensed integrator (PRAL or others), and a full transition phasing out manual sales-tax invoices is underway (target mid-2026). If/when the business becomes registered/in-scope, this becomes mandatory, not optional. **Architect the invoicing workflow so an FBR connector can be bolted on later** (see Phase 8) without re-doing the data model.
- Full statutory accounting (bank reconciliation, OCR, formal financial statements) — Community's accounting is invoicing-grade; books handed to an accountant for now.
- Multi-company, advanced HR/payroll, e-commerce storefront.

---

## 4. Tech stack

- **Odoo Community** — official Docker image (`odoo:18.0`, or current stable tag; confirm latest at build time).
- **PostgreSQL 16** — official image.
- **Caddy 2** — reverse proxy + automatic Let's Encrypt TLS.
- **Docker + Docker Compose** — orchestration.
- **Host OS:** Ubuntu LTS (22.04/24.04) on the VPS.
- **Backups:** `pg_dump` + Odoo filestore → compressed → pushed offsite (e.g. Contabo Object Storage / any S3-compatible bucket via `rclone` or `aws s3`).
- A **domain name** is required for HTTPS (point an A record at the VPS IP).

> ⚠️ If hosting on **Oracle Cloud Always Free (ARM)**, confirm the Odoo image tag supports `arm64` and pull the matching Postgres arch. On Contabo/Hetzner (x86) this is a non-issue.

---

## 5. Target architecture

```
                Internet (HTTPS :443)
                        │
                        ▼
              ┌───────────────────┐
              │   Caddy (proxy)   │  ← auto TLS, terminates HTTPS,
              │                   │    forwards to Odoo, sets headers
              └─────────┬─────────┘
                        │ (internal docker network, :8069 / :8072 longpolling)
                        ▼
              ┌───────────────────┐        ┌────────────────────┐
              │   Odoo (web)      │ ─────► │  PostgreSQL 16      │
              │   workers + cron  │        │  (internal only)    │
              └─────────┬─────────┘        └────────────────────┘
                        │ volumes
          ┌─────────────┴──────────────┐
          │ odoo-web-data (filestore)  │
          │ odoo-db-data (postgres)    │
          │ ./addons (custom modules)  │
          │ ./config (odoo.conf)       │
          └────────────────────────────┘
                        │ nightly
                        ▼
              Offsite backup bucket (S3-compatible)
```

Key points:
- Only Caddy is exposed to the internet (ports 80/443). Odoo and Postgres are **not** published to the host's public interface — they talk over the internal Docker network.
- Postgres is never exposed publicly.
- `proxy_mode = True` in Odoo so it trusts Caddy's forwarded headers.

---

## 6. Phased build plan

Work through these in order. Each phase has concrete tasks and a "done when" check. Tell Claude Code which phase you're on.

### Phase 0 — Local prototype (optional but recommended)
- [ ] Run the stack locally with Docker Compose, no proxy, on `localhost:8069`.
- [ ] Create a test database, install the target apps, click around.
- **Done when:** you've confirmed the apps cover your workflow before paying for a server.

### Phase 1 — Provision the server
- [ ] Pick host + region + plan (default: Contabo Cloud VPS 10/20, Singapore; annual billing to skip setup fee).
- [ ] Create Ubuntu LTS VPS, SSH in, create a non-root sudo user, add SSH key, disable password login.
- [ ] Install Docker + Docker Compose plugin.
- [ ] Point your domain's A record at the server IP.
- **Done when:** you can `ssh` in as a non-root user and `docker run hello-world` works.

### Phase 2 — Deploy Odoo + PostgreSQL via Docker Compose
- [ ] Create project dir with `docker-compose.yml`, `./config/odoo.conf`, `./addons/`.
- [ ] Set a strong **master (admin) password** in `odoo.conf` (`admin_passwd`).
- [ ] Configure `odoo.conf`: `db_host`, `proxy_mode = True`, `list_db = False` (hide DB manager), `workers` set per CPU (start with `workers = 2` on a 4-vCPU box), `limit_*` memory settings.
- [ ] `docker compose up -d`; create the production database via the UI (once), then keep DB listing disabled.
- **Done when:** Odoo reachable on the server's internal port and the prod DB exists.

### Phase 3 — Reverse proxy + HTTPS (Caddy)
- [ ] Add Caddy service to the compose stack with a `Caddyfile` for your domain.
- [ ] Reverse-proxy `your.domain` → `odoo:8069`, and route the longpolling/websocket path → `odoo:8072`.
- [ ] Stop publishing Odoo/Postgres ports to the host; only Caddy exposes 80/443.
- **Done when:** `https://your.domain` loads Odoo with a valid certificate, no port number, no cert warnings.

### Phase 4 — Backups (do NOT skip — this is the real "reliability")
- [ ] Write a backup script: `pg_dump` the Odoo DB + tar the filestore volume, timestamp + compress.
- [ ] Push the archive to an **offsite** S3-compatible bucket (Contabo Object Storage, Backblaze B2, etc.) via `rclone`/`aws`.
- [ ] Schedule nightly via cron (or a systemd timer); keep a rolling retention (e.g. 7 daily + 4 weekly).
- [ ] **Test a restore** into a throwaway DB. A backup you haven't restored is not a backup.
- **Done when:** last night's backup exists in the bucket AND you've successfully restored it once.

### Phase 5 — App configuration
- [ ] Install apps: **CRM, Sales, Inventory, Purchase, Manufacturing, Invoicing** (+ Accounting/Invoicing module).
- [ ] Set up: company profile, currency (PKR), users + roles, product catalog, warehouse(s), basic chart of accounts / tax config (your VAT/sales-tax rate), email (outgoing SMTP) for sending invoices/quotes.
- [ ] Configure the sales → delivery → invoice flow and confirm stock moves correctly.
- **Done when:** you can run a full quote→invoice cycle and inventory updates as expected.

### Phase 6 — Customization (where Claude Code earns its keep)
- [ ] Scaffold a custom module in `./addons/` (e.g. `branding`) for a branded invoice/quote PDF (QWeb report template) with logo, company details, footer.
- [ ] Add any tailored fields, automated email rules, or report tweaks as needed.
- [ ] Keep customizations as version-controlled modules in `./addons/`, **not** by editing core — so upgrades stay manageable.
- **Done when:** invoices print with your branding and custom modules load cleanly.

### Phase 7 — Hardening & ops
- [ ] `ufw` firewall: allow 22, 80, 443 only.
- [ ] `fail2ban` for SSH.
- [ ] Confirm `list_db = False` and a strong `admin_passwd`.
- [ ] Unattended security updates on the host.
- [ ] Basic uptime monitoring (e.g. Uptime Kuma or an external ping service) + disk-space alert.
- [ ] Document the restore procedure in the repo.
- **Done when:** firewall is on, monitoring pings green, restore runbook is written.

### Phase 8 — FUTURE (parked): FBR e-invoicing
> Only if/when the business is sales-tax registered and in scope. Do not build now.
- Check for an existing maintained Odoo↔FBR connector module before writing one.
- Integrate via an FBR-**licensed integrator** API (you cannot connect to FBR directly).
- Handle: real-time invoice submission, the returned invoice number/QR, the 72-hour amendment window, and retry logic for internet-disruption rules.
- Treat issued e-invoices as near-immutable in the workflow.

---

## 7. Reliability principles (single-box self-host)

- **Backups are the reliability story**, not the host's brand. Nightly, offsite, tested restores.
- Keep the stack reproducible: everything in `docker-compose.yml` + config in the repo, so a rebuild on a fresh VPS is a `git clone` + `docker compose up` + restore.
- Don't edit Odoo core. All changes = versioned custom modules in `./addons/`.
- Pin image tags (don't run `:latest` in prod) so restarts are predictable.

---

## 8. Starting configs (refine, don't trust blindly)

> Starting point only. **Change every default credential before exposing anything.** Have Claude Code review/tighten these for the chosen host.

**`docker-compose.yml`**
```yaml
services:
  odoo:
    image: odoo:18.0
    depends_on: [db]
    volumes:
      - odoo-web-data:/var/lib/odoo
      - ./config:/etc/odoo
      - ./addons:/mnt/extra-addons
    environment:
      - HOST=db
      - USER=odoo
      - PASSWORD=CHANGE_ME_DB_PASSWORD
    restart: unless-stopped
    # NOTE: no ports published — Caddy reaches it on the internal network

  db:
    image: postgres:16
    environment:
      - POSTGRES_DB=postgres
      - POSTGRES_USER=odoo
      - POSTGRES_PASSWORD=CHANGE_ME_DB_PASSWORD
    volumes:
      - odoo-db-data:/var/lib/postgresql/data
    restart: unless-stopped

  caddy:
    image: caddy:2
    depends_on: [odoo]
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-data:/data
      - caddy-config:/config
    restart: unless-stopped

volumes:
  odoo-web-data:
  odoo-db-data:
  caddy-data:
  caddy-config:
```

**`config/odoo.conf`**
```ini
[options]
admin_passwd = CHANGE_ME_STRONG_MASTER_PASSWORD
db_host = db
db_user = odoo
db_password = CHANGE_ME_DB_PASSWORD
addons_path = /mnt/extra-addons
proxy_mode = True
list_db = False
workers = 2
limit_time_cpu = 600
limit_time_real = 1200
```

**`Caddyfile`**
```
your.domain {
    reverse_proxy /websocket odoo:8072
    reverse_proxy /longpolling/* odoo:8072
    reverse_proxy odoo:8069
}
```

**Backup script (sketch — Claude Code to flesh out)**
```bash
#!/usr/bin/env bash
set -euo pipefail
STAMP=$(date +%F)
# 1. dump DB
docker compose exec -T db pg_dump -U odoo <DBNAME> | gzip > "/tmp/db-$STAMP.sql.gz"
# 2. archive filestore
docker run --rm -v odoo-web-data:/data -v /tmp:/backup alpine \
  tar czf "/backup/filestore-$STAMP.tar.gz" -C /data .
# 3. push offsite (configure rclone remote first)
rclone copy "/tmp/db-$STAMP.sql.gz"        backup-bucket:odoo/
rclone copy "/tmp/filestore-$STAMP.tar.gz" backup-bucket:odoo/
# 4. cleanup local + enforce retention on remote
rm -f "/tmp/db-$STAMP.sql.gz" "/tmp/filestore-$STAMP.tar.gz"
```

---

## 9. Open decisions (answer these to unblock Claude Code)

1. **Host + region** — Contabo Singapore? Oracle free tier? LightNode (PK)? (Affects Phase 1 + ARM note.)
2. **Domain name** — what domain/subdomain will this run on? (Needed for Caddy/TLS in Phase 3.)
3. **Offsite backup target** — which S3-compatible bucket? (Phase 4.)
4. **Email/SMTP** — what will Odoo send mail through (e.g. a transactional provider)? (Phase 5.)
5. **Currency/tax** — confirm PKR + your applicable sales-tax/VAT rate for invoice config. (Phase 5.)
6. **Odoo version** — confirm the current stable tag at build time.

---

## 10. How to use this with Claude Code

1. Put this file in your project repo as `PLAN.md` (or `CLAUDE.md` so Claude Code auto-loads it as context).
2. Start with: *"Read PLAN.md. We're on Phase 0 — set up the local prototype."*
3. Move phase by phase; have Claude Code generate/refine the actual files, run commands, and check each "Done when".
4. Answer the open decisions in §9 as they come up; update this doc so it stays the source of truth.
5. Commit after each working phase so you can roll back.

**Guardrails to keep in mind:** change all default credentials before exposing anything; test a backup restore before going live; keep customizations as modules (never edit core); and remember the FBR/compliance note in §3 if the business's tax status changes.
