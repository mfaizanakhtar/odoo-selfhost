# POS Salary Payments (Advance + Pay Salary) — Design Spec

## Overview

Add two new POS cash-movement actions, "Salary Advance" and "Pay Salary", letting any cashier record money paid to an employee — either as an advance against future salary, or as an actual salary payment (which can partially or fully offset a prior advance). Complements the existing Collect Payment / Pay Out / Partner Drawing / Transfer Funds actions in the same addon. Employee salary is a real business expense (unlike Partner Drawing, which is an equity distribution) and must land in the P&L via the existing `4211001 Salary and Wages` expense account.

## Scope

Extend `sfya_pos_cash_movement` addon. No new addon, no new models — new fields on `res.company`, `pos.config`, `account.payment`, `account.move`. Adds `hr` to the addon's `depends` (already installed on this instance; used only to source the Employee picker from `hr.employee`).

## Access

Any cashier — same access level as Collect/Pay Out/Transfer Funds. Not restricted to shareholders (unlike Partner Drawing).

## Data Model

### `res.company`

```python
sfya_salary_expense_account_id = fields.Many2one(
    'account.account',
    string='Salary Expense Account',
    help='Expense account debited when salary is paid to an employee via POS.',
    domain="[('account_type', '=', 'expense')]",
)
sfya_employee_advance_account_id = fields.Many2one(
    'account.account',
    string='Employee Advance Account',
    help='Asset account debited when an employee is given a salary advance via '
         'POS, and credited when that advance is later offset against a salary '
         'payment.',
    domain="[('account_type', '=', 'asset_current')]",
)
sfya_salary_journal_id = fields.Many2one(
    'account.journal',
    string='Salary Offset Journal',
    help='Miscellaneous-operations journal used to post the cash-free portion '
         'of a POS salary payment that offsets a prior advance. Dedicated '
         '(not shared with Partner Transfer) so its move-name sequence is '
         'specific to salary entries.',
    domain="[('type', '=', 'general')]",
)
```

Auto-created/linked via `post_init_hook`, extending the existing search-by-code-then-create pattern:

- `sfya_salary_expense_account_id`: search `account.account` by code `4211001` first (this account already exists on this instance as "Salary and Wages" — the search will find and link it, not create a duplicate). Only creates a new one (code `4211001`, `account_type='expense'`) if truly missing.
- `sfya_employee_advance_account_id`: search by code `1995`; create if missing (`name='Employee Advances'`, `account_type='asset_current'`) — next free code after the existing `1994` Internal Transfers Clearing account.
- `sfya_salary_journal_id`: search `account.journal` by code `SLRY`; create if missing (`name='Salary Offsets'`, `type='general'`) — same rationale as the existing dedicated `PXFR` journal: a shared Misc Operations journal's sequence would mix salary-offset entries with unrelated postings.

### `pos.config`

```python
sfya_salary_expense_account_id = fields.Many2one(
    related='company_id.sfya_salary_expense_account_id', readonly=False,
    string='Salary Expense Account',
)
sfya_employee_advance_account_id = fields.Many2one(
    related='company_id.sfya_employee_advance_account_id', readonly=False,
    string='Employee Advance Account',
)
sfya_salary_journal_id = fields.Many2one(
    related='company_id.sfya_salary_journal_id', readonly=False,
    string='Salary Offset Journal',
)
```

Exposed in `pos_config_views.xml` SFYA Cash Control group, alongside the existing dedicated-resource fields.

### `account.payment`

```python
sfya_salary_kind = fields.Selection(
    [('advance', 'Advance'), ('payment', 'Payment')],
    copy=False,
    help='Set for POS-originated salary legs only. "advance" = money given '
         'ahead of payday (destination is the Employee Advance account). '
         '"payment" = actual salary expense recognized (destination is the '
         'Salary Expense account); amount is the NET cash paid, after any '
         'advance offset. Used to exclude these legs from the generic '
         'Collect/Pay Out/Drawing listings and total them separately for '
         'the till expected-cash adjustment.',
)
sfya_employee_id = fields.Many2one('hr.employee', string='Employee', copy=False)
sfya_salary_gross_amount = fields.Monetary(
    string='Gross Salary Amount', copy=False,
    help='Only set when sfya_salary_kind="payment". Full salary amount for '
         'the period, before any advance offset. Equal to `amount` when no '
         'offset was applied.',
)
sfya_salary_advance_offset = fields.Monetary(
    string='Advance Offset Applied', copy=False,
    help='Only set when sfya_salary_kind="payment". Portion of gross salary '
         'that was cleared against a prior advance instead of paid in cash/bank.',
)
sfya_salary_offset_move_id = fields.Many2one(
    'account.move', string='Salary Offset Entry', copy=False,
    help='The cash-free journal entry (if any) that cleared the advance '
         'offset alongside this payment.',
)
```

`pos_session_id` already exists on this model (reused, not new).

### `account.move`

```python
sfya_is_salary_offset = fields.Boolean(default=False, copy=False)
sfya_salary_offset_employee_id = fields.Many2one('hr.employee', copy=False)
sfya_salary_offset_amount = fields.Monetary(copy=False)
```

`pos_session_id` already exists on this model (reused from the Partner Transfer feature).

## Backend RPC

### `account.payment.sfya_pos_salary_advance(session_id, employee_id, amount, journal_id, memo='', date=None)`

Class method. Validates:
- Session exists and is open
- Employee exists, is active, belongs to session's company
- `amount > 0`
- Journal exists, `type in ('cash', 'bank')`, belongs to session's company
- Company has `sfya_employee_advance_account_id` configured (else `UserError`)

Date handling identical to Partner Drawing: cash journal forces today (ignore passed date); bank journal accepts the passed date if not in the future.

Creates one `account.payment`:

| Field | Value |
|---|---|
| `payment_type` | `outbound` |
| `partner_id` | `employee.work_contact_id.id` |
| `partner_type` | `supplier` |
| `journal_id` | the chosen journal |
| `destination_account_id` | `sfya_employee_advance_account_id` |
| `sfya_salary_kind` | `'advance'` |
| `sfya_employee_id` | `employee.id` |
| `pos_session_id` | `session.id` |

`action_post()`. Returns `{id, name, employee_id, employee_name, amount, memo, journal_id, journal_name, journal_type, direction: 'salary_advance'}`.

### `account.payment.sfya_pos_salary_payment(session_id, employee_id, gross_amount, advance_offset, journal_id, memo='', date=None)`

Class method. Validates:
- Session exists and is open
- Employee exists, is active, belongs to session's company
- `gross_amount > 0`
- `advance_offset >= 0` (defaults to `0` if not passed)
- `advance_offset <= gross_amount + 0.005` (else `UserError`: "Advance offset cannot exceed gross salary amount.") — the `0.005` tolerance matches the existing float-rounding tolerance convention already used in `_sfya_resolve_partner_type`, so a cashier offsetting the exact full balance isn't rejected by floating-point noise. Clamp `advance_offset = min(advance_offset, gross_amount)` after the check passes.
- Journal exists, `type in ('cash', 'bank')`, belongs to session's company
- Company has `sfya_salary_expense_account_id` configured (else `UserError`)
- If `advance_offset > 0`: company has both `sfya_employee_advance_account_id` and `sfya_salary_journal_id` configured (else `UserError`)
- If `advance_offset > 0`: compute the employee's outstanding advance balance (see below) and require `advance_offset <= outstanding_balance + 0.005` (else `UserError`: "Advance offset exceeds this employee's outstanding advance balance of {balance}."), then clamp `advance_offset = min(advance_offset, outstanding_balance)` after the check passes

**Outstanding advance balance** (company-wide, not session-scoped — an advance can be cleared in a later session):
```python
advances_given = sum(account.payment.search([
    ('sfya_employee_id', '=', employee.id),
    ('sfya_salary_kind', '=', 'advance'),
    ('state', 'in', ['paid', 'in_process']),
    ('company_id', '=', session.company_id.id),
]).mapped('amount'))
offsets_cleared = sum(account.move.search([
    ('sfya_salary_offset_employee_id', '=', employee.id),
    ('sfya_is_salary_offset', '=', True),
    ('state', '=', 'posted'),
    ('company_id', '=', session.company_id.id),
]).mapped('sfya_salary_offset_amount'))
outstanding_balance = advances_given - offsets_cleared
```

Date handling: same cash/bank rule as other actions in this module, keyed off the chosen journal's type.

`net_cash = gross_amount - advance_offset`.

**If `net_cash > 0`**, create one `account.payment`:

| Field | Value |
|---|---|
| `payment_type` | `outbound` |
| `partner_id` | `employee.work_contact_id.id` |
| `partner_type` | `supplier` |
| `amount` | `net_cash` |
| `journal_id` | the chosen journal |
| `destination_account_id` | `sfya_salary_expense_account_id` |
| `sfya_salary_kind` | `'payment'` |
| `sfya_employee_id` | `employee.id` |
| `sfya_salary_gross_amount` | `gross_amount` |
| `sfya_salary_advance_offset` | `advance_offset` |
| `pos_session_id` | `session.id` |

`action_post()`.

**If `advance_offset > 0`**, create one 2-line `account.move` (same construction pattern as the existing `sfya_pos_partner_transfer`, no journal-liquidity leg — this entry never touches cash/bank):

```python
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
            'account_id': session.company_id.sfya_salary_expense_account_id.id,
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
```

If a payment was also created (`net_cash > 0`), set `payment.sfya_salary_offset_move_id = move.id` to link the two.

**Edge case — full salary covered by advance** (`advance_offset == gross_amount`, so `net_cash == 0`): only the `account.move` is created; no `account.payment` at all (an `account.payment` with `amount = 0` is not created — mirrors the existing `amount > 0` validation convention used everywhere else in this module). The move's `sfya_salary_offset_amount` equals the full gross salary in this case — no separate field needed to record that.

Returns:
```python
{
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
```

### `account.payment.get_sfya_salary_advance_balance(employee_id)`

Class method (`@api.model`), callable from the frontend when an employee is picked in the Pay Salary modal, so the cashier sees the live outstanding balance before entering an offset. Runs the same `outstanding_balance` computation as above, scoped to `self.env.company`. Returns a float (`0.0` if the employee has no advances).

### `pos.session.get_sfya_pos_employees(session_id)`

Class method (`@api.model`), same shape as the existing `get_sfya_allowed_journals`:

```python
session = self.sudo().browse(session_id).exists()
if not session:
    return []
employees = self.env['hr.employee'].sudo().search([
    ('company_id', '=', session.company_id.id),
    ('active', '=', True),
], order='name')
return [{'id': e.id, 'name': e.name} for e in employees]
```

## Cash-Movement Bucketing (`pos_session.py`)

`get_sfya_cash_movements`: exclude salary legs from the existing collects/payouts/drawings scan by adding `('sfya_salary_kind', '=', False)` to that method's payment search domain (same technique already used for `sfya_is_internal_transfer`).

Separately, within the same method, compute (restricted to `journal_id.type == 'cash'`, matching the existing Transfer Funds precedent — only cash is physically counted at session close):

```python
salary_legs = self.env['account.payment'].sudo().search([
    ('pos_session_id', '=', self.id),
    ('state', 'in', ['paid', 'in_process']),
    ('sfya_salary_kind', '!=', False),
    ('journal_id.type', '=', 'cash'),
])
salary_advances_total = sum(p.amount for p in salary_legs if p.sfya_salary_kind == 'advance')
salary_payments_total = sum(p.amount for p in salary_legs if p.sfya_salary_kind == 'payment')
```

Both merged into the returned `cash` dict as `salary_advances_total` / `salary_payments_total`. Note `salary_payments_total` here is already the **net cash** amount (an advance-covered `payment` leg either doesn't exist at all, or its `amount` is already `net_cash` — the offset portion never touched a cash journal, so it's correctly excluded automatically).

`get_closing_control_data` adjustment formula extends to:

```python
adjustment = (
    cash.collects_total - cash.payouts_total - cash.drawings_total
    + cash.transfers_in_total - cash.transfers_out_total
    - cash.salary_advances_total - cash.salary_payments_total
)
```

Both salary buckets are cash leaving the till, same sign convention as `drawings_total`. Bank-journal salary legs stay informational only (visible in the new `get_sfya_salary_payments` listing below, not in the per-bank Collect/Payout/Drawing buckets, and not part of the till adjustment) — consistent with how bank-journal transfers/collects/payouts are already handled.

### New method: `get_sfya_salary_payments(self)`

Returns every salary-related row for this session, both kinds merged and sorted by `create_date asc`, for the closing dialog's "Salary" section:

```python
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

# Full-salary-via-advance case: no payment leg exists, only the offset move.
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
```

## Frontend

### `cash_movement_modal.js`

- `mode` prop's `validate` list extends to `["collect", "payout", "drawing", "transfer", "salary_advance", "salary_payment"]`.
- New state: `employeeId: null`, `employees: []`, `advanceOffset: "0"`, `outstandingAdvance: 0`.
- `onWillStart`: when `props.mode === "salary_advance" || props.mode === "salary_payment"`, also call `pos.session.get_sfya_pos_employees` and populate `state.employees`; default `state.employeeId = employees[0]?.id ?? null`. If `props.mode === "salary_payment"` and a default employee was set, immediately fetch that employee's outstanding balance (same call used by `onEmployeeChange` below).
- New method `async onEmployeeChange(ev)`: reads the selected id from `ev.target.value`, sets `state.employeeId`, and if `props.mode === "salary_payment"`, calls `account.payment.get_sfya_salary_advance_balance` with `{employee_id: state.employeeId}` and stores the result in `state.outstandingAdvance` (reset `state.advanceOffset = "0"` on change).
- `title` adds: `salary_advance` → "Salary Advance", `salary_payment` → "Pay Salary".
- `confirmLabel` adds: `salary_advance` → "Give Advance", `salary_payment` → "Pay Salary".
- `confirmClass` adds: `salary_advance` → `"btn-info"`, `salary_payment` → `"btn-warning"`.
- `isValid` adds two branches (checked before the existing partner-based fallback, same style as the `transfer` branch):
  - `salary_advance`: amount valid, `submitting` false, `state.employeeId` set, `state.journal_id` set.
  - `salary_payment`: amount valid (this is the gross amount), `submitting` false, `state.employeeId` set, `state.journal_id` set, and `parseFloat(state.advanceOffset || 0)` is a finite number `>= 0`, `<= state.outstandingAdvance`, and `<= parseFloat(state.amount)`.
- `confirm()` gets two new early branches (parallel to the existing `transfer` branch, each returning before reaching the partner-dependent code):
  - `salary_advance`: calls `account.payment.sfya_pos_salary_advance` with `{session_id, employee_id: state.employeeId, amount, journal_id: state.journal_id, memo, date?}` (date included only when `selectedJournalIsBank`, same convention as drawing/collect/payout). Pushes result to `pos.sfyaCashMovements`, notification `"Advance of %s given to %s"`, prints slip with `direction: "salary_advance"` if requested, closes.
  - `salary_payment`: calls `account.payment.sfya_pos_salary_payment` with `{session_id, employee_id: state.employeeId, gross_amount: amount, advance_offset: parseFloat(state.advanceOffset || 0), journal_id: state.journal_id, memo, date?}`. Pushes result, notification `"Paid %s salary to %s (net %s after %s advance offset)"` when `advance_offset > 0`, else `"Paid %s salary to %s"`. Prints slip with `direction: "salary_payment"` (forwarding `gross_amount`/`advance_offset`/`net_cash`) if requested, closes.
- `_printSlip` forwards `employee_name`, and for `salary_payment` also `gross_amount`, `advance_offset`, `net_cash` (all defaulted to `""`/`0` when absent).

### `cash_movement_modal.xml`

- Existing Partner field block's guard changes from `t-if="props.mode !== 'transfer'"` to `t-if="props.mode !== 'transfer' and props.mode !== 'salary_advance' and props.mode !== 'salary_payment'"`.
- New block, `t-if="props.mode === 'salary_advance' or props.mode === 'salary_payment'"`, placed alongside the existing Transfer block:
  - Employee `<select>` (`t-on-change="onEmployeeChange"`, options from `state.employees`).
  - When `props.mode === 'salary_payment'`: a line showing `Outstanding Advance: PKR <t t-esc="state.outstandingAdvance"/>`; and, only `t-if="state.outstandingAdvance > 0"`, an "Advance Offset" number input (`t-model="state.advanceOffset"`, `min="0"`, `t-att-max="state.outstandingAdvance"`) plus a computed "Net cash to pay" line (`amount - advanceOffset`, floored at 0 for display).
- The existing Account+Date block's guard (`t-if="props.mode !== 'transfer' and !isPartnerDestination"`) already covers both new modes without modification — `isPartnerDestination` is always `false` outside `payout` mode, so Account+Date renders for `salary_advance`/`salary_payment` exactly as it does for `drawing`.
- `PaymentSlip` template: `Type:` line gains `t-elif="direction === 'salary_advance'"` → "Salary Advance" and `t-elif="direction === 'salary_payment'"` → "Pay Salary". The `Partner:` line's guard changes from `t-if="direction !== 'internal_transfer'"` to also exclude the two new directions; a new line block shows `Employee: <t t-esc="employee_name"/>` for both new directions, and for `salary_payment` additionally shows `Gross: PKR <t t-esc="gross_amount"/>`, `Advance Offset: PKR <t t-esc="advance_offset"/>` (only when `> 0`), `Net Paid: PKR <t t-esc="net_cash"/>`. Bottom signature line gains `t-elif="direction === 'salary_advance' or direction === 'salary_payment'"` → "Received by: ______________".

### `product_screen_buttons.js` / `.xml`

Two new methods/buttons, positioned after Transfer Funds and before Customer Overview:

```js
openSalaryAdvance() {
    this.dialog.add(CashMovementModal, { mode: "salary_advance" });
},
openSalaryPayment() {
    this.dialog.add(CashMovementModal, { mode: "salary_payment" });
},
```

Buttons: "Salary Advance" (`o_cash_movement_salary_advance` class, `fa-clock-o` icon, `text-info`), "Pay Salary" (`o_cash_movement_salary_payment` class, `fa-money` icon, `text-warning`).

### `closing_dialog_patch.js` / `.xml`

- New state: `salaryPayments: []`, `salaryPaymentsOpen: true`, loaded via `get_sfya_salary_payments` in the same `onWillStart` block that already loads partner/internal transfers (own try/catch, same pattern).
- New getter `sfyaSalaryPaymentsTotal`: `this.sfya.salaryPayments.reduce((sum, r) => sum + r.net_cash, 0)` — the actual till/bank cash impact (not the gross total), labeled "Till Impact Total" in the template to avoid confusion with the gross salary figures shown per row.
- New collapsible "Salary" section (same shape as "Internal Transfers"), placed after Internal Transfers, before Banks. Each row shows: Employee, Kind (Advance / Payment badge), Gross, Advance Offset (only if `> 0`), Net Cash, Memo. Outer visibility `t-if` extended to include `sfya.salaryPayments.length`.

## Out of Scope

- No payroll periods/schedules, tax/deduction calculations, payslip documents, or employee self-service — this is purely POS-triggered cash movement + expense recognition, same tier as the existing Collect/Pay Out/Drawing/Transfer actions.
- No `sfya_customer_statement` changes — salary legs use `hr.employee`'s linked partner only for the accounting partner ledger; they are not customer/vendor transactions and won't be routed into that statement's rows (mirrors the Internal Transfer feature's exclusion, verified by the same reasoning: no vendor-bill/customer-credit relationship is involved).
- No enforcement that an employee can only have salary paid once per pay period — the cashier is trusted to not double-pay, same trust level as every other action in this module.

## Files

All paths relative to `addons/sfya_pos_cash_movement/`.

| File | Action | Purpose |
|------|--------|---------|
| `__manifest__.py` | EDIT | Add `'hr'` to `depends`; bump version |
| `models/res_company.py` | EDIT | Add `sfya_salary_expense_account_id`, `sfya_employee_advance_account_id`, `sfya_salary_journal_id` |
| `models/pos_config.py` | EDIT | Add related passthroughs for the three new fields |
| `views/pos_config_views.xml` | EDIT | Expose new fields in SFYA Cash Control group |
| `models/account_payment.py` | EDIT | Add `sfya_salary_kind`, `sfya_employee_id`, `sfya_salary_gross_amount`, `sfya_salary_advance_offset`, `sfya_salary_offset_move_id` fields + `sfya_pos_salary_advance()`, `sfya_pos_salary_payment()`, `get_sfya_salary_advance_balance()` RPCs |
| `models/account_move.py` | EDIT | Add `sfya_is_salary_offset`, `sfya_salary_offset_employee_id`, `sfya_salary_offset_amount` fields |
| `models/pos_session.py` | EDIT | Exclude salary legs from `get_sfya_cash_movements` main scan, add salary totals to `cash` dict, extend `get_closing_control_data` adjustment, add `get_sfya_salary_payments()`, add `get_sfya_pos_employees()` |
| `__init__.py` | EDIT | `post_init_hook`: create/link the two new dedicated accounts + dedicated journal per company |
| `static/src/app/cash_movement_modal.js` | EDIT | `"salary_advance"`/`"salary_payment"` modes: employee state, outstanding-balance fetch, validation, confirm branches, print slip forwarding |
| `static/src/app/cash_movement_modal.xml` | EDIT | Employee-picker UI, advance-offset UI, PaymentSlip branches |
| `static/src/app/product_screen_buttons.js` | EDIT | Add `openSalaryAdvance()`, `openSalaryPayment()` |
| `static/src/app/product_screen_buttons.xml` | EDIT | Add "Salary Advance", "Pay Salary" buttons |
| `static/src/app/closing_dialog_patch.js` | EDIT | Load + expose salary payments |
| `static/src/app/closing_dialog_patch.xml` | EDIT | "Salary" section |

## Constraints

- No new models or database tables
- No new addon — extend `sfya_pos_cash_movement`
- Follow existing code style (OWL components, `useState`, `useService`, `@api.model` RPC methods on the relevant model)
- Reuse the dedicated-resource `post_init_hook` pattern (search-by-code, create-if-missing) rather than searching/guessing among existing accounts — except the expense account, which intentionally links to the pre-existing `4211001 Salary and Wages` account rather than creating a new one
- Currency: PKR hardcoded (matches existing cash movement code)
- Any cashier can perform either salary action — no shareholder restriction
- Outstanding advance balance is computed company-wide, not session-scoped (an advance given in one session can be offset in a later one)
