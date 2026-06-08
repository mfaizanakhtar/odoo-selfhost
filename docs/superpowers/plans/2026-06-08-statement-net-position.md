# Customer Statement Net Position Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show vendor bills + vendor payments inline in customer statement so running balance reflects net AR − AP. Sort oldest→newest. Aging block becomes optional via wizard checkbox.

**Architecture:** Two new query blocks in `res_partner.get_statement_data()` mirror the existing per-source pattern. Remove the `rows.reverse()` to flip display sort. Add `show_aging` boolean to wizard; gate aging computation. No template changes (aging already wrapped in `t-if`).

**Tech Stack:** Odoo 18 (Python + QWeb XML), PostgreSQL, Docker on Hetzner with GitHub Actions CI/CD.

**Spec:** `docs/superpowers/specs/2026-06-08-statement-net-position-design.md`

**No automated tests:** Addon has no `tests/` dir. Verification is via `odoo shell` round-trips + headless Chrome render comparison. Each task ends with a verification step that runs on the deployed container after the deploy task (Task 8). Local-only sanity for code-shape comes from `python -c "import ast; ast.parse(open(...).read())"` per task.

---

## File Structure

| Path | Action | Responsibility |
|------|--------|----------------|
| `addons/sfya_customer_statement/models/res_partner.py` | Modify | Add vendor bill + vendor payment query blocks. Drop `rows.reverse()`. Accept `show_aging` param. Gate aging. |
| `addons/sfya_customer_statement/wizards/statement_wizard.py` | Modify | Add `show_aging` boolean field. |
| `addons/sfya_customer_statement/wizards/statement_wizard_views.xml` | Modify | Add `<field name="show_aging"/>` in form. |
| `addons/sfya_customer_statement/reports/statement_report.py` | Modify | Pass `wizard.show_aging` into `get_statement_data`. |
| `addons/sfya_customer_statement/__manifest__.py` | Modify | Version bump `18.0.1.14.0` → `18.0.2.0.0`. |

Templates untouched. Existing pattern: per-source block adds rows then chronological sort + running-balance pass at end.

---

### Task 1: Add `show_aging` field to wizard model

**Files:**
- Modify: `addons/sfya_customer_statement/wizards/statement_wizard.py:20-23`

- [ ] **Step 1: Read current file**

Run: `cat addons/sfya_customer_statement/wizards/statement_wizard.py`

Expected: shows `include_drafts = fields.Boolean(...)` at lines 20-23.

- [ ] **Step 2: Add field after `include_drafts`**

Edit `addons/sfya_customer_statement/wizards/statement_wizard.py`. Replace:

```python
    include_drafts = fields.Boolean(
        string='Include draft POS orders',
        default=False,
    )
```

with:

```python
    include_drafts = fields.Boolean(
        string='Include draft POS orders',
        default=False,
    )
    show_aging = fields.Boolean(
        string='Show Aging',
        default=False,
    )
```

- [ ] **Step 3: Local syntax check**

Run: `python3 -c "import ast; ast.parse(open('addons/sfya_customer_statement/wizards/statement_wizard.py').read())"`

Expected: no output (no SyntaxError).

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_customer_statement/wizards/statement_wizard.py
git commit -m "sfya_customer_statement: add show_aging field to wizard"
```

---

### Task 2: Add `show_aging` checkbox to wizard view

**Files:**
- Modify: `addons/sfya_customer_statement/wizards/statement_wizard_views.xml`

- [ ] **Step 1: Read current file**

Run: `cat addons/sfya_customer_statement/wizards/statement_wizard_views.xml`

Expected: shows the form containing `<field name="include_drafts"/>`.

- [ ] **Step 2: Add checkbox after `include_drafts`**

Find the line containing `<field name="include_drafts"/>` and insert immediately after:

```xml
<field name="show_aging"/>
```

Match exact indentation of the `include_drafts` line.

- [ ] **Step 3: Local XML validity check**

Run: `python3 -c "import xml.etree.ElementTree as ET; ET.parse('addons/sfya_customer_statement/wizards/statement_wizard_views.xml')"`

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_customer_statement/wizards/statement_wizard_views.xml
git commit -m "sfya_customer_statement: add Show Aging checkbox to wizard view"
```

---

### Task 3: Pass `show_aging` from report builder

**Files:**
- Modify: `addons/sfya_customer_statement/reports/statement_report.py:19-23`

- [ ] **Step 1: Read current call**

Run: `cat addons/sfya_customer_statement/reports/statement_report.py`

Expected: lines 19-23 show:
```python
        statement = wizard.partner_id.get_statement_data(
            wizard.date_from,
            wizard.date_to,
            include_drafts=wizard.include_drafts,
        )
```

- [ ] **Step 2: Add `show_aging` kwarg**

Replace those 5 lines with:

```python
        statement = wizard.partner_id.get_statement_data(
            wizard.date_from,
            wizard.date_to,
            include_drafts=wizard.include_drafts,
            show_aging=wizard.show_aging,
        )
```

- [ ] **Step 3: Local syntax check**

Run: `python3 -c "import ast; ast.parse(open('addons/sfya_customer_statement/reports/statement_report.py').read())"`

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_customer_statement/reports/statement_report.py
git commit -m "sfya_customer_statement: forward show_aging from wizard to data builder"
```

---

### Task 4: Accept `show_aging` param + gate aging in `get_statement_data`

**Files:**
- Modify: `addons/sfya_customer_statement/models/res_partner.py:9` (signature)
- Modify: `addons/sfya_customer_statement/models/res_partner.py:190` (aging line)

- [ ] **Step 1: Update signature**

Find:
```python
    def get_statement_data(self, date_from, date_to, include_drafts=False):
```

Replace with:
```python
    def get_statement_data(self, date_from, date_to, include_drafts=False, show_aging=False):
```

- [ ] **Step 2: Gate aging in return dict**

Find:
```python
            'aging': self._compute_aging_buckets(date_to),
```

Replace with:
```python
            'aging': self._compute_aging_buckets(date_to) if show_aging else [],
```

- [ ] **Step 3: Local syntax check**

Run: `python3 -c "import ast; ast.parse(open('addons/sfya_customer_statement/models/res_partner.py').read())"`

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_customer_statement/models/res_partner.py
git commit -m "sfya_customer_statement: gate aging computation on show_aging flag"
```

---

### Task 5: Add vendor bills source block

**Files:**
- Modify: `addons/sfya_customer_statement/models/res_partner.py` (insert after customer invoices block, before customer payments — around line 85)

- [ ] **Step 1: Read insertion point**

Run: `sed -n '80,95p' addons/sfya_customer_statement/models/res_partner.py`

Expected: shows end of `for inv in self.env['account.move'].search(inv_domain):` block — closing of the rows.append + blank line + `# Customer payments` comment.

- [ ] **Step 2: Insert vendor bills block**

Insert immediately AFTER the closing of the customer invoices `rows.append({...})` (the line that contains the closing brace + paren), and BEFORE the blank line preceding `# Customer payments`:

```python

        # Vendor bills (partner sells to us — counts as AP)
        bill_domain = [
            ('partner_id', '=', self.id),
            ('move_type', 'in', ['in_invoice', 'in_refund']),
            ('invoice_date', '>=', date_from),
            ('invoice_date', '<=', date_to),
            ('state', '=', 'posted'),
        ]
        for bill in self.env['account.move'].search(bill_domain):
            sign = 1 if bill.move_type == 'in_invoice' else -1
            lines = [{
                'name': (l.product_id.display_name or l.name or ''),
                'qty': l.quantity,
                'price_unit': l.price_unit,
                'subtotal': l.price_total,
            } for l in bill.invoice_line_ids if l.display_type not in ('line_section', 'line_note')]
            rows.append({
                'date': bill.invoice_date,
                'create_date': bill.create_date,
                'kind': 'vendor_bill' if sign > 0 else 'vendor_refund',
                'kind_label': _('Vendor Bill') if sign > 0 else _('Vendor Refund'),
                'doc_name': bill.name,
                'doc_id': bill.id,
                'doc_model': 'account.move',
                'lines': lines,
                'note': '',
                'debit': bill.amount_total if sign < 0 else 0.0,
                'credit': bill.amount_total if sign > 0 else 0.0,
                'balance': 0.0,
            })
```

- [ ] **Step 3: Local syntax check**

Run: `python3 -c "import ast; ast.parse(open('addons/sfya_customer_statement/models/res_partner.py').read())"`

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_customer_statement/models/res_partner.py
git commit -m "sfya_customer_statement: include vendor bills + refunds in statement"
```

---

### Task 6: Add vendor payments source block

**Files:**
- Modify: `addons/sfya_customer_statement/models/res_partner.py` (insert after customer payments block, before manual JE block)

- [ ] **Step 1: Read insertion point**

Run: `grep -n "Manual journal entries\|Customer payments" addons/sfya_customer_statement/models/res_partner.py`

Expected: line numbers of both comment markers. Insert between them.

- [ ] **Step 2: Insert vendor payments block**

Insert immediately AFTER the closing of the customer payments `rows.append({...})` loop body and BEFORE the blank line preceding `# Manual journal entries`:

```python

        # Vendor payments (we paid them — reduces our debt, raises net owed to us)
        vpay_domain = [
            ('partner_id', '=', self.id),
            ('partner_type', '=', 'supplier'),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('state', '=', 'posted'),
        ]
        for pay in self.env['account.payment'].search(vpay_domain):
            rows.append({
                'date': pay.date,
                'create_date': pay.create_date,
                'kind': 'vendor_payment',
                'kind_label': _('Vendor Payment'),
                'doc_name': pay.name,
                'doc_id': pay.id,
                'doc_model': 'account.payment',
                'lines': [],
                'note': _('Vendor Payment - %s', pay.journal_id.name) + (
                    ' (%s)' % pay.ref if pay.ref else ''
                ),
                'debit': pay.amount,
                'credit': 0.0,
                'balance': 0.0,
            })
```

- [ ] **Step 3: Local syntax check**

Run: `python3 -c "import ast; ast.parse(open('addons/sfya_customer_statement/models/res_partner.py').read())"`

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_customer_statement/models/res_partner.py
git commit -m "sfya_customer_statement: include vendor payments in statement"
```

---

### Task 7: Drop `rows.reverse()` for old→new display

**Files:**
- Modify: `addons/sfya_customer_statement/models/res_partner.py` (around line 157)

- [ ] **Step 1: Locate the reverse + surrounding context**

Run: `grep -n "rows.reverse\|Reverse for display" addons/sfya_customer_statement/models/res_partner.py`

Expected: two adjacent lines — comment + call.

- [ ] **Step 2: Remove both lines**

Find:
```python
        # Reverse for display (latest first)
        rows.reverse()
```

Delete both lines (and any blank line that becomes orphaned).

- [ ] **Step 3: Update the chronological-sort docstring comment**

Find in `get_statement_data()` docstring:
```python
        """Return chronological statement rows + meta for QWeb/screen rendering.

        Display order: latest first. Running balance computed in chronological
        (asc) order then rows are reversed so the newest sits at top.
        """
```

Replace with:
```python
        """Return chronological statement rows + meta for QWeb/screen rendering.

        Display order: oldest first. Opening row is pinned at top by template.
        Running balance computed in chronological (asc) order, same as display.
        """
```

- [ ] **Step 4: Local syntax check**

Run: `python3 -c "import ast; ast.parse(open('addons/sfya_customer_statement/models/res_partner.py').read())"`

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add addons/sfya_customer_statement/models/res_partner.py
git commit -m "sfya_customer_statement: sort statement rows oldest first"
```

---

### Task 8: Bump manifest version + deploy

**Files:**
- Modify: `addons/sfya_customer_statement/__manifest__.py:3`

- [ ] **Step 1: Bump version**

Find:
```python
    'version': '18.0.1.14.0',
```

Replace with:
```python
    'version': '18.0.2.0.0',
```

(Minor bump — balance semantics change from AR-only to net AR−AP, plus new wizard field.)

- [ ] **Step 2: Commit**

```bash
git add addons/sfya_customer_statement/__manifest__.py
git commit -m "sfya_customer_statement: bump to 18.0.2.0.0 (net AR-AP statement)"
```

- [ ] **Step 3: Push to trigger CI/CD**

```bash
git push origin main
```

- [ ] **Step 4: Wait for CI**

Run: `gh run list --limit 2`

Wait until both Lint + Deploy show `completed success` for the latest commit. Re-run command every ~60s. Typical total: 3-5 min after push.

- [ ] **Step 5: SSH upgrade module + clear assets**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http << 'EOF'
mod = env['ir.module.module'].search([('name', '=', 'sfya_customer_statement')])
print('Before:', mod.installed_version, mod.state)
mod.button_immediate_upgrade()
env.cr.commit()
mod = env['ir.module.module'].search([('name', '=', 'sfya_customer_statement')])
print('After:', mod.installed_version, mod.state)
assets = env['ir.attachment'].search([('url', '=like', '/web/assets/%')])
print('Assets to clear:', len(assets))
assets.unlink()
env.cr.commit()
print('Done')
EOF
"
```

Expected: `After: 18.0.2.0.0 installed`, assets count > 0 cleared, "Done" printed. No tracebacks.

---

### Task 9: Verify sort, vendor sources, aging gate

**Files:** none — verification only.

- [ ] **Step 1: Render report from server with aging hidden (default)**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http << 'EOF'
from datetime import date
w = env['sfya.statement.wizard'].create({
    'partner_id': 17,
    'date_from': date(2025,6,7),
    'date_to': date(2026,6,8),
    'include_drafts': False,
    'show_aging': False,
})
data = env['res.partner'].browse(17).get_statement_data(w.date_from, w.date_to, include_drafts=False, show_aging=False)
print('rows count:', len(data['rows']))
print('first row date:', data['rows'][0]['date'] if data['rows'] else None)
print('last row date:', data['rows'][-1]['date'] if data['rows'] else None)
print('aging:', data['aging'])
print('kinds present:', sorted({r['kind'] for r in data['rows']}))
EOF
"
```

Expected:
- `first row date` is OLDER than `last row date` (chronological ascending).
- `aging: []`
- `kinds present` includes `pos` and may include `vendor_bill`, `vendor_payment` if any exist for this partner.

- [ ] **Step 2: Confirm aging shows when toggled on**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http << 'EOF'
from datetime import date
data = env['res.partner'].browse(17).get_statement_data(date(2025,6,7), date(2026,6,8), show_aging=True)
print('aging:', data['aging'])
EOF
"
```

Expected: `aging:` shows list of 4 bucket dicts (0-30, 31-60, 61-90, 90+).

- [ ] **Step 3: Render full HTML, copy local, screenshot**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http << 'EOF'
from datetime import date
w = env['sfya.statement.wizard'].create({
    'partner_id': 17,
    'date_from': date(2025,6,7),
    'date_to': date(2026,6,8),
    'include_drafts': False,
    'show_aging': False,
})
html = env['ir.actions.report'].sudo()._render_qweb_html('sfya_customer_statement.action_report_customer_statement', [w.id])[0]
with open('/tmp/stmt-v2.html', 'wb') as f:
    f.write(html)
print('Wrote', len(html))
EOF
"

scp deploy@46.224.228.181:/tmp/stmt-v2.html /tmp/stmt-v2.html

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --headless --disable-gpu --no-sandbox --hide-scrollbars --force-device-scale-factor=4 --window-size=2000,2800 --screenshot=/tmp/stmt-v2.png "file:///tmp/stmt-v2.html"

sips -c 4500 6000 --cropOffset 0 2300 /tmp/stmt-v2.png --out /tmp/stmt-v2-table.png
```

Expected:
- HTML file present locally.
- PNG generated.
- Opening row at top with note "Opening Balance".
- Subsequent rows in ascending date order (oldest first).
- No aging block at bottom.
- If any vendor bills/payments exist for partner 17 in range, they appear with kind_label "Vendor Bill" / "Vendor Refund" / "Vendor Payment" in appropriate debit/credit columns.

- [ ] **Step 4: Open browser preview for user**

```bash
open /tmp/stmt-v2.html
```

Tell user: "Verify visually — old→new order, no aging by default, opening row pinned at top. Then toggle Show Aging in wizard to confirm aging renders when ON."

- [ ] **Step 5: Test wizard UI for new checkbox**

User-driven: open POS / Contacts → AJ Mobile → Action → "Customer Statement" → wizard appears with new "Show Aging" checkbox (unchecked default). Toggle and re-print.

Expected: checkbox present and labeled "Show Aging". Toggling ON → aging block renders. Toggling OFF → aging block absent.

- [ ] **Step 6: Sign-math spot check**

If partner 17 has any vendor bill in the range:

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http << 'EOF'
from datetime import date
data = env['res.partner'].browse(17).get_statement_data(date(2025,6,7), date(2026,6,8))
bills = [r for r in data['rows'] if r['kind'] in ('vendor_bill', 'vendor_refund')]
for b in bills:
    print(b['kind'], b['doc_name'], 'debit:', b['debit'], 'credit:', b['credit'], 'balance after:', b['balance'])
print('closing:', data['closing_balance'])
EOF
"
```

Expected: `vendor_bill` shows `credit` populated and `debit=0`; balance dropped after that row. Closing reflects net AR−AP.

---

## Self-Review

**1. Spec coverage:**
- Sort change → Task 7 ✓
- Vendor bills → Task 5 ✓
- Vendor payments → Task 6 ✓
- Aging gate (data layer) → Task 4 ✓
- Aging wizard field → Task 1 ✓
- Aging wizard view → Task 2 ✓
- Aging wired through report builder → Task 3 ✓
- Manifest bump → Task 8 ✓
- Verification (sort, vendor rows, aging gate) → Task 9 ✓
- Sign math (the table in spec) → Task 9 Step 6 ✓

**2. Placeholder scan:** No "TBD", "TODO", "later", "appropriate", "as needed". All code blocks complete. All commands exact.

**3. Type consistency:** Param name `show_aging` consistent across:
- Wizard field (Task 1)
- View `<field name="show_aging"/>` (Task 2)
- Report builder kwarg `show_aging=wizard.show_aging` (Task 3)
- Function signature `show_aging=False` (Task 4)
- Verification calls `show_aging=False` / `show_aging=True` (Task 9) ✓

Row dict keys for new sources match existing pattern: `date`, `create_date`, `kind`, `kind_label`, `doc_name`, `doc_id`, `doc_model`, `lines`, `note`, `debit`, `credit`, `balance`. Confirmed against res_partner.py:38-51 (POS) and :71-84 (invoice) ✓
