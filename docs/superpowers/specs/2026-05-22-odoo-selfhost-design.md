# Odoo Community Self-Host — Design Spec

**Date:** 2026-05-22
**Status:** Draft (pending user review)
**Source plan:** [`PLAN.md`](../../../PLAN.md) (from prior agent, treated as authoritative starting point)

---

## 1. Goal

Stand up self-hosted **Odoo Community Edition** for a small team. Docker on cheap VPS. HTTPS access. Apps: CRM, Sales, Invoicing, Inventory, Purchase, Manufacturing. Extensible via custom modules.

**Success:** team member logs in over HTTPS, runs full quote → sale → delivery → invoice flow against live inventory.

**Out of scope (this spec):** FBR e-invoicing, full statutory accounting, multi-company, HR/payroll, e-commerce, automated backups (deferred), outbound SMTP email (deferred).

---

## 2. Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Platform | Odoo Community 18.0 | Free, fits workflow, large module ecosystem |
| Deployment | Docker Compose, self-host | Cheap, portable, reproducible |
| Database | PostgreSQL 16 (containerized) | Odoo requirement |
| Reverse proxy / TLS | Caddy 2 | Auto Let's Encrypt, near-zero config |
| Host | **Hetzner CX23** | €3.99/mo, 2 vCPU / 4GB / 40GB NVMe x86, cheapest x86 plan post April-2026 price hike; Odoo runs comfortably with `workers=1` for small team |
| Host region | Hetzner Nuremberg (DE) or Helsinki (FI) | User accepts EU latency |
| Host OS | Ubuntu 24.04 LTS | Standard, well-supported |
| Project dir (local) | `~/odoo-selfhost/` | Git-tracked, source of truth |
| Domain | User-provided subdomain (e.g. `odoo.<userdomain>`) | Required for TLS |
| Automation | `hcloud` CLI + SSH | Hetzner has official CLI + API |

## 3. Deferred decisions (revisit before going live)

| Item | Status | Risk if shipped without |
|---|---|---|
| Offsite backups (Phase 4) | **Deferred** | ⚠️ **HIGH**: VPS loss = full data loss. Re-enable before real business data lands. |
| Outbound SMTP (Phase 5 partial) | **Deferred** | No emailed invoices/quotes/password resets. Manual export workaround. |
| FBR e-invoicing (Phase 8) | **Parked** | Mandatory if business becomes sales-tax registered. Architect invoicing now so connector bolts on later. |
| Fail2ban / unattended-upgrades (Phase 7 partial) | **Included in Phase 7** | SSH brute-force exposure if skipped. |

## 4. VPS provider research (May 2026)

Top candidates evaluated:

| Provider | Plan | vCPU/RAM/Disk | $/mo | Notes |
|---|---|---|---|---|
| **Hetzner** | CX23 | 2 / 4GB / 40GB NVMe | €3.99 (~$4.30) | **Winner** (post April 2026 price hike — CX23 now cheapest x86, beat ARM CAX11 €4.49). |
| Hetzner | CX33 | 4 / 8GB / 80GB NVMe | €6.49 | Considered but overspec for 2-3 user team. |
| Contabo | VPS 10 | 4 / 8GB / 75GB | ~$4.90 | Cheapest but 20-40% CPU steal complaints, slow support. |
| Netcup | VPS 500 G12 | 2 / 4GB DDR5 ECC / 128GB | ~$6.30 | ECC RAM nice, 4GB tight for Odoo+PG. |
| Oracle | Always Free Ampere | 4 / 24GB / 200GB ARM | $0 | ARM, capacity reclamation risk, "Out of Capacity" common. |

Decision: **Hetzner CX23** — €3.99/mo, cheapest x86 with reliable provider. Trade-off: `workers=1` instead of 2 (fine for small team, ~200ms wait worst case when two users click simultaneously). Resize to CX33 in-place later if needed (~1min downtime).

---

## 5. Architecture

```
                Internet (HTTPS :443)
                        │
                        ▼
              ┌───────────────────┐
              │   Caddy (proxy)   │  auto TLS via Let's Encrypt
              └─────────┬─────────┘
                        │ docker internal network
                        │ :8069 (web) / :8072 (longpolling/websocket)
                        ▼
              ┌───────────────────┐        ┌────────────────────┐
              │  Odoo 18 Community│ ─────► │  PostgreSQL 16     │
              │  workers + cron   │        │  (internal only)   │
              └─────────┬─────────┘        └────────────────────┘
                        │ named volumes
          ┌─────────────┴──────────────┐
          │ odoo-web-data (filestore)  │
          │ odoo-db-data (postgres)    │
          │ ./addons (custom modules)  │
          │ ./config (odoo.conf)       │
          └────────────────────────────┘
```

**Network boundary:** only Caddy publishes ports 80/443 to host. Odoo + Postgres talk over internal Docker network only — never exposed publicly.

**Trust:** Odoo runs with `proxy_mode = True` so it trusts Caddy's `X-Forwarded-*` headers.

---

## 6. Components

### 6.1 Hetzner VPS
- **Plan:** CX23 (2 vCPU AMD x86, 4GB RAM, 40GB NVMe)
- **OS:** Ubuntu 24.04 LTS
- **Region:** Nuremberg (default) or Helsinki — pick at provision time
- **SSH:** key-only, password disabled
- **User:** non-root sudo user, `deploy`
- **Firewall (Hetzner Cloud Firewall + ufw):** allow inbound 22 (SSH), 80, 443 only

### 6.2 Docker stack
Services: `odoo`, `db`, `caddy`. Single `docker-compose.yml` in repo root. Volumes named, never bind-mounted to host paths for DB/filestore.

### 6.3 Odoo configuration
`config/odoo.conf` key settings:
- `admin_passwd` — strong random, stored in password manager
- `list_db = False` — hide DB manager from public
- `proxy_mode = True` — trust Caddy headers
- `workers = 1` — fits 2 vCPU / 4GB box; Postgres needs ~500MB, each Odoo worker ~300-500MB working set
- `limit_memory_soft = 629145600` (600MB), `limit_memory_hard = 786432000` (750MB) — tighter limits for 4GB host
- `limit_time_cpu = 600`, `limit_time_real = 1200` — long-report tolerance

### 6.4 Caddy
- `Caddyfile` reverse-proxies `<subdomain>` → `odoo:8069`
- Routes `/websocket` and `/longpolling/*` → `odoo:8072`
- Auto-issues + renews Let's Encrypt cert (port 80 must be open for ACME HTTP-01 challenge)

### 6.5 Custom addons
- Directory `./addons/` mounted into Odoo container at `/mnt/extra-addons`
- All customizations live here as versioned modules — **never edit Odoo core**
- First module (Phase 6): `branding` — branded QWeb invoice/quote PDF

---

## 7. Repo layout

```
~/odoo-selfhost/
├── PLAN.md                              # original plan doc
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-22-odoo-selfhost-design.md
├── docker-compose.yml
├── Caddyfile
├── config/
│   └── odoo.conf
├── addons/
│   └── (custom modules)
├── scripts/
│   ├── provision.sh                     # hcloud commands
│   ├── bootstrap.sh                     # remote setup (Docker, ufw, users)
│   └── backup.sh                        # deferred to Phase 4
└── .gitignore                           # ignore secrets/.env
```

Secrets (`admin_passwd`, DB password, Hetzner token) live in `.env` file — gitignored. Real values stored in user's password manager.

---

## 8. Phased build (mirrors PLAN.md, adapted)

| Phase | Scope | Done when |
|---|---|---|
| **1. Provision** | Hetzner CX23 via `hcloud` CLI, SSH key, firewall, non-root user, Docker | `ssh deploy@<ip>` works, `docker run hello-world` succeeds |
| **2. Deploy stack** | `docker-compose.yml`, `odoo.conf` with strong creds, `docker compose up -d`, create prod DB via UI | Odoo reachable on internal port, prod DB exists |
| **3. Caddy + HTTPS** | A record (user adds), `Caddyfile`, drop public ports from Odoo/Postgres | `https://<subdomain>` loads Odoo, valid cert, no warnings |
| **4. Backups** | **Deferred** — revisit before real data | (deferred) |
| **5. App config** | Install CRM/Sales/Inventory/Purchase/MRP/Invoicing, company profile, PKR currency, users, products, tax rate | Full quote→invoice cycle runs, inventory updates |
| **6. Customization** | Scaffold `branding` addon, branded invoice PDF | Invoice prints with branding, custom module loads |
| **7. Hardening** | ufw, fail2ban, unattended-upgrades, confirm `list_db = False`, basic uptime monitor | Firewall on, monitor green, restore runbook (deferred until Phase 4) |
| **8. FBR** | **Parked** | (future) |

---

## 9. User vs. assistant responsibilities

**User does:**
- Create Hetzner account, add payment, generate API token, paste to assistant
- Pick subdomain, add A record at DNS registrar when assistant gives VPS IP
- Click through Odoo first-time DB creation + admin user via browser
- Configure company profile / users / products via Odoo UI (Phase 5)
- Store generated secrets in password manager

**Assistant does:**
- All `hcloud` CLI provisioning
- All `ssh` server bootstrap (Docker install, user creation, ufw, hardening)
- Write all config files (`docker-compose.yml`, `odoo.conf`, `Caddyfile`)
- Generate strong passwords
- Build `branding` custom module
- Document restore procedure (when Phase 4 ships)

---

## 10. Reliability principles

- **Backups are the reliability story** — Phase 4 not optional long-term, even if deferred now.
- **Reproducible from git:** `git clone` + `docker compose up` + restore = fresh VPS in 1 hour.
- **Never edit core:** all changes = versioned modules in `./addons/`.
- **Pin image tags:** `odoo:18.0`, `postgres:16`, `caddy:2.8` — never `:latest` in prod.

---

## 11. Open questions (must answer before Phase 1)

1. **Subdomain** — exact FQDN (e.g. `odoo.example.com`)?
2. **Hetzner API token** — created in console, paste when ready
3. **Region** — Nuremberg (DE) or Helsinki (FI)? (Default: Nuremberg)
4. **Backup deferral acknowledged** — confirm OK with no recovery if VPS dies during Phase 1-3
