# Bank Statement Addon — Design

**Status:** Draft 2026-06-17
**Addon:** `sfya_bank_statement` (new)
**Depends on:** `account`, `sfya_customer_statement` (for shared `sfya_opening_balance_account_id` field on res.company)

---

## Goal

Mirror the existing customer-statement workflow for bank/cash journals: any non-technical user opens a journal's form (or runs a menu), clicks **Set Opening Balance**, fills amount + date, JE posts. Same user clicks **Print Statement**, picks date range, gets a PDF identical in layout to the customer statement — but listing every line on the bank's GL account with running balance.

## Motivation

Cashier setup needs each bank/cash account to start at a known opening balance so Odoo's running balance matches the real bank app. Reusing the customer-statement pattern keeps the UX consistent — same fields, same look, same equity counter-account (3999 Opening Balance Equity).

## Scope

**In scope:**
- New addon `sfya_bank_statement` with two TransientModel wizards + one PDF report.
- Buttons on `account.journal` form (visible only for journal `type in ('bank', 'cash')`): **Set Opening Balance**, **Print Statement**.
- Optional menu entry under Reporting → Bank Statements for direct access from anywhere.
- Opening balance JE: debit journal's `default_account_id`, credit `res.company.sfya_opening_balance_account_id`, ref `BANK-OPENING-BAL-<journal_id>`.
- Per-GL-account statement: data filtered by `account.move.line.account_id == journal.default_account_id` (not `journal_id`), so opening JEs posted via General journal still appear.
- Override checkbox on opening wizard gated to `base.group_system` (Administrator only).
- Statement PDF mirrors customer statement layout (header, opening row, lines table, closing row, footer, same CSS).

**Out of scope:**
- Multi-currency statements (SFYA is single currency PKR).
- Reconciliation widget changes (separate concern).
- Bank import flow (CSV/CAMT) — out of scope; use Odoo built-in if needed later.
- Per-line "matched" indicator.
- Aging analysis on bank lines (not a meaningful concept for cash accounts).

## Architecture

### Files (all new, under `addons/sfya_bank_statement/`)

| Path | Purpose |
|---|---|
| `__manifest__.py` | Depends on `account`, `sfya_customer_statement`; data lists views + wizards + reports + security |
| `__init__.py` | Imports `wizards`, `reports` |
| `security/ir.model.access.csv` | RW access to both wizard models for `base.group_user` |
| `wizards/__init__.py` | Imports both wizard modules |
| `wizards/bank_opening_balance_wizard.py` | `sfya.bank.opening.balance.wizard` TransientModel |
| `wizards/bank_opening_balance_wizard_views.xml` | Form view + act_window |
| `wizards/bank_statement_wizard.py` | `sfya.bank.statement.wizard` TransientModel |
| `wizards/bank_statement_wizard_views.xml` | Form view + act_window |
| `reports/__init__.py` | Imports `bank_statement_report` |
| `reports/bank_statement_report.py` | `AbstractModel` `report.sfya_bank_statement.report_bank_statement` with `_get_report_values` |
| `reports/bank_statement_report_action.xml` | `ir.actions.report` declaration |
| `reports/bank_statement_report.xml` | QWeb template, layout mirrors customer statement |
| `views/account_journal_views.xml` | Inherits journal form; adds 2 buttons gated by `type in ('bank','cash')` |

No model field additions to `account.journal` or `res.company` — equity field already lives on `res.company` from customer statement addon.

### Opening balance wizard

```python
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
    is_admin = fields.Boolean(
        compute='_compute_is_admin',
        help='Used to hide Override checkbox for non-admins.',
    )

    def _compute_is_admin(self):
        for w in self:
            w.is_admin = self.env.user.has_group('base.group_system')
```

`force` field rendered with `invisible="not is_admin"` in form view → non-admin can't see/check it.

`action_create_move()`:
1. Resolve `account = journal_id.default_account_id`; UserError if missing.
2. Resolve `equity = company.sfya_opening_balance_account_id`; UserError if missing.
3. If `not force`: search for posted move with `ref = 'BANK-OPENING-BAL-{journal_id}'`; if found, UserError naming the existing move.
4. If `not force and not is_admin and existing`: same error — non-admin path covered.
5. If `force and not is_admin`: UserError "Only administrators can override." (defense in depth — view hides it, but block at server too.)
6. Sign: positive → debit bank, credit equity. Negative → credit bank, debit equity.
7. Create + post account.move with `move_type='entry'`, `ref='BANK-OPENING-BAL-{journal.id}'`, two lines.
8. Return success notification.

### Statement wizard

```python
class BankStatementWizard(models.TransientModel):
    _name = 'sfya.bank.statement.wizard'
    _description = 'Bank/Cash Statement Wizard'

    journal_id = fields.Many2one(
        'account.journal', required=True,
        domain="[('type', 'in', ['bank', 'cash'])]",
        default=lambda self: self.env.context.get('active_id'),
    )
    date_from = fields.Date(required=True,
        default=lambda self: fields.Date.today() - timedelta(days=180))
    date_to = fields.Date(required=True, default=fields.Date.today)

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            'sfya_bank_statement.action_report_bank_statement'
        ).report_action(self, config=False)

    def action_view_html(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/report/html/sfya_bank_statement.report_bank_statement/{self.id}',
            'target': 'new',
        }
```

### Report data builder

`_get_report_values(docids, data=None)` returns dict per wizard:

```python
{
    'doc_ids': docids,
    'doc_model': 'sfya.bank.statement.wizard',
    'docs': wizards,
    'company': self.env.company,
    'lines_by_wizard': {wizard.id: [...]},  # list of dicts per line
    'opening_by_wizard': {wizard.id: opening_balance_float},
    'closing_by_wizard': {wizard.id: closing_balance_float},
}
```

Each line dict: `{date, ref, partner_name, label, debit, credit, running_balance}`.

Query:
```python
acct = wizard.journal_id.default_account_id
opening = sum debit-credit for posted move.lines on acct where date < date_from
lines = move.lines on acct where date_from <= date <= date_to, posted, order by date asc, id asc
running = opening
for line in lines:
    running += line.debit - line.credit
    yield {...running...}
closing = running
```

### Report template structure (mirror customer statement)

```xml
<t t-call="web.html_container">
    <t t-foreach="docs" t-as="w">
        <t t-call="web.external_layout">
            <div class="page o_sfya_statement">
                <h2>Bank Statement — <t t-esc="w.journal_id.name"/></h2>
                <div>Period: <t t-esc="w.date_from"/> → <t t-esc="w.date_to"/></div>
                <div>Account: <t t-esc="w.journal_id.default_account_id.code"/> <t t-esc="w.journal_id.default_account_id.name"/></div>
                <table class="table table-sm">
                    <thead>
                        <tr><th>Date</th><th>Ref</th><th>Partner</th><th>Label</th>
                            <th class="text-end">Debit</th><th class="text-end">Credit</th>
                            <th class="text-end">Balance</th></tr>
                    </thead>
                    <tbody>
                        <tr class="opening"><td colspan="6"><b>Opening Balance</b></td>
                            <td class="text-end"><b><t t-esc="opening_by_wizard[w.id]"/></b></td></tr>
                        <tr t-foreach="lines_by_wizard[w.id]" t-as="l">
                            <td><t t-esc="l['date']"/></td>
                            <td><t t-esc="l['ref']"/></td>
                            <td><t t-esc="l['partner_name']"/></td>
                            <td><t t-esc="l['label']"/></td>
                            <td class="text-end"><t t-esc="l['debit']"/></td>
                            <td class="text-end"><t t-esc="l['credit']"/></td>
                            <td class="text-end"><t t-esc="l['running_balance']"/></td>
                        </tr>
                    </tbody>
                    <tfoot>
                        <tr><td colspan="6"><b>Closing Balance</b></td>
                            <td class="text-end"><b><t t-esc="closing_by_wizard[w.id]"/></b></td></tr>
                    </tfoot>
                </table>
            </div>
        </t>
    </t>
</t>
```

Reuse SFYA statement CSS classes (`o_sfya_statement`) — customer addon assets already load them, but this addon needs its own asset entry to load them in report context. Add to manifest:
```python
'assets': {
    'web.report_assets_common': [
        'sfya_customer_statement/static/src/report/statement.css',
    ],
},
```
(Reuses customer statement's existing CSS file — verify path during impl.)

### Journal form buttons

`views/account_journal_views.xml`:
```xml
<record id="view_account_journal_form_sfya_bank" model="ir.ui.view">
    <field name="name">account.journal.form.sfya.bank.statement</field>
    <field name="model">account.journal</field>
    <field name="inherit_id" ref="account.view_account_journal_form"/>
    <field name="arch" type="xml">
        <xpath expr="//sheet" position="inside">
            <div class="oe_button_box" invisible="type not in ['bank', 'cash']">
                <button name="%(action_sfya_bank_opening_balance_wizard)d"
                        type="action" class="oe_stat_button" icon="fa-bank"
                        context="{'active_id': id, 'active_model': 'account.journal'}">
                    <span>Set Opening Balance</span>
                </button>
                <button name="%(action_sfya_bank_statement_wizard)d"
                        type="action" class="oe_stat_button" icon="fa-file-text-o"
                        context="{'active_id': id, 'active_model': 'account.journal'}">
                    <span>Print Statement</span>
                </button>
            </div>
        </xpath>
    </field>
</record>
```

(Exact xpath / position may need adjustment — confirm against actual `account.view_account_journal_form` arch during implementation.)

## Validation matrix

| Condition | Behavior |
|---|---|
| Amount = 0 | UserError "Amount must be non-zero." |
| Journal type ≠ bank/cash | Filtered by domain — won't appear |
| Journal has no default_account_id | UserError "Journal X has no default account." |
| Company has no `sfya_opening_balance_account_id` | UserError directing to Settings → Companies |
| OB already posted + force unchecked | UserError "Opening balance already posted (move N). Tick Override to add another (Admin only)." |
| Non-admin ticks force (server check) | UserError "Only administrators can override." |
| date_from > date_to in statement wizard | UserError "Date From must be before Date To." |
| No lines in range | Report still renders: opening row + closing row, empty table body |

## Testing

Verification-only via odoo shell + browser smoke.

| Check | How |
|---|---|
| Wizard opens from journal form | Navigate to Meezan bank journal → button visible → click → modal opens with journal pre-filled |
| Buttons hidden for non-bank/cash journals | Open a Sales journal → buttons absent |
| Opening balance posts correctly | Set Meezan +10000 on 2026-01-01 → JE created, debit 1126001 +10000, credit 3999 +10000 |
| Override blocked for non-admin | Login as cashier user, open wizard for journal with existing OB → no Override checkbox visible; if forced via debug → server rejects |
| Override allowed for admin | Login as admin, tick Override → second OB JE posts |
| Statement PDF renders | Print Statement on Meezan → PDF shows opening, lines, closing, balance math correct |
| Statement HTML preview works | Click View HTML on wizard → opens in new tab |
| Empty range | Date range with no activity → opening = closing, empty body |
| Per-GL-account scope catches OB | Statement on Meezan includes the OB JE (which was posted via General journal) |

## Risks / Tradeoffs

- **Per-GL-account scope** means if two journals share a default account (unusual but possible), their statements would show identical data. SFYA banks each have unique accounts — non-issue here.
- **CSS reuse from customer statement** creates a soft dependency: deleting `sfya_customer_statement` would break this report's styling. Acceptable since both addons are SFYA-owned.
- **Override gating** is server + UI both. UI hide is convenience; server check is the real lock. Defense in depth.
- **Opening balance JE posted via General journal** means it shows under the General journal's list view too. Cashier might find this confusing. Mitigation: clear `ref` field `BANK-OPENING-BAL-<id>` makes intent obvious; statement report itself shows it under the bank account properly.

## Acceptance

Plan complete when:
- Module installs cleanly on VPS, version 18.0.1.0.0.
- Bank/cash journal form shows two SFYA buttons.
- Setting opening balance on Meezan posts the expected balanced JE.
- Statement PDF for Meezan over a date range matches manual math (opening + sum lines = closing).
- Non-admin user cannot override existing opening balance; admin can.
- Layout visually consistent with customer statement (same fonts, table style, borders).
