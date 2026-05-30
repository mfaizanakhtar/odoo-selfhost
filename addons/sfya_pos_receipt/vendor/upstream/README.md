# Upstream snapshots — REFERENCE ONLY

These files are NOT loaded by the addon. They mirror the upstream Odoo
`point_of_sale` code that this module's xpath inherits and JS patches target.

Refresh after every image bump and `git diff` to spot template drift that
could silently break our `t-inherit` xpaths or `patch()` extensions.

Source: `odoo:18.0` image, see `SOURCE.txt` for digest + extraction date.
