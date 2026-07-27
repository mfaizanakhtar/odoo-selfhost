# POS Internal Transfer (Cash Till ↔ Bank ↔ Bank) — Design Spec

## Overview

Add a 4th POS cash-movement action, "Transfer Funds", letting a cashier move money between any two of the company's own cash/bank journals — shop cash till to a bank account, or bank account to bank account — with no partner involved. Complements the existing Collect Payment / Pay Out / Partner Drawing actions and the prior Partner Transfer feature (settling a Pay Out via another partner's balance, no cash/bank leg at all — this feature is the reverse: two cash/bank legs, no partner).

## Scope

Extend `sfya_pos_cash_movement` addon. No new addon, no new models — new fields on `res.company`, `pos.config`, `account.payment`.

## Access

Any cashier — same access level as Collect/Pay Out today. Not restricted to shareholders (unlike Partner Drawing).

## Data Model

### `res.company`

```python
sfya_internal_transfer_account_id = fields.Many2one(
    'account.account',
    string='Internal Transfer Clearing Account',
    domain="[('account_type', '=', 'asset_current')]",
)
```

Dedicated clearing account, code `1994`, name "Internal Transfers Clearing", `account_type='asset_current'`. Both legs of a transfer post in the same call and always net to zero on this account. Auto-created via `post_init_hook`, same search-by-code-then-create pattern already used for `sfya_owner_drawing_account_id` (code `3100`) and `sfya_partner_transfer_journal_id` (code `PXFR`).

### `pos.config`

```python
sfya_internal_transfer_account_id = fields.Many2one(
    related='company_id.sfya_internal_transfer_account_id',
    readonly=False,
    string='Internal Transfer Clearing Account',
)
```

Exposed in `pos_config_views.xml` SFYA Cash Control group, alongside the other two dedicated-resource fields.

### `account.payment`

```python
sfya_is_internal_transfer = fields.Boolean(default=False, copy=False)
sfya_transfer_pair_id = fields.Many2one('account.payment', copy=False)
```

`pos_session_id` already exists on this model (reused, not new).

## Backend RPC

### `account.payment.sfya_pos_internal_transfer(session_id, from_journal_id, to_journal_id, amount, memo='', date=None)`

Class method. Validates:
- Session exists and is open
- `from_journal_id != to_journal_id`
- Both journals exist, `type in ('cash', 'bank')`, belong to session's company
- `amount > 0`
- Company has `sfya_internal_transfer_account_id` configured (else `UserError`)

Date handling: if both journals are `cash`, force today (ignore passed date). If either is `bank`, accept the passed date (must not be in the future) — same rule already applied per-journal elsewhere in this module.

Creates two `account.payment` records, no partner (`partner_id=False`):

| | Out leg | In leg |
|---|---|---|
| `payment_type` | `outbound` | `inbound` |
| `journal_id` | `from_journal` | `to_journal` |
| `destination_account_id` | clearing account | clearing account |
| `sfya_is_internal_transfer` | `True` | `True` |
| `pos_session_id` | session.id | session.id |

After create, set `out.sfya_transfer_pair_id = in.id` and `in.sfya_transfer_pair_id = out.id`, then `action_post()` both.

Returns `{out_name, in_name, from_journal_id, from_journal_name, to_journal_id, to_journal_name, amount, memo, direction: 'internal_transfer'}`.

**Implementation-time verification required:** every existing payment method in this module sets a real `partner_id` even when overriding `destination_account_id` (Partner Drawing uses the shareholder as `partner_id`). A blank `partner_id` alongside `destination_account_id` override has not been proven in this codebase's create-and-post path, though it mirrors how Odoo core's own internal-transfer feature behaves. The implementer must test posting locally before deploying. Fallback if it errors: a single 2-line `account.move` (debit destination journal's `default_account_id`, credit source journal's `default_account_id`) — same architecture as the existing Partner Transfer feature — instead of two `account.payment` records.

## Cash-Movement Bucketing (`pos_session.py`)

`get_sfya_cash_movements`: exclude `sfya_is_internal_transfer = True` from the existing collects/payouts/drawings scan (add `('sfya_is_internal_transfer', '=', False)` to that method's payment search domain), so transfer legs never get mislabeled as a generic Collect/Pay Out with a blank partner.

Separately, within the same method, compute (restricted to `journal_id.type == 'cash'`, since that's what's physically counted at session close):
```python
transfers_in_total = sum(amount where sfya_is_internal_transfer=True, payment_type='inbound', journal type=cash)
transfers_out_total = sum(amount where sfya_is_internal_transfer=True, payment_type='outbound', journal type=cash)
```
Both merged into the returned `cash` dict.

`get_closing_control_data` adjustment formula extends to:
```python
adjustment = (
    cash.collects_total - cash.payouts_total - cash.drawings_total
    + cash.transfers_in_total - cash.transfers_out_total
)
```
Bank-journal legs of a transfer stay informational only — bank journals aren't physically counted at POS close (consistent with existing behavior for bank collects/payouts).

### New method: `get_sfya_internal_transfers(self)`

Lists each transfer once via its outbound leg (`sfya_is_internal_transfer=True, payment_type='outbound'`), joining to `sfya_transfer_pair_id` for the destination journal name. Returns `[{id, name, from_journal_name, to_journal_name, amount, memo}]`, ordered by `create_date asc`. Same shape/purpose as the existing `get_sfya_partner_transfers`.

## Frontend

### `cash_movement_modal.js`

- Add `"transfer"` to the `mode` prop's `validate` list: `["collect", "payout", "drawing", "transfer"]`.
- Transfer mode has no partner picker at all. New state fields `fromJournalId`, `toJournalId` (both default to `null`, populated from the already-loaded `state.journals` list — same list used for the existing Account picker).
- `title`/`confirmLabel`/`confirmClass` add a `"transfer"` branch: "Transfer Funds" / "Transfer" / `btn-primary`.
- `isValid` for transfer mode: amount valid, `submitting` false, `fromJournalId` and `toJournalId` both set and different.
- `confirm()`: new early branch (parallel to the existing `isPartnerDestination` branch) — when `props.mode === 'transfer'`, calls `pos.data.call("account.payment", "sfya_pos_internal_transfer", [], {session_id, from_journal_id, to_journal_id, amount, memo, date})`, pushes result to `pos.sfyaCashMovements`, shows notification, prints slip if requested, closes.
- `_printSlip` gains support for `direction: 'internal_transfer'`, passing `from_journal_name`/`to_journal_name` instead of `partner_name`.

### `cash_movement_modal.xml`

- Existing Partner field block wrapped `t-if="props.mode !== 'transfer'"`.
- New block, `t-if="props.mode === 'transfer'"`, with two journal `<select>` inputs ("From Journal", "To Journal"), reusing the existing Account-select markup pattern.
- `PaymentSlip` template: new `t-elif="direction === 'internal_transfer'"` branch showing "Internal Transfer", From/To journal name lines instead of a partner line.

### `product_screen_buttons.js` / `.xml`

New 4th button, "Transfer Funds" (`fa-exchange` icon), positioned after Partner Drawing and before Customer Overview → `openTransfer()` → `this.dialog.add(CashMovementModal, { mode: "transfer" })`.

### `closing_dialog_patch.js` / `.xml`

New state `internalTransfers: []`, loaded via `get_sfya_internal_transfers` in the same `onWillStart` block that already loads partner transfers. New collapsible "Internal Transfers" section, same shape as the existing "Partner Transfers" section: From Journal → To Journal, amount, memo, per row.

## Out of Scope

No `sfya_customer_statement` changes — internal transfers have no partner and never touch a partner ledger.

## Files

All paths relative to `addons/sfya_pos_cash_movement/`.

| File | Action | Purpose |
|------|--------|---------|
| `models/res_company.py` | EDIT | Add `sfya_internal_transfer_account_id` |
| `models/pos_config.py` | EDIT | Add related `sfya_internal_transfer_account_id` |
| `views/pos_config_views.xml` | EDIT | Expose new field in SFYA Cash Control group |
| `models/account_payment.py` | EDIT | Add `sfya_is_internal_transfer`, `sfya_transfer_pair_id` fields + `sfya_pos_internal_transfer()` RPC |
| `models/pos_session.py` | EDIT | Exclude transfers from `get_sfya_cash_movements` main scan, add transfer totals to `cash` dict, extend `get_closing_control_data` adjustment, add `get_sfya_internal_transfers()` |
| `__init__.py` | EDIT | `post_init_hook`: create dedicated clearing account per company |
| `static/src/app/cash_movement_modal.js` | EDIT | `"transfer"` mode: journal-pair state, validation, confirm branch, print slip |
| `static/src/app/cash_movement_modal.xml` | EDIT | Transfer-mode UI (no partner, two journal selects), PaymentSlip branch |
| `static/src/app/product_screen_buttons.js` | EDIT | Add `openTransfer()` |
| `static/src/app/product_screen_buttons.xml` | EDIT | Add "Transfer Funds" button |
| `static/src/app/closing_dialog_patch.js` | EDIT | Load + expose internal transfers |
| `static/src/app/closing_dialog_patch.xml` | EDIT | "Internal Transfers" section |
| `__manifest__.py` | EDIT | Bump version |

## Constraints

- No new models or database tables
- No new addon — extend `sfya_pos_cash_movement`
- Follow existing code style (OWL components, `useState`, `useService`, `@api.model` RPC methods on the relevant model)
- Reuse the dedicated-resource `post_init_hook` pattern (search-by-code, create-if-missing) rather than searching/guessing among existing accounts
- Currency: PKR hardcoded (matches existing cash movement code)
- Any cashier can perform a transfer — no shareholder restriction
