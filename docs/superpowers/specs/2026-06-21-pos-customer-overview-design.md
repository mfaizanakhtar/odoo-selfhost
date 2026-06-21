# POS Customer Overview Modal — Design Spec

## Overview

Add a "Customer Overview" button to the POS product screen (inside `sfya_pos_cash_movement`) that opens a modal with two tabs: outstanding customer balances and recent collections. Tapping a balance row opens the Collect Payment modal pre-filled with that partner.

## Scope

Extend `sfya_pos_cash_movement` addon. No new addon, no new models.

## UI

### Button

- Label: "Customer Overview"
- Icon: `fa-users`
- Color: `text-primary`
- Location: product screen control buttons, after Partner Drawing button
- Opens: `CustomerOverviewModal`

### Modal: `CustomerOverviewModal`

Single `Dialog` component, size `lg`. Two tab sections toggled by tab buttons at the top.

#### Tab 1: Outstanding Balances (default active)

Scrollable table with columns:

| Customer | Balance (PKR) |
|----------|---------------|

- Shows all partners with non-zero AR balance
- Positive balance = customer owes you
- Sorted by balance descending (highest debt first)
- Row is clickable: closes overview modal, opens `CashMovementModal` with `mode: "collect"` and partner pre-selected
- Empty state: "No outstanding balances"

#### Tab 2: Recent Collections

Date range controls at top:
- "From" date input (default: today minus 15 days)
- "To" date input (default: today)
- "Refresh" button to reload with new dates

Table with columns:

| Date | Customer | Amount (PKR) | Source |
|------|----------|--------------|--------|

- Source: "POS" if `pos_session_id` is set, otherwise "Invoice/Manual"
- Sorted by date descending (newest first)
- All inbound customer payments across all sources (POS + backend)
- Empty state: "No collections in this period"

## Backend RPC

### `res.partner.get_customer_balances()`

Class method (no record). Returns list of `{partner_id, partner_name, balance}` for all partners with non-zero unreconciled AR balance.

Implementation: query `account_move_line` on accounts where `account_type = 'asset_receivable'`, group by partner, sum `debit - credit`, filter where sum != 0. Only posted entries.

### `account.payment.get_recent_collections(date_from, date_to)`

Class method. Returns list of `{id, date, partner_name, amount, source}`.

Filters: `payment_type = 'inbound'`, `partner_type = 'customer'`, `state in ('posted', 'paid', 'in_process')`, `date >= date_from`, `date <= date_to`.

Source field: `'POS'` if `pos_session_id` is truthy, else `'Invoice/Manual'`.

Sorted by date descending.

## Collect Flow Integration

When user taps a balance row:
1. Close `CustomerOverviewModal`
2. Open `CashMovementModal` with `mode: "collect"`
3. Pre-fill partner (pass partner object or minimal `{id, name}` so modal skips partner picker)

This requires `CashMovementModal` to accept an optional `partner` prop. When provided, `state.partner` initializes to that value and the partner picker button shows the pre-filled name (user can still change it).

## Files

All paths relative to `addons/sfya_pos_cash_movement/`.

| File | Action | Purpose |
|------|--------|---------|
| `models/res_partner.py` | EDIT | Add `get_customer_balances()` RPC |
| `models/account_payment.py` | EDIT | Add `get_recent_collections()` RPC |
| `static/src/app/customer_overview_modal.js` | CREATE | Modal component with tabs, data loading, collect flow |
| `static/src/app/customer_overview_modal.xml` | CREATE | Modal template with balance table + collections table |
| `static/src/app/product_screen_buttons.js` | EDIT | Add `openOverview()` handler |
| `static/src/app/product_screen_buttons.xml` | EDIT | Add "Customer Overview" button |
| `static/src/app/cash_movement_modal.js` | EDIT | Accept optional `partner` prop for pre-fill |
| `__manifest__.py` | EDIT | Add new assets, bump version to 18.0.5.0.0 |

## Constraints

- No new models or database tables
- No new addon — extend `sfya_pos_cash_movement`
- Reuse `CashMovementModal` for collect action (no duplication)
- Use `//sheet` position `inside` for any view inherits (proven safe pattern)
- Follow existing code style (OWL components, `useState`, `useService`)
- Currency: PKR hardcoded (matches existing cash movement code)
