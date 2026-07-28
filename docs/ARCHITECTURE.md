# odoo-selfhost — Architecture & Operations

> Self-hosted Odoo 18 Community for SFYA Enterprises. Single VPS (Hetzner), reproducible from git.

---

## TL;DR — Is my code safe?

**Yes, fully.** Everything that defines the deployment lives in this git repo, pushed to
`github.com/mfaizanakhtar/odoo-selfhost` (branch `main`). The VPS is a derived artifact —
if it dies, you can rebuild it from this repo + the latest DB dump in under an hour.

What is **NOT** in git (must be backed up separately):
- Postgres data (the actual ERP records: invoices, products, partners, settings, etc.)
- Filestore (attachments, receipt scans) → Docker volume `odoo-stack_odoo-web-data`
- GitHub Actions secrets (DB password, master password, SSH key)

---

## Topology

```
┌──────────────────────────────────────────────────────────┐
│  Developer Mac (this repo)                               │
│  /Users/faizanakhter/odoo-selfhost                       │
└─────────────────────┬────────────────────────────────────┘
                      │ git push origin main
                      ▼
┌──────────────────────────────────────────────────────────┐
│  GitHub — mfaizanakhtar/odoo-selfhost                    │
│  - branch: main (source of truth)                        │
│  - Actions: .github/workflows/deploy.yml                 │
│  - Secrets: DEPLOY_SSH_KEY, ODOO_DB_*, SUBDOMAIN, ...    │
└─────────────────────┬────────────────────────────────────┘
                      │ GitHub Actions runner (Ubuntu)
                      │ 1. checkout
                      │ 2. envsubst odoo.conf
                      │ 3. ssh: pg_dump pre-deploy backup
                      │ 4. rsync payload → VPS
                      │ 5. ssh: docker compose up -d --build
                      │ 6. health check (HTTPS /web/login)
                      ▼
┌──────────────────────────────────────────────────────────┐
│  Hetzner VPS — deploy@46.224.228.181                     │
│  ~/odoo-stack/                                           │
│    ├── docker-compose.yml  (services: odoo, db, caddy)   │
│    ├── Dockerfile          (odoo:18.0 + openupgradelib)  │
│    ├── Caddyfile           (HTTPS reverse proxy)         │
│    ├── config/odoo.conf    (rendered from template)      │
│    ├── addons/             (rsync'd from repo)           │
│    │   ├── sfya_pos_receipt/        (custom POS receipt) │
│    │   ├── sfya_customer_statement/ (per-customer report)│
│    │   ├── sfya_pos_cash_movement/  (POS collect/payout) │
│    │   └── oca/                (vendored OCA modules)    │
│    └── .env                (DB creds, subdomain)         │
│                                                          │
│  Docker volumes (persistent, NOT in repo):               │
│    - odoo-stack_odoo-db-data  ← Postgres data            │
│    - odoo-stack_odoo-web-data ← Odoo filestore           │
│    - odoo-stack_caddy-data    ← TLS certs                │
│    - odoo-stack_caddy-config                             │
│                                                          │
│  Pre-deploy backups:                                     │
│    ~/odoo-pre-deploy-YYYYMMDDTHHMMSS.dump (keeps last 7) │
└─────────────────────┬────────────────────────────────────┘
                      │ HTTPS (Caddy auto-TLS)
                      ▼
            https://odoo.edashlytic.com
```

---

## What is in the repo

```
odoo-selfhost/
├── .github/workflows/
│   ├── deploy.yml      ← CI/CD: push to main → deploy
│   └── lint.yml        ← runs on every push
├── Dockerfile          ← FROM odoo:18.0@sha256:... + pip openupgradelib
├── docker-compose.yml  ← services: odoo (build:.), db (postgres:16), caddy (caddy:2.8)
├── Caddyfile           ← reverse proxy + TLS for ${SUBDOMAIN}
├── config/
│   └── odoo.conf.template  ← addons_path, workers, memory limits (envsubst at deploy)
├── addons/
│   ├── sfya_pos_receipt/         ← custom POS receipt (OWL inherit + JS patch)
│   ├── sfya_customer_statement/  ← per-customer statement report + opening-balance wizard
│   ├── sfya_pos_cash_movement/   ← POS Collect / Pay Out buttons (account.payment + pos.session)
│   └── oca/                      ← vendored 3rd-party (AGPL-3, OCA)
│       ├── account_financial_report/   Trial Balance, GL, Aged, VAT, ...
│       ├── mis_builder/                MIS engine
│       ├── mis_template_financial_report/  P&L + Balance Sheet templates
│       ├── date_range/                 dep
│       └── report_xlsx/                dep
├── scripts/
│   └── bulk_import_products.py    ← one-off product import helper
└── docs/
    ├── ARCHITECTURE.md            ← this file
    └── superpowers/
        ├── specs/                 ← design specs (committed)
        └── plans/                 ← implementation plans (committed)
```

---

## Deployment flow

**Trigger:** `git push origin main` (or manual via Actions → Deploy → Run workflow).

**Workflow:** `.github/workflows/deploy.yml`

1. **Checkout** repo on GitHub-hosted runner.
2. **Build payload** under `.build/payload/` — copies addons, Dockerfile, docker-compose.yml,
   Caddyfile; renders `odoo.conf` from template using secrets; writes `.env`.
3. **Pre-deploy DB backup** — SSH to VPS, run `pg_dump -Fc odoo > ~/odoo-pre-deploy-<ts>.dump`,
   prune to last 7 backups.
4. **Rsync** payload → `~/odoo-stack/` on VPS (with `--delete`, so removed files vanish).
5. **Restart stack** — SSH: `cd ~/odoo-stack && docker compose up -d --build --remove-orphans`
   - `--build` rebuilds the odoo image if the Dockerfile or its context changed.
6. **Health check** — curl `https://${SUBDOMAIN}/web/login` until HTTP 200/3xx (max 30 × 5s).
   On failure, dumps the last 50 lines of odoo logs to the Actions output.

**End-to-end deploy time:** ~30s for code-only; ~3-5 min if the Docker image is rebuilt.

---

## Image strategy

The odoo container is built **on the VPS** from a thin Dockerfile that extends a pinned base:

```dockerfile
FROM odoo:18.0@sha256:b9fad113ae0274da19b769db65193bfdbcd1993128acd8b708bc842cbd7f4185
USER root
RUN pip3 install --no-cache-dir --break-system-packages openupgradelib
USER odoo
```

**Why this shape:**
- **`@sha256:...` digest pin** — the upstream `odoo:18.0` tag is mutable (Odoo bumps it for
  every patch release). Pinning the digest means the image *never* moves until we bump it
  intentionally. Prevents silent template / API drift breaking our xpath inherits.
- **Extending the base** — `mis_builder` declares `openupgradelib` as a Python
  `external_dependency`; Odoo refuses to install the module unless the package is
  importable. The Dockerfile adds it on top of the pinned base.

**To bump Odoo to a newer patch release:**

1. Pull the new tag on the VPS, get the new digest:
   ```
   ssh deploy@46.224.228.181 'docker pull odoo:18.0 && docker inspect odoo:18.0 --format "{{index .RepoDigests 0}}"'
   ```
2. Update the digest in `Dockerfile` (and `addons/sfya_pos_receipt/vendor/upstream/SOURCE.txt`
   for traceability).
3. Re-extract upstream `point_of_sale` snapshots into `addons/sfya_pos_receipt/vendor/upstream/`
   (one diff check below) to spot template drift.
4. Commit, push, deploy.

---

## Installed addons (current state)

**Custom (this repo, `addons/`):**
- `sfya_pos_receipt` — replaces POS receipt with SFYA branded layout (OWL `t-inherit` + JS `patch`)
- `sfya_customer_statement` — per-customer statement (POS, invoices, payments, manual entries) with opening-balance wizard
- `sfya_pos_cash_movement` — adds Collect Payment / Pay Out / Partner Drawing / Transfer Funds buttons to POS; records `account.payment` against any cash or bank journal of the company (cashier picks via Account dropdown), linked to the active `pos.session` for till reconciliation. Cash movements adjust expected cash in the closing dialog; bank movements appear as informational per-journal sections with no till impact. Transfer Funds moves money directly between two of the company's own journals (e.g. shop cash till to a bank account) via a dedicated clearing account, with the cash-journal leg (if any) folded into the till's expected-cash math. A separate Partner Transfer flow settles a Pay Out via another partner's balance instead (2-line ledger entry, no cash/bank leg at all).

**OCA vendored (this repo, `addons/oca/`):**
- `account_financial_report` — Trial Balance, General Ledger, Aged Partner, Open Items, VAT, Journal Ledger
- `mis_builder` — MIS engine for arbitrary financial reports
- `mis_template_financial_report` — preconfigured **P&L** and **Balance Sheet** templates
- `date_range`, `report_xlsx` — deps

**Odoo Community core (installed via UI / shell, not in this repo):**
- `account` (Invoicing), `hr`, `hr_expense`, `sale_expense`, `board`, etc.

To see the live module list:
```
ssh deploy@46.224.228.181 'docker exec odoo-stack-odoo-1 odoo shell -d odoo --no-http --stop-after-init <<<"print([(m.name,m.state) for m in env[\"ir.module.module\"].search([(\"state\",\"=\",\"installed\")])])"'
```

---

## Disaster recovery

### Scenario A — Lost laptop (only)

Repo is on GitHub. On a new machine:
```
git clone git@github.com:mfaizanakhtar/odoo-selfhost.git
```
That's it. Nothing missing — all addons, infra, docs are versioned.

### Scenario B — VPS dies, repo intact

1. Provision new Hetzner box, SSH as a user with docker installed.
2. Update GitHub Actions secrets: `SSH_HOST` to the new IP, regenerate `DEPLOY_SSH_KEY` if needed.
3. Point DNS (`odoo.edashlytic.com`) at the new IP.
4. Restore the latest Postgres dump:
   ```
   scp odoo-pre-deploy-<latest>.dump deploy@<new-ip>:~/
   ssh deploy@<new-ip> 'docker exec -i odoo-stack-db-1 pg_restore -U <user> -d odoo --clean --if-exists < ~/odoo-pre-deploy-<latest>.dump'
   ```
   (Requires the stack to be up — push to main first to provision empty stack, then restore.)
5. Restore filestore from off-VPS backup if you have one (attachments / receipt scans live in
   the `odoo-stack_odoo-web-data` Docker volume — NOT in git, NOT in pg_dump).
6. Trigger deploy: push any commit (or re-run last Action).

### Scenario C — Bad deploy broke prod

The deploy workflow took a backup *before* applying changes. Roll back:
```
ssh deploy@46.224.228.181
ls -t ~/odoo-pre-deploy-*.dump | head -3   # pick the one from before the bad deploy
docker exec -i odoo-stack-db-1 pg_restore -U <user> -d odoo --clean --if-exists < ~/odoo-pre-deploy-<timestamp>.dump
```
Then `git revert` the bad commit and push.

### Scenario D — Module install corrupted DB

Same as C. Restore the dump taken before the install.

---

## Backup hygiene (recommended next steps, not yet done)

- **Off-VPS DB backups** — current 7 dumps live on the same VPS that hosts the DB. If the
  VPS is destroyed, the dumps go with it. Push to S3 / Backblaze / Hetzner Storage Box on a
  cron. Daily, retain 30.
- **Filestore backup** — `docker run --rm -v odoo-stack_odoo-web-data:/data -v $PWD:/backup
  alpine tar -czf /backup/filestore-$(date +%Y%m%d).tar.gz /data` on a cron, ship off-VPS.
- **Postgres WAL archiving** — for point-in-time recovery, set up `archive_mode=on` and ship
  WAL segments to object storage. Overkill until you have a few months of usage.

---

## Common operations

**Deploy:** `git push origin main` (auto)

**Install a new module:**
```
ssh deploy@46.224.228.181 'docker exec -i odoo-stack-odoo-1 odoo shell -d odoo --no-http --stop-after-init' <<EOF
m = env["ir.module.module"].search([("name","=","<module_name>")])
m.button_immediate_install()
env.cr.commit()
EOF
```
If that doesn't take (some modules need a clean process), use the offline route:
```
ssh deploy@46.224.228.181 'cd /home/deploy/odoo-stack && docker compose stop odoo && docker compose run --rm odoo odoo -d odoo --no-http --stop-after-init -i <module_name> && docker compose up -d odoo'
```

**Manual DB backup:**
```
ssh deploy@46.224.228.181 'docker exec odoo-stack-db-1 pg_dump -U <user> -Fc odoo > ~/manual-$(date -u +%Y%m%dT%H%M%S).dump'
```

**Tail logs:**
```
ssh deploy@46.224.228.181 'docker compose -f /home/deploy/odoo-stack/docker-compose.yml logs -f --tail 100 odoo'
```

**Drift check (POS receipt vs upstream):**
```
diff \
  <(ssh deploy@46.224.228.181 'docker exec odoo-stack-odoo-1 cat /usr/lib/python3/dist-packages/odoo/addons/point_of_sale/static/src/app/screens/receipt_screen/receipt/order_receipt.xml') \
  addons/sfya_pos_receipt/vendor/upstream/order_receipt.xml
```
Empty output = our inherit xpaths still target valid nodes.

---

## What lives where — quick reference

| Concern                          | Location                                                                |
| -------------------------------- | ----------------------------------------------------------------------- |
| Source of truth (code, infra)    | `git@github.com:mfaizanakhtar/odoo-selfhost.git`, branch `main`         |
| CI / deploy pipeline             | `.github/workflows/deploy.yml`                                          |
| CI secrets                       | GitHub repo → Settings → Secrets and variables → Actions                |
| VPS                              | Hetzner, `deploy@46.224.228.181`                                        |
| Deployed payload                 | `/home/deploy/odoo-stack/` on VPS                                       |
| Postgres data                    | Docker volume `odoo-stack_odoo-db-data` on VPS                          |
| Filestore (attachments)          | Docker volume `odoo-stack_odoo-web-data` on VPS                         |
| TLS certs                        | Docker volume `odoo-stack_caddy-data` on VPS (auto-renewed by Caddy)    |
| Pre-deploy DB backups (last 7)   | `~/odoo-pre-deploy-*.dump` on VPS                                       |
| Domain                           | `odoo.edashlytic.com` → Hetzner VPS IP (DNS, manually managed)          |
| Custom addon source              | `addons/sfya_pos_receipt/` (in this repo)                               |
| Vendored OCA addons              | `addons/oca/` (in this repo)                                            |
| Upstream Odoo source (reference) | `addons/sfya_pos_receipt/vendor/upstream/` (snapshots, NOT loaded)      |
