#!/usr/bin/env bash
# Renders odoo.conf from template + rsyncs stack to VPS.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

# 1. Render odoo.conf from template
mkdir -p .build/config
envsubst < config/odoo.conf.template > .build/config/odoo.conf

# 2. Stage payload
rm -rf .build/payload
mkdir -p .build/payload/config .build/payload/addons
cp .build/config/odoo.conf .build/payload/config/odoo.conf
if compgen -G "addons/*" > /dev/null; then
  cp -R addons/. .build/payload/addons/
fi
cp docker-compose.yml Caddyfile .build/payload/

# Sanitized .env (only runtime vars compose + caddy need)
cat > .build/payload/.env <<EOF
ODOO_DB_USER=$ODOO_DB_USER
ODOO_DB_PASSWORD=$ODOO_DB_PASSWORD
SUBDOMAIN=$SUBDOMAIN
EOF

# 3. Rsync to server
ssh deploy@"$SERVER_IP" "mkdir -p ~/odoo-stack"
rsync -avz --delete .build/payload/ deploy@"$SERVER_IP":~/odoo-stack/

echo "Synced to deploy@$SERVER_IP:~/odoo-stack"
