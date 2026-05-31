FROM odoo:18.0@sha256:b9fad113ae0274da19b769db65193bfdbcd1993128acd8b708bc842cbd7f4185

USER root

# OCA mis_builder declares openupgradelib as external_dependency; required at
# install time even though only migrations import it.
RUN pip3 install --no-cache-dir --break-system-packages openupgradelib

USER odoo
