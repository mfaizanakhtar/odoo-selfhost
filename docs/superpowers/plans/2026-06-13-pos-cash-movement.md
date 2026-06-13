# POS Cash Movement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a new `sfya_pos_cash_movement` Odoo addon adding Collect Payment / Pay Out buttons to POS that create posted `account.payment` records linked to the active session, surfaced in POS closing dialog for till reconciliation.

**Architecture:** Self-contained addon. Backend extends `account.payment` with a `pos_session_id` field + two `@api.model` RPC entry points (`sfya_pos_collect`, `sfya_pos_payout`) that wrap a private `_sfya_pos_create_payment`. A `pos.session.get_sfya_cash_movements()` helper aggregates payments for closing-dialog display. Frontend patches `ProductScreen` (two new buttons), introduces a single OWL `CashMovementModal` (reused for both directions), and patches `ClosingPosDialog` to render expandable Customer Receipts / Vendor Pay-outs sections and correct the expected-cash math. Existing `sfya_customer_statement` picks up new payments automatically with zero changes.

**Tech Stack:** Odoo 18, Python, OWL (Odoo Web Library) JS components, QWeb XML, Docker Compose, GitHub Actions CI/CD, SSH `deploy@46.224.228.181`.

**Reference spec:** `docs/superpowers/specs/2026-06-13-pos-cash-movement-design.md`

**Testing approach:** Project has zero Python unit tests in any `sfya_*` addon — convention is manual verification via `odoo shell` and browser. Each backend task pairs implementation with an `odoo shell` one-liner that proves the behavior. Frontend tasks are deploy-then-smoke-test in browser. Commits land continuously so any regression is bisectable.

---

## File Structure

**Create (12 files):**

```
addons/sfya_pos_cash_movement/
├── __init__.py                                    # imports models
├── __manifest__.py                                # depends point_of_sale + account, asset bundle
├── models/
│   ├── __init__.py                                # imports account_payment, pos_session
│   ├── account_payment.py                         # pos_session_id field + 2 RPCs + private helper
│   └── pos_session.py                             # get_sfya_cash_movements()
├── security/
│   └── ir.model.access.csv                        # empty header — no new models
└── static/src/app/
    ├── product_screen_buttons.js                  # patches ProductScreen with 2 buttons
    ├── product_screen_buttons.xml                 # xpath insert of buttons into control buttons area
    ├── cash_movement_modal.js                     # OWL Dialog component, partner picker + amount + memo + print toggle
    ├── cash_movement_modal.xml                    # modal template
    ├── closing_dialog_patch.js                    # patches ClosingPosDialog: fetch movements + override expected
    └── closing_dialog_patch.xml                   # xpath insert of two expandable sections
```

**Modify:** None. Self-contained.

**Boundaries:** Backend file split = one file per Odoo model (`account_payment.py`, `pos_session.py`). Frontend split = one component per file. Modal is shared by both directions (variant via `mode` prop).

---

## Deploy Loop (used at end of every task that touches the running container)

```bash
git add <files>
git commit -m "<message>"
git push origin main
# Wait ~3 min for CI: https://github.com/<user>/odoo-selfhost/actions
```

After CI green, on first install of the new addon:

```bash
ssh deploy@46.224.228.181
cd ~/odoo-stack
docker compose exec -T odoo odoo shell -d odoo --no-http << 'EOF'
mod = env['ir.module.module'].search([('name', '=', 'sfya_pos_cash_movement')])
mod.button_immediate_install()   # first run
# mod.button_immediate_upgrade() # subsequent runs after manifest version bump
env.cr.commit()
env['ir.attachment'].search([('url', '=like', '/web/assets/%')]).unlink()
env.cr.commit()
EOF
```

Then in browser: hard-refresh POS + Application tab → Storage → Clear site data (PWA cache invalidation).

---

### Task 1: Scaffold empty addon

**Files:**
- Create: `addons/sfya_pos_cash_movement/__init__.py`
- Create: `addons/sfya_pos_cash_movement/__manifest__.py`
- Create: `addons/sfya_pos_cash_movement/models/__init__.py`
- Create: `addons/sfya_pos_cash_movement/security/ir.model.access.csv`

- [ ] **Step 1: Create top-level `__init__.py`**

Write `addons/sfya_pos_cash_movement/__init__.py`:

```python
from . import models
```

- [ ] **Step 2: Create `__manifest__.py`**

Write `addons/sfya_pos_cash_movement/__manifest__.py`:

```python
{
    'name': 'SFYA POS Cash Movement',
    'version': '18.0.1.0.0',
    'summary': 'Collect Payment / Pay Out buttons on POS, linked to pos.session for till reconciliation',
    'category': 'Point of Sale',
    'author': 'SFYA Enterprises',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'account'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'sfya_pos_cash_movement/static/src/app/cash_movement_modal.js',
            'sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml',
            'sfya_pos_cash_movement/static/src/app/product_screen_buttons.js',
            'sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml',
            'sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js',
            'sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
```

- [ ] **Step 3: Create `models/__init__.py`**

Write `addons/sfya_pos_cash_movement/models/__init__.py`:

```python
from . import account_payment
from . import pos_session
```

- [ ] **Step 4: Create empty `security/ir.model.access.csv`**

Write `addons/sfya_pos_cash_movement/security/ir.model.access.csv`:

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
```

(Header only — no new models declared by this addon, only inherits.)

- [ ] **Step 5: Commit scaffold**

```bash
git add addons/sfya_pos_cash_movement/__init__.py addons/sfya_pos_cash_movement/__manifest__.py addons/sfya_pos_cash_movement/models/__init__.py addons/sfya_pos_cash_movement/security/ir.model.access.csv
git commit -m "feat(pos_cash_movement): scaffold addon"
```

Do **not** push yet — install will fail because models files don't exist. Continue to Task 2.

---

### Task 2: Add `pos_session_id` field to `account.payment`

**Files:**
- Create: `addons/sfya_pos_cash_movement/models/account_payment.py`

- [ ] **Step 1: Write the field-only model**

Write `addons/sfya_pos_cash_movement/models/account_payment.py`:

```python
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    pos_session_id = fields.Many2one(
        'pos.session',
        string='POS Session',
        index=True,
        copy=False,
        help='If set, payment originated from POS Collect/Pay-Out flow during this session.',
    )
```

(RPC methods come in Task 3 — keeping field-only commit small so install can be verified independently.)

- [ ] **Step 2: Push and install**

```bash
git add addons/sfya_pos_cash_movement/models/account_payment.py
git commit -m "feat(pos_cash_movement): add pos_session_id field to account.payment"
git push origin main
```

Wait for CI green (~3 min).

- [ ] **Step 3: Install addon**

SSH and run (replace `button_immediate_install` with `button_immediate_upgrade` on later runs):

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
mod = env['ir.module.module'].search([('name', '=', 'sfya_pos_cash_movement')])
print('Before:', mod.state)
mod.button_immediate_install()
env.cr.commit()
mod = env['ir.module.module'].search([('name', '=', 'sfya_pos_cash_movement')])
print('After:', mod.state)
EOF"
```

Expected output contains:
```
Before: uninstalled
After: installed
```

- [ ] **Step 4: Verify field exists**

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
print('pos_session_id' in env['account.payment']._fields)
EOF"
```

Expected: `True`

---

### Task 3: Add `sfya_pos_collect` and `sfya_pos_payout` RPC methods

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/account_payment.py`

- [ ] **Step 1: Extend the model with helper + two RPCs**

Edit `addons/sfya_pos_cash_movement/models/account_payment.py`. Replace its full contents with:

```python
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    pos_session_id = fields.Many2one(
        'pos.session',
        string='POS Session',
        index=True,
        copy=False,
        help='If set, payment originated from POS Collect/Pay-Out flow during this session.',
    )

    @api.model
    def sfya_pos_collect(self, session_id, partner_id, amount, memo=''):
        """RPC: cashier collects cash from a customer or vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, memo, payment_type='inbound',
        )

    @api.model
    def sfya_pos_payout(self, session_id, partner_id, amount, memo=''):
        """RPC: cashier pays cash out to a vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, memo, payment_type='outbound',
        )

    def _sfya_pos_create_payment(self, session_id, partner_id, amount, memo, payment_type):
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        partner = self.env['res.partner'].sudo().browse(partner_id).exists()
        if not partner:
            raise UserError(_('Partner not found.'))
        if amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        partner_type = 'supplier' if payment_type == 'outbound' else 'customer'
        cash_pm = session.config_id.payment_method_ids.filtered(
            lambda m: m.type == 'cash'
        )[:1]
        if not cash_pm or not cash_pm.journal_id:
            raise UserError(_('No cash journal configured on this POS.'))
        payment = self.sudo().create({
            'partner_id': partner.id,
            'partner_type': partner_type,
            'payment_type': payment_type,
            'amount': amount,
            'journal_id': cash_pm.journal_id.id,
            'date': fields.Date.today(),
            'memo': memo or False,
            'pos_session_id': session.id,
        })
        payment.action_post()
        return {
            'id': payment.id,
            'name': payment.name,
            'partner_id': partner.id,
            'partner_name': partner.name,
            'amount': payment.amount,
            'memo': payment.memo or '',
            'direction': payment_type,
        }
```

- [ ] **Step 2: Push and upgrade**

```bash
git add addons/sfya_pos_cash_movement/models/account_payment.py
git commit -m "feat(pos_cash_movement): add sfya_pos_collect/sfya_pos_payout RPC"
git push origin main
```

Wait for CI green. Then bump-upgrade:

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
mod = env['ir.module.module'].search([('name', '=', 'sfya_pos_cash_movement')])
mod.button_immediate_upgrade()
env.cr.commit()
EOF"
```

- [ ] **Step 3: Verify collect RPC end-to-end**

Pick an open POS session id and a customer id (Bukhari = 23 historically; substitute current value if different) and run:

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
print('session:', sess.id, sess.name if sess else 'NONE')
partner = env['res.partner'].search([('customer_rank', '>', 0)], limit=1)
print('partner:', partner.id, partner.name)
result = env['account.payment'].sfya_pos_collect(sess.id, partner.id, 100.0, 'smoke-test-collect')
print('result:', result)
pay = env['account.payment'].browse(result['id'])
print('state:', pay.state, 'pos_session_id:', pay.pos_session_id.id, 'amount:', pay.amount)
EOF"
```

Expected: `state: paid` (or `in_process` if delayed reconcile), `pos_session_id` equals the session id, `result` dict populated with all keys.

If no open session exists, open one via POS UI first (any cashier login).

- [ ] **Step 4: Verify error paths**

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
partner = env['res.partner'].search([('customer_rank', '>', 0)], limit=1)
from odoo.exceptions import UserError
for desc, args in [
    ('zero amount', (sess.id, partner.id, 0.0, '')),
    ('negative amount', (sess.id, partner.id, -10.0, '')),
    ('missing partner', (sess.id, 99999999, 50.0, '')),
    ('missing session', (99999999, partner.id, 50.0, '')),
]:
    try:
        env['account.payment'].sfya_pos_collect(*args)
        print(desc, 'FAIL (no error)')
    except UserError as e:
        print(desc, 'OK:', str(e))
EOF"
```

Expected: each line ends with `OK:` and a meaningful error message.

- [ ] **Step 5: Commit done — already committed in Step 2**

No additional commit needed.

---

### Task 4: Add `get_sfya_cash_movements()` helper on `pos.session`

**Files:**
- Create: `addons/sfya_pos_cash_movement/models/pos_session.py`

- [ ] **Step 1: Write the model**

Write `addons/sfya_pos_cash_movement/models/pos_session.py`:

```python
from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def get_sfya_cash_movements(self):
        """Return cash collected / paid out via POS Cash Movement during this session.

        Returns:
            {
                'collects':       [{id, name, partner_id, partner_name, amount, memo}, ...],
                'collects_total': float,
                'payouts':        [{...}, ...],
                'payouts_total':  float,
            }
        """
        self.ensure_one()
        payments = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('state', 'in', ['paid', 'in_process']),
        ], order='create_date asc')
        collects, payouts = [], []
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
            'collects_total': sum(r['amount'] for r in collects),
            'payouts': payouts,
            'payouts_total': sum(r['amount'] for r in payouts),
        }
```

- [ ] **Step 2: Push and upgrade**

```bash
git add addons/sfya_pos_cash_movement/models/pos_session.py
git commit -m "feat(pos_cash_movement): add get_sfya_cash_movements helper"
git push origin main
```

Wait for CI green. Upgrade:

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
mod = env['ir.module.module'].search([('name', '=', 'sfya_pos_cash_movement')])
mod.button_immediate_upgrade()
env.cr.commit()
EOF"
```

- [ ] **Step 3: Verify helper**

Pick a session that already has the 100.0 smoke-test payment from Task 3:

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
print(sess.get_sfya_cash_movements())
EOF"
```

Expected: dict with `collects` containing the 100.0 smoke-test row, `collects_total=100.0`, `payouts=[]`, `payouts_total=0.0`.

- [ ] **Step 4: Verify payout side too**

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
vendor = env['res.partner'].search([('supplier_rank', '>', 0)], limit=1)
print('vendor:', vendor.id, vendor.name)
env['account.payment'].sfya_pos_payout(sess.id, vendor.id, 50.0, 'smoke-test-payout')
print(sess.get_sfya_cash_movements())
EOF"
```

Expected: `payouts` now contains the vendor row, `payouts_total=50.0`.

---

### Task 5: Build `CashMovementModal` OWL component

**Files:**
- Create: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`
- Create: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml`

- [ ] **Step 1: Inspect existing POS dialog patterns in the container**

Confirm the dialog base class is `@point_of_sale/app/store/pos_store` exposes `pos.dialog.add`, and that `Dialog` is at `@web/core/dialog/dialog`:

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo bash -lc 'find /usr/lib/python3*/site-packages/odoo/addons/point_of_sale/static/src/app -name \"*.js\" | xargs grep -l \"makeAwaitable\\|Dialog\" | head -10'"
```

Then check how POS opens a partner picker (used in modal):

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo bash -lc 'grep -rn \"PartnerList\\|partner_list\" /usr/lib/python3*/site-packages/odoo/addons/point_of_sale/static/src/app/screens 2>/dev/null | head -20'"
```

Note the exact import path of `PartnerListScreen` — substitute into the code below if it differs from `@point_of_sale/app/screens/partner_list/partner_list`.

- [ ] **Step 2: Write the modal JS**

Write `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`:

```javascript
/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { PartnerListScreen } from "@point_of_sale/app/screens/partner_list/partner_list";

export class CashMovementModal extends Component {
    static template = "sfya_pos_cash_movement.CashMovementModal";
    static components = { Dialog };
    static props = {
        mode: { type: String, validate: (v) => ["collect", "payout"].includes(v) },
        close: Function,
    };

    setup() {
        this.pos = useService("pos");
        this.notification = useService("notification");
        this.state = useState({
            partner: null,
            amount: "",
            memo: "",
            print: false,
            submitting: false,
            error: "",
        });
    }

    get title() {
        return this.props.mode === "collect" ? _t("Collect Payment") : _t("Pay Out");
    }

    get confirmLabel() {
        return this.props.mode === "collect" ? _t("Collect") : _t("Pay Out");
    }

    get confirmClass() {
        return this.props.mode === "collect" ? "btn-success" : "btn-warning";
    }

    get isValid() {
        const amt = parseFloat(this.state.amount);
        return !!this.state.partner && Number.isFinite(amt) && amt > 0 && !this.state.submitting;
    }

    async pickPartner() {
        const partner = await makeAwaitable(this.pos.dialog, PartnerListScreen, {
            partner: this.state.partner,
        });
        if (!partner) return;
        if (this.props.mode === "payout" && !partner.supplier_rank) {
            this.state.error = _t("Pay Out is only allowed for vendors.");
            return;
        }
        this.state.partner = partner;
        this.state.error = "";
    }

    async confirm() {
        if (!this.isValid) return;
        this.state.submitting = true;
        this.state.error = "";
        const rpcName = this.props.mode === "collect" ? "sfya_pos_collect" : "sfya_pos_payout";
        try {
            const result = await this.pos.data.call(
                "account.payment",
                rpcName,
                [],
                {
                    session_id: this.pos.session.id,
                    partner_id: this.state.partner.id,
                    amount: parseFloat(this.state.amount),
                    memo: this.state.memo || "",
                },
            );
            this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
            this.pos.sfyaCashMovements.push(result);
            this.notification.add(
                this.props.mode === "collect"
                    ? _t("Collected %s from %s", result.amount, result.partner_name)
                    : _t("Paid %s to %s", result.amount, result.partner_name),
                { type: "success" },
            );
            if (this.state.print) {
                await this._printSlip(result);
            }
            this.props.close();
        } catch (e) {
            this.state.error = e?.data?.message || e?.message || _t("Failed to record payment.");
            this.state.submitting = false;
        }
    }

    async _printSlip(result) {
        try {
            await this.pos.printer.print(
                "sfya_pos_cash_movement.PaymentSlip",
                {
                    direction: result.direction,
                    name: result.name,
                    partner_name: result.partner_name,
                    amount: result.amount,
                    memo: result.memo,
                    date: new Date().toLocaleString(),
                    cashier: this.pos.get_cashier()?.name || "",
                },
            );
        } catch (e) {
            this.notification.add(_t("Payment recorded but print failed."), { type: "warning" });
        }
    }
}
```

- [ ] **Step 3: Write the modal template + receipt slip template**

Write `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates id="template" xml:space="preserve">

    <t t-name="sfya_pos_cash_movement.CashMovementModal">
        <Dialog title="title" size="'md'">
            <div class="o_cash_movement_modal d-flex flex-column gap-3">
                <div>
                    <label class="form-label fw-bold">Partner</label>
                    <div class="d-flex align-items-center gap-2">
                        <button class="btn btn-outline-secondary" t-on-click="pickPartner">
                            <t t-if="state.partner" t-esc="state.partner.name"/>
                            <t t-else="">Select Partner</t>
                        </button>
                    </div>
                </div>
                <div>
                    <label class="form-label fw-bold">Amount</label>
                    <input type="number" class="form-control" step="0.01" min="0"
                           t-model="state.amount" placeholder="0.00"/>
                </div>
                <div>
                    <label class="form-label fw-bold">Memo (optional)</label>
                    <input type="text" class="form-control" t-model="state.memo"
                           placeholder="e.g. Repayment of old credit"/>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="sfya_cm_print"
                           t-model="state.print"/>
                    <label class="form-check-label" for="sfya_cm_print">Print receipt slip</label>
                </div>
                <div t-if="state.error" class="alert alert-danger mb-0 py-1 px-2"
                     t-esc="state.error"/>
            </div>
            <t t-set-slot="footer">
                <button class="btn btn-secondary" t-on-click="() => props.close()">Cancel</button>
                <button class="btn" t-att-class="confirmClass" t-att-disabled="!isValid"
                        t-on-click="confirm">
                    <t t-esc="confirmLabel"/>
                </button>
            </t>
        </Dialog>
    </t>

    <t t-name="sfya_pos_cash_movement.PaymentSlip">
        <div class="pos-receipt">
            <div class="text-center fw-bold">SFYA ENTERPRISES</div>
            <div class="text-center">Payment Slip</div>
            <hr/>
            <div>Date:    <t t-esc="date"/></div>
            <div>Cashier: <t t-esc="cashier"/></div>
            <div>Type:    <t t-if="direction === 'inbound'">Collect Payment</t><t t-else="">Pay Out</t></div>
            <hr/>
            <div>Partner: <t t-esc="partner_name"/></div>
            <div>Amount:  PKR <t t-esc="amount"/></div>
            <div t-if="memo">Memo:    <t t-esc="memo"/></div>
            <div>Ref:     <t t-esc="name"/></div>
            <hr/>
            <div t-if="direction === 'inbound'">Received by: ______________</div>
            <div t-else="">Paid to:     ______________</div>
        </div>
    </t>

</templates>
```

- [ ] **Step 4: Commit (no deploy yet — buttons in Task 6 trigger the modal)**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml
git commit -m "feat(pos_cash_movement): add CashMovementModal component"
```

---

### Task 6: Add Collect Payment / Pay Out buttons to ProductScreen

**Files:**
- Create: `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js`
- Create: `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml`

- [ ] **Step 1: Find the right xpath anchor for ProductScreen buttons**

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo bash -lc 'grep -n \"control-buttons\\|t-name=.ProductScreen\\|ControlButtons\" /usr/lib/python3*/site-packages/odoo/addons/point_of_sale/static/src/app/screens/product_screen/*.xml /usr/lib/python3*/site-packages/odoo/addons/point_of_sale/static/src/app/screens/product_screen/control_buttons/*.xml 2>/dev/null'"
```

Note the template id that owns the row of action buttons (commonly `point_of_sale.ControlButtons`). Adjust the inherit target in Step 3 if the template id differs.

- [ ] **Step 2: Write the JS patch**

Write `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js`:

```javascript
/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { CashMovementModal } from "./cash_movement_modal";

patch(ControlButtons.prototype, {
    openCollect() {
        this.pos.dialog.add(CashMovementModal, { mode: "collect" });
    },
    openPayout() {
        this.pos.dialog.add(CashMovementModal, { mode: "payout" });
    },
});
```

- [ ] **Step 3: Write the XML xpath inherit**

Write `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates id="template" xml:space="preserve">
    <t t-name="sfya_pos_cash_movement.ControlButtons" t-inherit="point_of_sale.ControlButtons" t-inherit-mode="extension">
        <xpath expr="//div[hasclass('control-buttons')]" position="inside">
            <button class="control-button btn btn-light o_cash_movement_collect"
                    t-on-click="openCollect">
                <i class="fa fa-arrow-down text-success me-1"/>
                Collect Payment
            </button>
            <button class="control-button btn btn-light o_cash_movement_payout"
                    t-on-click="openPayout">
                <i class="fa fa-arrow-up text-warning me-1"/>
                Pay Out
            </button>
        </xpath>
    </t>
</templates>
```

If the Step 1 grep showed the action-button container has a different class (not `control-buttons`), adjust the `xpath expr` accordingly before committing.

- [ ] **Step 4: Push and upgrade + bust assets**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml addons/sfya_pos_cash_movement/__manifest__.py
# Bump version so upgrade is forced
```

Edit `__manifest__.py` and change `'version': '18.0.1.0.0'` → `'version': '18.0.1.1.0'`, then:

```bash
git commit -m "feat(pos_cash_movement): add Collect Payment + Pay Out buttons to ProductScreen"
git push origin main
```

Wait for CI green. Upgrade + clear assets:

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
mod = env['ir.module.module'].search([('name', '=', 'sfya_pos_cash_movement')])
mod.button_immediate_upgrade()
env.cr.commit()
env['ir.attachment'].search([('url', '=like', '/web/assets/%')]).unlink()
env.cr.commit()
EOF"
```

- [ ] **Step 5: Browser smoke test**

In browser:
1. Hard-refresh POS URL.
2. Application tab → Storage → Clear site data.
3. Open POS session.
4. Verify two new buttons visible in the action button row.
5. Click **Collect Payment**: modal opens with title "Collect Payment".
6. Click partner button: PartnerListScreen opens, any partner pickable.
7. Pick a partner, enter 100, leave memo blank, leave print unticked, click Collect.
8. Toast shows "Collected 100 from X". Modal closes.
9. Open Invoicing → Accounting → Customers → Payments. Confirm new row with state Paid, journal Shop Cash, our partner, 100.
10. Click **Pay Out**: title is "Pay Out". Pick a vendor (supplier_rank>0), enter 50, click Pay Out. Toast + payment exists.
11. Pay Out + pick a customer-only partner: should show inline error "Pay Out is only allowed for vendors".

---

### Task 7: Patch ClosingPosDialog with Customer Receipts / Vendor Pay-outs sections

**Files:**
- Create: `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js`
- Create: `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml`

- [ ] **Step 1: Locate ClosingPosDialog source and theoretical-cash property**

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo bash -lc 'grep -rn \"ClosingPosDialog\\|theoretical_cash\\|theoreticalCash\\|expected_cash\" /usr/lib/python3*/site-packages/odoo/addons/point_of_sale/static/src/app/navbar/closing_popup 2>/dev/null | head -30'"
```

Note the template id (likely `point_of_sale.ClosingPosDialog`) and which getter or state field holds the expected-cash value. Adjust the `xpath expr` and the override-property name in Step 3 to match.

- [ ] **Step 2: Write the JS patch**

Write `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js`:

```javascript
/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ClosingPosDialog } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { onWillStart, useState } from "@odoo/owl";

patch(ClosingPosDialog.prototype, {
    setup() {
        super.setup();
        this.sfya = useState({
            collects: [],
            collects_total: 0,
            payouts: [],
            payouts_total: 0,
            collectsOpen: true,
            payoutsOpen: true,
            loaded: false,
        });
        onWillStart(async () => {
            try {
                const data = await this.pos.data.call(
                    "pos.session",
                    "get_sfya_cash_movements",
                    [[this.pos.session.id]],
                );
                Object.assign(this.sfya, data, { loaded: true });
            } catch (e) {
                this.sfya.loaded = true;
            }
        });
    },

    get sfyaExpectedAdjustment() {
        return (this.sfya.collects_total || 0) - (this.sfya.payouts_total || 0);
    },
});
```

- [ ] **Step 3: Write the XML patch**

Write `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates id="template" xml:space="preserve">
    <t t-name="sfya_pos_cash_movement.ClosingPosDialog" t-inherit="point_of_sale.ClosingPosDialog" t-inherit-mode="extension">
        <xpath expr="//div[hasclass('cash-control')]" position="after">
            <div t-if="sfya.loaded" class="sfya-cash-movements mt-3">
                <div class="sfya-section border rounded p-2 mb-2">
                    <div class="d-flex justify-content-between align-items-center cursor-pointer"
                         t-on-click="() => sfya.collectsOpen = !sfya.collectsOpen">
                        <strong>
                            <i t-att-class="sfya.collectsOpen ? 'fa fa-caret-down me-1' : 'fa fa-caret-right me-1'"/>
                            Customer Receipts
                        </strong>
                        <span class="text-success">+ <t t-esc="sfya.collects_total.toFixed(2)"/></span>
                    </div>
                    <table t-if="sfya.collectsOpen and sfya.collects.length" class="table table-sm mb-0 mt-2">
                        <tbody>
                            <tr t-foreach="sfya.collects" t-as="row" t-key="row.id">
                                <td t-esc="row.partner_name"/>
                                <td class="text-end" t-esc="row.amount.toFixed(2)"/>
                                <td class="text-muted small" t-esc="row.memo"/>
                            </tr>
                        </tbody>
                    </table>
                    <div t-if="sfya.collectsOpen and !sfya.collects.length" class="text-muted small mt-1">No customer receipts this session.</div>
                </div>

                <div class="sfya-section border rounded p-2">
                    <div class="d-flex justify-content-between align-items-center cursor-pointer"
                         t-on-click="() => sfya.payoutsOpen = !sfya.payoutsOpen">
                        <strong>
                            <i t-att-class="sfya.payoutsOpen ? 'fa fa-caret-down me-1' : 'fa fa-caret-right me-1'"/>
                            Vendor Pay-outs
                        </strong>
                        <span class="text-warning">- <t t-esc="sfya.payouts_total.toFixed(2)"/></span>
                    </div>
                    <table t-if="sfya.payoutsOpen and sfya.payouts.length" class="table table-sm mb-0 mt-2">
                        <tbody>
                            <tr t-foreach="sfya.payouts" t-as="row" t-key="row.id">
                                <td t-esc="row.partner_name"/>
                                <td class="text-end" t-esc="row.amount.toFixed(2)"/>
                                <td class="text-muted small" t-esc="row.memo"/>
                            </tr>
                        </tbody>
                    </table>
                    <div t-if="sfya.payoutsOpen and !sfya.payouts.length" class="text-muted small mt-1">No vendor pay-outs this session.</div>
                </div>
            </div>
        </xpath>
    </t>
</templates>
```

If Step 1 showed the cash-control wrapper uses a different class (e.g. `cash_control` underscore), adjust the `xpath expr` before committing.

- [ ] **Step 4: Patch theoretical-cash math**

Read Odoo's closing popup JS once to confirm which property holds expected cash. Then add an override to `closing_dialog_patch.js` immediately below the existing patch (same file). Append to `closing_dialog_patch.js`:

```javascript
// Override expected-cash calc: include our movements
patch(ClosingPosDialog.prototype, {
    get theoreticalCash() {
        const base = super.theoreticalCash ?? 0;
        return base + (this.sfya?.collects_total || 0) - (this.sfya?.payouts_total || 0);
    },
});
```

If the source attribute differs (e.g. `state.payments[default_cash].counted`), replace `theoreticalCash` with the correct getter name surfaced by Step 1's grep. If Odoo computes expected cash imperatively (not via getter), instead extend the same getter the template binds to.

- [ ] **Step 5: Bump manifest, push, upgrade, bust assets**

Edit `__manifest__.py`: `'version': '18.0.1.1.0'` → `'version': '18.0.1.2.0'`.

```bash
git add addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "feat(pos_cash_movement): patch ClosingPosDialog with movement sections + expected cash"
git push origin main
```

Wait for CI green. Upgrade + clear assets:

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
mod = env['ir.module.module'].search([('name', '=', 'sfya_pos_cash_movement')])
mod.button_immediate_upgrade()
env.cr.commit()
env['ir.attachment'].search([('url', '=like', '/web/assets/%')]).unlink()
env.cr.commit()
EOF"
```

- [ ] **Step 6: Browser smoke test of closing dialog**

1. Hard-refresh + clear site data.
2. Open POS session if not already open. Note opening cash (e.g. 1000).
3. Make 1 normal POS cash sale of 500 to Walk-In Customer.
4. Click Collect Payment → pick a customer → 300 → confirm.
5. Click Pay Out → pick a vendor → 100 → confirm.
6. Click Close Session.
7. Dialog should show:
   - Cash Drawer Expected = 1000 (opening) + 500 (sale) + 300 (collect) − 100 (payout) = **1700**
   - Section "Customer Receipts + 300.00" with the row.
   - Section "Vendor Pay-outs − 100.00" with the row.
   - Expanding/collapsing sections works.
8. Take a screenshot for the PR/commit log.

---

### Task 8: Customer Statement regression check + Walk-In sanity

**Files:** None changed. This is a verification-only task.

- [ ] **Step 1: Verify collected payment shows in customer statement**

In browser:
1. Go to Contacts → open the partner you used in the 300 Collect test.
2. Action menu → Print → Customer Statement → run for today's date range.
3. Confirm a "Payment Received" row appears with the 300 amount, on today's date.
4. Confirm closing balance is consistent.

- [ ] **Step 2: Verify vendor pay-out shows in vendor partner statement**

1. Contacts → open the vendor used in the 100 Pay Out test.
2. Customer Statement (works for vendors too via the existing wizard).
3. Confirm row appears.

- [ ] **Step 3: Verify Walk-In Customer statement still net-zero on POS cash sale**

1. Customer Statement for Walk-In Customer.
2. The 500 POS cash sale done in Task 7 should net to zero (POS sale row + corresponding cash receipt cancel out) — no double counting.

- [ ] **Step 4: Verify multi-session isolation**

```bash
ssh deploy@46.224.228.181 -t "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
print('Open session:', sess.id, sess.name)
print('Movements only for this session:')
print(sess.get_sfya_cash_movements())
EOF"
```

Movements returned should only belong to this `pos_session_id`.

- [ ] **Step 5: Mark verification complete — no commit (no code change)**

---

### Task 9: Add fallback handling for missing cash journal + final polish

**Files:**
- Modify: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js` (if any Task 6/7 smoke surfaced UX issues)

This task only runs if the Task 6 / Task 7 / Task 8 smoke tests surfaced specific issues. Below are the most common gotchas and how to fix each.

- [ ] **Step 1: If toast text doesn't format amount with currency, change `_t` calls**

Edit `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`, in `confirm()`:

Find:
```javascript
this.notification.add(
    this.props.mode === "collect"
        ? _t("Collected %s from %s", result.amount, result.partner_name)
        : _t("Paid %s to %s", result.amount, result.partner_name),
    { type: "success" },
);
```

Replace with:
```javascript
const formattedAmount = this.env.utils.formatCurrency(result.amount);
this.notification.add(
    this.props.mode === "collect"
        ? _t("Collected %s from %s", formattedAmount, result.partner_name)
        : _t("Paid %s to %s", formattedAmount, result.partner_name),
    { type: "success" },
);
```

- [ ] **Step 2: If print path threw because `this.pos.printer` is undefined, guard it**

Edit `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`, in `_printSlip()`:

Find:
```javascript
async _printSlip(result) {
    try {
        await this.pos.printer.print(
```

Replace with:
```javascript
async _printSlip(result) {
    if (!this.pos.printer || typeof this.pos.printer.print !== "function") {
        this.notification.add(_t("Printer not configured; payment was recorded."), { type: "info" });
        return;
    }
    try {
        await this.pos.printer.print(
```

- [ ] **Step 3: If buttons appeared but click did nothing, add diagnostic log**

Edit `addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js`, replace contents:

```javascript
/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { CashMovementModal } from "./cash_movement_modal";

patch(ControlButtons.prototype, {
    openCollect() {
        console.debug("[sfya_pos_cash_movement] openCollect");
        this.pos.dialog.add(CashMovementModal, { mode: "collect" });
    },
    openPayout() {
        console.debug("[sfya_pos_cash_movement] openPayout");
        this.pos.dialog.add(CashMovementModal, { mode: "payout" });
    },
});
```

Inspect browser console; if `this.pos.dialog` is undefined, replace with `this.env.services.dialog`.

- [ ] **Step 4: Commit polish (only if any sub-step applied)**

Bump `__manifest__.py` version to `18.0.1.3.0`.

```bash
git add addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js addons/sfya_pos_cash_movement/static/src/app/product_screen_buttons.js addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "fix(pos_cash_movement): polish UX from smoke-test findings"
git push origin main
```

Upgrade + bust assets per the standard deploy loop.

- [ ] **Step 5: Re-run Task 6 + Task 7 smoke tests**

Confirm the issues are gone.

---

### Task 10: Update project documentation

**Files:**
- Modify: `docs/ARCHITECTURE.md` (if it exists at repo root)
- Modify: `MEMORY.md` indirectly via memory file

- [ ] **Step 1: Check whether `docs/ARCHITECTURE.md` mentions the addon list**

```bash
ls /Users/faizanakhter/odoo-selfhost/docs/ARCHITECTURE.md 2>/dev/null && grep -n "sfya_" /Users/faizanakhter/odoo-selfhost/docs/ARCHITECTURE.md | head
```

If present and lists existing `sfya_*` addons, add a one-liner for `sfya_pos_cash_movement` describing: "Adds Collect Payment / Pay Out buttons to POS, linked to active pos.session for till reconciliation."

- [ ] **Step 2: Commit doc**

If a doc edit was made:

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs: list sfya_pos_cash_movement addon"
git push origin main
```

- [ ] **Step 3: Final acceptance**

Confirm all spec checklist items satisfied:

| Spec requirement | Verified in |
|---|---|
| Two persistent buttons on ProductScreen | Task 6 Step 5 |
| Modal: partner picker scoped (any / vendor only) | Task 6 Step 5 (#7, #11) |
| Backend creates posted `account.payment` w/ `pos_session_id` | Task 3 Step 3 |
| Error paths reject zero/negative/missing | Task 3 Step 4 |
| `get_sfya_cash_movements` returns correct totals | Task 4 Step 3, Step 4 |
| Closing dialog shows sections + correct expected cash | Task 7 Step 6 |
| Statement reflects payments same day | Task 8 Step 1 |
| Walk-In statement still net-zero on POS sale | Task 8 Step 3 |
| Receipt print toggle works | Task 6 Step 5 (re-test with print box ticked) |

Plan complete.
