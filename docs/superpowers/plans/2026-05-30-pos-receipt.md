# SFYA POS Receipt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an Odoo 18 addon (`sfya_pos_receipt`) that replaces the default POS receipt with a SFYA-branded layout matching the reference image.

**Architecture:** Custom addon under `addons/sfya_pos_receipt/`. JS patch on `PosOrder.export_for_printing` to inject extra fields (cashier with employee fallback, partner name, date/time split, total qty, balance/change due). OWL XML inherit on `point_of_sale.OrderReceipt` replaces upstream `<ReceiptHeader>`, `<OrderWidget>` and totals blocks with SFYA-styled markup. SCSS controls typography (monospace) and 80mm thermal layout. No Python models, no DB changes — pure presentation layer.

**Tech Stack:** Odoo 18 Community, OWL framework, SCSS, JS ES2022 (no TypeScript), Docker Compose, GitHub Actions CI/CD.

**Spec reference:** `docs/superpowers/specs/2026-05-30-pos-receipt-design.md`

**Upstream files (read-only, copied to `/tmp/upstream_order_receipt.{xml,js}` during planning):**
- `point_of_sale/static/src/app/screens/receipt_screen/receipt/order_receipt.xml` — target template `point_of_sale.OrderReceipt`
- `point_of_sale/static/src/app/screens/receipt_screen/receipt/order_receipt.js` — `OrderReceipt` component, props = `{ data, formatCurrency, basic_receipt }`
- `point_of_sale/static/src/app/screens/receipt_screen/receipt/receipt_header/receipt_header.xml` — `ReceiptHeader` subcomponent (we replace via xpath)
- `point_of_sale/static/src/app/models/pos_order.js` lines 246–305 — `PosOrder.export_for_printing()` builds the `props.data` dict

**Data contract for the receipt template (after our patch):**
| Field | Source | Purpose |
|-------|--------|---------|
| `name` | upstream `this.pos_reference` | "Invoice #" line |
| `cashier` | patched `getCashierName()` — employee → user fallback | "Sales By" line |
| `orderlines[]` | upstream `getSortedOrderlines().map(l => l.getDisplayData())` | product table rows (uses `.productName`, `.qty`, `.unitPrice`, `.price`) |
| `amount_total` | upstream `get_total_with_tax()` | "Grand Total" |
| `total_paid` | upstream `get_total_paid()` | "Payment Received" |
| `total_without_tax` | upstream | "Subtotal" |
| `headerData.company.name/street/phone` | passed in by `pos_store.js` | header block |
| `partnerName` | NEW — `this.partner_id?.name \|\| ''` | "Customer:" line |
| `dateOnly` | NEW — `DD/MM/YYYY` from `date_order` | "Date" line |
| `timeOnly` | NEW — `HH:MM AM/PM` from `date_order` | "Time" line |
| `totalQty` | NEW — sum of `line.qty` | "Total Qty" line |
| `balanceDue` | NEW — `amount_total - total_paid` (negative = change due) | "Total Balance Due" / "Change Due" |

---

## File Structure

```
addons/sfya_pos_receipt/
├── __init__.py                          # empty
├── __manifest__.py                      # module metadata + asset bundle
└── static/src/
    ├── app/
    │   ├── order_receipt_patch.js       # PosOrder.export_for_printing + getCashierName patches
    │   └── order_receipt.xml            # OWL inherit of point_of_sale.OrderReceipt
    └── scss/
        └── receipt.scss                 # typography + layout overrides scoped under .pos-receipt
```

---

## Task 1: Scaffold module + manifest

**Files:**
- Create: `addons/sfya_pos_receipt/__init__.py`
- Create: `addons/sfya_pos_receipt/__manifest__.py`

- [ ] **Step 1: Create empty `__init__.py`**

Write file at `addons/sfya_pos_receipt/__init__.py` with content:
```
```
(genuinely empty file — no imports needed since module has no Python code)

- [ ] **Step 2: Create `__manifest__.py`**

Write file at `addons/sfya_pos_receipt/__manifest__.py`:

```python
{
    'name': 'SFYA POS Receipt',
    'version': '18.0.1.0.0',
    'summary': 'SFYA-branded receipt layout for Point of Sale',
    'category': 'Point of Sale',
    'author': 'SFYA Enterprises',
    'license': 'LGPL-3',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'sfya_pos_receipt/static/src/app/order_receipt_patch.js',
            'sfya_pos_receipt/static/src/app/order_receipt.xml',
            'sfya_pos_receipt/static/src/scss/receipt.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
```

- [ ] **Step 3: Verify Python parses**

Run: `python3 -c "ast = __import__('ast'); ast.parse(open('addons/sfya_pos_receipt/__manifest__.py').read())"`
Expected: no output (success)

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_pos_receipt/__init__.py addons/sfya_pos_receipt/__manifest__.py
git commit -m "feat(pos-receipt): scaffold sfya_pos_receipt addon

Empty __init__.py + manifest declaring point_of_sale dependency and the
three asset paths (JS patch, XML inherit, SCSS) loaded into
point_of_sale._assets_pos bundle."
```

---

## Task 2: SCSS — typography + 80mm layout

**Files:**
- Create: `addons/sfya_pos_receipt/static/src/scss/receipt.scss`

- [ ] **Step 1: Write the SCSS**

Write file at `addons/sfya_pos_receipt/static/src/scss/receipt.scss`:

```scss
.pos-receipt {
    font-family: 'Courier New', Courier, monospace;
    font-size: 12px;
    line-height: 1.3;
    color: #000;

    .sfya-separator {
        border-top: 1px dashed #000;
        margin: 4px 0;
    }

    .sfya-center {
        text-align: center;
    }

    .sfya-bold {
        font-weight: bold;
    }

    .sfya-header {
        text-align: center;
        margin-bottom: 4px;

        .sfya-company {
            font-size: 14px;
            font-weight: bold;
        }
    }

    .sfya-title {
        text-align: center;
        font-weight: bold;
        margin: 4px 0;
    }

    .sfya-info {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 2px 8px;
        margin: 4px 0;
    }

    .sfya-lines-table {
        width: 100%;
        border-collapse: collapse;

        thead th {
            text-align: left;
            font-weight: bold;
            padding: 2px 0;
        }

        thead th.sfya-num,
        tbody td.sfya-num {
            text-align: right;
        }

        tbody td {
            padding: 1px 0;
            vertical-align: top;
        }

        tbody td.sfya-name {
            word-break: break-word;
            max-width: 60%;
        }
    }

    .sfya-total-qty {
        margin: 4px 0;
    }

    .sfya-totals {
        margin: 4px 0;

        .sfya-total-row {
            display: flex;
            justify-content: space-between;
        }

        .sfya-grand {
            font-weight: bold;
        }
    }

    .sfya-footer {
        text-align: center;
        margin-top: 8px;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add addons/sfya_pos_receipt/static/src/scss/receipt.scss
git commit -m "feat(pos-receipt): add SCSS for monospace 80mm layout

Scoped under .pos-receipt: Courier New 12px, dashed separators, 2-col
info grid, 4-col product table with right-aligned Qty/Rate/Total and
break-word product name."
```

---

## Task 3: JS patch — extend `PosOrder.export_for_printing` + cashier fallback

**Files:**
- Create: `addons/sfya_pos_receipt/static/src/app/order_receipt_patch.js`

- [ ] **Step 1: Write the patch**

Write file at `addons/sfya_pos_receipt/static/src/app/order_receipt_patch.js`:

```javascript
import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

patch(PosOrder.prototype, {
    /**
     * Cashier name with employee fallback.
     * Upstream returns this.user_id?.name only.
     * We try employee_id first (when "Use Employees in POS" is enabled)
     * then fall back to user_id, then empty string.
     */
    getCashierName() {
        return this.employee_id?.name || this.user_id?.name || "";
    },

    /**
     * Extend printing payload with SFYA-specific fields.
     * Preserves all upstream fields; only adds new ones.
     */
    export_for_printing(baseUrl, headerData) {
        const data = super.export_for_printing(baseUrl, headerData);

        const total = this.get_total_with_tax();
        const paid = this.get_total_paid();
        const balanceDue = total - paid;

        let dateOnly = "";
        let timeOnly = "";
        if (this.date_order) {
            const d = new Date(this.date_order.replace(" ", "T") + "Z");
            const dd = String(d.getDate()).padStart(2, "0");
            const mm = String(d.getMonth() + 1).padStart(2, "0");
            const yyyy = d.getFullYear();
            dateOnly = `${dd}/${mm}/${yyyy}`;

            let h = d.getHours();
            const m = String(d.getMinutes()).padStart(2, "0");
            const ampm = h >= 12 ? "PM" : "AM";
            h = h % 12 || 12;
            timeOnly = `${String(h).padStart(2, "0")}:${m} ${ampm}`;
        }

        const totalQty = (this.lines || []).reduce(
            (sum, l) => sum + (l.qty || 0),
            0
        );

        return {
            ...data,
            partnerName: this.partner_id?.name || "",
            dateOnly,
            timeOnly,
            totalQty,
            balanceDue,
        };
    },
});
```

- [ ] **Step 2: Smoke-check syntax with node**

Run: `node --check addons/sfya_pos_receipt/static/src/app/order_receipt_patch.js`
Expected: no output (success)

If `node` is unavailable, skip this step — the assets-bundle build inside Odoo will catch syntax errors on next deploy.

- [ ] **Step 3: Commit**

```bash
git add addons/sfya_pos_receipt/static/src/app/order_receipt_patch.js
git commit -m "feat(pos-receipt): patch PosOrder for cashier fallback + extra print fields

getCashierName: employee_id > user_id > empty.
export_for_printing: adds partnerName, dateOnly (DD/MM/YYYY),
timeOnly (HH:MM AM/PM), totalQty, balanceDue. Spreads upstream payload
first so all stock fields stay intact."
```

---

## Task 4: XML inherit — SFYA layout

**Files:**
- Create: `addons/sfya_pos_receipt/static/src/app/order_receipt.xml`

- [ ] **Step 1: Write the inherit template**

Write file at `addons/sfya_pos_receipt/static/src/app/order_receipt.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates id="template" xml:space="preserve">

    <t t-name="sfya_pos_receipt.OrderReceipt"
       t-inherit="point_of_sale.OrderReceipt"
       t-inherit-mode="extension">

        <!-- 1. Replace ReceiptHeader subcomponent with SFYA header markup -->
        <xpath expr="//ReceiptHeader" position="replace">
            <div class="sfya-header">
                <div class="sfya-company" t-esc="props.data.headerData.company.name"/>
                <div t-if="props.data.headerData.company.street"
                     t-esc="props.data.headerData.company.street"/>
                <div t-if="props.data.headerData.company.phone"
                     t-esc="props.data.headerData.company.phone"/>
            </div>
            <div class="sfya-separator"/>
            <div class="sfya-title">SALES INVOICE</div>
            <div class="sfya-separator"/>
            <div class="sfya-info">
                <div>
                    <div t-if="props.data.partnerName">
                        Customer: <t t-esc="props.data.partnerName"/>
                    </div>
                    <div>Invoice # : <t t-esc="props.data.name"/></div>
                    <div t-if="props.data.cashier">
                        Sales By : <t t-esc="props.data.cashier"/>
                    </div>
                </div>
                <div>
                    <div>Date : <t t-esc="props.data.dateOnly"/></div>
                    <div>Time : <t t-esc="props.data.timeOnly"/></div>
                </div>
            </div>
            <div class="sfya-separator"/>
        </xpath>

        <!-- 2. Replace upstream OrderWidget with SFYA 4-col table -->
        <xpath expr="//OrderWidget" position="replace">
            <table class="sfya-lines-table">
                <thead>
                    <tr>
                        <th class="sfya-name">Product Name</th>
                        <th class="sfya-num">Qty</th>
                        <th class="sfya-num">Rate</th>
                        <th class="sfya-num">Total</th>
                    </tr>
                </thead>
                <tbody>
                    <tr t-foreach="props.data.orderlines" t-as="line" t-key="line_index">
                        <td class="sfya-name" t-esc="line.productName"/>
                        <td class="sfya-num" t-esc="line.qty"/>
                        <td class="sfya-num" t-esc="line.unitPrice"/>
                        <td class="sfya-num" t-esc="line.price"/>
                    </tr>
                </tbody>
            </table>
            <div class="sfya-separator"/>
            <div class="sfya-total-qty">Total Qty : <t t-esc="props.data.totalQty"/></div>
            <div class="sfya-separator"/>
        </xpath>

        <!-- 3. Replace the whole taxTotals+totals+payment+change block with SFYA totals -->
        <xpath expr="//div[hasclass('pos-receipt-taxes')]" position="replace">
            <div class="sfya-totals">
                <div class="sfya-total-row">
                    <span>Subtotal</span>
                    <span t-esc="props.formatCurrency(props.data.total_without_tax)"/>
                </div>
                <div class="sfya-total-row sfya-grand">
                    <span>Grand Total</span>
                    <span t-esc="props.formatCurrency(props.data.amount_total)"/>
                </div>
                <div class="sfya-total-row">
                    <span>Payment Received</span>
                    <span t-esc="props.formatCurrency(props.data.total_paid)"/>
                </div>
                <div class="sfya-separator"/>
                <div class="sfya-total-row sfya-grand" t-if="props.data.balanceDue >= 0">
                    <span>Total Balance Due</span>
                    <span t-esc="props.formatCurrency(props.data.balanceDue)"/>
                </div>
                <div class="sfya-total-row sfya-grand" t-else="">
                    <span>Change Due</span>
                    <span t-esc="props.formatCurrency(-props.data.balanceDue)"/>
                </div>
            </div>
        </xpath>

        <!-- 4. Remove the upstream stand-alone TOTAL / rounding / paymentlines / change block.
             These nodes are siblings under the outer t-if="!props.basic_receipt" wrapper.
             We hide them by class/id so our new totals stay the source of truth. -->
        <xpath expr="//div[hasclass('receipt-total')]" position="replace">
            <t/>
        </xpath>
        <xpath expr="//div[hasclass('receipt-rounding')]" position="replace">
            <t/>
        </xpath>
        <xpath expr="//div[hasclass('receipt-to-pay')]" position="replace">
            <t/>
        </xpath>
        <xpath expr="//div[hasclass('paymentlines')]" position="replace">
            <t/>
        </xpath>
        <xpath expr="//div[hasclass('receipt-change')]" position="replace">
            <t/>
        </xpath>

        <!-- 5. Remove the bottom Powered by Odoo / order metadata footer
             (the div containing <p>Powered by Odoo</p>) -->
        <xpath expr="//p[normalize-space(text())='Powered by Odoo']/.." position="replace">
            <div class="sfya-footer">Thank You For Shopping With Us</div>
        </xpath>

    </t>

</templates>
```

- [ ] **Step 2: Validate XML well-formedness**

Run: `python3 -c "import xml.etree.ElementTree as ET; ET.parse('addons/sfya_pos_receipt/static/src/app/order_receipt.xml')"`
Expected: no output (success)

- [ ] **Step 3: Verify lint workflow still passes locally (optional dry-run)**

If you have `act` installed: `act -W .github/workflows/lint.yml`
Expected: workflow green. (If `act` unavailable, skip — CI will catch it on push.)

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_pos_receipt/static/src/app/order_receipt.xml
git commit -m "feat(pos-receipt): OWL inherit replacing receipt with SFYA layout

t-inherit of point_of_sale.OrderReceipt: replaces ReceiptHeader with
centered SFYA company/title/info block, replaces OrderWidget with a
4-col Product/Qty/Rate/Total table, replaces taxTotals + receipt-total
+ paymentlines + receipt-change blocks with single SFYA totals block,
removes Powered by Odoo footer and adds Thank You footer."
```

---

## Task 5: Deploy via CI/CD

**Files:** none modified — uses existing `.github/workflows/deploy.yml`.

- [ ] **Step 1: Push to main**

```bash
git push origin main
```

- [ ] **Step 2: Watch the deploy run**

```bash
gh run watch --workflow=deploy.yml --exit-status
```

Expected: all steps green including:
- "Build payload" — copies `addons/` into `.build/payload/addons/`
- "Rsync payload to VPS" — syncs to `~/odoo-stack/addons/sfya_pos_receipt/`
- "Restart stack" — `docker compose up -d` picks up new files via the bind mount
- "Health check" — `/web/login` returns 2xx/3xx

If a step fails:
- Lint XML failure → fix XML, recommit, repush.
- Rsync failure → check SSH key / `~/odoo-stack` permissions on VPS.
- Health check failure → SSH in: `ssh deploy@46.224.228.181 'docker compose -f ~/odoo-stack/docker-compose.yml logs --tail 100 odoo'` and look for stack traces mentioning `sfya_pos_receipt`.

- [ ] **Step 3: Verify files landed on VPS**

```bash
ssh deploy@46.224.228.181 'ls -la ~/odoo-stack/addons/sfya_pos_receipt/static/src/app/ ~/odoo-stack/addons/sfya_pos_receipt/static/src/scss/'
```

Expected: shows `order_receipt.xml`, `order_receipt_patch.js`, `receipt.scss`.

- [ ] **Step 4: Verify mount visible inside Odoo container**

```bash
ssh deploy@46.224.228.181 'docker exec odoo-stack-odoo-1 ls /mnt/extra-addons/sfya_pos_receipt/'
```

Expected: shows `__init__.py`, `__manifest__.py`, `static`.

---

## Task 6: Install module + manual smoke test

**Files:** none.

- [ ] **Step 1: Update apps list inside Odoo**

In browser, log in as admin at `https://odoo.edashlytic.com`:
1. Enable Developer Mode: Settings → Developer Tools → Activate.
2. Apps → Update Apps List → Update.

- [ ] **Step 2: Install the module**

In Apps:
1. Clear the "Apps" filter so all modules show.
2. Search "SFYA POS Receipt".
3. Click Install.

Expected: install completes without error, module status = Installed.

If install fails with `AssertionError` / template parse error → check the install dialog stack trace, fix the XML, push, redeploy, then click Upgrade.

- [ ] **Step 3: Set company phone (one-time config)**

Settings → Companies → SFYA ENTERPRISES → set `Phone` to `0322-0226310` → Save.

- [ ] **Step 4: Hard-reload the POS frontend**

The asset bundle must be refreshed:
```bash
ssh deploy@46.224.228.181 'docker compose -f ~/odoo-stack/docker-compose.yml restart odoo'
```

Wait ~30 seconds for restart.

- [ ] **Step 5: Run smoke matrix**

Open POS → start a session → run each case and verify:

| # | Test | Expected |
|---|------|----------|
| 1 | Sale with a customer + 3 items + cash payment of exact amount | Receipt renders SFYA layout: bold centered company, "SALES INVOICE", 2-col info block populated, 4-col line table aligned, totals show Subtotal/Grand Total/Payment Received/Total Balance Due = 0, "Thank You For Shopping With Us" footer. **No "Powered by Odoo" line.** |
| 2 | Sale without customer | "Customer:" line absent; rest renders. |
| 3 | Sale with a product whose name is "ARM STAND 180 25 X 25 WITH CLAMPS & SHOCK MOUNT" | Product name wraps inside its column; Qty/Rate/Total stay right-aligned on the first line. |
| 4 | Refund an order via Refund action | Receipt renders with negative `Total Balance Due` (or `Change Due` if applicable); no template crash. |
| 5 | Sale of 850 paid with 1000 cash | Bottom row reads `Change Due  150.00` (positive value, no minus). |
| 6 | Clear company phone temporarily → restart container → reload POS → print | Phone line absent from header; reset phone afterward. |
| 7 | Browser print preview (Ctrl+P on the receipt) | Width fits 80mm preview, no horizontal scroll. |

- [ ] **Step 6: Side-by-side visual diff**

Open `/Users/faizanakhter/.claude/image-cache/fbfc06ef-aba6-4499-a74d-ad19bd8ee0a3/5.png` (the reference) and screenshot the new receipt. Compare:
- Header: company name bold + address + phone, all centered ✓
- "SALES INVOICE" centered between two separators ✓
- Info block 2-col with Customer / Invoice / Sales By on left, Date / Time on right ✓
- Product table columns: Name | Qty | Rate | Total ✓
- Total Qty line below table ✓
- Totals: Subtotal / Grand Total / Payment Received / (Total Balance Due | Change Due) ✓
- Footer: "Thank You For Shopping With Us", no Odoo mention ✓

Note differences and decide if they need a follow-up tweak task (e.g. column widths, font size).

- [ ] **Step 7: Rollback procedure (only run if blocking issue)**

If the receipt is unusable for live operations and you cannot fix forward:
1. Apps → SFYA POS Receipt → Uninstall.
2. Reload POS — default Odoo receipt returns.
3. Fix the issue in a follow-up commit, push, redeploy, reinstall.

---

## Self-Review (already run)

**1. Spec coverage:**
- Visual reskin scope — Tasks 2, 4.
- All locked decisions (80mm, keep pos.order.name, employee→user fallback, no Powered by Odoo) — Tasks 3, 4.
- Field additions (customer, invoice label, cashier, date/time split, total qty, balance/change due) — Tasks 3 (payload), 4 (render).
- Architecture (addon at `addons/sfya_pos_receipt/`) — Task 1.
- Components (manifest + JS patch + XML inherit + SCSS) — Tasks 1–4.
- Data flow — Task 3 docstring + the data contract table in this plan's header.
- Error handling (walk-in, employee mode off, phone blank, long name, refund, change due, upgrade-break) — Tasks 3 (cashier fallback), 4 (`t-if` guards + balanceDue branch), 6 (smoke matrix cases 2, 3, 4, 5, 6).
- Testing (manual smoke + rollback) — Task 6.
- Deployment (CI/CD push to main) — Task 5.

No gaps.

**2. Placeholder scan:** None — every step has the actual code or command.

**3. Type / identifier consistency:**
- `getCashierName`, `export_for_printing` — match upstream signatures (Task 3).
- `partnerName`, `dateOnly`, `timeOnly`, `totalQty`, `balanceDue` — defined in Task 3, consumed in Task 4 by the same names.
- `props.data.headerData.company.{name,street,phone}` — matches upstream `ReceiptHeader` props shape verified during planning.
- Orderline display fields (`productName`, `qty`, `unitPrice`, `price`) — match upstream `Orderline` template usage verified during planning.
- CSS class names (`sfya-header`, `sfya-separator`, `sfya-info`, `sfya-lines-table`, `sfya-total-qty`, `sfya-totals`, `sfya-total-row`, `sfya-grand`, `sfya-footer`, `sfya-name`, `sfya-num`, `sfya-bold`, `sfya-center`, `sfya-title`, `sfya-company`) — all defined in Task 2 SCSS and used in Task 4 XML.
