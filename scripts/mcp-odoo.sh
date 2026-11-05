#!/usr/bin/env bash
set -euo pipefail
# Personal AI VPS: credentials are fetched by the root-owned managed launcher.
if [[ -f /opt/personal-ai/odoo-tools/server.py ]]; then
  exec /usr/bin/sudo -n /usr/bin/python3 /opt/personal-ai/odoo-tools/server.py mcp
fi
set -a; source "$(dirname "$0")/../.env"; set +a
export ODOO_URL="https://${SUBDOMAIN}"
export ODOO_DB="${ODOO_DB_NAME}"
export ODOO_USER="${ODOO_ADMIN_USER}"
export ODOO_YOLO="read"
exec uvx mcp-server-odoo==0.8.0
