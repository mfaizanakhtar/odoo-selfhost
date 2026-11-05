# Odoo self-hosted

Odoo 18 Community for SFYA Enterprises. Custom addons, Docker infrastructure, and deployment automation live in this repository.

Production: **https://odoo.alogy.pk**. Production server: **Hetzner `odoo-prod` (ID `132432802`, CX33: 4 shared vCPU, 8 GB RAM, 80 GB disk), `deploy@46.224.228.181`**, stack `/home/deploy/odoo-stack`. The server runs Ubuntu 24.04 in Nuremberg (`nbg1`). The existing production firewall is `11011966`. The Personal AI development VPS is a separate machine; it does not host the ERP database.

## Working from the Personal AI VPS

The migrated project is `/home/ai/projects/odoo-selfhost-1d8943`. Select **odoo-selfhost** when starting a Discord Codex thread. Discord makes a task workspace from this project; use that workspace for changes and the managed GitHub tools to push a feature branch and open a PR. The desktop terminal can also work directly with the checkout.

Codex has two credential-backed integrations:

- **`odoo`**: the existing Odoo MCP connector for ERP searches and reads. `ODOO_YOLO=read` keeps its business-record tools read-only, matching the Mac connector. The VPS connector uses a loopback-only SSH tunnel to the production Odoo container, because Cloudflare challenges datacenter requests to the public hostname; traffic between machines stays encrypted and public protections are unchanged.
- **`odoo_ops`**: production server status, recent logs, Hetzner server details, and commands as the existing `deploy` user. Server commands can change production and should follow the backup and deployment procedures in [Architecture & Operations](docs/ARCHITECTURE.md).

In the VPS desktop terminal:

```sh
odoo-vps status
odoo-vps logs
odoo-vps hetzner
odoo-vps ssh 'hostname'
```

In Discord, ask Codex to use `odoo_server_status`, `odoo_server_logs`, `odoo_hetzner_details`, or `odoo_server_command`. New runs load the updated integrations; start a fresh thread if an existing session still has an old tool list. Do not ask the agent to display credentials.

## Credentials and configuration

The managed source is **Infisical → Personal AI VPS → Production → `/`**. Entries for this project use the prefix **`ODOO_OPS_`**. They include the existing Odoo API key, database and master passwords, administrator login name, Hetzner token and server metadata, deployment SSH key, and pinned production SSH host keys.

The root-owned launcher `/opt/personal-ai/odoo-tools/server.py` retrieves values at runtime and runs credential-bearing tools as the dedicated `personal-ai-odoo` Linux user. Agent jobs receive tool results; they do not receive a `.env`, an SSH private key, an Infisical login, or a Hetzner token. Known managed secret values are redacted from server command output. Production shell access remains powerful: the `deploy` account can administer Docker and read production configuration. It is not a read-only ERP interface.

Keep secrets out of Git, task workspaces, terminal output, and chat. Manage or rotate them in Infisical. The import preserves the Mac's original credentials and configuration. GitHub Actions continues to use its existing repository secrets; changing an Infisical password does **not** automatically rotate the production database, Actions secrets, or other consumers.

The MCP package currently installed on the AI VPS is `mcp-server-odoo==0.8.0`. The infrastructure launcher source and installer are maintained in the Personal AI VPS migration project under `apps/odoo-tools/`. The trusted install is root-owned; never replace it with an agent-editable workspace copy. Credentials are not committed to either repository.

## Deploying changes

Changes to `main` deploy through [the Deploy workflow](.github/workflows/deploy.yml), including a pre-deploy database backup. README/docs-only and MCP-launcher-only pushes skip production deployment. Develop on feature branches, inspect the diff, and follow the operations runbook for module upgrades and restores.

See [Architecture & Operations](docs/ARCHITECTURE.md) for topology, production paths, backups, and recovery. [PLAN.md](PLAN.md) is the original planning document; use the operations document for the current deployment.
