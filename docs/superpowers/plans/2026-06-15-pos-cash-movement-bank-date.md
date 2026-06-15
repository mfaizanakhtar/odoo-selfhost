# POS Cash Movement — Bank Payment Backdating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional Date input to the POS Cash Movement modal so cashiers can backdate bank payments to match the actual transfer date; cash payments stay locked to today; future dates rejected.

**Architecture:** Three-file in-place extension of `sfya_pos_cash_movement`. Backend RPC gains optional `date` kwarg with parse + not-future + cash-override gates. Frontend modal adds a conditional date input visible only when bank journal is selected. Minor version bump to `18.0.3.0.0` forces upgrade + asset reload.

**Tech Stack:** Odoo 18, OWL/QWeb (frontend), Python (backend), `account.payment` / `account.journal` / `pos.session` ORM. No automated tests — manual smoke via odoo shell + browser per task.

**Spec:** `docs/superpowers/specs/2026-06-15-pos-cash-movement-bank-date-design.md`

---

## Deploy / upgrade loop (used in every backend or asset task)

This addon is rsync-deployed via GitHub Actions on push to `main`. After commit + push:

1. Wait for CI: `gh run list --branch main --limit 3 --json conclusion,workflowName,headSha` — wait for both `Lint` and `Deploy` = success on your HEAD SHA.
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
3. For browser changes, user hard-refreshes (Cmd+Shift+R) and reopens POS.

Manifest version MUST be bumped in any task that changes Python or asset files, otherwise `button_immediate_upgrade` is a no-op and the JS bundle isn't rebuilt.

---

## File map (high-level)

| File | Task | Purpose |
|---|---|---|
| `addons/sfya_pos_cash_movement/models/account_payment.py` | 1 | RPC kwargs gain `date`; validate not-future; cash forces today. |
| `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js` | 2 | `state.date`; `selectedJournalIsBank` + `todayStr` getters; conditional payload. |
| `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml` | 2 | Date row with `t-if="selectedJournalIsBank"`, `t-att-max="todayStr"`. |
| `addons/sfya_pos_cash_movement/__manifest__.py` | 1, 2 | Patch-bump per task; final at `18.0.3.0.0`. |

No new files. No new XML data files. No security records.

---

## Task 1: Backend — accept `date` kwarg, validate, assign

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/account_payment.py`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

- [ ] **Step 1: Add `date=None` kwarg to RPC entry points**

Open `addons/sfya_pos_cash_movement/models/account_payment.py`. Replace lines 16-28 with:

```python
    @api.model
    def sfya_pos_collect(self, session_id, partner_id, amount, journal_id, memo='', date=None):
        """RPC: cashier collects cash/bank payment from a customer or vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, journal_id, memo, payment_type='inbound', date=date,
        )

    @api.model
    def sfya_pos_payout(self, session_id, partner_id, amount, journal_id, memo='', date=None):
        """RPC: cashier pays out cash/bank to a vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, journal_id, memo, payment_type='outbound', date=date,
        )
```

- [ ] **Step 2: Update `_sfya_pos_create_payment` signature**

Replace line 30 with:

```python
    def _sfya_pos_create_payment(self, session_id, partner_id, amount, journal_id, memo, payment_type, date=None):
```

- [ ] **Step 3: Add date resolution + validation block**

After the existing journal-company-check line (originally line 49: `raise UserError(_("Account does not belong to this POS's company."))`), and BEFORE the `partner_type = ...` assignment line, insert this block:

```python
        resolved_date = fields.Date.today()
        if journal.type == 'bank' and date:
            try:
                resolved_date = fields.Date.from_string(date)
            except (ValueError, TypeError):
                raise UserError(_("Invalid date format."))
            if resolved_date > fields.Date.today():
                raise UserError(_("Date cannot be in the future."))
        # cash journal: ignore passed date; resolved_date stays today
```

- [ ] **Step 4: Use `resolved_date` in `create` call**

Find this line in the `create` dict (originally line 57):
```python
            'date': fields.Date.today(),
```
Replace with:
```python
            'date': resolved_date,
```

- [ ] **Step 5: Bump manifest version**

Open `addons/sfya_pos_cash_movement/__manifest__.py`. Find the line:
```python
    'version': '18.0.2.0.4',
```
Replace with:
```python
    'version': '18.0.3.0.0',
```

- [ ] **Step 6: Commit**

```bash
git add addons/sfya_pos_cash_movement/models/account_payment.py addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "feat(pos_cash_movement): bank payments accept backdate via date kwarg"
git push origin main
```

- [ ] **Step 7: Wait for CI Lint + Deploy**

```bash
gh run list --branch main --limit 3 --json conclusion,workflowName,headSha,status
```
Expected: both `Lint` and `Deploy` jobs `conclusion=success` on the HEAD SHA from Step 6. Wait up to 90s; poll every 15s.

- [ ] **Step 8: SSH upgrade + clear assets**

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
Expected output contains `post installed: 18.0.3.0.0`.

- [ ] **Step 9: Backend smoke — bank past date**

Find an open session and a bank journal id (BANK 3 = id 12 on AJ Mobile, but verify via shell first if unsure).

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
partner = env['res.partner'].search([('name', '=', 'Accesology')], limit=1)
res = env['account.payment'].sfya_pos_collect(
    session_id=sess.id, partner_id=partner.id, amount=33.0,
    journal_id=12, memo='smoke bank backdate -1d', date='2026-06-14',
)
p = env['account.payment'].browse(res['id'])
print('NAME', p.name, 'DATE', p.date, 'JT', p.journal_id.type)
assert str(p.date) == '2026-06-14', f'expected backdated, got {p.date}'
print('OK bank backdate')
EOF" 2>&1 | tail -10
```
Expected: `NAME PBNK3/... DATE 2026-06-14 JT bank` then `OK bank backdate`.

- [ ] **Step 10: Backend smoke — future date rejected**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
from odoo.exceptions import UserError
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
partner = env['res.partner'].search([('name', '=', 'Accesology')], limit=1)
try:
    env['account.payment'].sfya_pos_collect(
        session_id=sess.id, partner_id=partner.id, amount=10.0,
        journal_id=12, memo='smoke future', date='2099-01-01',
    )
    print('FAIL: future date was accepted')
except UserError as e:
    print('OK rejected:', e.args[0] if e.args else e)
EOF" 2>&1 | tail -5
```
Expected: `OK rejected: Date cannot be in the future.`

- [ ] **Step 11: Backend smoke — cash override**

Verify that even if a date is sent for a cash journal, backend forces today.

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
from odoo import fields
sess = env['pos.session'].search([('state', '=', 'opened')], limit=1)
partner = env['res.partner'].search([('name', '=', 'Accesology')], limit=1)
res = env['account.payment'].sfya_pos_collect(
    session_id=sess.id, partner_id=partner.id, amount=11.0,
    journal_id=7, memo='smoke cash override', date='2026-01-01',
)
p = env['account.payment'].browse(res['id'])
print('NAME', p.name, 'DATE', p.date, 'JT', p.journal_id.type, 'TODAY', fields.Date.today())
assert str(p.date) == str(fields.Date.today()), f'cash should be today, got {p.date}'
print('OK cash forced today')
EOF" 2>&1 | tail -10
```
Expected: `DATE 2026-06-15 JT cash TODAY 2026-06-15` then `OK cash forced today`.

- [ ] **Step 12: Cleanup smoke payments**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
ps = env['account.payment'].search([('memo', 'in', ['smoke bank backdate -1d', 'smoke cash override'])])
print('cleaning', ps.mapped('name'))
ps.action_cancel()
ps.unlink()
env.cr.commit()
print('done')
EOF" 2>&1 | tail -5
```

---

## Task 2: Frontend — modal date input

**Files:**
- Modify: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

- [ ] **Step 1: Add `date` to `state`**

Open `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js`. In `setup()`, locate the `this.state = useState({...})` block (lines 21-30). Replace the entire `useState` block with:

```javascript
        this.state = useState({
            partner: null,
            journal_id: null,
            journals: [],
            amount: "",
            memo: "",
            date: this._todayStr(),
            print: false,
            submitting: false,
            error: "",
        });
```

- [ ] **Step 2: Add the three new getters/helpers**

In the same file, after the `get isValid()` block (originally ends at line 71), insert:

```javascript
    get selectedJournalIsBank() {
        const j = this.state.journals.find((x) => x.id === this.state.journal_id);
        return j?.type === "bank";
    }

    get todayStr() {
        return this._todayStr();
    }

    _todayStr() {
        const d = new Date();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return `${d.getFullYear()}-${m}-${day}`;
    }
```

- [ ] **Step 3: Conditionally include date in RPC payload**

In the same file, locate the `await this.pos.data.call(...)` call inside `confirm()` (originally lines 94-105). Replace the entire `try` block contents from `const result = await this.pos.data.call(` down through the closing `)` of the call with:

```javascript
            const kwargs = {
                session_id: this.pos.session.id,
                partner_id: this.state.partner.id,
                amount: parseFloat(this.state.amount),
                journal_id: this.state.journal_id,
                memo: this.state.memo || "",
            };
            if (this.selectedJournalIsBank) {
                kwargs.date = this.state.date;
            }
            const result = await this.pos.data.call(
                "account.payment",
                rpcName,
                [],
                kwargs,
            );
```

- [ ] **Step 4: Add Date row to modal template**

Open `addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml`. Find the closing `</div>` of the Account block (line 18) and the opening of the Partner block (line 19). Insert this new `<div>` between them — so it sits AFTER Account and BEFORE Partner:

```xml
                <div t-if="selectedJournalIsBank">
                    <label class="form-label fw-bold">Date</label>
                    <input type="date" class="form-control"
                           t-model="state.date" t-att-max="todayStr"/>
                    <small class="text-muted">Date the bank transfer actually happened. Today by default.</small>
                </div>
```

- [ ] **Step 5: Bump manifest version**

Open `addons/sfya_pos_cash_movement/__manifest__.py`. Find the line:
```python
    'version': '18.0.3.0.0',
```
Replace with:
```python
    'version': '18.0.3.0.1',
```

- [ ] **Step 6: Commit**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.js addons/sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "feat(pos_cash_movement): Date input for bank payments in modal"
git push origin main
```

- [ ] **Step 7: Wait for CI**

```bash
gh run list --branch main --limit 3 --json conclusion,workflowName,headSha,status
```
Wait until both `Lint` and `Deploy` succeed on HEAD.

- [ ] **Step 8: SSH upgrade + clear assets**

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
Expected `post installed: 18.0.3.0.1`.

- [ ] **Step 9: Browser smoke — bank shows Date**

User action (manual):
1. Hard refresh POS (Cmd+Shift+R), reopen AJ Mobile.
2. Click Collect Payment → modal opens.
3. Pick "BANK 3" in Account dropdown.
4. **Expected:** Date row appears between Account and Partner. Value = today. Try clicking the picker — future dates are disabled.

- [ ] **Step 10: Browser smoke — cash hides Date**

1. In same modal, switch Account to "Shop Cash".
2. **Expected:** Date row disappears.
3. Switch back to "BANK 3".
4. **Expected:** Date row reappears with previously-entered value (or today).

- [ ] **Step 11: Browser smoke — past-dated bank receipt posts**

1. With BANK 3 selected, change Date to yesterday's date.
2. Pick a customer (e.g., Accesology), Amount 50, Memo "smoke modal backdate".
3. Click Collect.
4. **Expected:** Modal closes, success toast.
5. Verify in odoo shell:

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
p = env['account.payment'].search([('memo', '=', 'smoke modal backdate')], limit=1)
print('NAME', p.name, 'DATE', p.date, 'JOURNAL', p.journal_id.name)
EOF" 2>&1 | tail -3
```
Expected: date = yesterday (e.g., `2026-06-14`).

- [ ] **Step 12: Cleanup smoke payment**

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
p = env['account.payment'].search([('memo', '=', 'smoke modal backdate')])
print('cleaning', p.mapped('name'))
p.action_cancel()
p.unlink()
env.cr.commit()
print('done')
EOF" 2>&1 | tail -3
```

---

## Task 3: Final acceptance checklist

**Files:** (none — verification only)

- [ ] **Step 1: Confirm all spec acceptance items**

Tick each one based on Tasks 1 + 2 verification output:

| Spec requirement | Verified in |
|---|---|
| Bank journal selected → Date input visible, default today | Task 2 Step 9 |
| Cash journal selected → Date input NOT visible | Task 2 Step 10 |
| Switching journal cash↔bank toggles field, state preserved | Task 2 Step 10 |
| Bank receipt with past date posts, payment.date = picked date | Task 1 Step 9, Task 2 Step 11 |
| Bank receipt with future date → UserError | Task 1 Step 10 |
| Cash always today (defensive override) | Task 1 Step 11 |
| Bank receipt with date in locked period → Odoo UserError | (deferred — no locked period configured) |
| All existing gates intact (amount>0, partner, vendor-only, session, journal type/company) | (regression check: Task 2 Step 11 confirms normal flow still works) |
| Manifest at `18.0.3.0.0` (or higher patch) | Task 2 Step 8 output |

- [ ] **Step 2: Regression sanity — Pay Out via bank backdated**

User action: open modal in Pay Out mode (Product Screen → Pay Out button), pick a bank journal, set date to yesterday, pick a vendor partner (FS Brothers), enter amount, confirm. Verify payment posts with backdated `account.payment.date` and `payment_type='outbound'`.

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
p = env['account.payment'].search([('partner_id.name', '=', 'FS Brothers'), ('pos_session_id', '!=', False)], order='id desc', limit=1)
print('NAME', p.name, 'DATE', p.date, 'DIR', p.payment_type, 'JOURNAL', p.journal_id.name)
EOF" 2>&1 | tail -3
```
Expected: most recent row shows yesterday's date + `outbound`.

- [ ] **Step 3: Cleanup regression payment**

The Step 2 regression test creates one payment on FS Brothers via the modal. Use its specific memo (e.g., "smoke modal pay out backdate") in the cleanup query.

```bash
ssh deploy@46.224.228.181 "cd ~/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http <<'EOF'
p = env['account.payment'].search([('memo', '=', 'smoke modal pay out backdate')])
print('cleaning', p.mapped('name'))
p.action_cancel()
p.unlink()
env.cr.commit()
print('done')
EOF" 2>&1 | tail -3
```

Plan complete.
