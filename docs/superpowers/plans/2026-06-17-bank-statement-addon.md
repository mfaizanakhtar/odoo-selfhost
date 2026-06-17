# Bank Statement Addon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `sfya_bank_statement` addon — mirrors `sfya_customer_statement` for bank/cash journals. Two wizards (Set Opening Balance + Print Statement) accessible from `account.journal` form for journals with `type in ('bank', 'cash')`. Per-GL-account statement PDF.

**Architecture:** New addon, 13 new files. Depends on `account` + `sfya_customer_statement` (reuses `res.company.sfya_opening_balance_account_id` field + statement CSS). No model field additions. Opening balance posts a balanced `account.move` via the company's General journal. Statement report queries `account.move.line` filtered by `journal.default_account_id`. Override gated to `base.group_system` both in view and server.

**Tech Stack:** Odoo 18 CE, Python, QWeb reports, no JS. Verification: odoo shell + browser smoke.

**Spec:** `docs/superpowers/specs/2026-06-17-bank-statement-addon-design.md`

---

## Deploy / upgrade loop (used in every task that ships code)

This addon is rsync-deployed via GitHub Actions on push to `main`. After commit + push:

1. Wait for CI: `gh run list --branch main --limit 3 --json conclusion,workflowName,headSha,status` — wait for both `Lint` and `Deploy` = success on your HEAD SHA.
2. SSH upgrade + clear assets:
   ```bash
   ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
   env['ir.module.module'].update_list()
   env.cr.commit()
   mod = env['ir.module.module'].search([('name', '=', 'sfya_bank_statement')])
   print('pre  state:', mod.state, 'installed:', mod.installed_version, 'manifest:', mod.latest_version)
   if mod.state == 'installed':
       mod.button_immediate_upgrade()
   else:
       mod.button_immediate_install()
   env.cr.commit()
   print('post state:', mod.state, 'installed:', mod.installed_version)
   n = env['ir.attachment'].search([('url', '=like', '/web/assets/%')]).unlink()
   env.cr.commit()
   print('cleared assets')
   EOF" 2>&1 | tail -8
   ```
3. For browser/UI tasks, user hard-refreshes (Cmd+Shift+R).

Manifest version MUST be bumped in any task after the first install, or `button_immediate_upgrade` is a no-op.

---

## File map (all new under `addons/sfya_bank_statement/`)

| File | Task | Purpose |
|---|---|---|
| `__manifest__.py` | 1 | Module metadata; depends `account`, `sfya_customer_statement`; data registry |
| `__init__.py` | 1 | Imports `wizards`, `reports` |
| `security/ir.model.access.csv` | 1 | RW on both wizards for `base.group_user` |
| `wizards/__init__.py` | 1 | Imports wizard modules |
| `wizards/bank_opening_balance_wizard.py` | 2 | TransientModel + `action_create_move` |
| `wizards/bank_opening_balance_wizard_views.xml` | 2 | Form + act_window |
| `wizards/bank_statement_wizard.py` | 3 | TransientModel + print/html actions |
| `wizards/bank_statement_wizard_views.xml` | 3 | Form + act_window |
| `reports/__init__.py` | 3 | Imports report Python |
| `reports/bank_statement_report.py` | 3 | `AbstractModel` `_get_report_values` |
| `reports/bank_statement_report_action.xml` | 3 | `ir.actions.report` |
| `reports/bank_statement_report.xml` | 3 | QWeb template |
| `views/account_journal_views.xml` | 2 | Inherit journal form; add 2 buttons |

---

## Task 1: Addon skeleton — install cleanly

**Files:**
- Create: `addons/sfya_bank_statement/__manifest__.py`
- Create: `addons/sfya_bank_statement/__init__.py`
- Create: `addons/sfya_bank_statement/wizards/__init__.py`
- Create: `addons/sfya_bank_statement/reports/__init__.py`
- Create: `addons/sfya_bank_statement/security/ir.model.access.csv`

- [ ] **Step 1: Write manifest**

`addons/sfya_bank_statement/__manifest__.py`:
```python
{
    'name': 'SFYA Bank Statement',
    'version': '18.0.1.0.0',
    'summary': 'Opening balance wizard + per-journal statement PDF for bank/cash journals',
    'category': 'Accounting',
    'author': 'SFYA Enterprises',
    'license': 'LGPL-3',
    'depends': ['account', 'sfya_customer_statement'],
    'data': [
        'security/ir.model.access.csv',
        'wizards/bank_opening_balance_wizard_views.xml',
        'wizards/bank_statement_wizard_views.xml',
        'reports/bank_statement_report_action.xml',
        'reports/bank_statement_report.xml',
        'views/account_journal_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
```

Note: this lists files that will be created in Tasks 2 + 3. Module is **not installable yet** until those files exist. We'll install at the end of Task 3.

- [ ] **Step 2: Write top-level `__init__.py`**

`addons/sfya_bank_statement/__init__.py`:
```python
from . import wizards
from . import reports
```

- [ ] **Step 3: Write wizards `__init__.py`**

`addons/sfya_bank_statement/wizards/__init__.py`:
```python
from . import bank_opening_balance_wizard
from . import bank_statement_wizard
```

- [ ] **Step 4: Write reports `__init__.py`**

`addons/sfya_bank_statement/reports/__init__.py`:
```python
from . import bank_statement_report
```

- [ ] **Step 5: Write security CSV**

`addons/sfya_bank_statement/security/ir.model.access.csv`:
```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_sfya_bank_opening_balance_wizard,sfya.bank.opening.balance.wizard,model_sfya_bank_opening_balance_wizard,base.group_user,1,1,1,1
access_sfya_bank_statement_wizard,sfya.bank.statement.wizard,model_sfya_bank_statement_wizard,base.group_user,1,1,1,1
```

- [ ] **Step 6: Commit skeleton (no push yet — module won't install without wizard files)**

```bash
git add addons/sfya_bank_statement/
git commit -m "feat(bank_statement): addon skeleton — manifest, init, security"
```

Do NOT push until Task 3 is committed; CI will try to load the module and we want the deploy to land a fully working version.

---

## Task 2: Opening balance wizard + journal form button

**Files:**
- Create: `addons/sfya_bank_statement/wizards/bank_opening_balance_wizard.py`
- Create: `addons/sfya_bank_statement/wizards/bank_opening_balance_wizard_views.xml`
- Create: `addons/sfya_bank_statement/views/account_journal_views.xml`

- [ ] **Step 1: Write wizard model**

`addons/sfya_bank_statement/wizards/bank_opening_balance_wizard.py`:
```python
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class BankOpeningBalanceWizard(models.TransientModel):
    _name = 'sfya.bank.opening.balance.wizard'
    _description = 'Set Bank/Cash Opening Balance'

    journal_id = fields.Many2one(
        'account.journal', required=True,
        domain="[('type', 'in', ['bank', 'cash'])]",
        default=lambda self: self.env.context.get('active_id'),
    )
    amount = fields.Monetary(
        required=True,
        help='Positive = bank/cash has money. Negative = overdraft / shortage.',
    )
    date = fields.Date(required=True, default=fields.Date.today)
    description = fields.Char(default='Opening balance — migrated')
    opening_journal_id = fields.Many2one(
        'account.journal', required=True,
        domain="[('type', '=', 'general')]",
        default=lambda self: self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.env.company.id)], limit=1,
        ),
        help='Journal that posts the opening JE (Miscellaneous / General).',
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id.id,
    )
    force = fields.Boolean(
        string='Override existing (Admin)',
        help='Allow creating another opening JE even if one already exists.',
    )
    is_admin = fields.Boolean(compute='_compute_is_admin')

    def _compute_is_admin(self):
        for w in self:
            w.is_admin = self.env.user.has_group('base.group_system')

    def action_create_move(self):
        self.ensure_one()
        journal = self.journal_id
        if not journal.default_account_id:
            raise UserError(_(
                'Journal %s has no default account configured.', journal.name,
            ))
        equity = self.env.company.sfya_opening_balance_account_id
        if not equity:
            raise UserError(_(
                "Opening Balance Equity account not set. "
                "Go to Settings → Companies → %s and set it.",
                self.env.company.name,
            ))
        if not self.amount:
            raise UserError(_('Amount must be non-zero.'))

        ref = f'BANK-OPENING-BAL-{journal.id}'
        existing = self.env['account.move'].search([
            ('ref', '=', ref),
            ('state', '=', 'posted'),
        ], limit=1)
        if existing and not self.force:
            raise UserError(_(
                "Opening balance already posted for %(j)s (move %(m)s). "
                "Tick Override to add another (Admin only).",
                j=journal.name, m=existing.name,
            ))
        if self.force and not self.is_admin:
            raise UserError(_("Only administrators can override an existing opening balance."))

        amt = self.amount
        sign_positive = amt > 0
        line_bank = {
            'account_id': journal.default_account_id.id,
            'name': self.description or _('Opening balance'),
            'debit': abs(amt) if sign_positive else 0.0,
            'credit': abs(amt) if not sign_positive else 0.0,
        }
        line_equity = {
            'account_id': equity.id,
            'name': self.description or _('Opening balance'),
            'debit': 0.0 if sign_positive else abs(amt),
            'credit': abs(amt) if sign_positive else 0.0,
        }
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.date,
            'journal_id': self.opening_journal_id.id,
            'ref': ref,
            'line_ids': [(0, 0, line_bank), (0, 0, line_equity)],
        })
        move.action_post()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Opening balance set'),
                'message': _(
                    'Created %(m)s for %(j)s (%(a)s).',
                    m=move.name, j=journal.name, a=amt,
                ),
                'type': 'success',
                'sticky': False,
            },
        }
```

- [ ] **Step 2: Write wizard view + action**

`addons/sfya_bank_statement/wizards/bank_opening_balance_wizard_views.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<odoo>
    <record id="view_sfya_bank_opening_balance_wizard_form" model="ir.ui.view">
        <field name="name">sfya.bank.opening.balance.wizard.form</field>
        <field name="model">sfya.bank.opening.balance.wizard</field>
        <field name="arch" type="xml">
            <form string="Set Bank/Cash Opening Balance">
                <sheet>
                    <group>
                        <field name="journal_id"/>
                        <field name="amount"/>
                        <field name="currency_id" invisible="1"/>
                        <field name="date"/>
                        <field name="description"/>
                        <field name="opening_journal_id"/>
                        <field name="is_admin" invisible="1"/>
                        <field name="force" invisible="not is_admin"/>
                    </group>
                </sheet>
                <footer>
                    <button name="action_create_move" type="object"
                            string="Create Opening Balance" class="btn-primary"/>
                    <button string="Cancel" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>

    <record id="action_sfya_bank_opening_balance_wizard" model="ir.actions.act_window">
        <field name="name">Set Opening Balance</field>
        <field name="res_model">sfya.bank.opening.balance.wizard</field>
        <field name="view_mode">form</field>
        <field name="target">new</field>
    </record>
</odoo>
```

- [ ] **Step 3: Add Set Opening Balance button to journal form**

`addons/sfya_bank_statement/views/account_journal_views.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<odoo>
    <record id="view_account_journal_form_sfya_bank" model="ir.ui.view">
        <field name="name">account.journal.form.sfya.bank.statement</field>
        <field name="model">account.journal</field>
        <field name="inherit_id" ref="account.view_account_journal_form"/>
        <field name="arch" type="xml">
            <xpath expr="//sheet" position="inside">
                <div class="oe_button_box" name="sfya_bank_buttons"
                     invisible="type not in ['bank', 'cash']">
                    <button name="%(sfya_bank_statement.action_sfya_bank_opening_balance_wizard)d"
                            type="action" class="oe_stat_button" icon="fa-bank"
                            context="{'active_id': id, 'active_model': 'account.journal'}">
                        <span>Set Opening Balance</span>
                    </button>
                </div>
            </xpath>
        </field>
    </record>
</odoo>
```

Note: Task 3 will add the Print Statement button into the same `oe_button_box` via a second xpath. For now, just the one button.

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_bank_statement/wizards/bank_opening_balance_wizard.py \
        addons/sfya_bank_statement/wizards/bank_opening_balance_wizard_views.xml \
        addons/sfya_bank_statement/views/account_journal_views.xml
git commit -m "feat(bank_statement): opening balance wizard + journal form button"
```

Still do NOT push — wait until Task 3.

---

## Task 3: Statement wizard + report + second journal button + install

**Files:**
- Create: `addons/sfya_bank_statement/wizards/bank_statement_wizard.py`
- Create: `addons/sfya_bank_statement/wizards/bank_statement_wizard_views.xml`
- Create: `addons/sfya_bank_statement/reports/bank_statement_report.py`
- Create: `addons/sfya_bank_statement/reports/bank_statement_report_action.xml`
- Create: `addons/sfya_bank_statement/reports/bank_statement_report.xml`
- Modify: `addons/sfya_bank_statement/views/account_journal_views.xml` (add second button)

- [ ] **Step 1: Write statement wizard model**

`addons/sfya_bank_statement/wizards/bank_statement_wizard.py`:
```python
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class BankStatementWizard(models.TransientModel):
    _name = 'sfya.bank.statement.wizard'
    _description = 'Bank/Cash Statement Wizard'

    journal_id = fields.Many2one(
        'account.journal', required=True,
        domain="[('type', 'in', ['bank', 'cash'])]",
        default=lambda self: self.env.context.get('active_id'),
    )
    date_from = fields.Date(
        required=True,
        default=lambda self: fields.Date.today() - timedelta(days=180),
    )
    date_to = fields.Date(required=True, default=fields.Date.today)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for w in self:
            if w.date_from > w.date_to:
                raise UserError(_('Date From must be before Date To.'))

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            'sfya_bank_statement.action_report_bank_statement'
        ).report_action(self, config=False)

    def action_view_html(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/report/html/sfya_bank_statement.report_bank_statement/'
                f'{self.id}'
            ),
            'target': 'new',
        }
```

- [ ] **Step 2: Write statement wizard view + action**

`addons/sfya_bank_statement/wizards/bank_statement_wizard_views.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<odoo>
    <record id="view_sfya_bank_statement_wizard_form" model="ir.ui.view">
        <field name="name">sfya.bank.statement.wizard.form</field>
        <field name="model">sfya.bank.statement.wizard</field>
        <field name="arch" type="xml">
            <form string="Print Bank/Cash Statement">
                <sheet>
                    <group>
                        <field name="journal_id"/>
                        <field name="date_from"/>
                        <field name="date_to"/>
                    </group>
                </sheet>
                <footer>
                    <button name="action_print_pdf" type="object"
                            string="Print PDF" class="btn-primary"/>
                    <button name="action_view_html" type="object"
                            string="View HTML" class="btn-secondary"/>
                    <button string="Cancel" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>

    <record id="action_sfya_bank_statement_wizard" model="ir.actions.act_window">
        <field name="name">Print Statement</field>
        <field name="res_model">sfya.bank.statement.wizard</field>
        <field name="view_mode">form</field>
        <field name="target">new</field>
    </record>
</odoo>
```

- [ ] **Step 3: Write report Python (AbstractModel + data builder)**

`addons/sfya_bank_statement/reports/bank_statement_report.py`:
```python
from odoo import api, models


class ReportBankStatement(models.AbstractModel):
    _name = 'report.sfya_bank_statement.report_bank_statement'
    _description = 'Bank Statement Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env['sfya.bank.statement.wizard'].browse(docids)
        lines_by_wizard = {}
        opening_by_wizard = {}
        closing_by_wizard = {}
        AML = self.env['account.move.line']
        for w in wizards:
            acct = w.journal_id.default_account_id
            if not acct:
                lines_by_wizard[w.id] = []
                opening_by_wizard[w.id] = 0.0
                closing_by_wizard[w.id] = 0.0
                continue
            base_domain = [
                ('account_id', '=', acct.id),
                ('parent_state', '=', 'posted'),
            ]
            prior = AML.search(base_domain + [('date', '<', w.date_from)])
            opening = sum(l.debit - l.credit for l in prior)
            in_range = AML.search(
                base_domain + [
                    ('date', '>=', w.date_from),
                    ('date', '<=', w.date_to),
                ],
                order='date asc, id asc',
            )
            running = opening
            line_dicts = []
            for line in in_range:
                running += line.debit - line.credit
                line_dicts.append({
                    'date': line.date,
                    'ref': line.move_id.ref or line.move_id.name or '',
                    'partner_name': line.partner_id.name or '',
                    'label': line.name or '',
                    'debit': line.debit,
                    'credit': line.credit,
                    'running_balance': running,
                })
            lines_by_wizard[w.id] = line_dicts
            opening_by_wizard[w.id] = opening
            closing_by_wizard[w.id] = running
        return {
            'doc_ids': docids,
            'doc_model': 'sfya.bank.statement.wizard',
            'docs': wizards,
            'company': self.env.company,
            'lines_by_wizard': lines_by_wizard,
            'opening_by_wizard': opening_by_wizard,
            'closing_by_wizard': closing_by_wizard,
        }
```

- [ ] **Step 4: Write report action XML**

`addons/sfya_bank_statement/reports/bank_statement_report_action.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<odoo>
    <record id="action_report_bank_statement" model="ir.actions.report">
        <field name="name">Bank Statement</field>
        <field name="model">sfya.bank.statement.wizard</field>
        <field name="report_type">qweb-pdf</field>
        <field name="report_name">sfya_bank_statement.report_bank_statement</field>
        <field name="report_file">sfya_bank_statement.report_bank_statement</field>
        <field name="binding_model_id" eval="False"/>
        <field name="print_report_name">'Bank Statement - %s' % (object.journal_id.name or '')</field>
    </record>
</odoo>
```

- [ ] **Step 5: Write QWeb template**

`addons/sfya_bank_statement/reports/bank_statement_report.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<odoo>
    <template id="report_bank_statement">
        <t t-call="web.html_container">
            <t t-foreach="docs" t-as="w">
                <t t-call="web.external_layout">
                    <div class="page o_sfya_statement">
                        <h2>
                            <span>Bank Statement — </span>
                            <span t-esc="w.journal_id.name"/>
                        </h2>
                        <div>
                            <strong>Period: </strong>
                            <span t-esc="w.date_from"/> → <span t-esc="w.date_to"/>
                        </div>
                        <div>
                            <strong>Account: </strong>
                            <span t-esc="w.journal_id.default_account_id.code"/>
                            <span> </span>
                            <span t-esc="w.journal_id.default_account_id.name"/>
                        </div>
                        <table class="table table-sm mt-3">
                            <thead>
                                <tr>
                                    <th>Date</th>
                                    <th>Ref</th>
                                    <th>Partner</th>
                                    <th>Label</th>
                                    <th class="text-end">Debit</th>
                                    <th class="text-end">Credit</th>
                                    <th class="text-end">Balance</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr class="opening-row">
                                    <td colspan="6"><strong>Opening Balance</strong></td>
                                    <td class="text-end">
                                        <strong t-esc="opening_by_wizard[w.id]"
                                                t-options="{'widget': 'monetary', 'display_currency': company.currency_id}"/>
                                    </td>
                                </tr>
                                <tr t-foreach="lines_by_wizard[w.id]" t-as="l">
                                    <td><span t-esc="l['date']"/></td>
                                    <td><span t-esc="l['ref']"/></td>
                                    <td><span t-esc="l['partner_name']"/></td>
                                    <td><span t-esc="l['label']"/></td>
                                    <td class="text-end">
                                        <span t-esc="l['debit']"
                                              t-options="{'widget': 'monetary', 'display_currency': company.currency_id}"/>
                                    </td>
                                    <td class="text-end">
                                        <span t-esc="l['credit']"
                                              t-options="{'widget': 'monetary', 'display_currency': company.currency_id}"/>
                                    </td>
                                    <td class="text-end">
                                        <span t-esc="l['running_balance']"
                                              t-options="{'widget': 'monetary', 'display_currency': company.currency_id}"/>
                                    </td>
                                </tr>
                            </tbody>
                            <tfoot>
                                <tr class="closing-row">
                                    <td colspan="6"><strong>Closing Balance</strong></td>
                                    <td class="text-end">
                                        <strong t-esc="closing_by_wizard[w.id]"
                                                t-options="{'widget': 'monetary', 'display_currency': company.currency_id}"/>
                                    </td>
                                </tr>
                            </tfoot>
                        </table>
                    </div>
                </t>
            </t>
        </t>
    </template>
</odoo>
```

- [ ] **Step 6: Add Print Statement button to journal form**

Open `addons/sfya_bank_statement/views/account_journal_views.xml` from Task 2. Find the existing single `<button>` inside `<div class="oe_button_box">`. Add a second button right after it. Replace the whole `<div>` block with:

```xml
                <div class="oe_button_box" name="sfya_bank_buttons"
                     invisible="type not in ['bank', 'cash']">
                    <button name="%(sfya_bank_statement.action_sfya_bank_opening_balance_wizard)d"
                            type="action" class="oe_stat_button" icon="fa-bank"
                            context="{'active_id': id, 'active_model': 'account.journal'}">
                        <span>Set Opening Balance</span>
                    </button>
                    <button name="%(sfya_bank_statement.action_sfya_bank_statement_wizard)d"
                            type="action" class="oe_stat_button" icon="fa-file-text-o"
                            context="{'active_id': id, 'active_model': 'account.journal'}">
                        <span>Print Statement</span>
                    </button>
                </div>
```

- [ ] **Step 7: Commit + push**

```bash
git add addons/sfya_bank_statement/wizards/bank_statement_wizard.py \
        addons/sfya_bank_statement/wizards/bank_statement_wizard_views.xml \
        addons/sfya_bank_statement/reports/bank_statement_report.py \
        addons/sfya_bank_statement/reports/bank_statement_report_action.xml \
        addons/sfya_bank_statement/reports/bank_statement_report.xml \
        addons/sfya_bank_statement/views/account_journal_views.xml
git commit -m "feat(bank_statement): statement wizard + PDF report + print button"
git push origin main
```

This push includes Task 1 + Task 2 + Task 3 commits together — first deploy of the addon.

- [ ] **Step 8: Wait for CI**

```bash
gh run list --branch main --limit 3 --json conclusion,workflowName,headSha,status
```
Wait until both `Lint` and `Deploy` succeed on the HEAD SHA from Step 7.

- [ ] **Step 9: Install module on VPS + clear assets**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
env['ir.module.module'].update_list()
env.cr.commit()
mod = env['ir.module.module'].search([('name', '=', 'sfya_bank_statement')])
print('pre  state:', mod.state, 'manifest:', mod.latest_version)
mod.button_immediate_install()
env.cr.commit()
print('post state:', mod.state, 'installed:', mod.installed_version)
n = env['ir.attachment'].search([('url', '=like', '/web/assets/%')]).unlink()
env.cr.commit()
print('cleared assets')
EOF" 2>&1 | tail -8
```
Expected: `post state: installed installed: 18.0.1.0.0`.

If install fails with view xpath error on `//sheet`, the inherited journal form may not have a `<sheet>` at root. Fallback: change the xpath in `views/account_journal_views.xml` to `//div[@name='journal_settings_container']` or `//field[@name='name']` `position="before"`. Test by re-trying install.

- [ ] **Step 10: Smoke — set opening balance via shell (proxy for UI)**

Pick a real bank journal (BANK 3 = id 12). Verify the wizard's `action_create_move` works end-to-end.

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
journal = env['account.journal'].browse(12)
gen = env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', env.company.id)], limit=1)
w = env['sfya.bank.opening.balance.wizard'].create({
    'journal_id': journal.id,
    'amount': 12345.0,
    'date': '2026-06-01',
    'description': 'smoke OB',
    'opening_journal_id': gen.id,
})
res = w.action_create_move()
print('result:', res.get('params', {}).get('message'))
move = env['account.move'].search([('ref', '=', f'BANK-OPENING-BAL-{journal.id}'), ('state', '=', 'posted')], limit=1)
print('NAME', move.name, 'DATE', move.date, 'JOURNAL', move.journal_id.name)
for line in move.line_ids:
    print('  line:', line.account_id.code, line.account_id.name, 'D', line.debit, 'C', line.credit)
EOF" 2>&1 | tail -10
```
Expected: 2 lines — one debit Rs 12345 on BANK 3's account (e.g. 1126007), one credit Rs 12345 on equity account (3999).

- [ ] **Step 11: Smoke — block duplicate without override**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
from odoo.exceptions import UserError
journal = env['account.journal'].browse(12)
gen = env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', env.company.id)], limit=1)
w = env['sfya.bank.opening.balance.wizard'].create({
    'journal_id': journal.id,
    'amount': 99.0,
    'date': '2026-06-02',
    'description': 'smoke dup block',
    'opening_journal_id': gen.id,
})
try:
    w.action_create_move()
    print('FAIL: duplicate accepted')
except UserError as e:
    print('OK rejected:', e.args[0] if e.args else e)
EOF" 2>&1 | tail -5
```
Expected: `OK rejected: Opening balance already posted for BANK 3 (move ...). Tick Override...`

- [ ] **Step 12: Smoke — admin override succeeds**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
journal = env['account.journal'].browse(12)
gen = env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', env.company.id)], limit=1)
w = env['sfya.bank.opening.balance.wizard'].create({
    'journal_id': journal.id,
    'amount': 100.0,
    'date': '2026-06-03',
    'description': 'smoke admin override',
    'opening_journal_id': gen.id,
    'force': True,
})
res = w.action_create_move()
print('result:', res.get('params', {}).get('message'))
EOF" 2>&1 | tail -3
```
Expected: success notification message.

- [ ] **Step 13: Smoke — non-admin override blocked (server-side)**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
from odoo.exceptions import UserError
# Find a non-admin user; create one if none exists
nonadmin = env['res.users'].search([('groups_id', 'not in', env.ref('base.group_system').id), ('share', '=', False)], limit=1)
if not nonadmin:
    print('SKIP: no non-admin internal user to test with')
else:
    print('using user:', nonadmin.login)
    env2 = env(user=nonadmin)
    journal = env2['account.journal'].browse(12)
    gen = env2['account.journal'].search([('type', '=', 'general'), ('company_id', '=', env2.company.id)], limit=1)
    w = env2['sfya.bank.opening.balance.wizard'].create({
        'journal_id': journal.id,
        'amount': 1.0,
        'date': '2026-06-04',
        'description': 'smoke nonadmin force',
        'opening_journal_id': gen.id,
        'force': True,
    })
    try:
        w.action_create_move()
        print('FAIL: non-admin override accepted')
    except UserError as e:
        print('OK rejected:', e.args[0] if e.args else e)
EOF" 2>&1 | tail -5
```
Expected: `OK rejected: Only administrators can override an existing opening balance.` Or `SKIP: no non-admin internal user`.

- [ ] **Step 14: Smoke — statement data builder**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
w = env['sfya.bank.statement.wizard'].create({
    'journal_id': 12,
    'date_from': '2026-01-01',
    'date_to': '2026-12-31',
})
vals = env['report.sfya_bank_statement.report_bank_statement']._get_report_values([w.id])
print('opening:', vals['opening_by_wizard'][w.id])
print('closing:', vals['closing_by_wizard'][w.id])
print('lines:', len(vals['lines_by_wizard'][w.id]))
for l in vals['lines_by_wizard'][w.id][:5]:
    print(' ', l['date'], l['ref'], 'D', l['debit'], 'C', l['credit'], 'BAL', l['running_balance'])
EOF" 2>&1 | tail -15
```
Expected: opening = 0 (no activity before 2026-01-01), closing = sum of (debit-credit) across all lines including the 3 OB JEs above (12345 + 100 + any existing activity), reasonable line list. Math sanity: opening + sum(debits) - sum(credits) within range == closing.

- [ ] **Step 15: Smoke — PDF render via HTML URL**

Skip browser, render HTML output via shell using report service:
```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
w = env['sfya.bank.statement.wizard'].create({
    'journal_id': 12,
    'date_from': '2026-01-01',
    'date_to': '2026-12-31',
})
html = env['ir.actions.report']._render_qweb_html('sfya_bank_statement.report_bank_statement', [w.id])
print('html length:', len(html[0]))
print('contains BANK 3:', b'BANK 3' in html[0])
print('contains Opening:', b'Opening Balance' in html[0])
print('contains Closing:', b'Closing Balance' in html[0])
EOF" 2>&1 | tail -8
```
Expected: html length > 0, all three booleans True.

- [ ] **Step 16: Cleanup smoke moves**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
moves = env['account.move'].search([('ref', '=', 'BANK-OPENING-BAL-12'), ('state', '=', 'posted')])
print('cleaning', moves.mapped('name'))
moves.button_draft()
moves.unlink()
env.cr.commit()
print('done')
EOF" 2>&1 | tail -3
```

---

## Task 4: Final acceptance + browser smokes deferred to user

**Files:** none — verification only.

- [ ] **Step 1: Walk acceptance matrix**

| Spec acceptance item | How verified |
|---|---|
| Module installs cleanly on VPS, version 18.0.1.0.0 | Task 3 Step 9 output |
| Bank/cash journal form shows two SFYA buttons | DEFERRED — user opens Invoicing → Configuration → Journals → Meezan bank → buttons visible |
| Setting opening balance on Meezan posts expected balanced JE | Task 3 Step 10 (via shell on BANK 3); user does Meezan via UI |
| Statement PDF matches manual math | Task 3 Step 14 (data) + Step 15 (render) |
| Non-admin cannot override existing opening balance | Task 3 Step 13 |
| Admin can override | Task 3 Step 12 |
| Layout visually consistent with customer statement | DEFERRED — user prints statement, compares to customer statement PDF |

- [ ] **Step 2: Compose deferred-to-user list**

Produce a copyable handoff block for the user covering:
1. Hard refresh POS / Odoo (Cmd+Shift+R)
2. For each bank (Meezan, HMB, BANK 3) and each cash account (Shop Cash): Configuration → Journals → open → **Set Opening Balance** button → enter amount + date → Create
3. Verify: Reporting → ... → or Configuration → Journals → open → **Print Statement** → date range → PDF shows the OB
4. Compare PDF layout to a customer statement PDF — flag any visual gap

Plan complete.
