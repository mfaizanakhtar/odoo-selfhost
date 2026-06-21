# POS Close Validation + Order Discount — Design

## Goal

Two independent POS enhancements for SFYA Enterprises:

1. **Close Validation** — Block POS session close when counted cash is 0 or cash difference exceeds a configurable threshold.
2. **Order Discount** — Let cashiers apply a global order discount (by % or fixed amount) before payment, visible on the receipt.

---

## Feature 1: Session Close Validation

### Problem

Cashiers occasionally close the POS session without entering the actual cash count (counted = 0) or with a large discrepancy between expected and actual cash. Odoo 18's upstream `ClosePosPopup` allows closing in both cases with no warning.

### Solution

Extend `sfya_pos_cash_movement` (which already patches `ClosePosPopup`) to add two guards before the session close is allowed:

1. **Zero count guard** — if counted cash = 0, block with message: *"Please enter actual cash count before closing."*
2. **Difference guard** — if `|counted − expected| > sfya_max_cash_difference`, block with message: *"Cash difference of Rs X exceeds allowed limit of Rs Y. Please recount or adjust."*

Both guards show an inline error (or `alert` dialog) inside the existing popup and prevent close until the condition is resolved.

### Data Model

**`pos.config`** — new field:

| Field | Type | Default | Label |
|---|---|---|---|
| `sfya_max_cash_difference` | `Float` | `500.0` | Max Allowed Cash Difference (Rs) |

Field is exposed in the POS backend config form view and auto-syncs to frontend via Odoo's `_pos_ui_models_to_load` mechanism (no manual sync needed — `pos.config` is always loaded).

### Architecture

**Addon:** `sfya_pos_cash_movement`

**Python changes:**
- `models/pos_config.py` (new file) — add `sfya_max_cash_difference` field to `pos.config`
- `views/pos_config_views.xml` (new file) — inject field into POS settings form under "Connected Devices" or a new "Cash Control" section

**JS changes (extend existing `closing_dialog_patch.js`):**
- Patch an additional method on `ClosePosPopup` — the confirm/close trigger (likely `closeSession()` or `confirm()` — to be confirmed during implementation by grepping the upstream component)
- Before calling `super`, run:

```js
// Guard 1: zero count
const counted = parseFloat(this.state.notes?.cash?.amount ?? 0);
if (counted === 0) {
    this.sfya.closeError = _t("Please enter actual cash count before closing.");
    return;
}
// Guard 2: difference exceeds threshold
const diff = Math.abs(counted - this.props.default_cash_details.amount);
const maxDiff = this.pos.config.sfya_max_cash_difference ?? 500;
if (maxDiff > 0 && diff > maxDiff) {
    this.sfya.closeError = _t(
        "Cash difference of Rs %s exceeds allowed limit of Rs %s. Please recount or adjust.",
        diff.toFixed(0), maxDiff.toFixed(0)
    );
    return;
}
this.sfya.closeError = null;
```

- Add `closeError` key to existing `this.sfya` state (initialized to `null`)
- **XML:** inject `t-if="sfya.closeError"` error alert block into `closing_dialog_patch.xml` (near the close button)

### Manifest changes

- Add `pos_config.py` to `models/__init__.py`
- Add `views/pos_config_views.xml` to `data` list in `__manifest__.py`
- Bump version: `18.0.3.0.1` → `18.0.3.1.0`

---

## Feature 2: Global Order Discount

### Problem

Cashiers need to offer ad-hoc discounts on entire orders (e.g., "10% off for loyal customer", "Rs 200 off"). Today there is no POS-side discount mechanism — the SFYA receipt doesn't render discounts, and no discount button exists.

### Solution

Add a **Discount** button to the POS order screen control buttons area. Clicking it opens a popup where the cashier enters a discount as a percentage OR a fixed rupee amount. The discount is applied as an equal per-line `discount` field across all order lines (using Odoo's built-in `pos.order.line.discount` field). The SFYA receipt template gains a conditional discount row.

### Architecture

**Addon:** `sfya_pos_receipt`

**New JS files (`static/src/app/`):**

| File | Purpose |
|---|---|
| `discount_button_patch.js` | Patches `ProductScreen` to add a Discount button to control buttons |
| `DiscountPopup.js` | OWL popup component: % / Rs toggle + number input + confirm |
| `DiscountPopup.xml` | Template for the popup |
| `discount_button.xml` | Template for the Discount button (via XPath into product_screen) |

**Receipt changes (`order_receipt.xml`):**
- Add one new XPath to existing `sfya_pos_receipt` template override
- Insert a discount row `t-if="props.data.total_discount > 0"` between Subtotal and Grand Total rows
- Row format: `Discount | -Rs [amount]`

**No Python changes needed.** Odoo's `pos.order.line.discount` field already exists in the data model and is persisted/synced. `get_total_discount()` on the order already sums per-line discounts.

### Discount Button

**Placement:** control buttons area (same pattern as Collect Payment / Pay Out in `sfya_pos_cash_movement`)

**Enabled state:** only when `order.orderlines.length > 0`

**Label:** "Discount" with a percent icon (`fa-tag`)

### Discount Popup

```
┌─────────────────────────────┐
│         Add Discount        │
│                             │
│  Order Total: Rs 5,000      │
│                             │
│  ┌──────────────────────┐   │
│  │  [  %  ] [ Rs ]      │   │  ← toggle
│  └──────────────────────┘   │
│                             │
│  ┌──────────────────────┐   │
│  │  10                  │   │  ← input (keyboard/numpad)
│  └──────────────────────┘   │
│                             │
│  [   Cancel   ] [ Apply ]   │
└─────────────────────────────┘
```

**% mode:** `line.set_discount(value)` for each line (Odoo built-in method)

**Rs mode:**
```js
const pct = (amount / order.get_total_with_tax()) * 100;
order.get_orderlines().forEach(line => line.set_discount(pct));
```

**Clear discount:** if value = 0 or Apply clicked with empty input, reset all lines to `set_discount(0)`.

**Re-apply:** clicking Discount again while a discount is already active pre-fills the popup with current discount % (derived from first line's discount field if uniform, else blank).

### Receipt

The existing SFYA receipt (`order_receipt.xml`) already replaces the full totals block via XPath. Add one line to that block:

```xml
<t t-if="props.data.total_discount > 0">
    <div class="sfya-total-row">
        <span>Discount</span>
        <span>-<t t-esc="formatCurrency(props.data.total_discount)"/></span>
    </div>
</t>
```

Position: between Subtotal row and Grand Total row.

`props.data.total_discount` comes from upstream `export_for_printing` → `this.get_total_discount()` — already present, no `export_for_printing` patch changes needed.

### Manifest changes

- Add 4 new static assets to `point_of_sale._assets_pos` in `sfya_pos_receipt/__manifest__.py`
- Bump version

---

## Design Decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Close guard: counted = 0 | Block (not warn) |
| 2 | Close guard: difference threshold | Configurable via `pos.config.sfya_max_cash_difference` |
| 3 | Close guard: which journals | Cash only (already the scope of existing `ClosePosPopup` cash section) |
| 4 | Discount scope | Global order (applied as equal % across all lines) |
| 5 | Discount input | Both % and fixed Rs (with toggle) |
| 6 | Discount persistence | Per-line `discount` field (standard Odoo field, auto-synced) |
| 7 | Discount placement | Control buttons area of `ProductScreen` |
| 8 | Discount on receipt | Conditional row between Subtotal and Grand Total |
| 9 | Addon for close validation | Extend `sfya_pos_cash_movement` |
| 10 | Addon for discount | Extend `sfya_pos_receipt` |

---

## File Change Summary

### `sfya_pos_cash_movement` (Feature 1)

**New files:**
- `models/pos_config.py`
- `views/pos_config_views.xml`

**Modified files:**
- `models/__init__.py` — import `pos_config`
- `__manifest__.py` — add view to `data`, bump version
- `static/src/app/closing_dialog_patch.js` — add close validation guards
- `static/src/app/closing_dialog_patch.xml` — add error display block

### `sfya_pos_receipt` (Feature 2)

**New files:**
- `static/src/app/discount_button_patch.js`
- `static/src/app/DiscountPopup.js`
- `static/src/app/DiscountPopup.xml`
- `static/src/app/discount_button.xml`

**Modified files:**
- `static/src/app/order_receipt.xml` — add discount row XPath
- `__manifest__.py` — add 4 new assets, bump version

---

## Verification

### Feature 1
1. Go to Invoicing → Configuration → Point of Sale → [config] → set Max Cash Difference = 200
2. Open POS session, make a sale, click Close
3. **Test A:** Leave cash count at 0 → error appears, Close button stays blocked
4. **Test B:** Enter counted = expected + 300 → error appears (exceeds 200 threshold)
5. **Test C:** Enter counted = expected + 100 → no error, session closes normally

### Feature 2
1. Open POS, add items to order
2. Click "Discount" button in control area
3. **Test A:** Enter 10% → all order lines show 10% discount, total updates
4. **Test B:** Switch to Rs, enter 500 on a 5000-order → equivalent ~10% applied
5. **Test C:** Proceed to payment → receipt shows Discount row between Subtotal and Grand Total
6. **Test D:** Click Discount again → popup pre-fills with current discount %
7. **Test E:** Enter 0 and Apply → discount cleared from all lines
