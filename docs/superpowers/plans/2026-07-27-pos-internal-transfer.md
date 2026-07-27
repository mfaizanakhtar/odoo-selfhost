# POS Internal Transfer (Cash Till ↔ Bank ↔ Bank) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 4th POS cash-movement action, "Transfer Funds", so a cashier can move money between any two of the company's own cash/bank journals (shop cash till → bank, or bank → bank) with no partner involved.

**Architecture:** In-place extension of `sfya_pos_cash_movement`. A dedicated "Internal Transfers Clearing" account (auto-created per company, same pattern as the existing Owner's Drawing account and Partner Transfer journal) backs both legs of every transfer. `account.payment.sfya_pos_internal_transfer()` creates two linked, partner-less payments (outbound from-leg, inbound to-leg) against that clearing account. `pos_session.get_sfya_cash_movements` excludes these from the generic Collect/Pay Out/Drawing buckets and totals the cash-journal leg separately so `get_closing_control_data`'s till math stays correct. Frontend adds a 4th `CashMovementModal` mode ("transfer") with two journal pickers instead of a partner picker, a new toolbar button, and a new "Internal Transfers" section in the closing dialog.

**Tech Stack:** Odoo 18, OWL/QWeb (frontend), Python (backend), `account.payment` / `account.journal` / `pos.session` ORM. No test infra — manual smoke via `odoo shell` + browser per task.

**Spec:** `docs/superpowers/specs/2026-07-27-pos-internal-transfer-design.md`

## Global Constraints

- No new models or database tables; no new addon — extend `sfya_pos_cash_movement` in place.
- Any cashier can perform a transfer — no shareholder restriction (unlike Partner Drawing).
- Reuse the dedicated-resource `post_init_hook` pattern: search-by-code, create-if-missing. Never search/guess among existing accounts.
- Currency: PKR hardcoded (matches existing cash-movement code) — no new currency handling.
- No `sfya_customer_statement` changes — internal transfers have no partner and never touch a partner ledger.
- `post_init_hook` only runs on fresh module **install**, never on `-u` upgrade — every task that adds a `post_init_hook`-populated field must include a manual one-time re-invocation of the hook on the already-installed VPS instance.

---

## Deploy / upgrade loop (used in every task)

This addon is rsync-deployed via GitHub Actions on push to `main`. After commit + push:

1. `gh run list --branch main --limit 3 --json conclusion,workflowName,headSha` — wait for both `Lint` and `Deploy` = success on your HEAD SHA.
2. SSH upgrade:
   ```bash
   ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
   mod = env['ir.module.module'].search([('name', '=', 'sfya_pos_cash_movement')])
   print('pre  installed:', mod.installed_version, 'manifest:', mod.latest_version)
   mod.button_immediate_upgrade()
   env.cr.commit()
   print('post installed:', mod.installed_version, 'manifest:', mod.latest_version)
   n = env['ir.attachment'].search([('url', '=like', '/web/assets/%')]).unlink()
   env.cr.commit()
   print('cleared assets')
   EOF" 2>&1 | tail -8
   ```
3. For browser changes, hard-refresh (Cmd+Shift+R) and reopen POS.

Manifest version MUST be bumped in every task that changes Python or asset files, otherwise `button_immediate_upgrade` is a no-op and the JS bundle isn't rebuilt.

---

## File map (high-level)

| File | Task | Purpose |
|---|---|---|
| `addons/sfya_pos_cash_movement/models/res_company.py` | 1 | Add `sfya_internal_transfer_account_id` |
| `addons/sfya_pos_cash_movement/models/pos_config.py` | 1 | Related passthrough field |
| `addons/sfya_pos_cash_movement/views/pos_config_views.xml` | 1 | Expose field in SFYA Cash Control group |
| `addons/sfya_pos_cash_movement/__init__.py` | 1 | `post_init_hook`: create dedicated clearing account per company |
| `addons/sfya_pos_cash_movement/models/account_payment.py` | 2 | New fields + `sfya_pos_internal_transfer()` RPC |
| `addons/sfya_pos_cash_movement/models/pos_session.py` | 3 | Exclude transfers from generic scan, total cash-leg, extend till adjustment, `get_sfya_internal_transfers()` |
| `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js` | 4 | `"transfer"` mode: state, validation, confirm branch, print slip |
| `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml` | 4 | Transfer-mode UI, PaymentSlip branch |
| `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js` | 4 | `openTransfer()` |
| `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml` | 4 | "Transfer Funds" button |
| `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js` | 5 | Load + expose internal transfers |
| `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml` | 5 | "Internal Transfers" section |
| `addons/sfya_pos_cash_movement/__manifest__.py` | 1-5 | Patch-bump per task |
| `docs/ARCHITECTURE.md` | 7 | Note the new capability |

---

## Task 1: Backend — dedicated clearing account (company config + post_init_hook)

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/res_company.py`
- Modify: `addons/sfya_pos_cash_movement/models/pos_config.py`
- Modify: `addons/sfya_pos_cash_movement/views/pos_config_views.xml`
- Modify: `addons/sfya_pos_cash_movement/__init__.py`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

**Interfaces:**
- Produces: `res.company.sfya_internal_transfer_account_id` (Many2one `account.account`) — consumed by Task 2's RPC.

- [ ] **Step 1: Add company field**

Open `addons/sfya_pos_cash_movement/models/res_company.py`. Current full content:

```python
from odoo import fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'
    sfya_owner_drawing_account_id = fields.Many2one(
        'account.account',
        string="Owner's Drawing Account",
        help='Equity account debited when partners withdraw cash/bank funds.',
        domain="[('account_type', 'in', ['equity', 'equity_unaffected'])]",
    )
    sfya_partner_transfer_journal_id = fields.Many2one(
        'account.journal',
        string='Partner Transfer Journal',
        help='Miscellaneous-operations journal used to post POS Pay Out '
             '"settle via another partner" transfers. These entries have no '
             'cash/bank leg, so any type=General journal works; set this '
             'explicitly if the company has more than one.',
        domain="[('type', '=', 'general')]",
    )
```

Add a new field after `sfya_partner_transfer_journal_id`, making the file:

```python
from odoo import fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'
    sfya_owner_drawing_account_id = fields.Many2one(
        'account.account',
        string="Owner's Drawing Account",
        help='Equity account debited when partners withdraw cash/bank funds.',
        domain="[('account_type', 'in', ['equity', 'equity_unaffected'])]",
    )
    sfya_partner_transfer_journal_id = fields.Many2one(
        'account.journal',
        string='Partner Transfer Journal',
        help='Miscellaneous-operations journal used to post POS Pay Out '
             '"settle via another partner" transfers. These entries have no '
             'cash/bank leg, so any type=General journal works; set this '
             'explicitly if the company has more than one.',
        domain="[('type', '=', 'general')]",
    )
    sfya_internal_transfer_account_id = fields.Many2one(
        'account.account',
        string='Internal Transfer Clearing Account',
        help='Counterpart account used on both legs of a POS-initiated '
             'journal-to-journal transfer (e.g. shop cash till to a bank '
             'account). Both legs post together, so this account always '
             'nets to zero.',
        domain="[('account_type', '=', 'asset_current')]",
    )
```

- [ ] **Step 2: Add related field on `pos.config`**

Open `addons/sfya_pos_cash_movement/models/pos_config.py`. Current full content:

```python
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    sfya_max_cash_difference = fields.Float(
        string='Max Allowed Cash Difference (Rs)',
        default=500.0,
        help='Block session closing if cash difference (|counted - expected|) exceeds this amount. '
             'Set to 0 to disable the threshold check (zero-count check still applies).',
    )
    sfya_owner_drawing_account_id = fields.Many2one(
        related='company_id.sfya_owner_drawing_account_id',
        readonly=False,
        string='Owner Drawing Account',
    )
    sfya_partner_transfer_journal_id = fields.Many2one(
        related='company_id.sfya_partner_transfer_journal_id',
        readonly=False,
        string='Partner Transfer Journal',
    )
```

Add after `sfya_partner_transfer_journal_id`, making the file:

```python
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    sfya_max_cash_difference = fields.Float(
        string='Max Allowed Cash Difference (Rs)',
        default=500.0,
        help='Block session closing if cash difference (|counted - expected|) exceeds this amount. '
             'Set to 0 to disable the threshold check (zero-count check still applies).',
    )
    sfya_owner_drawing_account_id = fields.Many2one(
        related='company_id.sfya_owner_drawing_account_id',
        readonly=False,
        string='Owner Drawing Account',
    )
    sfya_partner_transfer_journal_id = fields.Many2one(
        related='company_id.sfya_partner_transfer_journal_id',
        readonly=False,
        string='Partner Transfer Journal',
    )
    sfya_internal_transfer_account_id = fields.Many2one(
        related='company_id.sfya_internal_transfer_account_id',
        readonly=False,
        string='Internal Transfer Clearing Account',
    )
```

- [ ] **Step 3: Expose field in the POS config view**

Open `addons/sfya_pos_cash_movement/views/pos_config_views.xml`. Current full content:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="pos_config_view_form_sfya_cash_control" model="ir.ui.view">
        <field name="name">pos.config.form.inherit.sfya.cash.control</field>
        <field name="model">pos.config</field>
        <field name="inherit_id" ref="point_of_sale.pos_config_view_form"/>
        <field name="arch" type="xml">
            <xpath expr="//sheet" position="inside">
                <group string="SFYA Cash Control">
                    <field name="sfya_max_cash_difference"/>
                    <field name="sfya_owner_drawing_account_id"/>
                    <field name="sfya_partner_transfer_journal_id"/>
                </group>
            </xpath>
        </field>
    </record>
</odoo>
```

Replace the `<group>` block:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="pos_config_view_form_sfya_cash_control" model="ir.ui.view">
        <field name="name">pos.config.form.inherit.sfya.cash.control</field>
        <field name="model">pos.config</field>
        <field name="inherit_id" ref="point_of_sale.pos_config_view_form"/>
        <field name="arch" type="xml">
            <xpath expr="//sheet" position="inside">
                <group string="SFYA Cash Control">
                    <field name="sfya_max_cash_difference"/>
                    <field name="sfya_owner_drawing_account_id"/>
                    <field name="sfya_partner_transfer_journal_id"/>
                    <field name="sfya_internal_transfer_account_id"/>
                </group>
            </xpath>
        </field>
    </record>
</odoo>
```

- [ ] **Step 4: Extend `post_init_hook` to create the clearing account**

Open `addons/sfya_pos_cash_movement/__init__.py`. Current full content:

```python
from . import models


def _post_init_create_drawing_account(env):
    """Create 'Owner\'s Drawing' account per company if missing."""
    for company in env['res.company'].search([]):
        if company.sfya_owner_drawing_account_id:
            continue
        existing = env['account.account'].search([
            ('company_ids', 'in', company.id),
            ('code', '=', '3100'),
        ], limit=1)
        if existing:
            company.sfya_owner_drawing_account_id = existing.id
            continue
        # Need a chart of accounts to be installed for the company
        if not env['account.account'].search_count([('company_ids', 'in', company.id)], limit=1):
            continue
        account = env['account.account'].create({
            'code': '3100',
            'name': "Owner's Drawing",
            'account_type': 'equity',
            'company_ids': [(6, 0, [company.id])],
        })
        company.sfya_owner_drawing_account_id = account.id

    for company in env['res.company'].search([]):
        if company.sfya_partner_transfer_journal_id:
            continue
        # Dedicated journal rather than reusing an existing general journal
        # (e.g. Misc Operations): that journal's move-name sequence is
        # whatever the company already uses it for, and partner-transfer
        # entries would inherit an unrelated naming pattern.
        existing = env['account.journal'].search([
            ('code', '=', 'PXFR'),
            ('company_id', '=', company.id),
        ], limit=1)
        if existing:
            company.sfya_partner_transfer_journal_id = existing.id
            continue
        if not env['account.account'].search_count([('company_ids', 'in', company.id)], limit=1):
            continue
        journal = env['account.journal'].create({
            'name': 'Partner Transfers',
            'code': 'PXFR',
            'type': 'general',
            'company_id': company.id,
        })
        company.sfya_partner_transfer_journal_id = journal.id
```

Append a third loop at the end of the function (same file, same function, new loop after the existing two):

```python
    for company in env['res.company'].search([]):
        if company.sfya_internal_transfer_account_id:
            continue
        existing = env['account.account'].search([
            ('company_ids', 'in', company.id),
            ('code', '=', '1994'),
        ], limit=1)
        if existing:
            company.sfya_internal_transfer_account_id = existing.id
            continue
        if not env['account.account'].search_count([('company_ids', 'in', company.id)], limit=1):
            continue
        account = env['account.account'].create({
            'code': '1994',
            'name': 'Internal Transfers Clearing',
            'account_type': 'asset_current',
            'company_ids': [(6, 0, [company.id])],
        })
        company.sfya_internal_transfer_account_id = account.id
```

- [ ] **Step 5: Bump manifest version**

Edit `addons/sfya_pos_cash_movement/__manifest__.py`:

```python
'version': '18.0.6.0.0',
```

- [ ] **Step 6: Syntax check**

```bash
python3 -m py_compile addons/sfya_pos_cash_movement/__init__.py \
    addons/sfya_pos_cash_movement/models/res_company.py \
    addons/sfya_pos_cash_movement/models/pos_config.py
```

Expected: no output, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add addons/sfya_pos_cash_movement/models/res_company.py \
        addons/sfya_pos_cash_movement/models/pos_config.py \
        addons/sfya_pos_cash_movement/views/pos_config_views.xml \
        addons/sfya_pos_cash_movement/__init__.py \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "$(cat <<'EOF'
feat(pos_cash_movement): add dedicated Internal Transfer clearing account

New sfya_internal_transfer_account_id on res.company/pos.config, auto-
created (code 1994, asset_current) via post_init_hook, same
search-by-code-then-create pattern as the existing Owner's Drawing
account and Partner Transfer journal. No behavior yet - this is the
config groundwork for Task 2's transfer RPC.
EOF
)"
git push origin main
```

- [ ] **Step 8: Wait for CI + upgrade**

Run the Deploy / upgrade loop above.

- [ ] **Step 9: One-time manual hook re-run (post_init_hook does not run on `-u` upgrade)**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
from odoo.addons.sfya_pos_cash_movement import _post_init_create_drawing_account
_post_init_create_drawing_account(env)
env.cr.commit()
for company in env['res.company'].search([]):
    acc = company.sfya_internal_transfer_account_id
    print(company.name, '->', acc.id, acc.code, acc.name)
EOF" 2>&1 | tail -10
```

Expected: every company prints an account with `code=1994`, `name=Internal Transfers Clearing`.

---

## Task 2: Backend — `account.payment` fields + `sfya_pos_internal_transfer` RPC

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/account_payment.py`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

**Interfaces:**
- Consumes: `res.company.sfya_internal_transfer_account_id` (Task 1).
- Produces: `account.payment.sfya_pos_internal_transfer(session_id, from_journal_id, to_journal_id, amount, memo='', date=None)` → `{out_id, out_name, in_id, in_name, from_journal_id, from_journal_name, to_journal_id, to_journal_name, amount, memo, direction: 'internal_transfer'}` — consumed by Task 4's modal. `account.payment.sfya_is_internal_transfer` / `sfya_transfer_pair_id` — consumed by Task 3's bucketing.

⚠️ **Verify before proceeding to Task 3:** every existing payment method in this module sets a real `partner_id` even when overriding `destination_account_id` (Partner Drawing uses the shareholder as `partner_id`). This task creates payments with `partner_id` left unset entirely. Step 6 below is the proof this works on `action_post()`. If it raises, STOP and fall back to a single 2-line `account.move` (debit destination journal's `default_account_id`, credit source journal's `default_account_id`) — same architecture as the existing Partner Transfer feature (`models/account_move.py`) — instead of two `account.payment` records, before continuing to Task 3.

- [ ] **Step 1: Add the two new fields**

Open `addons/sfya_pos_cash_movement/models/account_payment.py`. Insert directly after the existing `pos_session_id` field declaration (before the blank line preceding `@api.model` / `sfya_pos_collect`):

```python
    sfya_is_internal_transfer = fields.Boolean(
        default=False,
        copy=False,
        help='True for both legs of a POS-initiated journal-to-journal '
             'transfer (e.g. shop cash till to a bank account). Used to '
             'exclude these from the generic Collect/Pay Out/Drawing '
             'listings and total them separately for the till '
             'expected-cash adjustment.',
    )
    sfya_transfer_pair_id = fields.Many2one(
        'account.payment',
        string='Paired Transfer Leg',
        copy=False,
        help='The other leg of this internal transfer (out<->in).',
    )
```

- [ ] **Step 2: Add the `sfya_pos_internal_transfer` RPC**

In the same file, insert the new method directly after `sfya_pos_partner_drawing` (i.e. right before the `def _sfya_resolve_partner_type` method):

```python
    @api.model
    def sfya_pos_internal_transfer(self, session_id, from_journal_id, to_journal_id, amount, memo='', date=None):
        """RPC: move funds directly between two of the company's own cash/bank
        journals (e.g. shop cash till to a bank account, or bank to bank).

        Posts two linked account.payment records with no partner, using a
        dedicated clearing account as the counterpart on both legs so the
        pair always nets to zero. Till expected-cash math is adjusted
        separately in pos_session.get_sfya_cash_movements.
        """
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        if from_journal_id == to_journal_id:
            raise UserError(_('Source and destination account must be different.'))
        from_journal = self.env['account.journal'].sudo().browse(from_journal_id).exists()
        to_journal = self.env['account.journal'].sudo().browse(to_journal_id).exists()
        if not from_journal or not to_journal:
            raise UserError(_('Account not found.'))
        if from_journal.type not in ('cash', 'bank') or to_journal.type not in ('cash', 'bank'):
            raise UserError(_('Both accounts must be a cash or bank journal.'))
        if from_journal.company_id.id != session.company_id.id or to_journal.company_id.id != session.company_id.id:
            raise UserError(_("Account does not belong to this POS's company."))
        if amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        clearing_account = session.company_id.sfya_internal_transfer_account_id
        if not clearing_account:
            raise UserError(_('Internal Transfer Clearing Account is not configured for this company.'))

        resolved_date = fields.Date.today()
        if (from_journal.type == 'bank' or to_journal.type == 'bank') and date:
            try:
                resolved_date = fields.Date.from_string(date)
            except (ValueError, TypeError):
                raise UserError(_("Invalid date format."))
            if resolved_date > fields.Date.today():
                raise UserError(_("Date cannot be in the future."))
        # both journals cash: ignore passed date; resolved_date stays today

        payment_out = self.sudo().create({
            'payment_type': 'outbound',
            'journal_id': from_journal.id,
            'amount': amount,
            'date': resolved_date,
            'memo': memo or False,
            'pos_session_id': session.id,
            'destination_account_id': clearing_account.id,
            'sfya_is_internal_transfer': True,
        })
        payment_in = self.sudo().create({
            'payment_type': 'inbound',
            'journal_id': to_journal.id,
            'amount': amount,
            'date': resolved_date,
            'memo': memo or False,
            'pos_session_id': session.id,
            'destination_account_id': clearing_account.id,
            'sfya_is_internal_transfer': True,
        })
        payment_out.sfya_transfer_pair_id = payment_in.id
        payment_in.sfya_transfer_pair_id = payment_out.id
        payment_out.action_post()
        payment_in.action_post()
        return {
            'out_id': payment_out.id,
            'out_name': payment_out.name,
            'in_id': payment_in.id,
            'in_name': payment_in.name,
            'from_journal_id': from_journal.id,
            'from_journal_name': from_journal.name,
            'to_journal_id': to_journal.id,
            'to_journal_name': to_journal.name,
            'amount': amount,
            'memo': memo or '',
            'direction': 'internal_transfer',
        }
```

- [ ] **Step 3: Bump manifest version**

Edit `addons/sfya_pos_cash_movement/__manifest__.py`:

```python
'version': '18.0.6.0.1',
```

- [ ] **Step 4: Syntax check**

```bash
python3 -m py_compile addons/sfya_pos_cash_movement/models/account_payment.py
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add addons/sfya_pos_cash_movement/models/account_payment.py \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "$(cat <<'EOF'
feat(pos_cash_movement): add sfya_pos_internal_transfer RPC

Two linked, partner-less account.payment legs against the new clearing
account (Task 1). New sfya_is_internal_transfer / sfya_transfer_pair_id
fields mark and link both legs for pos_session's bucketing (Task 3).
EOF
)"
git push origin main
```

- [ ] **Step 6: Wait for CI + upgrade, then smoke — cash-to-bank transfer posts cleanly**

Run the Deploy / upgrade loop, then:

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
print('session:', sess.id, sess.name)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
print('journals:', js)
cash_jid = next(j['id'] for j in js if j['type'] == 'cash')
bank_jid = next((j['id'] for j in js if j['type'] == 'bank'), None)
if not bank_jid:
    print('NO BANK JOURNAL - create one first (Settings > Accounting > Journals > New, type=Bank)')
else:
    r = env['account.payment'].sfya_pos_internal_transfer(sess.id, cash_jid, bank_jid, 500.0, memo='task2 smoke')
    print('result:', r)
    env.cr.commit()
    out = env['account.payment'].browse(r['out_id'])
    inn = env['account.payment'].browse(r['in_id'])
    print('out state:', out.state, 'destination_account:', out.destination_account_id.code, 'partner:', out.partner_id)
    print('in  state:', inn.state, 'destination_account:', inn.destination_account_id.code, 'partner:', inn.partner_id)
    print('pair link ok:', out.sfya_transfer_pair_id.id == inn.id and inn.sfya_transfer_pair_id.id == out.id)
    clearing = sess.company_id.sfya_internal_transfer_account_id
    lines = env['account.move.line'].search([
        ('account_id', '=', clearing.id),
        ('move_id', 'in', [out.move_id.id, inn.move_id.id]),
    ])
    net = sum(l.debit - l.credit for l in lines)
    print('clearing account net for this pair (expect 0.0):', net)
EOF" 2>&1 | tail -20
```

Expected: `out state: posted`, `in state: posted`, both `destination_account: 1994`, both `partner: res.partner()` (empty recordset — falsy), `pair link ok: True`, `clearing account net for this pair (expect 0.0): 0.0`. If `action_post()` raises here instead, apply the fallback described in the risk note above before continuing.

---

## Task 3: Backend — `pos_session.py` bucketing + till adjustment

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/pos_session.py`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

**Interfaces:**
- Consumes: `account.payment.sfya_is_internal_transfer` / `sfya_transfer_pair_id` (Task 2).
- Produces: `pos.session.get_sfya_internal_transfers()` → `[{id, name, from_journal_name, to_journal_name, amount, memo}]` — consumed by Task 5's closing dialog. `get_sfya_cash_movements()`'s `cash` dict gains `transfers_in_total` / `transfers_out_total` keys.

- [ ] **Step 1: Replace `get_sfya_cash_movements`**

Open `addons/sfya_pos_cash_movement/models/pos_session.py`. Replace the entire `get_sfya_cash_movements` method (from `def get_sfya_cash_movements(self):` through its closing `return { ... }`) with:

```python
    def get_sfya_cash_movements(self):
        """Return SFYA POS-recorded cash + bank payments for this session.

        Returns:
            {
                'cash': {collects, collects_total, payouts, payouts_total,
                         drawings, drawings_total,
                         transfers_in_total, transfers_out_total},
                'banks': [
                    {journal_id, journal_name, collects, collects_total,
                     payouts, payouts_total, drawings, drawings_total},
                    ...
                ],
            }

        Banks list contains only journals that had at least one movement
        this session, sorted by journal name. Internal-transfer payments
        (sfya_is_internal_transfer=True) are excluded from all of the
        above and totalled separately into cash.transfers_in_total /
        transfers_out_total, restricted to the cash journal only - that's
        the only leg that affects the physically-counted till.
        """
        self.ensure_one()
        payments = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('state', 'in', ['paid', 'in_process']),
            ('journal_id.type', 'in', ['cash', 'bank']),
            ('sfya_is_internal_transfer', '=', False),
        ], order='create_date asc')

        def _row(p):
            return {
                'id': p.id,
                'name': p.name,
                'partner_id': p.partner_id.id,
                'partner_name': p.partner_id.name or '',
                'amount': p.amount,
                'memo': p.memo or '',
            }

        drawing_account = self.company_id.sfya_owner_drawing_account_id

        cash_collects, cash_payouts, cash_drawings = [], [], []
        bank_buckets = {}
        for p in payments:
            row = _row(p)
            j = p.journal_id
            is_drawing = bool(drawing_account and p.destination_account_id == drawing_account)
            if j.type == 'cash':
                if p.payment_type == 'inbound':
                    cash_collects.append(row)
                elif is_drawing:
                    cash_drawings.append(row)
                else:
                    cash_payouts.append(row)
            else:  # bank
                bucket = bank_buckets.setdefault(j.id, {
                    'journal_id': j.id,
                    'journal_name': j.name,
                    'collects': [],
                    'payouts': [],
                    'drawings': [],
                })
                if p.payment_type == 'inbound':
                    bucket['collects'].append(row)
                elif is_drawing:
                    bucket['drawings'].append(row)
                else:
                    bucket['payouts'].append(row)

        banks = []
        for b in sorted(bank_buckets.values(), key=lambda b: b['journal_name']):
            b['collects_total'] = sum(r['amount'] for r in b['collects'])
            b['payouts_total'] = sum(r['amount'] for r in b['payouts'])
            b['drawings_total'] = sum(r['amount'] for r in b['drawings'])
            banks.append(b)

        transfers = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('state', 'in', ['paid', 'in_process']),
            ('sfya_is_internal_transfer', '=', True),
            ('journal_id.type', '=', 'cash'),
        ])
        transfers_in_total = sum(p.amount for p in transfers if p.payment_type == 'inbound')
        transfers_out_total = sum(p.amount for p in transfers if p.payment_type == 'outbound')

        return {
            'cash': {
                'collects': cash_collects,
                'collects_total': sum(r['amount'] for r in cash_collects),
                'payouts': cash_payouts,
                'payouts_total': sum(r['amount'] for r in cash_payouts),
                'drawings': cash_drawings,
                'drawings_total': sum(r['amount'] for r in cash_drawings),
                'transfers_in_total': transfers_in_total,
                'transfers_out_total': transfers_out_total,
            },
            'banks': banks,
        }
```

- [ ] **Step 2: Add `get_sfya_internal_transfers`**

In the same file, insert this new method directly after `get_sfya_partner_transfers` (i.e. right before `get_sfya_allowed_journals`):

```python
    def get_sfya_internal_transfers(self):
        """Return this session's journal-to-journal transfers, one row per
        pair (via the outbound leg), informational for the closing dialog.

        Only the cash-journal leg (if any) affects the till count, and
        that's already folded into get_sfya_cash_movements's cash dict -
        this listing is purely for display.
        """
        self.ensure_one()
        payments = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('sfya_is_internal_transfer', '=', True),
            ('payment_type', '=', 'outbound'),
            ('state', 'in', ['paid', 'in_process']),
        ], order='create_date asc')
        return [{
            'id': p.id,
            'name': p.name,
            'from_journal_name': p.journal_id.name,
            'to_journal_name': p.sfya_transfer_pair_id.journal_id.name if p.sfya_transfer_pair_id else '',
            'amount': p.amount,
            'memo': p.memo or '',
        } for p in payments]
```

- [ ] **Step 3: Extend `get_closing_control_data`'s adjustment formula**

In the same file, replace the existing `get_closing_control_data` method:

```python
    def get_closing_control_data(self):
        data = super().get_closing_control_data()
        movements = self.get_sfya_cash_movements()
        cash = movements.get('cash') or {}
        adjustment = (cash.get('collects_total') or 0.0) - (cash.get('payouts_total') or 0.0) - (cash.get('drawings_total') or 0.0)
        if data.get('default_cash_details') and adjustment:
            data['default_cash_details']['amount'] = (
                data['default_cash_details'].get('amount', 0.0) + adjustment
            )
        return data
```

with:

```python
    def get_closing_control_data(self):
        data = super().get_closing_control_data()
        movements = self.get_sfya_cash_movements()
        cash = movements.get('cash') or {}
        adjustment = (
            (cash.get('collects_total') or 0.0) - (cash.get('payouts_total') or 0.0) - (cash.get('drawings_total') or 0.0)
            + (cash.get('transfers_in_total') or 0.0) - (cash.get('transfers_out_total') or 0.0)
        )
        if data.get('default_cash_details') and adjustment:
            data['default_cash_details']['amount'] = (
                data['default_cash_details'].get('amount', 0.0) + adjustment
            )
        return data
```

- [ ] **Step 4: Bump manifest version**

Edit `addons/sfya_pos_cash_movement/__manifest__.py`:

```python
'version': '18.0.6.0.2',
```

- [ ] **Step 5: Syntax check**

```bash
python3 -m py_compile addons/sfya_pos_cash_movement/models/pos_session.py
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add addons/sfya_pos_cash_movement/models/pos_session.py \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "$(cat <<'EOF'
feat(pos_cash_movement): fold internal transfers into till math + listing

get_sfya_cash_movements excludes transfer legs from the generic
Collect/Pay Out/Drawing buckets and totals the cash-journal leg
separately (transfers_in_total/transfers_out_total). Closing control
data's expected-cash adjustment now includes that net. New
get_sfya_internal_transfers() lists each transfer once via its
outbound leg for the closing dialog's informational display.
EOF
)"
git push origin main
```

- [ ] **Step 7: Wait for CI + upgrade, then smoke — bucketing + till math**

Run the Deploy / upgrade loop, then:

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
import json
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
mv = sess.get_sfya_cash_movements()
print('cash bucket keys:', sorted(mv['cash'].keys()))
print('cash payouts (should NOT include the Task 2 transfer leg):', [r['id'] for r in mv['cash']['payouts']])
print('cash collects (should NOT include the Task 2 transfer leg):', [r['id'] for r in mv['cash']['collects']])
print('transfers_in_total:', mv['cash']['transfers_in_total'], ' transfers_out_total:', mv['cash']['transfers_out_total'])
data = sess.get_closing_control_data()
print('default_cash_details.amount:', data.get('default_cash_details', {}).get('amount'))
print(json.dumps(sess.get_sfya_internal_transfers(), indent=2, default=str))
EOF" 2>&1 | tail -20
```

Expected: `cash bucket keys` includes `transfers_in_total`/`transfers_out_total` alongside the existing keys. Neither `cash.payouts` nor `cash.collects` contains the Task 2 smoke transfer's payment ids (500.0 cash-out leg from that smoke). `transfers_out_total` is `>= 500.0` (the cash leg from Task 2's smoke was outbound-from-cash). `get_sfya_internal_transfers()` output includes one row with `amount: 500.0`, `memo: 'task2 smoke'`, correct `from_journal_name`/`to_journal_name`.

---

## Task 4: Frontend — Transfer mode in the modal + toolbar button

**Files:**
- Modify: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

**Interfaces:**
- Consumes: `account.payment.sfya_pos_internal_transfer` RPC (Task 2), `pos.session.get_sfya_allowed_journals` (existing, unchanged).

- [ ] **Step 1: Allow `"transfer"` mode + add journal-pair state**

Open `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`. Change the `mode` prop validation:

```javascript
    static props = {
        mode: { type: String, validate: (v) => ["collect", "payout", "drawing", "transfer"].includes(v) },
        initialPartner: { type: Object, optional: true },
        close: Function,
    };
```

Replace `setup()`:

```javascript
    setup() {
        this.pos = useService("pos");
        this.notification = useService("notification");
        this.state = useState({
            partner: this.props.initialPartner || null,
            journal_id: null,
            journals: [],
            fromJournalId: null,
            toJournalId: null,
            amount: "",
            memo: "",
            date: this._todayStr(),
            print: false,
            submitting: false,
            error: "",
            destination: "journal", // "journal" | "partner" (payout mode only)
            fundingPartner: null,
        });
        onWillStart(async () => {
            try {
                const journals = await this.pos.data.call(
                    "pos.session",
                    "get_sfya_allowed_journals",
                    [],
                    { session_id: this.pos.session.id },
                );
                this.state.journals = journals || [];
                if (this.state.journals.length > 0) {
                    this.state.journal_id = this.state.journals[0].id;
                    if (this.props.mode === "transfer") {
                        this.state.fromJournalId = this.state.journals[0].id;
                        this.state.toJournalId = this.state.journals.length > 1
                            ? this.state.journals[1].id
                            : null;
                    }
                } else {
                    this.state.error = _t("No cash or bank journal configured for this company.");
                }
            } catch (e) {
                this.state.error = e?.data?.message || e?.message || _t("Failed to load accounts.");
            }
        });
    }
```

- [ ] **Step 2: Add `"transfer"` branches to `title`/`confirmLabel`/`confirmClass`, add `eitherJournalIsBank` getter**

Replace the three getters:

```javascript
    get title() {
        if (this.props.mode === "collect") return _t("Collect Payment");
        if (this.props.mode === "drawing") return _t("Partner Drawing");
        if (this.props.mode === "transfer") return _t("Transfer Funds");
        return _t("Pay Out");
    }

    get confirmLabel() {
        if (this.props.mode === "collect") return _t("Collect");
        if (this.props.mode === "drawing") return _t("Record Drawing");
        if (this.props.mode === "transfer") return _t("Transfer");
        return _t("Pay Out");
    }

    get confirmClass() {
        if (this.props.mode === "collect") return "btn-success";
        if (this.props.mode === "drawing") return "btn-info";
        if (this.props.mode === "transfer") return "btn-primary";
        return "btn-warning";
    }
```

Add this new getter directly after `get selectedJournalIsBank()`:

```javascript
    get eitherJournalIsBank() {
        const from = this.state.journals.find((x) => x.id === this.state.fromJournalId);
        const to = this.state.journals.find((x) => x.id === this.state.toJournalId);
        return from?.type === "bank" || to?.type === "bank";
    }
```

- [ ] **Step 3: Rewrite `isValid` to branch on transfer mode**

Replace `get isValid()`:

```javascript
    get isValid() {
        const amt = parseFloat(this.state.amount);
        if (!Number.isFinite(amt) || amt <= 0 || this.state.submitting) {
            return false;
        }
        if (this.props.mode === "transfer") {
            return (
                !!this.state.fromJournalId &&
                !!this.state.toJournalId &&
                this.state.fromJournalId !== this.state.toJournalId
            );
        }
        if (!this.state.partner) {
            return false;
        }
        if (this.isPartnerDestination) {
            return !!this.state.fundingPartner && this.state.fundingPartner.id !== this.state.partner.id;
        }
        return !!this.state.journal_id;
    }
```

- [ ] **Step 4: Add the transfer branch to `confirm()`**

Replace the whole `async confirm()` method:

```javascript
    async confirm() {
        if (!this.isValid) return;
        this.state.submitting = true;
        this.state.error = "";
        const sessionId = this.pos.session.id;
        const amount = parseFloat(this.state.amount);
        const memo = this.state.memo || "";

        if (this.props.mode === "transfer") {
            try {
                const kwargs = {
                    session_id: sessionId,
                    from_journal_id: this.state.fromJournalId,
                    to_journal_id: this.state.toJournalId,
                    amount,
                    memo,
                };
                if (this.eitherJournalIsBank) kwargs.date = this.state.date;
                const result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_internal_transfer",
                    [],
                    kwargs,
                );
                this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
                this.pos.sfyaCashMovements.push(result);
                this.notification.add(
                    _t("Transferred %s from %s to %s", result.amount, result.from_journal_name, result.to_journal_name),
                    { type: "success" },
                );
                if (this.state.print) {
                    await this._printSlip({
                        direction: "internal_transfer",
                        name: `${result.out_name} / ${result.in_name}`,
                        from_journal_name: result.from_journal_name,
                        to_journal_name: result.to_journal_name,
                        amount: result.amount,
                        memo: result.memo,
                    });
                }
                this.props.close();
            } catch (e) {
                this.state.error = e?.data?.message || e?.message || _t("Failed to record transfer.");
                this.state.submitting = false;
            }
            return;
        }

        const partnerId = this.state.partner.id;
        const journalId = this.state.journal_id;
        const dateVal = this.isPartnerDestination
            ? undefined
            : this.selectedJournalIsBank ? this.state.date : undefined;
        try {
            let result;
            if (this.isPartnerDestination) {
                const kwargs = {
                    session_id: sessionId,
                    from_partner_id: this.state.fundingPartner.id,
                    to_partner_id: partnerId,
                    amount,
                    memo,
                };
                result = await this.pos.data.call(
                    "account.move",
                    "sfya_pos_partner_transfer",
                    [],
                    kwargs,
                );
                this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
                this.pos.sfyaCashMovements.push(result);
                this.notification.add(
                    _t("Paid %s to %s, funded by %s", result.amount, result.to_partner_name, result.from_partner_name),
                    { type: "success" },
                );
                if (this.state.print) {
                    await this._printSlip({
                        direction: "transfer",
                        name: result.name,
                        partner_name: result.to_partner_name,
                        funding_partner_name: result.from_partner_name,
                        amount: result.amount,
                        memo: result.memo,
                        date: new Date().toLocaleString(),
                        cashier: this.pos.get_cashier()?.name || "",
                    });
                }
                this.props.close();
                return;
            }
            if (this.props.mode === "drawing") {
                const kwargs = {
                    session_id: sessionId,
                    partner_id: partnerId,
                    amount,
                    journal_id: journalId,
                    memo,
                };
                if (dateVal !== undefined) kwargs.date = dateVal;
                result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_partner_drawing",
                    [],
                    kwargs,
                );
            } else if (this.props.mode === "collect") {
                const kwargs = {
                    session_id: sessionId,
                    partner_id: partnerId,
                    amount,
                    journal_id: journalId,
                    memo,
                };
                if (dateVal !== undefined) kwargs.date = dateVal;
                result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_collect",
                    [],
                    kwargs,
                );
            } else {
                const kwargs = {
                    session_id: sessionId,
                    partner_id: partnerId,
                    amount,
                    journal_id: journalId,
                    memo,
                };
                if (dateVal !== undefined) kwargs.date = dateVal;
                result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_payout",
                    [],
                    kwargs,
                );
            }
            this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
            this.pos.sfyaCashMovements.push(result);
            if (this.props.mode === "drawing") {
                this.notification.add(
                    _t("Drawing of %s recorded for %s", result.amount, result.partner_name),
                    { type: "success" },
                );
            } else {
                this.notification.add(
                    this.props.mode === "collect"
                        ? _t("Collected %s from %s", result.amount, result.partner_name)
                        : _t("Paid %s to %s", result.amount, result.partner_name),
                    { type: "success" },
                );
            }
            if (this.state.print) {
                const slipData = { ...result };
                if (this.props.mode === "drawing") slipData.direction = "drawing";
                await this._printSlip(slipData);
            }
            this.props.close();
        } catch (e) {
            this.state.error = e?.data?.message || e?.message || _t("Failed to record payment.");
            this.state.submitting = false;
        }
    }
```

(Everything from `const partnerId = ...` down is the pre-existing body, unchanged — only the new transfer-mode block above it and the early `return` inside it are new.)

- [ ] **Step 5: Pass journal names through `_printSlip`**

Replace `async _printSlip(result)`:

```javascript
    async _printSlip(result) {
        try {
            await this.pos.printer.print(
                "sfya_pos_cash_movement.PaymentSlip",
                {
                    direction: result.direction,
                    name: result.name,
                    partner_name: result.partner_name,
                    funding_partner_name: result.funding_partner_name || "",
                    from_journal_name: result.from_journal_name || "",
                    to_journal_name: result.to_journal_name || "",
                    amount: result.amount,
                    memo: result.memo,
                    date: new Date().toLocaleString(),
                    cashier: this.pos.get_cashier()?.name || "",
                },
            );
        } catch (e) {
            this.notification.add(_t("Payment recorded but print failed."), { type: "warning" });
        }
    }
```

- [ ] **Step 6: Rework the modal template's top section for transfer mode**

Open `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml`. Replace everything from the opening `<div class="o_cash_movement_modal d-flex flex-column gap-3">` line through the closing `</div>` that immediately precedes the Amount block (i.e. lines 6-56 of the current file) with:

```xml
            <div class="o_cash_movement_modal d-flex flex-column gap-3">
                <t t-if="props.mode !== 'transfer'">
                    <div>
                        <label class="form-label fw-bold">Partner</label>
                        <div class="d-flex align-items-center gap-2">
                            <button class="btn btn-outline-secondary" t-on-click="pickPartner">
                                <t t-if="state.partner" t-esc="state.partner.name"/>
                                <t t-else="">Select Partner</t>
                            </button>
                        </div>
                    </div>
                    <div t-if="canUsePartnerDestination">
                        <label class="form-label fw-bold">Destination</label>
                        <div class="btn-group w-100" role="group">
                            <button type="button" class="btn"
                                    t-att-class="state.destination === 'journal' ? 'btn-primary' : 'btn-outline-secondary'"
                                    t-on-click="() => state.destination = 'journal'">Cash / Bank</button>
                            <button type="button" class="btn"
                                    t-att-class="state.destination === 'partner' ? 'btn-primary' : 'btn-outline-secondary'"
                                    t-on-click="() => state.destination = 'partner'">Another Partner</button>
                        </div>
                    </div>
                </t>
                <t t-if="props.mode === 'transfer'">
                    <div>
                        <label class="form-label fw-bold">From Account</label>
                        <select class="form-select" t-model.number="state.fromJournalId"
                                t-att-disabled="state.submitting or !state.journals.length">
                            <t t-foreach="state.journals" t-as="j" t-key="j.id">
                                <option t-att-value="j.id">
                                    <t t-esc="j.name"/>
                                    <t t-if="j.type === 'bank'"> (Bank)</t>
                                </option>
                            </t>
                        </select>
                    </div>
                    <div>
                        <label class="form-label fw-bold">To Account</label>
                        <select class="form-select" t-model.number="state.toJournalId"
                                t-att-disabled="state.submitting or !state.journals.length">
                            <t t-foreach="state.journals" t-as="j" t-key="j.id">
                                <option t-att-value="j.id">
                                    <t t-esc="j.name"/>
                                    <t t-if="j.type === 'bank'"> (Bank)</t>
                                </option>
                            </t>
                        </select>
                    </div>
                    <div t-if="state.fromJournalId and state.fromJournalId === state.toJournalId"
                         class="alert alert-warning mb-0 py-1 px-2">
                        From and To accounts must be different.
                    </div>
                    <div t-if="eitherJournalIsBank">
                        <label class="form-label fw-bold">Date</label>
                        <input type="date" class="form-control"
                               t-model="state.date" t-att-max="todayStr"/>
                        <small class="text-muted">Date the bank transfer actually happened. Today by default.</small>
                    </div>
                </t>
                <t t-if="props.mode !== 'transfer' and !isPartnerDestination">
                    <div>
                        <label class="form-label fw-bold">Account</label>
                        <select class="form-select" t-model.number="state.journal_id"
                                t-att-disabled="state.submitting or !state.journals.length">
                            <t t-foreach="state.journals" t-as="j" t-key="j.id">
                                <option t-att-value="j.id">
                                    <t t-esc="j.name"/>
                                    <t t-if="j.type === 'bank'"> (Bank)</t>
                                </option>
                            </t>
                        </select>
                    </div>
                    <div t-if="selectedJournalIsBank">
                        <label class="form-label fw-bold">Date</label>
                        <input type="date" class="form-control"
                               t-model="state.date" t-att-max="todayStr"/>
                        <small class="text-muted">Date the bank transfer actually happened. Today by default.</small>
                    </div>
                </t>
                <div t-if="props.mode !== 'transfer' and isPartnerDestination">
                    <label class="form-label fw-bold">Funded By</label>
                    <div class="d-flex align-items-center gap-2">
                        <button class="btn btn-outline-secondary" t-on-click="pickFundingPartner">
                            <t t-if="state.fundingPartner" t-esc="state.fundingPartner.name"/>
                            <t t-else="">Select Partner</t>
                        </button>
                    </div>
                    <small class="text-muted">This partner's balance settles the payout instead of cash/bank. No till impact.</small>
                </div>
```

Everything after this (Amount, Memo, Print checkbox, error div, footer, and the `PaymentSlip` template) stays exactly as-is in the file — only the block above (partner/destination/account/funded-by section) is replaced.

- [ ] **Step 7: Add `internal_transfer` branches to the `PaymentSlip` template**

In the same file, in the `sfya_pos_cash_movement.PaymentSlip` template, replace the `Type:` line:

```xml
            <div>Type:    <t t-if="direction === 'inbound'">Collect Payment</t><t t-elif="direction === 'drawing'">Partner Drawing</t><t t-elif="direction === 'transfer'">Pay Out (via Partner)</t><t t-elif="direction === 'internal_transfer'">Internal Transfer</t><t t-else="">Pay Out</t></div>
```

Replace the `Partner:` / `Funded By:` lines with:

```xml
            <div t-if="direction !== 'internal_transfer'">Partner: <t t-esc="partner_name"/></div>
            <div t-if="funding_partner_name">Funded By: <t t-esc="funding_partner_name"/></div>
            <div t-if="direction === 'internal_transfer'">From:    <t t-esc="from_journal_name"/></div>
            <div t-if="direction === 'internal_transfer'">To:      <t t-esc="to_journal_name"/></div>
```

Replace the bottom signature line:

```xml
            <div t-if="direction === 'inbound'">Received by: ______________</div>
            <div t-elif="direction === 'drawing'">Withdrawn by: _____________</div>
            <div t-elif="direction === 'internal_transfer'">Processed by: ______________</div>
            <div t-else="">Paid to:     ______________</div>
```

- [ ] **Step 8: Add the toolbar button**

Open `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js`. Add a new method to the `patch(ControlButtons.prototype, {...})` block, directly after `openDrawing()`:

```javascript
    openTransfer() {
        this.dialog.add(CashMovementModal, { mode: "transfer" });
    },
```

Open `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml`. Insert a new button directly after the Partner Drawing button, before the Customer Overview button:

```xml
            <button class="control-button btn btn-secondary btn-lg py-5 o_cash_movement_transfer"
                    t-on-click="openTransfer">
                <i class="fa fa-exchange text-primary me-1"/>
                Transfer Funds
            </button>
```

- [ ] **Step 9: Bump manifest version**

Edit `addons/sfya_pos_cash_movement/__manifest__.py`:

```python
'version': '18.0.6.0.3',
```

- [ ] **Step 10: Syntax check**

```bash
node --check addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js
node --check addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js
```

Expected: no output (both are plain ES modules; `node --check` parses syntax without executing). If `node` isn't on PATH, skip and rely on Step 12's browser load instead (a JS syntax error surfaces immediately as a failed asset bundle).

- [ ] **Step 11: Commit**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js \
        addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml \
        addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js \
        addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "$(cat <<'EOF'
feat(pos_cash_movement): Transfer Funds mode in Cash Movement modal

New "transfer" mode: no partner picker, two journal pickers (From/To
Account) instead, calls sfya_pos_internal_transfer. New toolbar button
"Transfer Funds" opens the modal in that mode. Print slip gains a
matching internal_transfer branch (From/To journal instead of partner).
EOF
)"
git push origin main
```

- [ ] **Step 12: Wait for CI + upgrade, then browser smoke**

Run the Deploy / upgrade loop, hard-refresh the POS browser tab, then:

1. POS → control buttons → "Transfer Funds" (new button, exchange icon) → modal opens titled "Transfer Funds".
2. No Partner field visible. "From Account" and "To Account" dropdowns visible, both populated, defaulted to two different journals if 2+ exist.
3. Pick the shop cash till as From, a bank journal as To. Enter 100. Confirm button reads "Transfer".
4. Click Transfer. Toast: "Transferred 100 from <Till> to <Bank>".
5. Reopen the modal, pick the SAME journal for both From and To → inline warning "From and To accounts must be different." appears, Transfer button stays disabled.
6. Verify backend:
   ```bash
   ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
   p = env['account.payment'].search([('sfya_is_internal_transfer', '=', True)], order='id desc', limit=2)
   for x in p:
       print(x.name, x.payment_type, x.journal_id.name, x.amount, x.state)
   EOF" 2>&1 | tail -5
   ```
   Expected: 2 most recent rows are the out/in pair from step 4, correct journals and amount.

---

## Task 5: Frontend — "Internal Transfers" section in the closing dialog

**Files:**
- Modify: `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

**Interfaces:**
- Consumes: `pos.session.get_sfya_internal_transfers()` (Task 3).

- [ ] **Step 1: Load internal transfers into closing-dialog state**

Open `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js`. Replace the `patch(ClosePosPopup.prototype, {...})` block's `setup()`:

```javascript
    setup() {
        super.setup();
        this.sfya = useState({
            cash: {
                collects: [],
                collects_total: 0,
                payouts: [],
                payouts_total: 0,
                drawings: [],
                drawings_total: 0,
            },
            banks: [],
            transfers: [],
            internalTransfers: [],
            cashCollectsOpen: true,
            cashPayoutsOpen: true,
            drawingsOpen: true,
            transfersOpen: true,
            internalTransfersOpen: true,
            banksOpen: {}, // journal_id -> boolean
            loaded: false,
            closeError: null,
        });
        onWillStart(async () => {
            try {
                const data = await this.pos.data.call(
                    "pos.session",
                    "get_sfya_cash_movements",
                    [[this.pos.session.id]],
                );
                if (data?.cash) {
                    Object.assign(this.sfya.cash, data.cash);
                }
                this.sfya.banks = data?.banks || [];
                for (const b of this.sfya.banks) {
                    this.sfya.banksOpen[b.journal_id] = true;
                }
                this.sfya.loaded = true;
            } catch (e) {
                console.warn("[SFYA] Failed to load cash movements:", e);
                this.sfya.loaded = true;
            }
            try {
                this.sfya.transfers = await this.pos.data.call(
                    "pos.session",
                    "get_sfya_partner_transfers",
                    [[this.pos.session.id]],
                );
            } catch (e) {
                console.warn("[SFYA] Failed to load partner transfers:", e);
            }
            try {
                this.sfya.internalTransfers = await this.pos.data.call(
                    "pos.session",
                    "get_sfya_internal_transfers",
                    [[this.pos.session.id]],
                );
            } catch (e) {
                console.warn("[SFYA] Failed to load internal transfers:", e);
            }
        });
    },
```

Add the new getter directly after `get sfyaTransfersTotal()`:

```javascript
    get sfyaInternalTransfersTotal() {
        return this.sfya.internalTransfers.reduce((sum, t) => sum + t.amount, 0);
    },
```

(`toggleSfyaBank` and `closeSession` stay unchanged.)

- [ ] **Step 2: Render the "Internal Transfers" section**

Open `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml`. Change the outer visibility condition (the `<div t-if="...">` right after `<xpath expr="//hr" position="after">`):

```xml
            <div t-if="sfya.loaded and (sfya.cash.collects.length or sfya.cash.payouts.length or sfya.cash.drawings.length or sfya.banks.length or sfya.transfers.length or sfya.internalTransfers.length)"
                 class="o_sfya_cash_movements mt-2">
```

Insert a new section directly after the "Partner transfers" `<div>` block and before the "Banks" `<t t-foreach="sfya.banks" ...>` block:

```xml
                <!-- Internal transfers: journal-to-journal; cash leg (if any) is already folded into till math -->
                <div t-if="sfya.internalTransfers.length" class="border rounded p-2 mb-2">
                    <div class="d-flex justify-content-between fw-bold" style="cursor: pointer;"
                         t-on-click="() => sfya.internalTransfersOpen = !sfya.internalTransfersOpen">
                        <span>
                            <i class="fa" t-att-class="sfya.internalTransfersOpen ? 'fa-chevron-down' : 'fa-chevron-right'"/>
                            Internal Transfers
                        </span>
                        <span class="text-muted">
                            <t t-esc="sfyaInternalTransfersTotal.toFixed(2)"/>
                        </span>
                    </div>
                    <table t-if="sfya.internalTransfersOpen" class="table table-sm mb-0 mt-1">
                        <tbody>
                            <t t-foreach="sfya.internalTransfers" t-as="r" t-key="r.id">
                                <tr>
                                    <td><t t-esc="r.from_journal_name"/> <i class="fa fa-arrow-right mx-1"/> <t t-esc="r.to_journal_name"/></td>
                                    <td t-esc="r.memo"/>
                                    <td class="text-end" t-esc="r.amount.toFixed(2)"/>
                                </tr>
                            </t>
                        </tbody>
                    </table>
                </div>
```

- [ ] **Step 3: Bump manifest version**

Edit `addons/sfya_pos_cash_movement/__manifest__.py`:

```python
'version': '18.0.6.0.4',
```

- [ ] **Step 4: Syntax check**

```bash
node --check addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js
```

Expected: no output (skip if `node` isn't on PATH — see Task 4 Step 10 note).

- [ ] **Step 5: Commit**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js \
        addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "$(cat <<'EOF'
feat(pos_cash_movement): Internal Transfers section in closing dialog

New collapsible section, same shape as the existing Partner Transfers
section, listing each journal-to-journal transfer (From -> To, memo,
amount). No "no till impact" label here - a cash-touching transfer DOES
affect the till, already folded into the expected-cash figure above.
EOF
)"
git push origin main
```

- [ ] **Step 6: Wait for CI + upgrade, then browser smoke**

Run the Deploy / upgrade loop, hard-refresh, then:

1. With the Task 4 smoke transfer still in the open session, POS → Close Session.
2. Closing dialog shows the usual cash/bank sections, plus a new "Internal Transfers" section below "Partner Transfers" (or in its usual position if no partner transfers this session).
3. Section shows one row: "<Till> → <Bank>", memo, amount 100.00.
4. Click the header → collapses/expands.
5. Cancel the close (don't actually close unless intended).

---

## Task 6: Verification — full happy-path + edge cases

**Files:** None changed. Smoke-only.

- [ ] **Step 1: Bank-to-bank transfer (no cash journal involved)**

Requires 2 bank journals; create a second one first if needed (Settings → Accounting → Journals → New, type Bank).

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
banks = [j for j in js if j['type'] == 'bank']
if len(banks) < 2:
    print('SKIP: need 2 bank journals')
else:
    r = env['account.payment'].sfya_pos_internal_transfer(sess.id, banks[0]['id'], banks[1]['id'], 250.0, memo='bank-to-bank smoke')
    print(r)
    env.cr.commit()
    mv = sess.get_sfya_cash_movements()
    print('cash transfers totals unaffected by bank-to-bank:', mv['cash']['transfers_in_total'], mv['cash']['transfers_out_total'])
EOF" 2>&1 | tail -10
```

Expected: transfer posts fine; `mv['cash']['transfers_in_total']`/`transfers_out_total` unchanged by this bank-to-bank transfer (no cash journal leg).

- [ ] **Step 2: Bank-to-cash transfer increases till expected cash**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
cash_jid = next(j['id'] for j in js if j['type'] == 'cash')
bank_jid = next(j['id'] for j in js if j['type'] == 'bank')
before = sess.get_closing_control_data()['default_cash_details']['amount']
r = env['account.payment'].sfya_pos_internal_transfer(sess.id, bank_jid, cash_jid, 300.0, memo='bank-to-cash smoke')
env.cr.commit()
after = sess.get_closing_control_data()['default_cash_details']['amount']
print('before:', before, ' after:', after, ' delta (expect +300.0):', after - before)
EOF" 2>&1 | tail -10
```

Expected: `delta (expect +300.0): 300.0`.

- [ ] **Step 3: Error paths**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
cash_jid = next(j['id'] for j in js if j['type'] == 'cash')
# same journal both sides
try:
    env['account.payment'].sfya_pos_internal_transfer(sess.id, cash_jid, cash_jid, 10.0)
    print('FAIL: expected UserError for same journal')
except Exception as e:
    print('OK same-journal:', e)
# zero amount
try:
    env['account.payment'].sfya_pos_internal_transfer(sess.id, cash_jid, cash_jid, 0.0)
    print('FAIL: expected UserError for zero amount')
except Exception as e:
    print('OK zero-amount:', e)
# non-cash/bank journal (find a sales journal)
sales_jid = env['account.journal'].search([('type', '=', 'sale')], limit=1).id
try:
    env['account.payment'].sfya_pos_internal_transfer(sess.id, cash_jid, sales_jid, 10.0)
    print('FAIL: expected UserError for sales journal')
except Exception as e:
    print('OK wrong-type:', e)
EOF" 2>&1 | tail -10
```

Expected: three `OK ...` lines, no `FAIL`.

- [ ] **Step 4: Statement unaffected (no partner involved)**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
from datetime import date
today = date.today()
# any partner with recent activity - internal transfers must NOT appear here
p = env['res.partner'].search([], limit=1)
data = p.get_statement_data(today, today)
transfer_rows = [r for r in data.get('rows', []) if 'internal_transfer' in str(r.get('doc_model', '')) or r.get('kind') in ('transfer_in', 'transfer_out')]
print('rows referencing internal transfer (expect none, partner transfers ok):', len(transfer_rows))
EOF" 2>&1 | tail -5
```

Expected: internal transfers never surface on any partner statement (they carry no `partner_id` at all).

- [ ] **Step 5: No commit (verification only)**

---

## Task 7: Update architecture doc

**Files:**
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Append the new capability to the addon's one-liner**

Open `docs/ARCHITECTURE.md`. Find the line (around line 165):

```
- `sfya_pos_cash_movement` — adds Collect Payment / Pay Out buttons to POS; records `account.payment` against any cash or bank journal of the company (cashier picks via Account dropdown), linked to the active `pos.session` for till reconciliation. Cash movements adjust expected cash in the closing dialog; bank movements appear as informational per-journal sections with no till impact.
```

Replace with:

```
- `sfya_pos_cash_movement` — adds Collect Payment / Pay Out / Partner Drawing / Transfer Funds buttons to POS; records `account.payment` against any cash or bank journal of the company (cashier picks via Account dropdown), linked to the active `pos.session` for till reconciliation. Cash movements adjust expected cash in the closing dialog; bank movements appear as informational per-journal sections with no till impact. Transfer Funds moves money directly between two of the company's own journals (e.g. shop cash till to a bank account) via a dedicated clearing account, with the cash-journal leg (if any) folded into the till's expected-cash math. A separate Partner Transfer flow settles a Pay Out via another partner's balance instead (2-line ledger entry, no cash/bank leg at all).
```

- [ ] **Step 2: Commit**

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs: note Transfer Funds capability in sfya_pos_cash_movement entry"
git push origin main
```

- [ ] **Step 3: Final acceptance checklist**

| Spec requirement | Verified in |
|---|---|
| Any cashier can perform a transfer (no shareholder gate) | Task 4 Step 12 (no gate encountered) |
| Dedicated clearing account auto-created, nets to zero per transfer | Task 1 Step 9, Task 2 Step 6 |
| `partner_id=False` posts cleanly (or fallback applied) | Task 2 Step 6 |
| Transfer legs excluded from generic Collect/Pay Out/Drawing buckets | Task 3 Step 7 |
| Cash-journal leg adjusts till expected-cash correctly (in and out) | Task 3 Step 7, Task 6 Steps 1-2 |
| Bank-only transfers don't affect till math | Task 6 Step 1 |
| Modal: no partner picker, two journal pickers, same/different-journal guard | Task 4 Step 12 |
| Toolbar button opens Transfer Funds modal | Task 4 Step 12 |
| Closing dialog shows Internal Transfers section | Task 5 Step 6 |
| Error paths (same journal, zero amount, wrong journal type) | Task 6 Step 3 |
| No customer-statement impact | Task 6 Step 4 |

Plan complete.
