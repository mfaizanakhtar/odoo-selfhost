# SFYA POS Receipt — Design

**Date:** 2026-05-30
**Status:** Approved for implementation
**Target:** Odoo 18 Community, self-hosted (`/Users/faizanakhter/odoo-selfhost`)

## Goal

Replace the default Point of Sale receipt with a SFYA-branded layout matching the reference image: centered company header, "SALES INVOICE" title, customer/invoice/cashier/date block, product table (Name/Qty/Rate/Total), totals block (Subtotal/Grand Total/Payment Received/Total Balance Due), and a "Thank You" footer.

## Scope

**In scope:**
- Visual reskin of the POS receipt template only.
- Field additions: customer name, invoice number (relabel of `pos.order.name`), cashier name (employee fallback to user), date split into Date / Time, total quantity, balance due, change due.
- Width: default Odoo POS receipt width (≈ 80mm thermal).
- Typography: monospace, separator lines (dashed or `===` style), centered headers.
- Remove "Powered by Odoo" footer.

**Out of scope:**
- Previous Balance / customer credit tracking.
- Custom invoice numbering sequence — keep `pos.order.name`, just relabel as "Invoice #".
- NTN / STRN tax IDs.
- A4 PDF invoice or backend QWeb changes.
- Email / SMS receipt delivery.
- Receipt printer driver changes (IoT box / ESC/POS).

## Locked decisions

| Decision | Choice |
|----------|--------|
| Scope | Visual reskin only, no Previous Balance |
| Paper width | Default (80mm thermal) |
| Invoice numbering | Keep `pos.order.name`, relabel as "Invoice #" on receipt |
| "Sales By" source | Employee (`pos.order.employee_id.name`) → fallback to user (`pos.order.user_id.name`) |
| "Powered by Odoo" footer | Remove |

## Architecture

New module under `addons/sfya_pos_receipt/`. The repo's `docker-compose.yml` already mounts `./addons:/mnt/extra-addons:ro`, so the module ships via the existing CI/CD pipeline. Install once via Apps UI after first deploy; subsequent template changes hot-reload on `docker compose restart odoo`.

```
addons/sfya_pos_receipt/
├── __init__.py
├── __manifest__.py
└── static/src/
    ├── app/
    │   ├── order_receipt.xml
    │   └── order_receipt.js
    └── scss/
        └── receipt.scss
```

No Python models, no data files, no security rules, no migrations.

## Components

### `__manifest__.py`

```python
{
    'name': 'SFYA POS Receipt',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'sfya_pos_receipt/static/src/app/order_receipt.js',
            'sfya_pos_receipt/static/src/app/order_receipt.xml',
            'sfya_pos_receipt/static/src/scss/receipt.scss',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
```

### `order_receipt.xml`

Single `<t t-inherit="point_of_sale.OrderReceipt" t-inherit-mode="extension">` block. Xpath surgeries (replace mode unless noted):

1. **Header** — company name (bold, centered) + street address (centered) + phone (centered, `t-if="order.company.phone"`).
2. **Title bar** — `===…===` separator line + `SALES INVOICE` centered.
3. **Info block** (inserted under title) — 2-column grid:
   - left: `Customer: <partner_id.name>` (`t-if="order.partner_id"`), `Invoice # : <order.name>`, `Sales By : <cashier_name>`
   - right: `Date : <DD/MM/YYYY>`, `Time : <HH:MM AM/PM>`
4. **Orderlines table** — replace header row with `Product Name | Qty | Rate | Total`; keep Odoo's existing line loop body unchanged.
5. **Total Qty** — insert `Total Qty : <sum>` row directly under table.
6. **Totals block** — replace with `Subtotal`, `Grand Total`, `Payment Received`, `Total Balance Due` (or `Change Due` when overpaid). Drop the existing "Previous Balance" / tax detail rows for now.
7. **Footer** — replace `Powered by Odoo` block with `Thank You For Shopping With Us` centered.

### `order_receipt.js`

Use `patch()` on the `OrderReceipt` OWL component to add four getters:

| Getter | Logic |
|--------|-------|
| `cashier_name` | `order.employee_id?.name \|\| order.user_id?.name \|\| ''` |
| `invoice_label` | `order.name` (so template can `t-esc="this.invoice_label"`) |
| `total_qty` | sum of `line.qty` across `order.lines` |
| `balance_due` | `order.amount_total - order.amount_paid` (negative = change due) |

No state, no lifecycle hooks. Pure derived values.

### `receipt.scss`

Scoped under `.pos-receipt`:

- `font-family: 'Courier New', monospace`
- `font-size: 12px`
- `.sfya-separator { border-top: 1px dashed #000; margin: 4px 0; }`
- `.sfya-center { text-align: center; }`
- `.sfya-info { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 8px; }`
- Right-align Qty / Rate / Total columns; `word-break: break-word` on product name; `max-width: 60%` on name column.

## Data flow

```
[Cashier validates payment]
   ↓
pos.order saved → order.name assigned
   ↓
ReceiptScreen renders OrderReceipt (props: { order })
   ↓
Patched OrderReceipt reads:
  order.company.name / .street / .phone   → header
  order.partner_id?.name                  → "Customer:"
  this.invoice_label                      → "Invoice #"
  this.cashier_name                       → "Sales By:"
  order.date_order (split)                → "Date" / "Time"
  order.lines (loop)                      → product table
  this.total_qty                          → "Total Qty"
  order.amount_total / amount_paid        → totals block
  this.balance_due                        → "Total Balance Due" or "Change Due"
   ↓
Browser print (window.print) or IoT/ESC/POS pipe
```

Two one-time configurations live outside this module:

1. `res.company.phone` for SFYA ENTERPRISES — set via Settings → Companies. Currently blank.
2. "Use Employees in POS" toggle — Settings → Point of Sale, optional. Without it, `Sales By` falls back to login user.

## Error handling

Template-only module; rendering glitches only. No try/except — OWL renders missing data as empty.

| Scenario | Behavior |
|----------|----------|
| Walk-in (no partner) | "Customer:" line hidden via `t-if` |
| Employee mode off | `cashier_name` falls back to `user_id.name`; both null → blank |
| Company phone blank | Phone line hidden via `t-if` |
| Long product name | CSS wraps inside Product Name column; Qty/Rate/Total stay right-aligned |
| Refund (negative qty/totals) | Odoo provides signed values; totals math handles natively |
| Multi-currency / tax-inclusive | Use `order.amount_total` (Odoo computes per company setting) |
| Overpayment (change due) | `balance_due < 0` → render `Change Due: <abs>` instead of `Total Balance Due` |
| Odoo minor upgrade renames xpath target | Module fails to load with a visible error in Apps; default receipt still works. Fix is re-targeting xpath. |

## Testing

No Python = no unit tests possible. Manual visual verification.

**Pre-deploy (local):** existing lint workflow already validates XML well-formedness on `addons/**/*.xml`. No additional lint changes.

**Post-deploy smoke matrix:**

1. Apps → Update Apps List → search "SFYA POS Receipt" → Install.
2. `docker compose restart odoo` (rebuild asset bundle).
3. Open POS session as cashier and run:

| Test | Expected |
|------|----------|
| Sale with customer + 3 items + cash | Receipt matches reference image |
| Walk-in sale | "Customer:" line absent |
| Sale with very long product name | Wraps cleanly, columns stay aligned |
| Refund existing order | Negative totals render, no crash |
| Overpayment (1000 for 850) | Shows "Change Due: 150.00" |
| Company phone blank → reload POS | Phone line absent |
| Print preview in browser | Fits 80mm, no horizontal scroll |

**Rollback:** Apps → SFYA POS Receipt → Uninstall. Default receipt returns immediately. No DB cleanup required.

## Files to add

- `addons/sfya_pos_receipt/__init__.py` (empty)
- `addons/sfya_pos_receipt/__manifest__.py`
- `addons/sfya_pos_receipt/static/src/app/order_receipt.xml`
- `addons/sfya_pos_receipt/static/src/app/order_receipt.js`
- `addons/sfya_pos_receipt/static/src/scss/receipt.scss`

## Files to modify

None.

## Deployment

Existing CI/CD handles deploy: push to `main` → GH Actions runs `rsync addons/ → VPS:~/odoo-stack/addons/` → `docker compose up -d`. After first push, log in to Odoo, install module manually via Apps UI (one-time).
