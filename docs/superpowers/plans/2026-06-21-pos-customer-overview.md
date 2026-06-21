# POS Customer Overview Modal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Customer Overview" button to the POS product screen that opens a modal showing outstanding customer balances and recent collections, with tap-to-collect flow.

**Architecture:** Two new backend RPC methods provide data (AR balances via raw SQL, collections via ORM). One new OWL modal component with two tabs consumes them. The existing `CashMovementModal` gains an optional `initialPartner` prop for pre-fill when tapping a balance row.

**Tech Stack:** Odoo 18 (Python 3.12, OWL 2, PostgreSQL)

## Global Constraints

- No new models or database tables
- Extend `sfya_pos_cash_movement` addon (no new addon)
- Use `//sheet` position `inside` for any view inherits
- Follow existing code style: OWL components with `useState`/`useService`, `_t()` for user-facing strings
- Currency: PKR (hardcoded, matching existing code)
- Version bump to `18.0.5.0.0`
- Verification: `python -c "import ast; ast.parse(open(f).read())"` for `.py`, `python -c "import xml.etree.ElementTree as ET; ET.parse(f)"` for `.xml`, `node --check` for `.js`

---

### Task 1: Backend RPC Methods

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/res_partner.py`
- Modify: `addons/sfya_pos_cash_movement/models/account_payment.py`

**Interfaces:**
- Produces: `res.partner.get_customer_balances()` → returns `list[dict]` with keys `{partner_id: int, partner_name: str, balance: float}`, sorted by `balance` descending. Only partners with non-zero balance. Only posted entries on receivable accounts.
- Produces: `account.payment.get_recent_collections(date_from: str, date_to: str)` → returns `list[dict]` with keys `{id: int, date: str, partner_name: str, amount: float, source: str}`, sorted by `date` descending. `source` is `"POS"` if `pos_session_id` is set, else `"Invoice/Manual"`. Filters: `payment_type='inbound'`, `partner_type='customer'`, `state in ('posted','paid','in_process')`.

- [ ] **Step 1: Add `get_customer_balances()` to `res.partner`**

Edit `addons/sfya_pos_cash_movement/models/res_partner.py` to add the RPC method. Use raw SQL for efficiency (groups all partners in one query instead of looping):

```python
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'
    is_shareholder = fields.Boolean(
        string='Shareholder / Partner',
        default=False,
        help='If checked, this partner appears in the POS Partner Drawing flow.',
    )

    @api.model
    def get_customer_balances(self):
        """Return partners with non-zero AR balance for POS overview."""
        self.env.cr.execute("""
            SELECT
                aml.partner_id,
                rp.name,
                SUM(aml.debit) - SUM(aml.credit) AS balance
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN account_account aa ON aa.id = aml.account_id
            JOIN res_partner rp ON rp.id = aml.partner_id
            WHERE aa.account_type = 'asset_receivable'
              AND am.state = 'posted'
              AND aml.partner_id IS NOT NULL
              AND aml.company_id = %s
            GROUP BY aml.partner_id, rp.name
            HAVING ABS(SUM(aml.debit) - SUM(aml.credit)) > 0.005
            ORDER BY balance DESC
        """, (self.env.company.id,))
        return [
            {'partner_id': r[0], 'partner_name': r[1], 'balance': round(r[2], 2)}
            for r in self.env.cr.fetchall()
        ]
```

- [ ] **Step 2: Add `get_recent_collections()` to `account.payment`**

Edit `addons/sfya_pos_cash_movement/models/account_payment.py`. Add new `@api.model` method after the existing RPC methods:

```python
    @api.model
    def get_recent_collections(self, date_from, date_to):
        """Return inbound customer payments in date range for POS overview."""
        try:
            d_from = fields.Date.from_string(date_from)
            d_to = fields.Date.from_string(date_to)
        except (ValueError, TypeError):
            raise UserError(_("Invalid date format."))
        payments = self.sudo().search([
            ('payment_type', '=', 'inbound'),
            ('partner_type', '=', 'customer'),
            ('state', 'in', ['posted', 'paid', 'in_process']),
            ('date', '>=', d_from),
            ('date', '<=', d_to),
            ('company_id', '=', self.env.company.id),
        ], order='date desc, id desc')
        return [{
            'id': p.id,
            'date': p.date.strftime('%d-%m-%Y'),
            'partner_name': p.partner_id.name,
            'amount': p.amount,
            'source': 'POS' if p.pos_session_id else 'Invoice/Manual',
        } for p in payments]
```

- [ ] **Step 3: Verify syntax**

Run:
```bash
python -c "import ast; ast.parse(open('addons/sfya_pos_cash_movement/models/res_partner.py').read())"
python -c "import ast; ast.parse(open('addons/sfya_pos_cash_movement/models/account_payment.py').read())"
```
Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_pos_cash_movement/models/res_partner.py addons/sfya_pos_cash_movement/models/account_payment.py
git commit -m "feat: add get_customer_balances and get_recent_collections RPCs"
```

---

### Task 2: CashMovementModal Pre-fill Support

**Files:**
- Modify: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`

**Interfaces:**
- Consumes: existing `CashMovementModal` component
- Produces: `CashMovementModal` accepts optional `initialPartner` prop (`{id: Number, name: String}` or `null`). When provided, `state.partner` initializes to that value. Partner picker button still works to change it.

- [ ] **Step 1: Add `initialPartner` optional prop and use it in setup**

Edit `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`:

Change the `static props` block to:

```javascript
    static props = {
        mode: { type: String, validate: (v) => ["collect", "payout", "drawing"].includes(v) },
        initialPartner: { type: Object, optional: true },
        close: Function,
    };
```

In the `setup()` method, change the `partner: null` line in `useState` to:

```javascript
            partner: this.props.initialPartner || null,
```

No other changes needed — the existing partner picker button already shows `state.partner.name` when set.

- [ ] **Step 2: Verify syntax**

Run:
```bash
node --check addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js
```
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js
git commit -m "feat: add initialPartner prop to CashMovementModal for pre-fill"
```

---

### Task 3: Customer Overview Modal + Button + Manifest

**Files:**
- Create: `addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.js`
- Create: `addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.xml`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

**Interfaces:**
- Consumes: `res.partner.get_customer_balances()` → `list[{partner_id, partner_name, balance}]` (from Task 1)
- Consumes: `account.payment.get_recent_collections(date_from, date_to)` → `list[{id, date, partner_name, amount, source}]` (from Task 1)
- Consumes: `CashMovementModal` with `initialPartner` prop (from Task 2)

- [ ] **Step 1: Create `customer_overview_modal.js`**

Create `addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.js`:

```javascript
/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { CashMovementModal } from "./cash_movement_modal";

export class CustomerOverviewModal extends Component {
    static template = "sfya_pos_cash_movement.CustomerOverviewModal";
    static components = { Dialog };
    static props = {
        close: Function,
    };

    setup() {
        this.pos = useService("pos");
        this.state = useState({
            tab: "balances",
            balances: [],
            collections: [],
            dateFrom: this._defaultFrom(),
            dateTo: this._todayStr(),
            loading: true,
            error: "",
        });
        onWillStart(() => this._loadAll());
    }

    _todayStr() {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    }

    _defaultFrom() {
        const d = new Date();
        d.setDate(d.getDate() - 15);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    }

    async _loadAll() {
        this.state.loading = true;
        this.state.error = "";
        try {
            const [balances, collections] = await Promise.all([
                this.pos.data.call("res.partner", "get_customer_balances", []),
                this.pos.data.call("account.payment", "get_recent_collections", [], {
                    date_from: this.state.dateFrom,
                    date_to: this.state.dateTo,
                }),
            ]);
            this.state.balances = balances || [];
            this.state.collections = collections || [];
        } catch (e) {
            this.state.error = e?.data?.message || e?.message || _t("Failed to load data.");
        }
        this.state.loading = false;
    }

    async refreshCollections() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.collections = await this.pos.data.call(
                "account.payment", "get_recent_collections", [],
                { date_from: this.state.dateFrom, date_to: this.state.dateTo },
            ) || [];
        } catch (e) {
            this.state.error = e?.data?.message || e?.message || _t("Failed to load collections.");
        }
        this.state.loading = false;
    }

    setTab(tab) {
        this.state.tab = tab;
    }

    collectFromPartner(row) {
        this.props.close();
        this.pos.dialog.add(CashMovementModal, {
            mode: "collect",
            initialPartner: { id: row.partner_id, name: row.partner_name },
        });
    }
}
```

- [ ] **Step 2: Create `customer_overview_modal.xml`**

Create `addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates id="template" xml:space="preserve">

    <t t-name="sfya_pos_cash_movement.CustomerOverviewModal">
        <Dialog title="'Customer Overview'" size="'lg'">
            <div class="o_customer_overview d-flex flex-column" style="min-height: 400px;">
                <!-- Tabs -->
                <ul class="nav nav-tabs mb-3">
                    <li class="nav-item">
                        <a class="nav-link" t-att-class="{ active: state.tab === 'balances' }"
                           href="#" t-on-click.prevent="() => this.setTab('balances')">
                            Outstanding Balances
                        </a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" t-att-class="{ active: state.tab === 'collections' }"
                           href="#" t-on-click.prevent="() => this.setTab('collections')">
                            Recent Collections
                        </a>
                    </li>
                </ul>

                <!-- Error -->
                <div t-if="state.error" class="alert alert-danger py-1 px-2 mb-2"
                     t-esc="state.error"/>

                <!-- Loading -->
                <div t-if="state.loading" class="text-center py-4">
                    <i class="fa fa-spinner fa-spin fa-2x"/>
                </div>

                <!-- Balances Tab -->
                <div t-elif="state.tab === 'balances'" class="flex-grow-1 overflow-auto">
                    <table t-if="state.balances.length" class="table table-sm table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Customer</th>
                                <th class="text-end">Balance (PKR)</th>
                            </tr>
                        </thead>
                        <tbody>
                            <t t-foreach="state.balances" t-as="row" t-key="row.partner_id">
                                <tr class="cursor-pointer" t-on-click="() => this.collectFromPartner(row)">
                                    <td t-esc="row.partner_name"/>
                                    <td class="text-end fw-bold"
                                        t-att-class="{ 'text-danger': row.balance > 0, 'text-success': row.balance &lt; 0 }">
                                        <t t-esc="row.balance.toLocaleString('en-PK', { minimumFractionDigits: 2 })"/>
                                    </td>
                                </tr>
                            </t>
                        </tbody>
                    </table>
                    <div t-else="" class="text-muted text-center py-4">
                        No outstanding balances
                    </div>
                </div>

                <!-- Collections Tab -->
                <div t-elif="state.tab === 'collections'" class="flex-grow-1 d-flex flex-column">
                    <!-- Date filters -->
                    <div class="d-flex gap-2 mb-3 align-items-end">
                        <div>
                            <label class="form-label mb-0 small">From</label>
                            <input type="date" class="form-control form-control-sm"
                                   t-model="state.dateFrom"/>
                        </div>
                        <div>
                            <label class="form-label mb-0 small">To</label>
                            <input type="date" class="form-control form-control-sm"
                                   t-model="state.dateTo"/>
                        </div>
                        <button class="btn btn-sm btn-outline-primary" t-on-click="refreshCollections">
                            <i class="fa fa-refresh"/> Refresh
                        </button>
                    </div>
                    <div class="overflow-auto flex-grow-1">
                        <table t-if="state.collections.length" class="table table-sm mb-0">
                            <thead class="table-light">
                                <tr>
                                    <th>Date</th>
                                    <th>Customer</th>
                                    <th class="text-end">Amount (PKR)</th>
                                    <th>Source</th>
                                </tr>
                            </thead>
                            <tbody>
                                <t t-foreach="state.collections" t-as="c" t-key="c.id">
                                    <tr>
                                        <td t-esc="c.date"/>
                                        <td t-esc="c.partner_name"/>
                                        <td class="text-end" t-esc="c.amount.toLocaleString('en-PK', { minimumFractionDigits: 2 })"/>
                                        <td>
                                            <span class="badge"
                                                  t-att-class="c.source === 'POS' ? 'bg-success' : 'bg-secondary'">
                                                <t t-esc="c.source"/>
                                            </span>
                                        </td>
                                    </tr>
                                </t>
                            </tbody>
                        </table>
                        <div t-else="" class="text-muted text-center py-4">
                            No collections in this period
                        </div>
                    </div>
                </div>
            </div>
            <t t-set-slot="footer">
                <button class="btn btn-secondary" t-on-click="() => props.close()">Close</button>
            </t>
        </Dialog>
    </t>

</templates>
```

- [ ] **Step 3: Add `openOverview()` to product screen buttons JS**

Edit `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js`. Add import for `CustomerOverviewModal` and new method:

```javascript
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
    openOverview() {
        this.dialog.add(CustomerOverviewModal, {});
    },
});
```

- [ ] **Step 4: Add "Customer Overview" button to product screen XML**

Edit `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml`. Add the fourth button after Partner Drawing:

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
            <button class="control-button btn btn-secondary btn-lg py-5 o_customer_overview"
                    t-on-click="openOverview">
                <i class="fa fa-users text-primary me-1"/>
                Customer Overview
            </button>
        </xpath>
    </t>
</templates>
```

- [ ] **Step 5: Update `__manifest__.py`**

Edit `addons/sfya_pos_cash_movement/__manifest__.py`:

- Bump version to `18.0.5.0.0`
- Add new JS and XML assets to `point_of_sale._assets_pos` list:
  - `'sfya_pos_cash_movement/static/src/app/customer_overview_modal.js'`
  - `'sfya_pos_cash_movement/static/src/app/customer_overview_modal.xml'`

Updated `__manifest__.py`:

```python
{
    'name': 'SFYA POS Cash Movement',
    'version': '18.0.5.0.0',
    'summary': 'Collect Payment, Pay Out, Partner Drawing & Customer Overview on POS',
    'category': 'Point of Sale',
    'author': 'SFYA Enterprises',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_partner_views.xml',
        'views/pos_config_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'sfya_pos_cash_movement/static/src/app/cash_movement_modal.js',
            'sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml',
            'sfya_pos_cash_movement/static/src/app/customer_overview_modal.js',
            'sfya_pos_cash_movement/static/src/app/customer_overview_modal.xml',
            'sfya_pos_cash_movement/static/src/app/product_screen_buttons.js',
            'sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml',
            'sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js',
            'sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': '_post_init_create_drawing_account',
}
```

- [ ] **Step 6: Verify all files**

Run:
```bash
python -c "import ast; ast.parse(open('addons/sfya_pos_cash_movement/models/res_partner.py').read())"
python -c "import ast; ast.parse(open('addons/sfya_pos_cash_movement/models/account_payment.py').read())"
node --check addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.js
node --check addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js
node --check addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js
python -c "import xml.etree.ElementTree as ET; ET.parse('addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.xml')"
python -c "import xml.etree.ElementTree as ET; ET.parse('addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml')"
```
Expected: no output (all pass).

- [ ] **Step 7: Commit**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.js \
        addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.xml \
        addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js \
        addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "feat: add Customer Overview modal with balances and collections tabs"
```

---

## Files Summary

| Path (relative to `addons/sfya_pos_cash_movement/`) | Action | Task |
|------|--------|------|
| `models/res_partner.py` | EDIT | 1 |
| `models/account_payment.py` | EDIT | 1 |
| `static/src/app/cash_movement_modal.js` | EDIT | 2 |
| `static/src/app/customer_overview_modal.js` | CREATE | 3 |
| `static/src/app/customer_overview_modal.xml` | CREATE | 3 |
| `static/src/app/product_screen_buttons.js` | EDIT | 3 |
| `static/src/app/product_screen_buttons.xml` | EDIT | 3 |
| `__manifest__.py` | EDIT | 3 |

## Verification (post-deploy)

1. Open POS → see four buttons: Collect Payment, Pay Out, Partner Drawing, Customer Overview
2. Click Customer Overview → modal opens with "Outstanding Balances" tab active
3. Balances tab shows partners with non-zero AR balance, sorted highest first
4. Tap a balance row → overview closes, Collect Payment modal opens with partner pre-filled
5. Switch to "Recent Collections" tab → shows last 15 days of inbound customer payments
6. Change date range, click Refresh → table updates
7. Collections show "POS" or "Invoice/Manual" source badge
8. Existing Collect/Pay Out/Drawing flows unchanged
