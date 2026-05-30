#!/usr/bin/env bash
set -euo pipefail
set -a; source "$(dirname "$0")/../.env"; set +a
export ODOO_URL="https://${SUBDOMAIN}"
export ODOO_DB="${ODOO_DB_NAME}"
export ODOO_USER="${ODOO_ADMIN_USER}"
export ODOO_YOLO="true"
exec /opt/homebrew/bin/uvx mcp-server-odoo
