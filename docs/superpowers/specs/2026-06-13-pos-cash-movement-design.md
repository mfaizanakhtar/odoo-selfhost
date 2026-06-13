# POS Cash Movement (Collect Payment / Pay Out) — Design

## Goal

Let cashiers record cash IN (customer/vendor pays us) and cash OUT (we pay a vendor) directly from POS UI during an open session. Each movement creates a posted `account.payment` linked to the active `pos.session` so it (a) reflects in customer statements immediately and (b) appears in the POS closing dialog for till reconciliation.

## Problem

Today, all non-POS-sale cash movements (Bukhari handing back 30k credit, paying Naushad 3k for maintenance, paying Bykea 100) flow through `Invoicing → Customers → Payments → New`. They post correctly to AR/AP, but:

- Cash physically enters/leaves the same till as POS sales.
- POS closing dialog only counts POS-collected cash → cashier's physical till count never matches expected total.
- Cashier has to mentally add/subtract backend payments to reconcile = error-prone.

## Solution Summary

New Odoo addon `sfya_pos_cash_movement` adding:

- Two persistent buttons on POS ProductScreen: **Collect Payment** (green) + **Pay Out** (orange).
- Modal capturing partner + amount + memo + print toggle.
- Backend RPC creates a posted `account.payment` (Cash journal) linked via new `pos_session_id` field on `account.payment`.
- POS closing dialog patched to show two expandable sections (Customer Receipts, Vendor Pay-outs) with per-transaction breakdown and corrected expected-cash math.

## Design Decisions (locked)

| # | Decision | Choice |
|---|---|---|
| 1 | Pay Out scope | Vendors only (existing `res.partner` with `supplier_rank > 0`) |
| 2 | Collect scope | Any partner (customer or vendor) |
| 3 | Reconciliation | No auto-reconcile — register payment, statement shows running balance |
| 4 | Payment methods | Cash only (Shop Cash journal) — non-cash stays in backend Invoicing |
| 5 | Button placement | Persistent buttons on main ProductScreen action bar |
| 6 | Memo field | Optional |
| 7 | Receipt print | Optional toggle in modal, defaults unticked |
| 8 | Permissions | Any cashier in `group_pos_user` for both buttons (audit trail via `create_uid`) |
| 9 | Closing dialog | Separate sections with expandable per-transaction breakdown |
| 10 | Cash mismatch | Keep existing block behavior (Odoo cash control default) |

## Module Structure

```
addons/sfya_pos_cash_movement/
├── __init__.py
├── __manifest__.py            # depends: point_of_sale, account
├── models/
│   ├── __init__.py
│   ├── account_payment.py     # pos_session_id field + RPC methods
│   └── pos_session.py         # get_sfya_cash_movements() helper
├── static/src/
│   └── app/
│       ├── product_screen_buttons.js
│       ├── product_screen_buttons.xml
│       ├── cash_movement_modal.js
│       ├── cash_movement_modal.xml
│       ├── closing_dialog_patch.js
│       └── closing_dialog_patch.xml
└── security/
    └── ir.model.access.csv
```

Separate addon (not merged into `sfya_pos_receipt`) for independent deploy cadence and easier disable.

## Backend Design

### `account.payment` extension

```python
class AccountPayment(models.Model):
    _inherit = 'account.payment'

    pos_session_id = fields.Many2one(
        'pos.session', string='POS Session', index=True, copy=False,
        help='If set, payment originated from POS Collect/Pay-Out flow during this session.',
    )

    @api.model
    def sfya_pos_collect(self, session_id, partner_id, amount, memo=''):
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, memo, payment_type='inbound',
        )

    @api.model
    def sfya_pos_payout(self, session_id, partner_id, amount, memo=''):
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, memo, payment_type='outbound',
        )

    def _sfya_pos_create_payment(self, session_id, partner_id, amount, memo, payment_type):
        session = self.env['pos.session'].browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            raise UserError(_('Partner not found.'))
        if amount <= 0:
            raise UserError(_('Amount must be positive.'))
        partner_type = 'supplier' if payment_type == 'outbound' else 'customer'
        cash_journal = session.config_id.payment_method_ids.filtered(
            lambda m: m.type == 'cash'
        )[:1].journal_id
        if not cash_journal:
            raise UserError(_('No cash journal on POS config.'))
        payment = self.create({
            'partner_id': partner.id,
            'partner_type': partner_type,
            'payment_type': payment_type,
            'amount': amount,
            'journal_id': cash_journal.id,
            'date': fields.Date.today(),
            'memo': memo or False,
            'pos_session_id': session.id,
        })
        payment.action_post()
        return {
            'id': payment.id,
            'name': payment.name,
            'partner_name': partner.name,
            'amount': payment.amount,
            'memo': payment.memo or '',
            'direction': payment_type,
        }
```

### `pos.session` helper

```python
class PosSession(models.Model):
    _inherit = 'pos.session'

    def get_sfya_cash_movements(self):
        self.ensure_one()
        payments = self.env['account.payment'].search([
            ('pos_session_id', '=', self.id),
            ('state', 'in', ['paid', 'in_process']),
        ])
        collects = []
        payouts = []
        for p in payments:
            row = {
                'id': p.id,
                'name': p.name,
                'partner_id': p.partner_id.id,
                'partner_name': p.partner_id.name,
                'amount': p.amount,
                'memo': p.memo or '',
            }
            (collects if p.payment_type == 'inbound' else payouts).append(row)
        return {
            'collects': collects,
            'collects_total': sum(c['amount'] for c in collects),
            'payouts': payouts,
            'payouts_total': sum(p['amount'] for p in payouts),
        }
```

## Frontend Design

### ProductScreen action bar

Add two buttons after existing Customer/Refund:

```
[ Customer ] [ Refund ] [ Collect Payment ] [ Pay Out ]
                          (green)             (orange)
```

### Cash Movement Modal

Single OWL component, reused for both directions (title + scope + button color change):

- Partner picker (reuses POS `PartnerListScreen`):
  - Collect: any partner (`customer_rank > 0 OR supplier_rank > 0`)
  - Pay Out: vendor only (`supplier_rank > 0`)
- Amount field (numeric, > 0)
- Memo field (optional text)
- Print receipt toggle (default off)
- Cancel / Confirm buttons (Confirm disabled until partner + amount valid)

### Receipt template (when print ticked)

```
        SFYA ENTERPRISES
        Payment Slip
─────────────────────────────────
Date:    13-06-2026 14:32
Cashier: Arsalan
Type:    Collect Payment   (or Pay Out)
─────────────────────────────────
Partner:  Bukhari
Amount:   PKR 30,000.00
Memo:     Repayment old credit
Ref:      PRCV/2026/0004X
─────────────────────────────────
Received by: ______________   (or Paid to:)
```

### Closing dialog patch

Adds two expandable sections between cash count and orders summary:

```
Cash Drawer Expected: 47,500
Counted:              [_____]

▼ Customer Receipts        + 30,000
  • Bukhari       30,000  "Old credit"

▼ Vendor Pay-outs          - 8,000
  • AKBA Whsl      5,000  "Bill #003"
  • Naushad        3,000  "Maint"

Orders Summary: ...
```

Patches Odoo's `theoretical_cash` computation:
```
Expected = Opening + POS Cash Sales + Customer Receipts − Vendor Pay-outs
```

Data fetched once when dialog opens via `pos.session.get_sfya_cash_movements()`.

## Data Flow (example: collect 30k from Bukhari)

```
Cashier taps "Collect Payment"
       ↓
Modal opens → picks Bukhari, enters 30000, memo "old credit", ticks Print
       ↓
Confirm tapped → POS calls RPC
       ↓
account.payment.sfya_pos_collect(session_id, 23, 30000, "old credit")
       ↓
Backend: creates + posts account.payment
   • partner_type=customer, payment_type=inbound
   • journal=Shop Cash, state→paid
   • pos_session_id=current
   • account.move PRCV/2026/00XXX created (debit cash, credit AR)
       ↓
RPC returns payment dict
       ↓
POS frontend:
   • Stashes in pos.sfya_cash_movements (in-memory)
   • Triggers printer service with templated slip
   • Toast: "✓ Collected 30,000 from Bukhari"
   • Closes modal
       ↓
Customer Statement (next refresh): row appears as "Payment Received"
       ↓
On session close: closing dialog fetches via get_sfya_cash_movements()
   • Section "Customer Receipts" shows Bukhari 30,000 "old credit"
   • Expected cash += 30,000
```

## Error Handling

| Scenario | Behavior |
|---|---|
| Network drop mid-RPC | Toast "Failed to record payment. Retry?" → cashier can retry |
| Closed session / missing partner / zero amount | Backend `UserError` → modal stays open, inline error |
| Cashier closes modal before confirm | No state change |
| Double-tap Confirm | Button disables on first tap until response |
| Receipt print fails | Payment still recorded. Toast "Recorded but print failed" |
| POS UI crashes after backend create | On close, RPC re-queries by `pos_session_id` → movement still appears in closing dialog (resilient by design) |

## Permissions

- Buttons visible to all users in `point_of_sale.group_pos_user`
- Backend RPC uses sudo where needed (cashier without accounting groups still works)
- Audit trail via `account.payment.create_uid`

## Testing

| Type | Coverage |
|---|---|
| Python unit | RPC creates payment with right fields (partner, type, journal, session_id, posted state) |
| Python unit | Rejects closed session, missing partner, zero/negative amount, no cash journal |
| Python unit | `get_sfya_cash_movements()` returns correct totals + per-partner breakdown |
| Manual UI | Tap button → modal opens → partner picker shows correct scope (any vs vendor only) |
| Manual UI | Confirm → toast → backend account.payment exists with right fields |
| Manual UI | Print toggle: prints / skips correctly |
| Manual UI | Closing dialog: sections appear, expand works, expected cash math correct |
| Manual UI | Customer Statement reflects payment same day |
| Manual edge | Close session mid-flow → next attempt rejected with error |
| Manual edge | Customer overpayment (advance) → balance negative → statement shows correctly |

## Deploy Process

Standard for this project:
1. Commit + push to main → CI deploys ~3 min
2. SSH `deploy@46.224.228.181` → `cd ~/odoo-stack` → odoo shell:
   ```
   mod = env['ir.module.module'].search([('name', '=', 'sfya_pos_cash_movement')])
   mod.button_immediate_install()  # first time
   mod.button_immediate_upgrade()  # subsequent
   env.cr.commit()
   env['ir.attachment'].search([('url', '=like', '/web/assets/%')]).unlink()
   env.cr.commit()
   ```
3. Cashier hard-refresh POS browser + clear site data (PWA cache)

## Out of Scope

- Multi-currency (single PKR shop)
- Non-cash methods (bank, card) — backend Invoicing remains source of truth for those
- Invoice reconciliation UX in POS (user chose: accountant reconciles later, statement shows running balance)
- Manager PIN gate (user chose: any cashier, audit trail is enough)
- Expense category payouts (vendors only per decision)
- Editing/voiding a movement from POS (use backend `account.payment` cancel workflow)

## Risks

| Risk | Mitigation |
|---|---|
| Cashier creates Pay Out for wrong vendor / wrong amount | Audit trail (`create_uid`, `create_date`) + accountant review via Customer Statement / Partner Ledger. Backend cancellation flow allows correction. |
| `pos_session_id` field on `account.payment` conflicts with future Odoo upgrade | Field is custom, in our addon's inheritance. Migration check at every Odoo version bump. |
| Closing dialog patches break on Odoo upstream changes | Wrap patches in try/except where reasonable; manual smoke test in staging before every Odoo upgrade. |
| Multi-session race (two POS configs open simultaneously) | Each payment carries explicit `pos_session_id` from frontend → no ambiguity. |

## Files Modified vs Created

### Create
- `addons/sfya_pos_cash_movement/__init__.py`
- `addons/sfya_pos_cash_movement/__manifest__.py`
- `addons/sfya_pos_cash_movement/models/__init__.py`
- `addons/sfya_pos_cash_movement/models/account_payment.py`
- `addons/sfya_pos_cash_movement/models/pos_session.py`
- `addons/sfya_pos_cash_movement/security/ir.model.access.csv`
- `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js`
- `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml`
- `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`
- `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml`
- `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js`
- `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml`

### Modify
None. Self-contained addon. Existing `sfya_customer_statement` already picks up the new `account.payment` rows automatically (they appear as "Payment Received" via existing source block).
