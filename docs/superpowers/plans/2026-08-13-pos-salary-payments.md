# POS Salary Payments (Advance + Pay Salary) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new POS cash-movement actions, "Salary Advance" and "Pay Salary", so a cashier can record money paid to an employee — either an advance against future salary, or an actual salary payment that can partially/fully offset a prior advance — with the full gross salary always recognized as an expense.

**Architecture:** In-place extension of `sfya_pos_cash_movement`. Two new dedicated resources (an "Employee Advances" asset account and a "Salary Offsets" journal, auto-created per company) plus a link to the existing "Salary and Wages" expense account back the two actions. `account.payment.sfya_pos_salary_advance()` posts one payment against the advance account. `account.payment.sfya_pos_salary_payment()` posts the net-cash leg (if any) as a payment against the salary expense account, plus a cash-free 2-line journal entry (if an advance offset was applied) that recognizes the offset portion of the expense and clears that much of the advance — same construction pattern as the existing Partner Transfer feature. `pos_session.get_sfya_cash_movements` excludes both salary leg types from the generic Collect/Pay Out/Drawing buckets and totals the cash-journal legs separately so `get_closing_control_data`'s till math stays correct. Frontend adds two new `CashMovementModal` modes with an Employee picker (sourced from `hr.employee`) instead of a partner picker, two new toolbar buttons, and a new "Salary" section in the closing dialog.

**Tech Stack:** Odoo 18, OWL/QWeb (frontend), Python (backend), `account.payment` / `account.move` / `hr.employee` / `pos.session` ORM. No test infra — manual smoke via `odoo shell` + browser per task.

**Spec:** `docs/superpowers/specs/2026-08-13-pos-salary-payments-design.md`

## Global Constraints

- No new models or database tables; no new addon — extend `sfya_pos_cash_movement` in place.
- Add `'hr'` to the addon's `depends` (already installed on this instance) — needed to source the Employee picker from `hr.employee`.
- Any cashier can perform either salary action — no shareholder restriction (unlike Partner Drawing).
- Reuse the dedicated-resource `post_init_hook` pattern: search-by-code, create-if-missing. Never search/guess among existing accounts — except the expense account, which intentionally links to the pre-existing `4211001 Salary and Wages` account rather than creating a new one.
- Currency: PKR hardcoded (matches existing cash-movement code) — no new currency handling.
- Salary legs set a real `partner_id` (`employee.work_contact_id`), unlike Internal Transfer's partner-less legs — this requires a small exclusion patch in `sfya_customer_statement` (Task 3) so they don't leak into the employee's partner statement as generic "Payment Out" rows, mirroring the existing Partner Drawing exclusion there.
- Outstanding advance balance is computed company-wide, not session-scoped (an advance given in one session can be offset in a later one).
- Float-rounding tolerance of `0.005` (matches the existing convention in `_sfya_resolve_partner_type`) applies to every advance-offset comparison — never reject a legitimate "clear full balance" request due to floating-point noise.
- `post_init_hook` only runs on fresh module **install**, never on `-u` upgrade — every task that adds a `post_init_hook`-populated field must include a manual one-time re-invocation of the hook on the already-installed VPS instance.

---

## Deploy / upgrade loop (used in every code task)

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
| `addons/sfya_pos_cash_movement/models/res_company.py` | 1 | Add 3 dedicated-resource fields |
| `addons/sfya_pos_cash_movement/models/pos_config.py` | 1 | Related passthrough fields |
| `addons/sfya_pos_cash_movement/views/pos_config_views.xml` | 1 | Expose fields in SFYA Cash Control group |
| `addons/sfya_pos_cash_movement/__init__.py` | 1 | `post_init_hook`: link/create the 3 dedicated resources per company |
| `addons/sfya_pos_cash_movement/__manifest__.py` | 1-5 | Add `hr` dep (Task 1); patch-bump per code task |
| `addons/sfya_pos_cash_movement/models/account_payment.py` | 2 | New fields + `sfya_pos_salary_advance()`, `sfya_pos_salary_payment()`, `get_sfya_salary_advance_balance()` RPCs |
| `addons/sfya_pos_cash_movement/models/account_move.py` | 2 | New fields for the cash-free advance-offset entry |
| `addons/sfya_pos_cash_movement/models/pos_session.py` | 3 | Exclude salary legs from generic scan, total cash-leg, extend till adjustment, `get_sfya_salary_payments()`, `get_sfya_pos_employees()` |
| `addons/sfya_customer_statement/models/res_partner.py` | 3 | Exclude salary legs from `get_statement_data`'s payment rows |
| `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js` | 4 | `"salary_advance"`/`"salary_payment"` modes: state, validation, confirm branches, print slip |
| `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml` | 4 | Employee-picker UI, advance-offset UI, PaymentSlip branches |
| `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js` | 4 | `openSalaryAdvance()`, `openSalaryPayment()` |
| `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml` | 4 | "Salary Advance", "Pay Salary" buttons |
| `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js` | 5 | Load + expose salary payments |
| `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml` | 5 | "Salary" section |
| `docs/ARCHITECTURE.md` | 7 | Note the new capability |

---

## Task 1: Backend — dedicated resources (accounts + journal) + `hr` dependency

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/res_company.py`
- Modify: `addons/sfya_pos_cash_movement/models/pos_config.py`
- Modify: `addons/sfya_pos_cash_movement/views/pos_config_views.xml`
- Modify: `addons/sfya_pos_cash_movement/__init__.py`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

**Interfaces:**
- Produces: `res.company.sfya_salary_expense_account_id`, `res.company.sfya_employee_advance_account_id`, `res.company.sfya_salary_journal_id` (all Many2one) — consumed by Task 2's RPCs.

- [ ] **Step 1: Add three company fields**

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

Append three new fields at the end of the class, making the file:

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
    sfya_salary_expense_account_id = fields.Many2one(
        'account.account',
        string='Salary Expense Account',
        help='Expense account debited when salary is paid to an employee via POS.',
        domain="[('account_type', '=', 'expense')]",
    )
    sfya_employee_advance_account_id = fields.Many2one(
        'account.account',
        string='Employee Advance Account',
        help='Asset account debited when an employee is given a salary '
             'advance via POS, and credited when that advance is later '
             'offset against a salary payment.',
        domain="[('account_type', '=', 'asset_current')]",
    )
    sfya_salary_journal_id = fields.Many2one(
        'account.journal',
        string='Salary Offset Journal',
        help='Miscellaneous-operations journal used to post the cash-free '
             'portion of a POS salary payment that offsets a prior advance. '
             'Dedicated (not shared with Partner Transfer) so its move-name '
             'sequence is specific to salary entries.',
        domain="[('type', '=', 'general')]",
    )
```

- [ ] **Step 2: Add related fields on `pos.config`**

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
    sfya_internal_transfer_account_id = fields.Many2one(
        related='company_id.sfya_internal_transfer_account_id',
        readonly=False,
        string='Internal Transfer Clearing Account',
    )
```

Append three related fields at the end of the class, making the file:

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
    sfya_salary_expense_account_id = fields.Many2one(
        related='company_id.sfya_salary_expense_account_id',
        readonly=False,
        string='Salary Expense Account',
    )
    sfya_employee_advance_account_id = fields.Many2one(
        related='company_id.sfya_employee_advance_account_id',
        readonly=False,
        string='Employee Advance Account',
    )
    sfya_salary_journal_id = fields.Many2one(
        related='company_id.sfya_salary_journal_id',
        readonly=False,
        string='Salary Offset Journal',
    )
```

- [ ] **Step 3: Expose fields in the POS config view**

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
                    <field name="sfya_internal_transfer_account_id"/>
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
                    <field name="sfya_salary_expense_account_id"/>
                    <field name="sfya_employee_advance_account_id"/>
                    <field name="sfya_salary_journal_id"/>
                </group>
            </xpath>
        </field>
    </record>
</odoo>
```

- [ ] **Step 4: Extend `post_init_hook`**

Open `addons/sfya_pos_cash_movement/__init__.py`. It currently ends with the third loop (creating `sfya_internal_transfer_account_id`, code `1994`). Append three more loops at the end of the same `_post_init_create_drawing_account` function:

```python
    for company in env['res.company'].search([]):
        if company.sfya_salary_expense_account_id:
            continue
        existing = env['account.account'].search([
            ('company_ids', 'in', company.id),
            ('code', '=', '4211001'),
        ], limit=1)
        if existing:
            company.sfya_salary_expense_account_id = existing.id
            continue
        if not env['account.account'].search_count([('company_ids', 'in', company.id)], limit=1):
            continue
        account = env['account.account'].create({
            'code': '4211001',
            'name': 'Salary and Wages',
            'account_type': 'expense',
            'company_ids': [(6, 0, [company.id])],
        })
        company.sfya_salary_expense_account_id = account.id

    for company in env['res.company'].search([]):
        if company.sfya_employee_advance_account_id:
            continue
        existing = env['account.account'].search([
            ('company_ids', 'in', company.id),
            ('code', '=', '1995'),
        ], limit=1)
        if existing:
            company.sfya_employee_advance_account_id = existing.id
            continue
        if not env['account.account'].search_count([('company_ids', 'in', company.id)], limit=1):
            continue
        account = env['account.account'].create({
            'code': '1995',
            'name': 'Employee Advances',
            'account_type': 'asset_current',
            'company_ids': [(6, 0, [company.id])],
        })
        company.sfya_employee_advance_account_id = account.id

    for company in env['res.company'].search([]):
        if company.sfya_salary_journal_id:
            continue
        # Dedicated journal, same rationale as PXFR (Partner Transfer): a
        # shared Misc Operations journal's sequence would mix salary-offset
        # entries with unrelated postings.
        existing = env['account.journal'].search([
            ('code', '=', 'SLRY'),
            ('company_id', '=', company.id),
        ], limit=1)
        if existing:
            company.sfya_salary_journal_id = existing.id
            continue
        if not env['account.account'].search_count([('company_ids', 'in', company.id)], limit=1):
            continue
        journal = env['account.journal'].create({
            'name': 'Salary Offsets',
            'code': 'SLRY',
            'type': 'general',
            'company_id': company.id,
        })
        company.sfya_salary_journal_id = journal.id
```

Note: for `sfya_salary_expense_account_id`, the search-by-code branch is expected to find the account on every company on this instance already (`4211001 Salary and Wages` exists in the current chart of accounts) — the create branch is a fallback for a company with no such account, not the expected path here.

- [ ] **Step 5: Add `hr` dependency and bump manifest version**

Open `addons/sfya_pos_cash_movement/__manifest__.py`. Change:

```python
    'depends': ['point_of_sale', 'account'],
```

to:

```python
    'depends': ['point_of_sale', 'account', 'hr'],
```

And change:

```python
    'version': '18.0.6.0.4',
```

to:

```python
    'version': '18.0.6.0.5',
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
feat(pos_cash_movement): add salary dedicated accounts + journal

New sfya_salary_expense_account_id (links existing 4211001 Salary and
Wages), sfya_employee_advance_account_id (new 1995 Employee Advances),
and sfya_salary_journal_id (new SLRY journal) on res.company/pos.config,
auto-linked/created via post_init_hook. Adds 'hr' dependency for the
upcoming Employee picker. No behavior yet - config groundwork for
Task 2's salary RPCs.
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
    se = company.sfya_salary_expense_account_id
    ea = company.sfya_employee_advance_account_id
    sj = company.sfya_salary_journal_id
    print(company.name, '| salary_expense ->', se.id, se.code, se.name)
    print(company.name, '| advance_account ->', ea.id, ea.code, ea.name)
    print(company.name, '| salary_journal  ->', sj.id, sj.code, sj.name)
EOF" 2>&1 | tail -20
```

Expected: every company prints `salary_expense` with `code=4211001, name=Salary and Wages`; `advance_account` with `code=1995, name=Employee Advances`; `salary_journal` with `code=SLRY, name=Salary Offsets`.

---

## Task 2: Backend — `account.payment`/`account.move` fields + salary RPCs

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/account_payment.py`
- Modify: `addons/sfya_pos_cash_movement/models/account_move.py`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

**Interfaces:**
- Consumes: `res.company.sfya_salary_expense_account_id`, `sfya_employee_advance_account_id`, `sfya_salary_journal_id` (Task 1).
- Produces:
  - `account.payment.sfya_pos_salary_advance(session_id, employee_id, amount, journal_id, memo='', date=None)` → `{id, name, employee_id, employee_name, amount, memo, direction: 'salary_advance', journal_id, journal_name, journal_type}` — consumed by Task 4's modal.
  - `account.payment.sfya_pos_salary_payment(session_id, employee_id, gross_amount, advance_offset, journal_id, memo='', date=None)` → `{payment_id, payment_name, move_id, move_name, employee_id, employee_name, gross_amount, advance_offset, net_cash, memo, journal_id, journal_name, journal_type, direction: 'salary_payment'}` — consumed by Task 4's modal.
  - `account.payment.get_sfya_salary_advance_balance(employee_id)` → `float` — consumed by Task 4's modal (live balance display) and by `sfya_pos_salary_payment` itself.
  - `account.payment.sfya_salary_kind` / `sfya_employee_id` / `sfya_salary_gross_amount` / `sfya_salary_advance_offset` / `sfya_salary_offset_move_id` — consumed by Task 3's bucketing/listing.
  - `account.move.sfya_is_salary_offset` / `sfya_salary_offset_employee_id` / `sfya_salary_offset_amount` — consumed by Task 3's listing.

- [ ] **Step 1: Add `Command` to imports and add the five new fields to `account.payment`**

Open `addons/sfya_pos_cash_movement/models/account_payment.py`. Change the import line:

```python
from odoo import _, api, fields, models
```

to:

```python
from odoo import Command, _, api, fields, models
```

Find the existing `sfya_transfer_pair_id` field declaration:

```python
    sfya_transfer_pair_id = fields.Many2one(
        'account.payment',
        string='Paired Transfer Leg',
        copy=False,
        help='The other leg of this internal transfer (out<->in).',
    )
```

Insert five new fields directly after it (before the blank line that precedes `@api.model` / `sfya_pos_collect`):

```python
    sfya_salary_kind = fields.Selection(
        [('advance', 'Advance'), ('payment', 'Payment')],
        copy=False,
        help='Set for POS-originated salary legs only. "advance" = money '
             'given ahead of payday (destination is the Employee Advance '
             'account). "payment" = actual salary expense recognized '
             '(destination is the Salary Expense account); amount is the '
             'NET cash paid, after any advance offset. Used to exclude '
             'these legs from the generic Collect/Pay Out/Drawing listings '
             'and total them separately for the till expected-cash '
             'adjustment.',
    )
    sfya_employee_id = fields.Many2one('hr.employee', string='Employee', copy=False)
    sfya_salary_gross_amount = fields.Monetary(
        string='Gross Salary Amount', copy=False,
        help='Only set when sfya_salary_kind="payment". Full salary amount '
             'for the period, before any advance offset. Equal to `amount` '
             'when no offset was applied.',
    )
    sfya_salary_advance_offset = fields.Monetary(
        string='Advance Offset Applied', copy=False,
        help='Only set when sfya_salary_kind="payment". Portion of gross '
             'salary that was cleared against a prior advance instead of '
             'paid in cash/bank.',
    )
    sfya_salary_offset_move_id = fields.Many2one(
        'account.move', string='Salary Offset Entry', copy=False,
        help='The cash-free journal entry (if any) that cleared the '
             'advance offset alongside this payment.',
    )
```

- [ ] **Step 2: Add three fields to `account.move`**

Open `addons/sfya_pos_cash_movement/models/account_move.py`. Find the existing `sfya_transfer_amount` field declaration (the last field before the `sfya_pos_partner_transfer` method):

```python
    sfya_transfer_amount = fields.Monetary(
        string='Transfer Amount',
        copy=False,
    )
```

Insert three new fields directly after it (before the blank line that precedes `@api.model` / `sfya_pos_partner_transfer`):

```python
    sfya_is_salary_offset = fields.Boolean(default=False, copy=False)
    sfya_salary_offset_employee_id = fields.Many2one('hr.employee', copy=False)
    sfya_salary_offset_amount = fields.Monetary(copy=False)
```

(No import changes needed in `account_move.py` — it already imports `Command`.)

- [ ] **Step 3: Add `sfya_pos_salary_advance` RPC**

In `addons/sfya_pos_cash_movement/models/account_payment.py`, find the end of the existing `sfya_pos_internal_transfer` method — it ends with:

```python
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

Insert two new `@api.model` methods directly after it (before the blank line that precedes `def _sfya_resolve_partner_type`):

```python
    @api.model
    def sfya_pos_salary_advance(self, session_id, employee_id, amount, journal_id, memo='', date=None):
        """RPC: cashier gives an employee a cash/bank advance against future salary."""
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        employee = self.env['hr.employee'].sudo().browse(employee_id).exists()
        if not employee or not employee.active:
            raise UserError(_('Employee not found.'))
        if employee.company_id.id != session.company_id.id:
            raise UserError(_("Employee does not belong to this POS's company."))
        if amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        if not journal_id:
            raise UserError(_('Account is required.'))
        journal = self.env['account.journal'].sudo().browse(journal_id).exists()
        if not journal:
            raise UserError(_('Account not found.'))
        if journal.type not in ('cash', 'bank'):
            raise UserError(_('Selected account is not a cash or bank journal.'))
        if journal.company_id.id != session.company_id.id:
            raise UserError(_("Account does not belong to this POS's company."))
        advance_account = session.company_id.sfya_employee_advance_account_id
        if not advance_account:
            raise UserError(_('Employee Advance account is not configured for this company.'))
        resolved_date = fields.Date.today()
        if journal.type == 'bank' and date:
            try:
                resolved_date = fields.Date.from_string(date)
            except (ValueError, TypeError):
                raise UserError(_("Invalid date format."))
            if resolved_date > fields.Date.today():
                raise UserError(_("Date cannot be in the future."))
        # cash journal: ignore passed date; resolved_date stays today
        payment = self.sudo().create({
            'partner_id': employee.work_contact_id.id,
            'partner_type': 'supplier',
            'payment_type': 'outbound',
            'amount': amount,
            'journal_id': journal.id,
            'date': resolved_date,
            'memo': memo or False,
            'pos_session_id': session.id,
            'destination_account_id': advance_account.id,
            'sfya_salary_kind': 'advance',
            'sfya_employee_id': employee.id,
        })
        payment.action_post()
        return {
            'id': payment.id,
            'name': payment.name,
            'employee_id': employee.id,
            'employee_name': employee.name,
            'amount': payment.amount,
            'memo': payment.memo or '',
            'direction': 'salary_advance',
            'journal_id': journal.id,
            'journal_name': journal.name,
            'journal_type': journal.type,
        }

    @api.model
    def sfya_pos_salary_payment(self, session_id, employee_id, gross_amount, advance_offset, journal_id, memo='', date=None):
        """RPC: cashier pays an employee's salary, optionally offsetting a prior advance.

        net_cash = gross_amount - advance_offset is posted as an
        account.payment against the Salary Expense account (skipped
        entirely if net_cash is 0). If advance_offset > 0, a cash-free
        2-line account.move recognizes that portion of the expense and
        clears the same amount off the Employee Advance account - same
        construction pattern as sfya_pos_partner_transfer.
        """
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        employee = self.env['hr.employee'].sudo().browse(employee_id).exists()
        if not employee or not employee.active:
            raise UserError(_('Employee not found.'))
        if employee.company_id.id != session.company_id.id:
            raise UserError(_("Employee does not belong to this POS's company."))
        if gross_amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        advance_offset = advance_offset or 0.0
        if advance_offset < 0:
            raise UserError(_('Advance offset cannot be negative.'))
        tol = 0.005  # float-rounding tolerance, matches _sfya_resolve_partner_type
        if advance_offset > gross_amount + tol:
            raise UserError(_('Advance offset cannot exceed gross salary amount.'))
        advance_offset = min(advance_offset, gross_amount)
        if not journal_id:
            raise UserError(_('Account is required.'))
        journal = self.env['account.journal'].sudo().browse(journal_id).exists()
        if not journal:
            raise UserError(_('Account not found.'))
        if journal.type not in ('cash', 'bank'):
            raise UserError(_('Selected account is not a cash or bank journal.'))
        if journal.company_id.id != session.company_id.id:
            raise UserError(_("Account does not belong to this POS's company."))
        salary_account = session.company_id.sfya_salary_expense_account_id
        if not salary_account:
            raise UserError(_('Salary Expense account is not configured for this company.'))
        if advance_offset > 0:
            advance_account = session.company_id.sfya_employee_advance_account_id
            salary_journal = session.company_id.sfya_salary_journal_id
            if not advance_account:
                raise UserError(_('Employee Advance account is not configured for this company.'))
            if not salary_journal:
                raise UserError(_('Salary Offset Journal is not configured for this company.'))
            outstanding_balance = self.get_sfya_salary_advance_balance(employee.id)
            if advance_offset > outstanding_balance + tol:
                raise UserError(_(
                    "Advance offset exceeds this employee's outstanding advance balance of %s.",
                    outstanding_balance,
                ))
            advance_offset = min(advance_offset, outstanding_balance)

        resolved_date = fields.Date.today()
        if journal.type == 'bank' and date:
            try:
                resolved_date = fields.Date.from_string(date)
            except (ValueError, TypeError):
                raise UserError(_("Invalid date format."))
            if resolved_date > fields.Date.today():
                raise UserError(_("Date cannot be in the future."))
        # cash journal: ignore passed date; resolved_date stays today

        net_cash = gross_amount - advance_offset
        payment = self.browse()
        if net_cash > 0:
            payment = self.sudo().create({
                'partner_id': employee.work_contact_id.id,
                'partner_type': 'supplier',
                'payment_type': 'outbound',
                'amount': net_cash,
                'journal_id': journal.id,
                'date': resolved_date,
                'memo': memo or False,
                'pos_session_id': session.id,
                'destination_account_id': salary_account.id,
                'sfya_salary_kind': 'payment',
                'sfya_employee_id': employee.id,
                'sfya_salary_gross_amount': gross_amount,
                'sfya_salary_advance_offset': advance_offset,
            })
            payment.action_post()

        move = self.env['account.move']
        if advance_offset > 0:
            move = self.env['account.move'].sudo().create({
                'move_type': 'entry',
                'journal_id': session.company_id.sfya_salary_journal_id.id,
                'date': resolved_date,
                'ref': memo or _('Salary advance offset: %s', employee.name),
                'pos_session_id': session.id,
                'sfya_is_salary_offset': True,
                'sfya_salary_offset_employee_id': employee.id,
                'sfya_salary_offset_amount': advance_offset,
                'line_ids': [
                    Command.create({
                        'partner_id': employee.work_contact_id.id,
                        'account_id': salary_account.id,
                        'debit': advance_offset,
                        'credit': 0.0,
                        'name': memo or _('Salary (advance offset) - %s', employee.name),
                    }),
                    Command.create({
                        'partner_id': employee.work_contact_id.id,
                        'account_id': session.company_id.sfya_employee_advance_account_id.id,
                        'debit': 0.0,
                        'credit': advance_offset,
                        'name': memo or _('Advance cleared - %s', employee.name),
                    }),
                ],
            })
            move.action_post()
            if net_cash > 0:
                payment.sfya_salary_offset_move_id = move.id

        return {
            'payment_id': payment.id if net_cash > 0 else None,
            'payment_name': payment.name if net_cash > 0 else None,
            'move_id': move.id if advance_offset > 0 else None,
            'move_name': move.name if advance_offset > 0 else None,
            'employee_id': employee.id,
            'employee_name': employee.name,
            'gross_amount': gross_amount,
            'advance_offset': advance_offset,
            'net_cash': net_cash,
            'memo': memo or '',
            'journal_id': journal.id,
            'journal_name': journal.name,
            'journal_type': journal.type,
            'direction': 'salary_payment',
        }

    @api.model
    def get_sfya_salary_advance_balance(self, employee_id):
        """Return an employee's outstanding advance balance (company-wide,
        not session-scoped): total advances given minus total already
        cleared via a salary-payment offset.
        """
        employee = self.env['hr.employee'].sudo().browse(employee_id).exists()
        if not employee:
            return 0.0
        advances_given = sum(self.sudo().search([
            ('sfya_employee_id', '=', employee.id),
            ('sfya_salary_kind', '=', 'advance'),
            ('state', 'in', ['paid', 'in_process']),
            ('company_id', '=', self.env.company.id),
        ]).mapped('amount'))
        offsets_cleared = sum(self.env['account.move'].sudo().search([
            ('sfya_salary_offset_employee_id', '=', employee.id),
            ('sfya_is_salary_offset', '=', True),
            ('state', '=', 'posted'),
            ('company_id', '=', self.env.company.id),
        ]).mapped('sfya_salary_offset_amount'))
        return advances_given - offsets_cleared
```

- [ ] **Step 4: Bump manifest version**

In `addons/sfya_pos_cash_movement/__manifest__.py`, change:

```python
    'version': '18.0.6.0.5',
```

to:

```python
    'version': '18.0.6.0.6',
```

- [ ] **Step 5: Syntax check**

```bash
python3 -m py_compile addons/sfya_pos_cash_movement/models/account_payment.py \
    addons/sfya_pos_cash_movement/models/account_move.py
```

Expected: no output, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add addons/sfya_pos_cash_movement/models/account_payment.py \
        addons/sfya_pos_cash_movement/models/account_move.py \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "$(cat <<'EOF'
feat(pos_cash_movement): add sfya_pos_salary_advance/payment RPCs

New account.payment fields (sfya_salary_kind, sfya_employee_id,
sfya_salary_gross_amount, sfya_salary_advance_offset,
sfya_salary_offset_move_id) and account.move fields
(sfya_is_salary_offset, sfya_salary_offset_employee_id,
sfya_salary_offset_amount).

sfya_pos_salary_advance() posts one payment against the Employee
Advance account. sfya_pos_salary_payment() posts the net-cash leg (if
any) against the Salary Expense account plus a cash-free 2-line move
(if an advance offset applies) that recognizes the offset portion of
the expense and clears the advance - same construction pattern as the
existing sfya_pos_partner_transfer. get_sfya_salary_advance_balance()
computes an employee's outstanding balance company-wide.

Not yet wired into till math or the frontend - Task 3/4.
EOF
)"
git push origin main
```

- [ ] **Step 7: Wait for CI + upgrade**

Run the Deploy / upgrade loop above.

- [ ] **Step 8: Smoke test — advance, then payment with offset, then balance check**

Requires an open POS session. If none is open, stop and ask before proceeding — do not improvise around this precondition.

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
emp = env['hr.employee'].search([('company_id', '=', sess.company_id.id), ('active', '=', True)], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
cash_jid = next(j['id'] for j in js if j['type'] == 'cash')

bal0 = env['account.payment'].get_sfya_salary_advance_balance(emp.id)
print('balance before advance:', bal0)

adv = env['account.payment'].sfya_pos_salary_advance(sess.id, emp.id, 500.0, cash_jid, memo='smoke advance')
print('advance result:', adv)
env.cr.commit()

bal1 = env['account.payment'].get_sfya_salary_advance_balance(emp.id)
print('balance after advance (expect 500.0):', bal1)

pay = env['account.payment'].sfya_pos_salary_payment(sess.id, emp.id, 2000.0, 300.0, cash_jid, memo='smoke payment')
print('payment result:', pay)
env.cr.commit()

bal2 = env['account.payment'].get_sfya_salary_advance_balance(emp.id)
print('balance after 300 offset (expect 200.0):', bal2)
print('net_cash in result (expect 1700.0):', pay['net_cash'])
EOF" 2>&1 | tail -20
```

Expected: `balance after advance` = `500.0`; `payment result` dict has non-`None` `payment_id` and `move_id`; `net_cash` = `1700.0`; `balance after 300 offset` = `200.0`.

---

## Task 3: Backend — till bucketing, salary listing, employee picker RPC, statement exclusion

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/pos_session.py`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`
- Modify: `addons/sfya_customer_statement/models/res_partner.py`
- Modify: `addons/sfya_customer_statement/__manifest__.py`

⚠️ **Correction to the design spec's "Out of Scope" claim:** the spec assumed no `sfya_customer_statement` change was needed, reasoning by analogy to Internal Transfer (which has no `partner_id` at all, so it can never appear in a partner statement). Salary legs are different — they set a real `partner_id` (`employee.work_contact_id`), same as Partner Drawing. Investigation of `sfya_customer_statement/models/res_partner.py`'s `get_statement_data` (payments section, ~line 143-169) confirmed it queries **every** `account.payment` with `partner_id = self.id` in the date range, with only one exclusion: a post-fetch skip when `destination_account_id == company.sfya_owner_drawing_account_id` (that's how Partner Drawing already stays out of statements today). Without an equivalent exclusion, both `sfya_pos_salary_advance` and `sfya_pos_salary_payment` legs would incorrectly show up as generic "Payment Out" rows on the employee's vendor statement. Step 2 below adds that exclusion.

**Interfaces:**
- Consumes: `account.payment.sfya_salary_kind` / `sfya_employee_id` / `sfya_salary_gross_amount` / `sfya_salary_advance_offset` / `sfya_salary_offset_move_id`, `account.move.sfya_is_salary_offset` / `sfya_salary_offset_employee_id` / `sfya_salary_offset_amount` (Task 2).
- Produces:
  - `pos.session.get_sfya_cash_movements()` — `cash` dict gains `salary_advances_total`, `salary_payments_total` — consumed by Task 5's closing dialog (indirectly, via `get_closing_control_data`).
  - `pos.session.get_sfya_salary_payments()` → `[{id, kind: 'advance'|'payment', employee_name, gross_amount, advance_offset, net_cash, journal_name, memo}]` — consumed by Task 5's closing dialog.
  - `pos.session.get_sfya_pos_employees(session_id)` → `[{id, name}]` — consumed by Task 4's modal.

- [ ] **Step 1: Replace `pos_session.py` with the extended version**

Open `addons/sfya_pos_cash_movement/models/pos_session.py`. Replace the entire file with:

```python
from odoo import api, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def get_sfya_cash_movements(self):
        """Return SFYA POS-recorded cash + bank payments for this session.

        Returns:
            {
                'cash': {collects, collects_total, payouts, payouts_total,
                         drawings, drawings_total,
                         transfers_in_total, transfers_out_total,
                         salary_advances_total, salary_payments_total},
                'banks': [
                    {journal_id, journal_name, collects, collects_total,
                     payouts, payouts_total, drawings, drawings_total},
                    ...
                ],
            }

        Banks list contains only journals that had at least one movement
        this session, sorted by journal name. Internal-transfer payments
        (sfya_is_internal_transfer=True) and salary legs
        (sfya_salary_kind set) are excluded from all of the above and
        totalled separately, restricted to the cash journal only - that's
        the only leg that affects the physically-counted till.
        """
        self.ensure_one()
        payments = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('state', 'in', ['paid', 'in_process']),
            ('journal_id.type', 'in', ['cash', 'bank']),
            ('sfya_is_internal_transfer', '=', False),
            ('sfya_salary_kind', '=', False),
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

        salary_legs = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('state', 'in', ['paid', 'in_process']),
            ('sfya_salary_kind', '!=', False),
            ('journal_id.type', '=', 'cash'),
        ])
        salary_advances_total = sum(p.amount for p in salary_legs if p.sfya_salary_kind == 'advance')
        salary_payments_total = sum(p.amount for p in salary_legs if p.sfya_salary_kind == 'payment')

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
                'salary_advances_total': salary_advances_total,
                'salary_payments_total': salary_payments_total,
            },
            'banks': banks,
        }

    def get_sfya_partner_transfers(self):
        """Return this session's partner-transfer entries, informational only.

        These never touch cash/bank (no journal leg at all), so they carry
        no till impact and aren't part of get_sfya_cash_movements.
        """
        self.ensure_one()
        moves = self.env['account.move'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('sfya_is_partner_transfer', '=', True),
            ('state', '=', 'posted'),
        ], order='create_date asc')
        return [{
            'id': m.id,
            'name': m.name,
            'from_partner_name': m.sfya_transfer_from_partner_id.name or '',
            'to_partner_name': m.sfya_transfer_to_partner_id.name or '',
            'amount': m.sfya_transfer_amount,
            'memo': m.ref or '',
        } for m in moves]

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

    def get_sfya_salary_payments(self):
        """Return this session's salary advance/payment rows, merged and
        sorted by creation time, for the closing dialog's "Salary" section.

        Advances are one row each. Payments are one row per net-cash leg
        (net_cash > 0). When an advance offset fully covers the gross
        salary (net_cash == 0), no payment leg exists at all - that case
        is represented by its cash-free offset account.move instead, found
        as an "orphan" move not linked from any payment in this session.
        """
        self.ensure_one()
        rows = []

        advances = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('sfya_salary_kind', '=', 'advance'),
            ('state', 'in', ['paid', 'in_process']),
        ], order='create_date asc')
        for a in advances:
            rows.append({
                'id': a.id, 'kind': 'advance',
                'employee_name': a.sfya_employee_id.name or '',
                'gross_amount': a.amount, 'advance_offset': 0.0, 'net_cash': a.amount,
                'journal_name': a.journal_id.name, 'memo': a.memo or '',
                'create_date': a.create_date,
            })

        payments = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('sfya_salary_kind', '=', 'payment'),
            ('state', 'in', ['paid', 'in_process']),
        ], order='create_date asc')
        linked_move_ids = payments.mapped('sfya_salary_offset_move_id').ids
        for p in payments:
            rows.append({
                'id': p.id, 'kind': 'payment',
                'employee_name': p.sfya_employee_id.name or '',
                'gross_amount': p.sfya_salary_gross_amount or p.amount,
                'advance_offset': p.sfya_salary_advance_offset or 0.0,
                'net_cash': p.amount,
                'journal_name': p.journal_id.name, 'memo': p.memo or '',
                'create_date': p.create_date,
            })

        orphan_moves = self.env['account.move'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('sfya_is_salary_offset', '=', True),
            ('state', '=', 'posted'),
            ('id', 'not in', linked_move_ids),
        ], order='create_date asc')
        for m in orphan_moves:
            rows.append({
                'id': m.id, 'kind': 'payment',
                'employee_name': m.sfya_salary_offset_employee_id.name or '',
                'gross_amount': m.sfya_salary_offset_amount,
                'advance_offset': m.sfya_salary_offset_amount,
                'net_cash': 0.0,
                'journal_name': '', 'memo': m.ref or '',
                'create_date': m.create_date,
            })

        rows.sort(key=lambda r: r['create_date'])
        for r in rows:
            del r['create_date']
        return rows

    @api.model
    def get_sfya_allowed_journals(self, session_id):
        """Return cash + bank journals selectable from the Cash Movement modal.

        Filters by session company. Cash journals are listed first, then
        banks; both groups sorted by name. The frontend modal picks the
        default selection.
        """
        session = self.sudo().browse(session_id).exists()
        if not session:
            return []
        journals = self.env['account.journal'].sudo().search([
            ('type', 'in', ['cash', 'bank']),
            ('company_id', '=', session.company_id.id),
        ])
        cash = journals.filtered(lambda j: j.type == 'cash').sorted('name')
        banks = journals.filtered(lambda j: j.type == 'bank').sorted('name')
        return [{'id': j.id, 'name': j.name, 'type': j.type} for j in (cash + banks)]

    @api.model
    def get_sfya_pos_employees(self, session_id):
        """Return active employees of the session's company, for the
        Salary Advance / Pay Salary modal's Employee picker.
        """
        session = self.sudo().browse(session_id).exists()
        if not session:
            return []
        employees = self.env['hr.employee'].sudo().search([
            ('company_id', '=', session.company_id.id),
            ('active', '=', True),
        ], order='name')
        return [{'id': e.id, 'name': e.name} for e in employees]

    def get_closing_control_data(self):
        data = super().get_closing_control_data()
        movements = self.get_sfya_cash_movements()
        cash = movements.get('cash') or {}
        adjustment = (
            (cash.get('collects_total') or 0.0) - (cash.get('payouts_total') or 0.0) - (cash.get('drawings_total') or 0.0)
            + (cash.get('transfers_in_total') or 0.0) - (cash.get('transfers_out_total') or 0.0)
            - (cash.get('salary_advances_total') or 0.0) - (cash.get('salary_payments_total') or 0.0)
        )
        if data.get('default_cash_details') and adjustment:
            data['default_cash_details']['amount'] = (
                data['default_cash_details'].get('amount', 0.0) + adjustment
            )
        return data
```

- [ ] **Step 2: Exclude salary legs from the customer/vendor statement**

Open `addons/sfya_customer_statement/models/res_partner.py`. Find the existing payments-section exclusion check (inside `get_statement_data`, in the `for pay in self.env['account.payment'].search(pay_domain):` loop):

```python
        for pay in self.env['account.payment'].search(pay_domain):
            if drawing_account and pay.destination_account_id == drawing_account:
                continue  # owner's equity drawing, not a customer/vendor movement
```

Replace with:

```python
        for pay in self.env['account.payment'].search(pay_domain):
            if drawing_account and pay.destination_account_id == drawing_account:
                continue  # owner's equity drawing, not a customer/vendor movement
            if pay.sfya_salary_kind:
                continue  # POS salary advance/payment, not a customer/vendor movement
```

- [ ] **Step 3: Bump both manifest versions**

In `addons/sfya_pos_cash_movement/__manifest__.py`, change:

```python
    'version': '18.0.6.0.6',
```

to:

```python
    'version': '18.0.6.0.7',
```

In `addons/sfya_customer_statement/__manifest__.py`, change:

```python
    'version': '18.0.2.3.0',
```

to:

```python
    'version': '18.0.2.3.1',
```

- [ ] **Step 4: Syntax check**

```bash
python3 -m py_compile addons/sfya_pos_cash_movement/models/pos_session.py \
    addons/sfya_customer_statement/models/res_partner.py
```

Expected: no output, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add addons/sfya_pos_cash_movement/models/pos_session.py \
        addons/sfya_pos_cash_movement/__manifest__.py \
        addons/sfya_customer_statement/models/res_partner.py \
        addons/sfya_customer_statement/__manifest__.py
git commit -m "$(cat <<'EOF'
feat(pos_cash_movement): fold salary legs into till math + add listing

get_sfya_cash_movements excludes salary legs (sfya_salary_kind set)
from the generic Collect/Pay Out/Drawing scan and totals the
cash-journal legs separately into salary_advances_total /
salary_payments_total. get_closing_control_data's adjustment formula
now subtracts both (cash leaving the till, same sign as drawings).

New get_sfya_salary_payments() merges advance/payment rows (plus
orphan cash-free offset moves for the fully-offset case) for the
closing dialog. New get_sfya_pos_employees() sources the Employee
picker for Task 4's modal.

Also excludes salary legs from sfya_customer_statement's partner
statement (same technique already used for Partner Drawing) - salary
payments carry a real employee partner_id, so without this exclusion
they'd incorrectly show up as generic "Payment Out" rows.
EOF
)"
git push origin main
```

- [ ] **Step 6: Wait for CI + upgrade both modules**

Wait for CI (`gh run list --branch main --limit 3 --json conclusion,workflowName,headSha`), then upgrade both addons in one shell session:

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
mods = env['ir.module.module'].search([('name', 'in', ['sfya_pos_cash_movement', 'sfya_customer_statement'])])
for m in mods:
    print('pre ', m.name, m.installed_version, '->', m.latest_version)
mods.button_immediate_upgrade()
env.cr.commit()
for m in mods:
    print('post', m.name, m.installed_version)
n = env['ir.attachment'].search([('url', '=like', '/web/assets/%')]).unlink()
env.cr.commit()
print('cleared assets')
EOF" 2>&1 | tail -10
```

- [ ] **Step 7: Smoke test — till math, listing, and statement exclusion, using Task 2's smoke records**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
from datetime import date
adv = env['account.payment'].search([('memo', '=', 'smoke advance')], limit=1, order='id desc')
sess = adv.pos_session_id
emp = adv.sfya_employee_id
print('session:', sess.id, sess.state, '| employee:', emp.name)

movements = sess.get_sfya_cash_movements()
print('salary_advances_total (expect >= 500.0):', movements['cash']['salary_advances_total'])
print('salary_payments_total (expect >= 1700.0):', movements['cash']['salary_payments_total'])

rows = sess.get_sfya_salary_payments()
print('salary rows:', rows)

emps = env['pos.session'].get_sfya_pos_employees(sess.id)
print('employees (expect at least the smoke-test employee):', emps)

data = sess.get_closing_control_data()
print('expected cash after adjustment:', data.get('default_cash_details', {}).get('amount'))

today = date.today()
stmt = emp.work_contact_id.get_statement_data(today, today)
salary_rows = [r for r in stmt.get('rows', []) if r.get('doc_model') == 'account.payment' and r.get('doc_id') in (adv.id,)]
print('smoke advance rows leaking into employee statement (expect 0):', len(salary_rows))
EOF" 2>&1 | tail -30
```

Expected: `salary_advances_total >= 500.0`, `salary_payments_total >= 1700.0` (the net cash from Task 2's payment smoke test); `salary rows` includes both the advance row (`kind: 'advance'`, `net_cash: 500.0`) and the payment row (`kind: 'payment'`, `gross_amount: 2000.0`, `advance_offset: 300.0`, `net_cash: 1700.0`); `employees` includes the smoke-test employee; `smoke advance rows leaking into employee statement` = `0`.

---

## Task 4: Frontend — modal modes + toolbar buttons

**Files:**
- Modify: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

**Interfaces:**
- Consumes: `account.payment.sfya_pos_salary_advance`, `sfya_pos_salary_payment`, `get_sfya_salary_advance_balance`, `pos.session.get_sfya_pos_employees` (Task 2/3).

- [ ] **Step 1: Replace `cash_movement_modal.js` with the extended version**

Open `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`. Replace the entire file with:

```js
/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";

export class CashMovementModal extends Component {
    static template = "sfya_pos_cash_movement.CashMovementModal";
    static components = { Dialog };
    static props = {
        mode: { type: String, validate: (v) => ["collect", "payout", "drawing", "transfer", "salary_advance", "salary_payment"].includes(v) },
        initialPartner: { type: Object, optional: true },
        close: Function,
    };

    setup() {
        this.pos = useService("pos");
        this.notification = useService("notification");
        this.state = useState({
            partner: this.props.initialPartner || null,
            journal_id: null,
            journals: [],
            fromJournalId: null,
            toJournalId: null,
            employeeId: null,
            employees: [],
            advanceOffset: "0",
            outstandingAdvance: 0,
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
            if (this.props.mode === "salary_advance" || this.props.mode === "salary_payment") {
                try {
                    const employees = await this.pos.data.call(
                        "pos.session",
                        "get_sfya_pos_employees",
                        [],
                        { session_id: this.pos.session.id },
                    );
                    this.state.employees = employees || [];
                    if (this.state.employees.length > 0) {
                        this.state.employeeId = this.state.employees[0].id;
                        if (this.props.mode === "salary_payment") {
                            await this._fetchOutstandingAdvance();
                        }
                    } else if (!this.state.error) {
                        this.state.error = _t("No employees configured for this company.");
                    }
                } catch (e) {
                    this.state.error = e?.data?.message || e?.message || _t("Failed to load employees.");
                }
            }
        });
    }

    get title() {
        if (this.props.mode === "collect") return _t("Collect Payment");
        if (this.props.mode === "drawing") return _t("Partner Drawing");
        if (this.props.mode === "transfer") return _t("Transfer Funds");
        if (this.props.mode === "salary_advance") return _t("Salary Advance");
        if (this.props.mode === "salary_payment") return _t("Pay Salary");
        return _t("Pay Out");
    }

    get confirmLabel() {
        if (this.props.mode === "collect") return _t("Collect");
        if (this.props.mode === "drawing") return _t("Record Drawing");
        if (this.props.mode === "transfer") return _t("Transfer");
        if (this.props.mode === "salary_advance") return _t("Give Advance");
        if (this.props.mode === "salary_payment") return _t("Pay Salary");
        return _t("Pay Out");
    }

    get confirmClass() {
        if (this.props.mode === "collect") return "btn-success";
        if (this.props.mode === "drawing") return "btn-info";
        if (this.props.mode === "transfer") return "btn-primary";
        if (this.props.mode === "salary_advance") return "btn-info";
        if (this.props.mode === "salary_payment") return "btn-warning";
        return "btn-warning";
    }

    get canUsePartnerDestination() {
        return this.props.mode === "payout";
    }

    get isPartnerDestination() {
        return this.canUsePartnerDestination && this.state.destination === "partner";
    }

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
        if (this.props.mode === "salary_advance") {
            return !!this.state.employeeId && !!this.state.journal_id;
        }
        if (this.props.mode === "salary_payment") {
            const offset = parseFloat(this.state.advanceOffset || 0);
            return (
                !!this.state.employeeId &&
                !!this.state.journal_id &&
                Number.isFinite(offset) &&
                offset >= 0 &&
                offset <= this.state.outstandingAdvance &&
                offset <= amt
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

    get selectedJournalIsBank() {
        const j = this.state.journals.find((x) => x.id === this.state.journal_id);
        return j?.type === "bank";
    }

    get eitherJournalIsBank() {
        const from = this.state.journals.find((x) => x.id === this.state.fromJournalId);
        const to = this.state.journals.find((x) => x.id === this.state.toJournalId);
        return from?.type === "bank" || to?.type === "bank";
    }

    get netToPay() {
        const amt = parseFloat(this.state.amount) || 0;
        const offset = parseFloat(this.state.advanceOffset) || 0;
        return Math.max(0, amt - offset);
    }

    get todayStr() {
        return this._todayStr();
    }

    _todayStr() {
        const d = new Date();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return `${d.getFullYear()}-${m}-${day}`;
    }

    async pickPartner() {
        const partner = await makeAwaitable(
            this.pos.dialog,
            PartnerList,
            this.state.partner ? { partner: this.state.partner } : {},
        );
        if (!partner) return;
        this.state.partner = partner;
        this.state.error = "";
    }

    async pickFundingPartner() {
        const partner = await makeAwaitable(
            this.pos.dialog,
            PartnerList,
            this.state.fundingPartner ? { partner: this.state.fundingPartner } : {},
        );
        if (!partner) return;
        if (this.state.partner && partner.id === this.state.partner.id) {
            this.state.error = _t("Funding partner must be different from the recipient partner.");
            return;
        }
        this.state.fundingPartner = partner;
        this.state.error = "";
    }

    async _fetchOutstandingAdvance() {
        try {
            this.state.outstandingAdvance = await this.pos.data.call(
                "account.payment",
                "get_sfya_salary_advance_balance",
                [],
                { employee_id: this.state.employeeId },
            );
        } catch (e) {
            this.state.outstandingAdvance = 0;
        }
    }

    async onEmployeeChange(ev) {
        this.state.employeeId = parseInt(ev.target.value, 10);
        this.state.error = "";
        if (this.props.mode === "salary_payment") {
            this.state.advanceOffset = "0";
            await this._fetchOutstandingAdvance();
        }
    }

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

        if (this.props.mode === "salary_advance") {
            try {
                const kwargs = {
                    session_id: sessionId,
                    employee_id: this.state.employeeId,
                    amount,
                    journal_id: this.state.journal_id,
                    memo,
                };
                if (this.selectedJournalIsBank) kwargs.date = this.state.date;
                const result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_salary_advance",
                    [],
                    kwargs,
                );
                this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
                this.pos.sfyaCashMovements.push(result);
                this.notification.add(
                    _t("Advance of %s given to %s", result.amount, result.employee_name),
                    { type: "success" },
                );
                if (this.state.print) {
                    await this._printSlip({
                        direction: "salary_advance",
                        name: result.name,
                        employee_name: result.employee_name,
                        amount: result.amount,
                        memo: result.memo,
                    });
                }
                this.props.close();
            } catch (e) {
                this.state.error = e?.data?.message || e?.message || _t("Failed to record advance.");
                this.state.submitting = false;
            }
            return;
        }

        if (this.props.mode === "salary_payment") {
            try {
                const advanceOffset = parseFloat(this.state.advanceOffset || 0);
                const kwargs = {
                    session_id: sessionId,
                    employee_id: this.state.employeeId,
                    gross_amount: amount,
                    advance_offset: advanceOffset,
                    journal_id: this.state.journal_id,
                    memo,
                };
                if (this.selectedJournalIsBank) kwargs.date = this.state.date;
                const result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_salary_payment",
                    [],
                    kwargs,
                );
                this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
                this.pos.sfyaCashMovements.push(result);
                this.notification.add(
                    result.advance_offset > 0
                        ? _t("Paid %s salary to %s (net %s after %s advance offset)", result.gross_amount, result.employee_name, result.net_cash, result.advance_offset)
                        : _t("Paid %s salary to %s", result.gross_amount, result.employee_name),
                    { type: "success" },
                );
                if (this.state.print) {
                    await this._printSlip({
                        direction: "salary_payment",
                        name: result.payment_name || result.move_name,
                        employee_name: result.employee_name,
                        amount: result.gross_amount,
                        gross_amount: result.gross_amount,
                        advance_offset: result.advance_offset,
                        net_cash: result.net_cash,
                        memo: result.memo,
                    });
                }
                this.props.close();
            } catch (e) {
                this.state.error = e?.data?.message || e?.message || _t("Failed to record salary payment.");
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
                    employee_name: result.employee_name || "",
                    gross_amount: result.gross_amount || 0,
                    advance_offset: result.advance_offset || 0,
                    net_cash: result.net_cash != null ? result.net_cash : (result.amount || 0),
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
}
```

- [ ] **Step 2: Replace `cash_movement_modal.xml` with the extended version**

Open `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml`. Replace the entire file with:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates id="template" xml:space="preserve">

    <t t-name="sfya_pos_cash_movement.CashMovementModal">
        <Dialog title="title" size="'md'">
            <div class="o_cash_movement_modal d-flex flex-column gap-3">
                <t t-if="props.mode !== 'transfer' and props.mode !== 'salary_advance' and props.mode !== 'salary_payment'">
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
                <t t-if="props.mode === 'salary_advance' or props.mode === 'salary_payment'">
                    <div>
                        <label class="form-label fw-bold">Employee</label>
                        <select class="form-select" t-on-change="onEmployeeChange"
                                t-att-disabled="state.submitting or !state.employees.length">
                            <t t-foreach="state.employees" t-as="e" t-key="e.id">
                                <option t-att-value="e.id" t-att-selected="e.id === state.employeeId">
                                    <t t-esc="e.name"/>
                                </option>
                            </t>
                        </select>
                    </div>
                    <div t-if="props.mode === 'salary_payment'">
                        <div class="text-muted">Outstanding Advance: PKR <t t-esc="state.outstandingAdvance.toFixed(2)"/></div>
                        <div t-if="state.outstandingAdvance > 0" class="mt-2">
                            <label class="form-label fw-bold">Advance Offset</label>
                            <input type="number" class="form-control" step="0.01" min="0"
                                   t-att-max="state.outstandingAdvance"
                                   t-model="state.advanceOffset" placeholder="0.00"/>
                        </div>
                        <div class="text-muted mt-1">Net cash to pay: PKR <t t-esc="netToPay.toFixed(2)"/></div>
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
                <div>
                    <label class="form-label fw-bold">Amount</label>
                    <input type="number" class="form-control" step="0.01" min="0"
                           t-model="state.amount" placeholder="0.00"/>
                </div>
                <div>
                    <label class="form-label fw-bold">Memo (optional)</label>
                    <input type="text" class="form-control" t-model="state.memo"
                           placeholder="e.g. Repayment of old credit"/>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="sfya_cm_print"
                           t-model="state.print"/>
                    <label class="form-check-label" for="sfya_cm_print">Print receipt slip</label>
                </div>
                <div t-if="state.error" class="alert alert-danger mb-0 py-1 px-2"
                     t-esc="state.error"/>
            </div>
            <t t-set-slot="footer">
                <button class="btn btn-secondary" t-on-click="() => props.close()">Cancel</button>
                <button class="btn" t-att-class="confirmClass" t-att-disabled="!isValid"
                        t-on-click="confirm">
                    <t t-esc="confirmLabel"/>
                </button>
            </t>
        </Dialog>
    </t>

    <t t-name="sfya_pos_cash_movement.PaymentSlip">
        <div class="pos-receipt">
            <div class="text-center fw-bold">SFYA ENTERPRISES</div>
            <div class="text-center">Payment Slip</div>
            <hr/>
            <div>Date:    <t t-esc="date"/></div>
            <div>Cashier: <t t-esc="cashier"/></div>
            <div>Type:    <t t-if="direction === 'inbound'">Collect Payment</t><t t-elif="direction === 'drawing'">Partner Drawing</t><t t-elif="direction === 'transfer'">Pay Out (via Partner)</t><t t-elif="direction === 'internal_transfer'">Internal Transfer</t><t t-elif="direction === 'salary_advance'">Salary Advance</t><t t-elif="direction === 'salary_payment'">Pay Salary</t><t t-else="">Pay Out</t></div>
            <hr/>
            <div t-if="direction !== 'internal_transfer' and direction !== 'salary_advance' and direction !== 'salary_payment'">Partner: <t t-esc="partner_name"/></div>
            <div t-if="funding_partner_name">Funded By: <t t-esc="funding_partner_name"/></div>
            <div t-if="direction === 'internal_transfer'">From:    <t t-esc="from_journal_name"/></div>
            <div t-if="direction === 'internal_transfer'">To:      <t t-esc="to_journal_name"/></div>
            <div t-if="direction === 'salary_advance' or direction === 'salary_payment'">Employee: <t t-esc="employee_name"/></div>
            <div t-if="direction === 'salary_payment'">Gross:   PKR <t t-esc="gross_amount"/></div>
            <div t-if="direction === 'salary_payment' and advance_offset">Advance Offset: PKR <t t-esc="advance_offset"/></div>
            <div t-if="direction === 'salary_payment'">Net Paid: PKR <t t-esc="net_cash"/></div>
            <div t-if="direction !== 'salary_payment'">Amount:  PKR <t t-esc="amount"/></div>
            <div t-if="memo">Memo:    <t t-esc="memo"/></div>
            <div>Ref:     <t t-esc="name"/></div>
            <hr/>
            <div t-if="direction === 'inbound'">Received by: ______________</div>
            <div t-elif="direction === 'drawing'">Withdrawn by: _____________</div>
            <div t-elif="direction === 'internal_transfer'">Processed by: ______________</div>
            <div t-elif="direction === 'salary_advance' or direction === 'salary_payment'">Received by: ______________</div>
            <div t-else="">Paid to:     ______________</div>
        </div>
    </t>

</templates>
```

- [ ] **Step 3: Add `openSalaryAdvance()` / `openSalaryPayment()`**

Open `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js`. Current full content:

```js
/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { CashMovementModal } from "./cash_movement_modal";
import { CustomerOverviewModal } from "./customer_overview_modal";

patch(ControlButtons.prototype, {
    openCollect() {
        this.dialog.add(CashMovementModal, { mode: "collect" });
    },
    openPayout() {
        this.dialog.add(CashMovementModal, { mode: "payout" });
    },
    openDrawing() {
        this.dialog.add(CashMovementModal, { mode: "drawing" });
    },
    openTransfer() {
        this.dialog.add(CashMovementModal, { mode: "transfer" });
    },
    openOverview() {
        this.dialog.add(CustomerOverviewModal, {});
    },
});
```

Replace with:

```js
/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { CashMovementModal } from "./cash_movement_modal";
import { CustomerOverviewModal } from "./customer_overview_modal";

patch(ControlButtons.prototype, {
    openCollect() {
        this.dialog.add(CashMovementModal, { mode: "collect" });
    },
    openPayout() {
        this.dialog.add(CashMovementModal, { mode: "payout" });
    },
    openDrawing() {
        this.dialog.add(CashMovementModal, { mode: "drawing" });
    },
    openTransfer() {
        this.dialog.add(CashMovementModal, { mode: "transfer" });
    },
    openSalaryAdvance() {
        this.dialog.add(CashMovementModal, { mode: "salary_advance" });
    },
    openSalaryPayment() {
        this.dialog.add(CashMovementModal, { mode: "salary_payment" });
    },
    openOverview() {
        this.dialog.add(CustomerOverviewModal, {});
    },
});
```

- [ ] **Step 4: Add "Salary Advance" / "Pay Salary" buttons**

Open `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml`. Current full content:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates id="template" xml:space="preserve">
    <t t-name="sfya_pos_cash_movement.ControlButtons" t-inherit="point_of_sale.ControlButtons" t-inherit-mode="extension">
        <xpath expr="//div[hasclass('control-buttons')]" position="inside">
            <button class="control-button btn btn-secondary btn-lg py-5 o_cash_movement_collect"
                    t-on-click="openCollect">
                <i class="fa fa-arrow-down text-success me-1"/>
                Collect Payment
            </button>
            <button class="control-button btn btn-secondary btn-lg py-5 o_cash_movement_payout"
                    t-on-click="openPayout">
                <i class="fa fa-arrow-up text-warning me-1"/>
                Pay Out
            </button>
            <button class="control-button btn btn-secondary btn-lg py-5 o_cash_movement_drawing"
                    t-on-click="openDrawing">
                <i class="fa fa-share-square text-info me-1"/>
                Partner Drawing
            </button>
            <button class="control-button btn btn-secondary btn-lg py-5 o_cash_movement_transfer"
                    t-on-click="openTransfer">
                <i class="fa fa-exchange text-primary me-1"/>
                Transfer Funds
            </button>
            <button class="control-button btn btn-secondary btn-lg py-5 o_customer_overview"
                    t-on-click="openOverview">
                <i class="fa fa-users text-primary me-1"/>
                Customer Overview
            </button>
        </xpath>
    </t>
</templates>
```

Replace with:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates id="template" xml:space="preserve">
    <t t-name="sfya_pos_cash_movement.ControlButtons" t-inherit="point_of_sale.ControlButtons" t-inherit-mode="extension">
        <xpath expr="//div[hasclass('control-buttons')]" position="inside">
            <button class="control-button btn btn-secondary btn-lg py-5 o_cash_movement_collect"
                    t-on-click="openCollect">
                <i class="fa fa-arrow-down text-success me-1"/>
                Collect Payment
            </button>
            <button class="control-button btn btn-secondary btn-lg py-5 o_cash_movement_payout"
                    t-on-click="openPayout">
                <i class="fa fa-arrow-up text-warning me-1"/>
                Pay Out
            </button>
            <button class="control-button btn btn-secondary btn-lg py-5 o_cash_movement_drawing"
                    t-on-click="openDrawing">
                <i class="fa fa-share-square text-info me-1"/>
                Partner Drawing
            </button>
            <button class="control-button btn btn-secondary btn-lg py-5 o_cash_movement_transfer"
                    t-on-click="openTransfer">
                <i class="fa fa-exchange text-primary me-1"/>
                Transfer Funds
            </button>
            <button class="control-button btn btn-secondary btn-lg py-5 o_cash_movement_salary_advance"
                    t-on-click="openSalaryAdvance">
                <i class="fa fa-clock-o text-info me-1"/>
                Salary Advance
            </button>
            <button class="control-button btn btn-secondary btn-lg py-5 o_cash_movement_salary_payment"
                    t-on-click="openSalaryPayment">
                <i class="fa fa-money text-warning me-1"/>
                Pay Salary
            </button>
            <button class="control-button btn btn-secondary btn-lg py-5 o_customer_overview"
                    t-on-click="openOverview">
                <i class="fa fa-users text-primary me-1"/>
                Customer Overview
            </button>
        </xpath>
    </t>
</templates>
```

- [ ] **Step 5: Bump manifest version**

In `addons/sfya_pos_cash_movement/__manifest__.py`, change:

```python
    'version': '18.0.6.0.7',
```

to:

```python
    'version': '18.0.6.0.8',
```

- [ ] **Step 6: Syntax check**

```bash
node --input-type=module --check < addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js
node --input-type=module --check < addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js
```

Expected: both commands produce no output (clean ES module parse). Plain `node --check <file>` will fail with "Cannot use import statement outside a module" — that's expected for these unbundled ES modules; the `--input-type=module` form above is the correct check.

- [ ] **Step 7: Commit**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js \
        addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml \
        addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js \
        addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "$(cat <<'EOF'
feat(pos_cash_movement): Salary Advance / Pay Salary modes + buttons

CashMovementModal gains "salary_advance" and "salary_payment" modes:
an Employee picker (sourced from hr.employee) replaces the partner
picker, and salary_payment additionally shows the employee's live
outstanding advance balance plus an Advance Offset input with a
computed net-cash-to-pay line. Two new toolbar buttons open each mode.

PaymentSlip gains matching branches (Employee line; Gross/Advance
Offset/Net Paid breakdown for salary_payment).
EOF
)"
git push origin main
```

- [ ] **Step 8: Wait for CI + upgrade**

Run the Deploy / upgrade loop above.

- [ ] **Step 9: Manual browser smoke test**

Open the POS session in a browser, open Register screen. Verify:
1. "Salary Advance" and "Pay Salary" buttons appear alongside the existing four.
2. Click "Salary Advance": Employee dropdown populated, no Partner picker visible. Pick an employee, an account, enter an amount, confirm. Notification shows "Advance of X given to <employee>".
3. Click "Pay Salary" for the same employee: "Outstanding Advance: PKR X" line matches the amount just given. Enter a gross amount larger than the advance, set Advance Offset to the full outstanding balance, confirm "Net cash to pay" updates live as the offset changes. Confirm the payment.
4. Re-open "Pay Salary" for the same employee: "Outstanding Advance" now shows `0.00` (fully cleared) and the Advance Offset input is hidden.

If no browser automation is available in this environment, disclose that explicitly and ask the human partner to either perform this check themselves or explicitly accept skipping it — do not silently skip.

---

## Task 5: Frontend — "Salary" section in the closing dialog

**Files:**
- Modify: `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

**Interfaces:**
- Consumes: `pos.session.get_sfya_salary_payments()` (Task 3).

- [ ] **Step 1: Replace `closing_dialog_patch.js` with the extended version**

Open `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js`. Replace the entire file with:

```js
/** @odoo-module **/

/**
 * Patch ClosePosPopup (Odoo 18 closing popup) with SFYA cash movement sections.
 *
 * Step 1 findings:
 *  - Component class: ClosePosPopup (NOT ClosingPosDialog)
 *  - Template name: point_of_sale.ClosePosPopup
 *  - Import path: @point_of_sale/app/navbar/closing_popup/closing_popup
 *  - this.pos is available directly from usePos() in setup()
 *  - Expected cash is props.default_cash_details.amount (a prop, NOT a getter)
 *    getDifference() = parseFloat(counted) - props.default_cash_details.amount
 *  - Expected-cash adjustment (collects_total - payouts_total) is applied on the
 *    Python side by overriding get_closing_control_data() in pos_session.py, so
 *    props.default_cash_details.amount already includes the SFYA movements.
 */

import { patch } from "@web/core/utils/patch";
import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { onWillStart, useState } from "@odoo/owl";

patch(ClosePosPopup.prototype, {
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
            salaryPayments: [],
            cashCollectsOpen: true,
            cashPayoutsOpen: true,
            drawingsOpen: true,
            transfersOpen: true,
            internalTransfersOpen: true,
            salaryPaymentsOpen: true,
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
            try {
                this.sfya.salaryPayments = await this.pos.data.call(
                    "pos.session",
                    "get_sfya_salary_payments",
                    [[this.pos.session.id]],
                );
            } catch (e) {
                console.warn("[SFYA] Failed to load salary payments:", e);
            }
        });
    },

    get sfyaCashAdjustment() {
        return (this.sfya.cash.collects_total || 0) - (this.sfya.cash.payouts_total || 0) - (this.sfya.cash.drawings_total || 0);
    },

    get sfyaTransfersTotal() {
        return this.sfya.transfers.reduce((sum, t) => sum + t.amount, 0);
    },

    get sfyaInternalTransfersTotal() {
        return this.sfya.internalTransfers.reduce((sum, t) => sum + t.amount, 0);
    },

    get sfyaSalaryPaymentsTotal() {
        return this.sfya.salaryPayments.reduce((sum, r) => sum + r.net_cash, 0);
    },

    toggleSfyaBank(journalId) {
        this.sfya.banksOpen[journalId] = !this.sfya.banksOpen[journalId];
    },

    async closeSession() {
        try {
            const cashId = this.props.default_cash_details?.id;
            const counted = parseFloat(
                cashId != null ? (this.state.payments[cashId]?.counted || 0) : 0
            );
            const expected = this.props.default_cash_details?.amount || 0;
            const maxDiff = this.pos.config.sfya_max_cash_difference ?? 500;

            if (counted === 0) {
                this.sfya.closeError = "Please enter actual cash count before closing.";
                return;
            }
            const diff = Math.abs(counted - expected);
            if (maxDiff > 0 && diff > maxDiff) {
                this.sfya.closeError = `Cash difference of Rs ${diff.toFixed(0)} exceeds allowed limit of Rs ${maxDiff.toFixed(0)}. Please recount or adjust.`;
                return;
            }
            this.sfya.closeError = null;
        } catch (e) {
            // Defensive: never block close on internal guard failure.
            console.warn("[SFYA] close validation failed, falling through:", e);
            this.sfya.closeError = null;
        }
        return super.closeSession(...arguments);
    }
});
```

- [ ] **Step 2: Replace `closing_dialog_patch.xml` with the extended version**

Open `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml`. Find the outer visibility `t-if`:

```xml
            <div t-if="sfya.loaded and (sfya.cash.collects.length or sfya.cash.payouts.length or sfya.cash.drawings.length or sfya.banks.length or sfya.transfers.length or sfya.internalTransfers.length)"
                 class="o_sfya_cash_movements mt-2">
```

Replace with:

```xml
            <div t-if="sfya.loaded and (sfya.cash.collects.length or sfya.cash.payouts.length or sfya.cash.drawings.length or sfya.banks.length or sfya.transfers.length or sfya.internalTransfers.length or sfya.salaryPayments.length)"
                 class="o_sfya_cash_movements mt-2">
```

Find the existing "Internal transfers" section (it ends right before the "Banks" comment):

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

                <!-- Banks: one section per journal, informational only -->
```

Insert a new "Salary" section between them, making it:

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

                <!-- Salary: advances + payments; net cash impact (if any) already folded into till math -->
                <div t-if="sfya.salaryPayments.length" class="border rounded p-2 mb-2">
                    <div class="d-flex justify-content-between fw-bold" style="cursor: pointer;"
                         t-on-click="() => sfya.salaryPaymentsOpen = !sfya.salaryPaymentsOpen">
                        <span>
                            <i class="fa" t-att-class="sfya.salaryPaymentsOpen ? 'fa-chevron-down' : 'fa-chevron-right'"/>
                            Salary
                            <small class="text-muted ms-2">(till impact total)</small>
                        </span>
                        <span class="text-muted">
                            <t t-esc="sfyaSalaryPaymentsTotal.toFixed(2)"/>
                        </span>
                    </div>
                    <table t-if="sfya.salaryPaymentsOpen" class="table table-sm mb-0 mt-1">
                        <thead>
                            <tr class="text-muted">
                                <th>Employee</th>
                                <th>Kind</th>
                                <th class="text-end">Gross</th>
                                <th class="text-end">Offset</th>
                                <th class="text-end">Net Cash</th>
                                <th>Memo</th>
                            </tr>
                        </thead>
                        <tbody>
                            <t t-foreach="sfya.salaryPayments" t-as="r" t-key="r.kind + '-' + r.id">
                                <tr>
                                    <td t-esc="r.employee_name"/>
                                    <td t-esc="r.kind === 'advance' ? 'Advance' : 'Payment'"/>
                                    <td class="text-end" t-esc="r.gross_amount.toFixed(2)"/>
                                    <td class="text-end" t-esc="r.advance_offset ? r.advance_offset.toFixed(2) : ''"/>
                                    <td class="text-end" t-esc="r.net_cash.toFixed(2)"/>
                                    <td t-esc="r.memo"/>
                                </tr>
                            </t>
                        </tbody>
                    </table>
                </div>

                <!-- Banks: one section per journal, informational only -->
```

(The rest of the file — the Banks `t-foreach` block and closing tags — is unchanged.)

- [ ] **Step 3: Bump manifest version**

In `addons/sfya_pos_cash_movement/__manifest__.py`, change:

```python
    'version': '18.0.6.0.8',
```

to:

```python
    'version': '18.0.6.0.9',
```

- [ ] **Step 4: Syntax check**

```bash
node --input-type=module --check < addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js
```

Expected: no output (clean ES module parse).

- [ ] **Step 5: Commit**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js \
        addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "$(cat <<'EOF'
feat(pos_cash_movement): Salary section in the closing dialog

Loads get_sfya_salary_payments() alongside the existing partner/
internal transfer listings. New collapsible "Salary" section shows
each advance/payment row (Employee, Kind, Gross, Offset, Net Cash,
Memo). sfyaSalaryPaymentsTotal sums net_cash - the actual till/bank
cash impact, already folded into props.default_cash_details.amount by
Task 3's get_closing_control_data override.
EOF
)"
git push origin main
```

- [ ] **Step 6: Wait for CI + upgrade**

Run the Deploy / upgrade loop above.

- [ ] **Step 7: Manual browser smoke test**

Open the POS session, trigger a Salary Advance and a Pay Salary (with a partial offset) via the buttons added in Task 4, then open the closing dialog (Close Register). Verify:
1. A "Salary" section appears, collapsible, showing both rows with correct Employee/Kind/Gross/Offset/Net Cash values.
2. The section's header total equals the sum of the rows' Net Cash column.
3. The expected cash amount shown at the top of the closing dialog already reflects the salary cash outflow (compare against a manual count, or against the pre-salary expected amount minus the net cash paid).

If no browser automation is available in this environment, disclose that explicitly and ask the human partner to either perform this check themselves or explicitly accept skipping it — do not silently skip.

---

## Task 6: Verification — full happy-path + edge cases

**Files:** None changed. Smoke-only.

- [ ] **Step 1: Full-advance-offset case (net_cash == 0) — no payment leg created**

Requires an open POS session. If none is open, stop and ask before proceeding — do not improvise around this precondition.

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
emp = env['hr.employee'].search([('company_id', '=', sess.company_id.id), ('active', '=', True)], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
cash_jid = next(j['id'] for j in js if j['type'] == 'cash')

adv = env['account.payment'].sfya_pos_salary_advance(sess.id, emp.id, 400.0, cash_jid, memo='smoke full-offset advance')
env.cr.commit()

pay = env['account.payment'].sfya_pos_salary_payment(sess.id, emp.id, 400.0, 400.0, cash_jid, memo='smoke full-offset payment')
print('payment result (expect payment_id None, move_id set, net_cash 0.0):', pay)
env.cr.commit()

bal = env['account.payment'].get_sfya_salary_advance_balance(emp.id)
print('balance after full offset (expect 0.0):', bal)

rows = sess.get_sfya_salary_payments()
orphan_rows = [r for r in rows if r['memo'] == 'smoke full-offset payment']
print('orphan payment row (expect one, net_cash 0.0):', orphan_rows)

from datetime import date
today = date.today()
stmt = emp.work_contact_id.get_statement_data(today, today)
leaked = [r for r in stmt.get('rows', []) if 'full-offset' in str(r.get('note', ''))]
print('full-offset move leaking into employee statement (expect 0):', len(leaked))
EOF" 2>&1 | tail -20
```

Expected: `payment_id` is `None`, `move_id` is not `None`, `net_cash` is `0.0`; balance after full offset is `0.0`; the orphan row appears in `get_sfya_salary_payments` with `net_cash: 0.0`, `gross_amount: 400.0`, `advance_offset: 400.0`; `0` leaked statement rows.

- [ ] **Step 2: Bank-journal salary payment — informational only, no till impact**

Requires a bank journal to exist (created during the Task 1/2 smoke tests' company setup, or any pre-existing one).

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
emp = env['hr.employee'].search([('company_id', '=', sess.company_id.id), ('active', '=', True)], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
bank_jid = next((j['id'] for j in js if j['type'] == 'bank'), None)
if not bank_jid:
    print('SKIP: no bank journal configured')
else:
    before = sess.get_sfya_cash_movements()['cash']['salary_payments_total']
    pay = env['account.payment'].sfya_pos_salary_payment(sess.id, emp.id, 1000.0, 0.0, bank_jid, memo='smoke bank salary')
    env.cr.commit()
    after = sess.get_sfya_cash_movements()['cash']['salary_payments_total']
    print('salary_payments_total unaffected by bank payment (expect equal):', before, after)
    rows = sess.get_sfya_salary_payments()
    bank_rows = [r for r in rows if r['memo'] == 'smoke bank salary']
    print('bank salary row still listed (expect one, journal_name set):', bank_rows)
EOF" 2>&1 | tail -10
```

Expected: `salary_payments_total` unchanged (bank legs don't affect the cash-restricted till total); the bank payment still appears in `get_sfya_salary_payments` with a non-empty `journal_name`.

- [ ] **Step 3: Error paths**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
emp = env['hr.employee'].search([('company_id', '=', sess.company_id.id), ('active', '=', True)], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
cash_jid = next(j['id'] for j in js if j['type'] == 'cash')

# zero amount
try:
    env['account.payment'].sfya_pos_salary_advance(sess.id, emp.id, 0.0, cash_jid)
    print('FAIL: expected UserError for zero amount')
except Exception as e:
    print('OK zero-amount advance:', e)

# advance_offset exceeds gross_amount
try:
    env['account.payment'].sfya_pos_salary_payment(sess.id, emp.id, 100.0, 200.0, cash_jid)
    print('FAIL: expected UserError for offset > gross')
except Exception as e:
    print('OK offset-exceeds-gross:', e)

# advance_offset exceeds outstanding balance (employee has 0 balance at this point if Step 1 fully cleared it)
bal = env['account.payment'].get_sfya_salary_advance_balance(emp.id)
try:
    env['account.payment'].sfya_pos_salary_payment(sess.id, emp.id, 1000.0, bal + 500.0, cash_jid)
    print('FAIL: expected UserError for offset > outstanding balance')
except Exception as e:
    print('OK offset-exceeds-balance:', e)

# non-cash/bank journal (find a sales journal)
sales_jid = env['account.journal'].search([('type', '=', 'sale')], limit=1).id
try:
    env['account.payment'].sfya_pos_salary_advance(sess.id, emp.id, 100.0, sales_jid)
    print('FAIL: expected UserError for sales journal')
except Exception as e:
    print('OK wrong-journal-type:', e)

# nonexistent employee
try:
    env['account.payment'].sfya_pos_salary_advance(sess.id, 999999, 100.0, cash_jid)
    print('FAIL: expected UserError for missing employee')
except Exception as e:
    print('OK missing-employee:', e)
EOF" 2>&1 | tail -15
```

Expected: five `OK ...` lines, no `FAIL`.

- [ ] **Step 4: No commit (verification only)**

---

## Task 7: Update architecture doc

**Files:**
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Update the `sfya_pos_cash_movement` one-liner**

Open `docs/ARCHITECTURE.md`. Find the existing line describing this addon (in the addons list, near line 165):

```
- `sfya_pos_cash_movement` — adds Collect Payment / Pay Out / Partner Drawing / Transfer Funds buttons to POS; records `account.payment` against any cash or bank journal of the company (cashier picks via Account dropdown), linked to the active `pos.session` for till reconciliation. Cash movements adjust expected cash in the closing dialog; bank movements appear as informational per-journal sections with no till impact. Transfer Funds moves money directly between two of the company's own journals (e.g. shop cash till to a bank account) via a dedicated clearing account, with the cash-journal leg (if any) folded into the till's expected-cash math. A separate Partner Transfer flow settles a Pay Out via another partner's balance instead (2-line ledger entry, no cash/bank leg at all).
```

Replace with:

```
- `sfya_pos_cash_movement` — adds Collect Payment / Pay Out / Partner Drawing / Transfer Funds / Salary Advance / Pay Salary buttons to POS; records `account.payment` against any cash or bank journal of the company (cashier picks via Account dropdown), linked to the active `pos.session` for till reconciliation. Cash movements adjust expected cash in the closing dialog; bank movements appear as informational per-journal sections with no till impact. Transfer Funds moves money directly between two of the company's own journals (e.g. shop cash till to a bank account) via a dedicated clearing account, with the cash-journal leg (if any) folded into the till's expected-cash math. A separate Partner Transfer flow settles a Pay Out via another partner's balance instead (2-line ledger entry, no cash/bank leg at all). Salary Advance/Pay Salary post against an employee (sourced from `hr.employee`): advances hit a dedicated Employee Advances account, and Pay Salary posts the net cash leg against the Salary and Wages expense account plus, when offsetting a prior advance, a cash-free entry that recognizes the offset portion of the expense and clears the advance — always recognizing the full gross salary regardless of how much was pre-paid. `sfya_customer_statement` excludes both salary leg types from partner statements, same technique as the existing Partner Drawing exclusion.
```

- [ ] **Step 2: Syntax check**

None needed (Markdown only).

- [ ] **Step 3: Commit**

```bash
git add docs/ARCHITECTURE.md
git commit -m "$(cat <<'EOF'
docs: note Salary Advance/Pay Salary capability in sfya_pos_cash_movement entry
EOF
)"
git push origin main
```

---

## Acceptance checklist

| Requirement (spec) | Task |
|---|---|
| Dedicated Employee Advance account + link to existing Salary expense account + dedicated offset journal, auto-created per company | 1 |
| Any cashier can use both actions (no shareholder restriction) | 2 |
| `sfya_pos_salary_advance` RPC: validation, posts against Employee Advance account | 2 |
| `sfya_pos_salary_payment` RPC: net-cash leg + cash-free offset entry, full gross always recognized as expense | 2 |
| Outstanding balance computed company-wide, not session-scoped | 2 |
| Float-rounding tolerance on offset comparisons | 2 |
| Salary legs excluded from generic Collect/Pay Out/Drawing buckets; cash-journal totals folded into till adjustment | 3 |
| `get_sfya_salary_payments` listing (advances + payments, including the full-offset orphan-move case) | 3 |
| `get_sfya_pos_employees` sources the Employee picker | 3 |
| Salary legs excluded from partner statement (spec correction found during planning) | 3 |
| Employee picker + advance-offset UI in the modal; two new toolbar buttons | 4 |
| "Salary" section in the closing dialog | 5 |
| Full-offset, bank-journal, and error-path edge cases verified | 6 |
| Architecture doc updated | 7 |
