# POS Cash Movement — Multi-Journal Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `sfya_pos_cash_movement` so cashiers can record payments to any cash or bank journal of the company — not only the POS cash till — with bank movements rendered as informational sections in the closing dialog that do NOT affect expected-cash math.

**Architecture:** In-place extension of the existing addon. Backend RPCs gain a `journal_id` arg + a new helper returning the allowed journals list. `get_sfya_cash_movements` returns a `{cash, banks}` split structure; `get_closing_control_data` keeps adjusting expected cash by the cash net only. Frontend modal adds an Account dropdown; closing dialog template iterates per-bank sections after the existing cash section. Major version bump (`18.0.2.0.0`) forces upgrade + asset reload.

**Tech Stack:** Odoo 18, OWL/QWeb (frontend), Python (backend), `account.payment` / `account.journal` / `pos.session` ORM. No test infra — manual smoke via odoo shell + browser per task.

**Spec:** `docs/superpowers/specs/2026-06-14-pos-cash-movement-journals-design.md`

---

## Deploy / upgrade loop (used in every task)

This addon is rsync-deployed via GitHub Actions on push to `main`. After commit + push:

1. `gh run list --branch main --limit 3 --json conclusion,workflowName,headSha` — wait for both `Lint` and `Deploy` = success on your HEAD SHA.
2. SSH upgrade + clear assets:
   ```bash
   ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
   mod = env['ir.module.module'].search([('name', '=', 'sfya_pos_cash_movement')])
   print('pre  installed:', mod.installed_version, 'manifest:', mod.latest_version)
   mod.button_immediate_upgrade()
   env.cr.commit()
   print('post installed:', mod.installed_version, 'manifest:', mod.latest_version)
   n = env['ir.attachment'].search([('url', '=like', '/web/assets/%')]).unlink()
   env.cr.commit()
   print('cleared assets')
   EOF" 2>&1 | tail -5
   ```
3. For browser changes, the user hard-refreshes (Cmd+Shift+R) and reopens POS.

Manifest version MUST be bumped in every task that changes Python or asset files, otherwise `button_immediate_upgrade` is a no-op and the JS bundle isn't rebuilt.

---

## File map (high-level)

| File | Task | Purpose |
|---|---|---|
| `addons/sfya_pos_cash_movement/models/pos_session.py` | 1, 2, 3 | Add allowed-journals RPC; split movements by cash/bank; keep till math correct. |
| `addons/sfya_pos_cash_movement/models/account_payment.py` | 1 | RPC takes `journal_id`; validates type + company; drops cash auto-lookup. |
| `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js` | 4 | Fetch journals on mount; state + RPC payload include `journal_id`. |
| `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml` | 4 | `<select>` "Account" above Partner. |
| `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js` | 5 | Read `{cash, banks}` shape into state. |
| `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml` | 5 | Render per-bank sections after cash. |
| `addons/sfya_pos_cash_movement/__manifest__.py` | every task that changes Python or assets | Patch-bump per task; final task bumps to `18.0.2.0.0`. |
| `docs/ARCHITECTURE.md` | 8 | One-liner note that the addon now supports bank journals. |

---

## Task 1: Backend — allowed-journals RPC + journal_id in payment create

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/pos_session.py`
- Modify: `addons/sfya_pos_cash_movement/models/account_payment.py`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

- [ ] **Step 1: Add `get_sfya_allowed_journals` to `pos.session`**

Open `addons/sfya_pos_cash_movement/models/pos_session.py`. After the existing `get_sfya_cash_movements` method, before `get_closing_control_data`, insert:

```python
    @api.model
    def get_sfya_allowed_journals(self, session_id):
        """Return cash + bank journals selectable from the Cash Movement modal.

        Filters by session company. Cash journals are listed first (so the
        default selection — first row — is the POS till), then banks sorted
        by name.
        """
        session = self.sudo().browse(session_id).exists()
        if not session:
            return []
        journals = self.env['account.journal'].sudo().search([
            ('type', 'in', ['cash', 'bank']),
            ('company_id', '=', session.company_id.id),
        ])
        cash = journals.filtered(lambda j: j.type == 'cash').sorted('name')
        banks = journals.filtered(lambda j: j.type == 'bank').sorted('name')
        return [{'id': j.id, 'name': j.name, 'type': j.type} for j in (cash + banks)]
```

Add `from odoo import api, models` at the top if `api` isn't already imported.

- [ ] **Step 2: Change `_sfya_pos_create_payment` to take `journal_id` + validate**

Open `addons/sfya_pos_cash_movement/models/account_payment.py`. Replace the body of `_sfya_pos_create_payment` and its callers:

```python
    @api.model
    def sfya_pos_collect(self, session_id, partner_id, amount, journal_id, memo=''):
        """RPC: cashier collects cash/bank payment from a customer or vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, journal_id, memo, payment_type='inbound',
        )

    @api.model
    def sfya_pos_payout(self, session_id, partner_id, amount, journal_id, memo=''):
        """RPC: cashier pays out cash/bank to a vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, journal_id, memo, payment_type='outbound',
        )

    def _sfya_pos_create_payment(self, session_id, partner_id, amount, journal_id, memo, payment_type):
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        partner = self.env['res.partner'].sudo().browse(partner_id).exists()
        if not partner:
            raise UserError(_('Partner not found.'))
        if payment_type == 'outbound' and not partner.supplier_rank:
            raise UserError(_('Pay Out is only allowed for vendor partners.'))
        if amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        if not journal_id:
            raise UserError(_('Account is required.'))
        journal = self.env['account.journal'].sudo().browse(journal_id).exists()
        if not journal:
            raise UserError(_('Account not found.'))
        if journal.type not in ('cash', 'bank'):
            raise UserError(_('Selected account is not a cash or bank journal.'))
        if journal.company_id != session.company_id:
            raise UserError(_("Account does not belong to this POS's company."))
        partner_type = 'supplier' if payment_type == 'outbound' else 'customer'
        payment = self.sudo().create({
            'partner_id': partner.id,
            'partner_type': partner_type,
            'payment_type': payment_type,
            'amount': amount,
            'journal_id': journal.id,
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
            'journal_id': journal.id,
            'journal_name': journal.name,
            'journal_type': journal.type,
        }
```

The change: signature added `journal_id`, removed `cash_pm` lookup, added 4 validation gates, return dict gains `journal_id` / `journal_name` / `journal_type`.

- [ ] **Step 3: Bump manifest version**

Edit `addons/sfya_pos_cash_movement/__manifest__.py`:

```python
'version': '18.0.2.0.0',
```

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_pos_cash_movement/models/pos_session.py \
        addons/sfya_pos_cash_movement/models/account_payment.py \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "feat(pos_cash_movement): add allowed-journals RPC + journal_id arg on payment RPCs

Backend now accepts journal_id explicitly (replaces hardcoded cash
lookup). Validates type in {cash,bank} and company match. New
get_sfya_allowed_journals method lists selectable journals for the
frontend dropdown. Manifest 18.0.2.0.0 (breaking RPC signature)."
git push origin main
```

- [ ] **Step 5: Wait for CI + upgrade**

Wait until both `Lint` and `Deploy` workflows = success on your HEAD SHA (see Deploy loop above), then run the upgrade snippet.

- [ ] **Step 6: Smoke — allowed journals**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
print('open session:', sess.id, sess.name, 'company:', sess.company_id.name)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
for j in js:
    print(' ', j)
EOF" 2>&1 | tail -20
```

Expected: at least one `type=cash` (the POS till). All bank journals of the company appear with `type=bank`. List ordered cash first, then banks alphabetical.

- [ ] **Step 7: Smoke — cash collect via journal_id**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
cash_jid = next(j['id'] for j in js if j['type'] == 'cash')
print('cash journal:', cash_jid)
r = env['account.payment'].sfya_pos_collect(sess.id, 19, 50.0, cash_jid, memo='task1 smoke cash')
print(r)
env.cr.commit()
EOF" 2>&1 | tail -10
```

Expected dict contains `direction='inbound'`, `journal_type='cash'`, `journal_name='Shop Cash'` (or whatever the cash journal is named on the live system).

- [ ] **Step 8: Smoke — bank collect via journal_id**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
bank_jid = next((j['id'] for j in js if j['type'] == 'bank'), None)
if not bank_jid:
    print('no bank journal — skip')
else:
    print('bank journal:', bank_jid)
    r = env['account.payment'].sfya_pos_collect(sess.id, 19, 75.0, bank_jid, memo='task1 smoke bank')
    print(r)
    env.cr.commit()
EOF" 2>&1 | tail -10
```

Expected: dict with `journal_type='bank'` and the bank journal name. If the test DB has no bank journal, output says "no bank journal — skip" — note this and create one before running Task 5 smokes (Settings → Accounting → Journals → New, type=Bank).

- [ ] **Step 9: Smoke — error paths**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
# missing journal_id
try:
    env['account.payment'].sfya_pos_collect(sess.id, 19, 50.0, 0, memo='err1')
    print('FAIL: expected UserError for missing journal_id')
except Exception as e:
    print('OK missing:', e)
# invalid journal type (find a sales journal)
sales_jid = env['account.journal'].search([('type','=','sale')], limit=1).id
try:
    env['account.payment'].sfya_pos_collect(sess.id, 19, 50.0, sales_jid, memo='err2')
    print('FAIL: expected UserError for sales journal')
except Exception as e:
    print('OK wrong-type:', e)
EOF" 2>&1 | tail -10
```

Expected: two `OK …` lines. No `FAIL`.

---

## Task 2: Backend — split `get_sfya_cash_movements` into {cash, banks}

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/pos_session.py`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

- [ ] **Step 1: Replace `get_sfya_cash_movements` body**

Open `addons/sfya_pos_cash_movement/models/pos_session.py`. Replace the existing `get_sfya_cash_movements` method with:

```python
    def get_sfya_cash_movements(self):
        """Return SFYA POS-recorded cash + bank payments for this session.

        Returns:
            {
                'cash': {collects, collects_total, payouts, payouts_total},
                'banks': [
                    {journal_id, journal_name, collects, collects_total,
                     payouts, payouts_total},
                    ...
                ],
            }

        Banks list contains only journals that had at least one movement
        this session, sorted by journal name.
        """
        self.ensure_one()
        payments = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('state', 'in', ['paid', 'in_process']),
            ('journal_id.type', 'in', ['cash', 'bank']),
        ], order='create_date asc')

        def _row(p):
            return {
                'id': p.id,
                'name': p.name,
                'partner_id': p.partner_id.id,
                'partner_name': p.partner_id.name,
                'amount': p.amount,
                'memo': p.memo or '',
            }

        cash_collects, cash_payouts = [], []
        bank_buckets = {}  # journal_id -> {journal_id, journal_name, collects, payouts}
        for p in payments:
            row = _row(p)
            j = p.journal_id
            if j.type == 'cash':
                (cash_collects if p.payment_type == 'inbound' else cash_payouts).append(row)
            else:  # bank
                bucket = bank_buckets.setdefault(j.id, {
                    'journal_id': j.id,
                    'journal_name': j.name,
                    'collects': [],
                    'payouts': [],
                })
                (bucket['collects'] if p.payment_type == 'inbound' else bucket['payouts']).append(row)

        banks = []
        for jid in sorted(bank_buckets, key=lambda i: bank_buckets[i]['journal_name']):
            b = bank_buckets[jid]
            b['collects_total'] = sum(r['amount'] for r in b['collects'])
            b['payouts_total'] = sum(r['amount'] for r in b['payouts'])
            banks.append(b)

        return {
            'cash': {
                'collects': cash_collects,
                'collects_total': sum(r['amount'] for r in cash_collects),
                'payouts': cash_payouts,
                'payouts_total': sum(r['amount'] for r in cash_payouts),
            },
            'banks': banks,
        }
```

- [ ] **Step 2: Bump manifest patch**

Edit `addons/sfya_pos_cash_movement/__manifest__.py`:

```python
'version': '18.0.2.0.1',
```

- [ ] **Step 3: Commit**

```bash
git add addons/sfya_pos_cash_movement/models/pos_session.py \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "refactor(pos_cash_movement): split get_sfya_cash_movements into cash + banks

Returns {cash: {...}, banks: [{journal_id, journal_name, ...}, ...]}.
Banks list groups movements per journal; only journals with movements
this session appear. Sets up the closing dialog to render per-bank
sections without till impact."
git push origin main
```

- [ ] **Step 4: Wait for CI + upgrade**

Run the upgrade snippet from Deploy loop.

- [ ] **Step 5: Smoke — split structure**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
import json
print(json.dumps(sess.get_sfya_cash_movements(), indent=2, default=str))
EOF" 2>&1 | tail -40
```

Expected: top-level keys `cash` and `banks`. Task 1 Step 7 cash payment appears in `cash.collects`. Task 1 Step 8 bank payment appears in `banks[0].collects` with the matching `journal_name`. Totals correct.

---

## Task 3: Backend — `get_closing_control_data` adapts to new shape

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/pos_session.py`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

- [ ] **Step 1: Update `get_closing_control_data` to read `cash` sub-dict**

Open `addons/sfya_pos_cash_movement/models/pos_session.py`. Replace the existing `get_closing_control_data` override with:

```python
    def get_closing_control_data(self):
        data = super().get_closing_control_data()
        movements = self.get_sfya_cash_movements()
        cash = movements.get('cash') or {}
        adjustment = (cash.get('collects_total') or 0.0) - (cash.get('payouts_total') or 0.0)
        if data.get('default_cash_details') and adjustment:
            data['default_cash_details']['amount'] = (
                data['default_cash_details'].get('amount', 0.0) + adjustment
            )
        return data
```

Bank movements are intentionally excluded from till math — that is the whole point of the split.

- [ ] **Step 2: Bump manifest patch**

Edit `addons/sfya_pos_cash_movement/__manifest__.py`:

```python
'version': '18.0.2.0.2',
```

- [ ] **Step 3: Commit**

```bash
git add addons/sfya_pos_cash_movement/models/pos_session.py \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "fix(pos_cash_movement): adjust expected cash by cash net only

Bank journal movements no longer leak into the till expected-cash
adjustment. Reads movements.cash.{collects,payouts}_total instead of
the previous flat structure."
git push origin main
```

- [ ] **Step 4: Wait for CI + upgrade**

Run the upgrade snippet.

- [ ] **Step 5: Smoke — till math correct after split**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
mv = sess.get_sfya_cash_movements()
cash_net = mv['cash']['collects_total'] - mv['cash']['payouts_total']
bank_net = sum(b['collects_total'] - b['payouts_total'] for b in mv['banks'])
print('cash net:', cash_net, '  bank net (NOT in till):', bank_net)
data = sess.get_closing_control_data()
amt = data.get('default_cash_details', {}).get('amount')
print('default_cash_details.amount:', amt)
print('expected adjustment applied = cash_net only:', cash_net != 0)
EOF" 2>&1 | tail -10
```

Expected: `default_cash_details.amount` reflects opening cash + cash_net. `bank_net` may be > 0 but is NOT added to that figure.

---

## Task 4: Frontend — modal Account dropdown

**Files:**
- Modify: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

- [ ] **Step 1: Add `onWillStart` import + journal state in `cash_movement_modal.js`**

Open `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`. Change the top imports:

```javascript
import { Component, useState, onWillStart } from "@odoo/owl";
```

Then replace the `setup()` method with:

```javascript
    setup() {
        this.pos = useService("pos");
        this.notification = useService("notification");
        this.state = useState({
            partner: null,
            journal_id: null,
            journals: [],
            amount: "",
            memo: "",
            print: false,
            submitting: false,
            error: "",
        });
        onWillStart(async () => {
            try {
                const journals = await this.pos.data.call(
                    "pos.session",
                    "get_sfya_allowed_journals",
                    [],
                    { session_id: this.pos.session.id },
                );
                this.state.journals = journals || [];
                if (this.state.journals.length > 0) {
                    this.state.journal_id = this.state.journals[0].id;
                } else {
                    this.state.error = _t("No cash or bank journal configured for this company.");
                }
            } catch (e) {
                this.state.error = e?.data?.message || e?.message || _t("Failed to load accounts.");
            }
        });
    }
```

`get_sfya_allowed_journals` is `@api.model` so the call args are `[]` and parameters go in kwargs. Default selection = first entry (cash, per Task 1 ordering).

- [ ] **Step 2: Update `isValid` to require a journal**

In the same file, change `get isValid()` to:

```javascript
    get isValid() {
        const amt = parseFloat(this.state.amount);
        return (
            !!this.state.partner &&
            !!this.state.journal_id &&
            Number.isFinite(amt) && amt > 0 &&
            !this.state.submitting
        );
    }
```

- [ ] **Step 3: Send `journal_id` in `confirm()` RPC**

Change the `confirm()` body's `this.pos.data.call(...)` payload kwargs to include `journal_id`:

```javascript
            const result = await this.pos.data.call(
                "account.payment",
                rpcName,
                [],
                {
                    session_id: this.pos.session.id,
                    partner_id: this.state.partner.id,
                    amount: parseFloat(this.state.amount),
                    journal_id: this.state.journal_id,
                    memo: this.state.memo || "",
                },
            );
```

(Add the one `journal_id:` line; don't touch the rest of `confirm`.)

- [ ] **Step 4: Add Account `<select>` to `cash_movement_modal.xml`**

Open `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml`. Insert this block ABOVE the existing Partner block (i.e. immediately after `<div class="o_cash_movement_modal d-flex flex-column gap-3">`):

```xml
                <div>
                    <label class="form-label fw-bold">Account</label>
                    <select class="form-select" t-model.number="state.journal_id"
                            t-att-disabled="state.submitting or !state.journals.length">
                        <t t-foreach="state.journals" t-as="j" t-key="j.id">
                            <option t-att-value="j.id">
                                <t t-esc="j.name"/>
                                <t t-if="j.type === 'bank'"> (Bank)</t>
                            </option>
                        </t>
                    </select>
                </div>
```

`t-model.number` ensures the value is an integer (matches the dict key on the Python side).

- [ ] **Step 5: Bump manifest patch**

Edit `addons/sfya_pos_cash_movement/__manifest__.py`:

```python
'version': '18.0.2.0.3',
```

- [ ] **Step 6: Commit**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js \
        addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "feat(pos_cash_movement): Account dropdown in Cash Movement modal

Loads cash + bank journals via get_sfya_allowed_journals on mount,
defaults to first cash journal (POS till). RPC payload now includes
journal_id. Confirm disabled until partner + amount + journal chosen."
git push origin main
```

- [ ] **Step 7: Wait for CI + upgrade**

Run the upgrade snippet. The asset cache MUST be cleared (the upgrade snippet does this) — the user then hard-refreshes the POS browser tab.

- [ ] **Step 8: Browser smoke — Account dropdown visible + posts to bank**

User flow:
1. POS → Actions (overflow popup) → Collect Payment → modal opens.
2. New "Account" dropdown appears at top. First option = Shop Cash (cash journal). Bank journals follow.
3. Pick a bank journal. Pick any customer. Enter 100. Click Collect.
4. Toast: "Collected 100 from <Customer>".
5. Verify backend:
   ```bash
   ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
   p = env['account.payment'].search([('pos_session_id', '!=', False)], order='id desc', limit=1)
   print(p.name, '  journal:', p.journal_id.name, '(', p.journal_id.type, ')  amt:', p.amount)
   EOF" 2>&1 | tail -3
   ```
   Expected: the most recent payment's `journal.type` is `bank` and `journal.name` matches the user's pick.

---

## Task 5: Frontend — closing dialog renders per-bank sections

**Files:**
- Modify: `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

- [ ] **Step 1: Read new `{cash, banks}` shape into state in `closing_dialog_patch.js`**

Open `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js`. Replace the `patch(ClosePosPopup.prototype, { setup() {...} })` block with:

```javascript
patch(ClosePosPopup.prototype, {
    setup() {
        super.setup();
        this.sfya = useState({
            cash: {
                collects: [],
                collects_total: 0,
                payouts: [],
                payouts_total: 0,
            },
            banks: [],
            cashCollectsOpen: true,
            cashPayoutsOpen: true,
            banksOpen: {}, // journal_id -> boolean
            loaded: false,
        });
        onWillStart(async () => {
            try {
                const data = await this.pos.data.call(
                    "pos.session",
                    "get_sfya_cash_movements",
                    [[this.pos.session.id]],
                );
                if (data?.cash) {
                    Object.assign(this.sfya.cash, data.cash);
                }
                this.sfya.banks = data?.banks || [];
                for (const b of this.sfya.banks) {
                    this.sfya.banksOpen[b.journal_id] = true;
                }
                this.sfya.loaded = true;
            } catch (e) {
                console.warn("[SFYA] Failed to load cash movements:", e);
                this.sfya.loaded = true;
            }
        });
    },

    get sfyaCashAdjustment() {
        return (this.sfya.cash.collects_total || 0) - (this.sfya.cash.payouts_total || 0);
    },

    toggleSfyaBank(journalId) {
        this.sfya.banksOpen[journalId] = !this.sfya.banksOpen[journalId];
    },
});
```

(Remove the old `sfyaExpectedAdjustment` getter and the old flat `collects` / `payouts` state — they're replaced.)

- [ ] **Step 2: Replace template body in `closing_dialog_patch.xml`**

Open `addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml`. Replace the inherited `<t>` block contents (everything inside the `<xpath>` element) with:

```xml
        <xpath expr="//hr" position="after">
            <div t-if="sfya.loaded and (sfya.cash.collects.length or sfya.cash.payouts.length or sfya.banks.length)"
                 class="o_sfya_cash_movements mt-2">

                <!-- Cash: collects -->
                <div t-if="sfya.cash.collects.length" class="border rounded p-2 mb-2">
                    <div class="d-flex justify-content-between fw-bold" style="cursor: pointer;"
                         t-on-click="() => state.sfya.cashCollectsOpen = !state.sfya.cashCollectsOpen">
                        <span>
                            <i class="fa" t-att-class="sfya.cashCollectsOpen ? 'fa-chevron-down' : 'fa-chevron-right'"/>
                            Customer Receipts (Cash)
                        </span>
                        <span class="text-success">
                            +<t t-esc="sfya.cash.collects_total.toFixed(2)"/>
                        </span>
                    </div>
                    <table t-if="sfya.cashCollectsOpen" class="table table-sm mb-0 mt-1">
                        <tbody>
                            <t t-foreach="sfya.cash.collects" t-as="r" t-key="r.id">
                                <tr>
                                    <td t-esc="r.partner_name"/>
                                    <td t-esc="r.memo"/>
                                    <td class="text-end" t-esc="r.amount.toFixed(2)"/>
                                </tr>
                            </t>
                        </tbody>
                    </table>
                </div>

                <!-- Cash: payouts -->
                <div t-if="sfya.cash.payouts.length" class="border rounded p-2 mb-2">
                    <div class="d-flex justify-content-between fw-bold" style="cursor: pointer;"
                         t-on-click="() => state.sfya.cashPayoutsOpen = !state.sfya.cashPayoutsOpen">
                        <span>
                            <i class="fa" t-att-class="sfya.cashPayoutsOpen ? 'fa-chevron-down' : 'fa-chevron-right'"/>
                            Vendor Pay-outs (Cash)
                        </span>
                        <span class="text-warning">
                            -<t t-esc="sfya.cash.payouts_total.toFixed(2)"/>
                        </span>
                    </div>
                    <table t-if="sfya.cashPayoutsOpen" class="table table-sm mb-0 mt-1">
                        <tbody>
                            <t t-foreach="sfya.cash.payouts" t-as="r" t-key="r.id">
                                <tr>
                                    <td t-esc="r.partner_name"/>
                                    <td t-esc="r.memo"/>
                                    <td class="text-end" t-esc="r.amount.toFixed(2)"/>
                                </tr>
                            </t>
                        </tbody>
                    </table>
                </div>

                <!-- Banks: one section per journal, informational only -->
                <t t-foreach="sfya.banks" t-as="b" t-key="b.journal_id">
                    <div class="border rounded p-2 mb-2">
                        <div class="d-flex justify-content-between fw-bold" style="cursor: pointer;"
                             t-on-click="() => this.toggleSfyaBank(b.journal_id)">
                            <span>
                                <i class="fa" t-att-class="sfya.banksOpen[b.journal_id] ? 'fa-chevron-down' : 'fa-chevron-right'"/>
                                <t t-esc="b.journal_name"/>
                                <small class="text-muted ms-2">(informational, no till impact)</small>
                            </span>
                            <span>
                                <span class="text-success me-2">+<t t-esc="b.collects_total.toFixed(2)"/></span>
                                <span class="text-warning">-<t t-esc="b.payouts_total.toFixed(2)"/></span>
                            </span>
                        </div>
                        <table t-if="sfya.banksOpen[b.journal_id]" class="table table-sm mb-0 mt-1">
                            <tbody>
                                <t t-foreach="b.collects" t-as="r" t-key="'c'+r.id">
                                    <tr>
                                        <td>+</td>
                                        <td t-esc="r.partner_name"/>
                                        <td t-esc="r.memo"/>
                                        <td class="text-end" t-esc="r.amount.toFixed(2)"/>
                                    </tr>
                                </t>
                                <t t-foreach="b.payouts" t-as="r" t-key="'p'+r.id">
                                    <tr>
                                        <td>−</td>
                                        <td t-esc="r.partner_name"/>
                                        <td t-esc="r.memo"/>
                                        <td class="text-end" t-esc="r.amount.toFixed(2)"/>
                                    </tr>
                                </t>
                            </tbody>
                        </table>
                    </div>
                </t>
            </div>
        </xpath>
```

The full XML wrapper around the xpath stays the same as the existing file (template inheriting `point_of_sale.ClosePosPopup`).

- [ ] **Step 3: Bump manifest patch**

Edit `addons/sfya_pos_cash_movement/__manifest__.py`:

```python
'version': '18.0.2.0.4',
```

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js \
        addons/sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "feat(pos_cash_movement): per-bank-journal sections in closing dialog

Closing popup now renders the cash collects/payouts in their own
collapsible sections (existing behavior, restructured) and adds one
collapsible per bank journal with movements. Bank sections labelled
'informational, no till impact'. Expected-cash math unchanged."
git push origin main
```

- [ ] **Step 5: Wait for CI + upgrade**

Run the upgrade snippet. User hard-refreshes POS.

- [ ] **Step 6: Browser smoke — closing dialog renders all sections**

Pre-condition: this session has at least one cash collect AND at least one bank collect on at least one bank journal (use Task 1 / Task 4 smoke payments if still in same session, or create more via the modal).

User flow:
1. POS → close session (Close button).
2. Expected: ClosePosPopup opens.
3. Counted/Expected cash row shows the cash adjustment (existing behavior).
4. Below the divider, new "Customer Receipts (Cash)" section appears with the smoke collect, +Total in green.
5. Below that, one section per bank journal (e.g. "Bank Alfalah (informational, no till impact)") with the bank collect rows, both +receipts and -payouts running totals on the right.
6. Click a section header → collapses/expands.
7. Cancel the close (don't actually close the session unless intended).

If the dialog renders blank or throws, open browser console; the `setup()` `catch` logs to `console.warn` with prefix `[SFYA]`.

---

## Task 6: Verification — full happy-path + edge cases

**Files:** None changed. Smoke-only.

- [ ] **Step 1: Multi-bank scenario**

If your DB has < 2 bank journals, create a second one first via Settings → Accounting → Journals → New → type Bank, then:

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
banks = [j for j in js if j['type'] == 'bank']
print('bank journals:', banks)
if len(banks) < 2:
    print('SKIP: need 2 bank journals')
else:
    env['account.payment'].sfya_pos_collect(sess.id, 19, 111.0, banks[0]['id'], memo='multi-bank A')
    env['account.payment'].sfya_pos_collect(sess.id, 19, 222.0, banks[1]['id'], memo='multi-bank B')
    env.cr.commit()
    import json
    print(json.dumps(sess.get_sfya_cash_movements()['banks'], indent=2))
EOF" 2>&1 | tail -40
```

Expected: `banks` list has 2 entries, each with its own journal_id/name and the right row. In the browser closing dialog these render as 2 separate collapsible sections.

- [ ] **Step 2: Pay Out to vendor via bank**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
bank_jid = next(j['id'] for j in js if j['type'] == 'bank')
r = env['account.payment'].sfya_pos_payout(sess.id, 20, 60.0, bank_jid, memo='bank payout to vendor')
print(r)
env.cr.commit()
EOF" 2>&1 | tail -5
```

Expected: returns dict, `direction='outbound'`, `journal_type='bank'`.

Then verify it appears under the right bank section in the closing dialog (browser).

- [ ] **Step 3: Vendor-only-payout gate still enforced for bank**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
js = env['pos.session'].get_sfya_allowed_journals(sess.id)
bank_jid = next(j['id'] for j in js if j['type'] == 'bank')
try:
    env['account.payment'].sfya_pos_payout(sess.id, 19, 10.0, bank_jid, memo='should fail')
    print('FAIL: vendor gate bypassed for bank journal')
except Exception as e:
    print('OK gate:', e)
EOF" 2>&1 | tail -3
```

Expected: `OK gate: ... Pay Out is only allowed for vendor partners.`. Partner 19 is Accesology (customer-only).

- [ ] **Step 4: Customer statement still picks up bank payment**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
from datetime import date
today = date.today()
acc = env['res.partner'].browse(19)
data = acc.get_statement_data(today, today)
for r in data.get('rows', []):
    if r['kind'] == 'payment':
        print(r['doc_name'], r['note'], 'cr=', r['credit'])
EOF" 2>&1 | tail -15
```

Expected: rows include the bank receipts created above; the `note` field contains the bank journal name (e.g. "Payment - Bank Alfalah (multi-bank A)").

- [ ] **Step 5: Expected-cash math sanity in closing dialog**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
mv = sess.get_sfya_cash_movements()
cash_net = mv['cash']['collects_total'] - mv['cash']['payouts_total']
data = sess.get_closing_control_data()
amt = data['default_cash_details']['amount']
print('cash net delta from movements:', cash_net)
print('expected cash on dialog:', amt)
print('  (bank totals NOT in that figure; cross-check by visual inspection)')
for b in mv['banks']:
    print('  ', b['journal_name'], '+', b['collects_total'], '-', b['payouts_total'])
EOF" 2>&1 | tail -10
```

Expected: `expected cash on dialog` reflects opening + cash_net. Bank totals printed but NOT in `amt`.

- [ ] **Step 6: No commit (verification only)**

---

## Task 7: Update architecture doc

**Files:**
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Update addon one-liner**

Open `docs/ARCHITECTURE.md`. Find the line:

```
- `sfya_pos_cash_movement` — adds Collect Payment / Pay Out buttons to POS; posts `account.payment` records linked to the active `pos.session` for till reconciliation in the closing dialog
```

Replace with:

```
- `sfya_pos_cash_movement` — adds Collect Payment / Pay Out buttons to POS; records `account.payment` against any cash or bank journal of the company (cashier picks via Account dropdown), linked to the active `pos.session` for till reconciliation. Cash movements adjust expected cash in the closing dialog; bank movements appear as informational per-journal sections with no till impact.
```

- [ ] **Step 2: Commit**

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs: note multi-journal support in sfya_pos_cash_movement entry"
git push origin main
```

- [ ] **Step 3: Final acceptance checklist**

Confirm all spec acceptance items satisfied:

| Spec requirement | Verified in |
|---|---|
| Modal lists cash + bank journals | Task 1 Step 6, Task 4 Step 8 |
| Bank receipt posts to chosen journal, visible in payments list | Task 4 Step 8 |
| Bank receipt visible in customer statement with journal name in note | Task 6 Step 4 |
| Closing dialog shows cash section + per-bank sections | Task 5 Step 6, Task 6 Step 1 |
| Expected cash = opening + cash net (banks excluded) | Task 3 Step 5, Task 6 Step 5 |
| Vendor-only-payout gate still in force for bank | Task 6 Step 3 |
| Amount>0 + session-open gates unchanged | Task 1 Step 9 |

Plan complete.
