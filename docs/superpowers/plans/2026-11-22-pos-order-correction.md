# Posted POS Order Correction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align an invoiced POS order to its correct customer safely, keep one clean corrected sale on the customer statement, and record an immutable audit trail.

**Architecture:** Two changes. `sfya_customer_statement` attributes posted-invoice POS rows to the invoice customer, groups by invoice, uses the invoice date, and omits non-posted linked invoices. New addon `sfya_pos_order_correction` adds a manager-only wizard that either aligns the order to the existing invoice customer or resets/reposts an open-credit invoice under a new customer.

**Tech Stack:** Odoo 18 Community, Python 3, Odoo ORM, XML views, Odoo `TestPoSCommon`.

**Spec:** `docs/superpowers/specs/2026-11-22-pos-order-correction-design.md`

> **Status:** The statement fix, customer correction, price/discount, and
> per-line quantity correction are implemented. Price and quantity changes edit
> invoice lines, keep the original POS order lines, show a correction banner on
> the POS order only, and leave the customer statement free of any correction
> banner. Quantity changes return excess stock or create an extra delivery for
> the difference.

## Global Constraints

- Odoo 18 Community only.
- No product, tax, refund, return, replacement, or credit-note changes.
- Price/discount and quantity changes are limited to open Customer Account invoices and are written to the invoice, not the posted POS order lines.
- Do not write posted invoice `partner_id` directly; use `button_draft()` first.
- No context-based security bypass.
- Correction records are append-only: no write, no unlink, no copy.
- Do not add a `pos.order` constraint requiring order/invoice customer equality. It would make the historical state and the draft-repost window invalid.
- Only `invoiced` orders with a posted linked `out_invoice` are eligible.
- Invoice writes require a fully unpaid, unreconciled invoice and Customer Account POS payments.
- Module versions: `sfya_customer_statement` `18.0.2.4.0`; `sfya_pos_order_correction` `18.0.1.0.0`.
- Do not deploy or modify production ERP records as part of this plan.

## Review Focus

- A paid or partially reconciled invoice must never be reset.
- A cash/bank POS order must not be treated as an open credit order.
- A draft/cancelled linked invoice must not produce a live statement debit.
- A refund row must not corrupt the credit total or closing balance.
- An invoiced row must appear in the period of its invoice date, not its POS order date.

---

### Task 1: Statement attribution, grouping, and period rules

**Files:**
- Modify: `addons/sfya_customer_statement/models/res_partner.py:19-72`
- Modify: `addons/sfya_customer_statement/__manifest__.py`
- Create: `addons/sfya_customer_statement/tests/__init__.py`
- Create: `addons/sfya_customer_statement/tests/test_statement_attribution.py`

**Interfaces:**
- Consumes: `res.partner.get_statement_data(date_from, date_to, include_drafts=False, show_aging=False) -> dict`
- Produces: same signature; POS rows follow the posted invoice customer and date.

- [ ] **Step 1: Write failing tests**

Use `@tagged('post_install', '-at_install')` and `TestPoSCommon`. Helpers create a session, product, order, invoice, and link. To create a posted mismatch without tripping later guards, create/link with the same customer, then `button_draft()`, change the invoice customer, and `action_post()`.

Tests:

```python
def test_invoiced_order_belongs_to_invoice_customer(self):
    # order + invoice on customer A; invoice reposted on B.
    self.assertFalse(self._pos_rows(self.customer))
    rows = self._pos_rows(self.other_customer)
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["debit"], 48000)

def test_linked_invoice_is_not_a_second_statement_row(self):
    # one pos row, zero invoice rows for the invoice partner.

def test_uninvoiced_order_keeps_order_customer(self):
    # paid order with no invoice appears under the order customer.

def test_multi_order_invoice_emits_one_row(self):
    # two orders linked to one invoice; one row, invoice total once.

def test_cancelled_or_draft_invoice_is_omitted(self):
    # linked invoice is draft, then cancelled; no pos row for either partner.

def test_invoiced_row_uses_invoice_date(self):
    # order date in December, invoice date in January.
    # December statement has no row; January statement has one.

def test_refund_uses_absolute_amount(self):
    # posted out_refund linked to a POS refund order.
    # credit is positive and closing balance is correct.
```

- [ ] **Step 2: Run tests; expect failure**

```bash
docker compose run --rm odoo odoo -d sfya_statement_test \
  -i sfya_customer_statement --test-enable \
  --test-tags /sfya_customer_statement --stop-after-init --no-http
```

- [ ] **Step 3: Implement grouping**

Remove the date predicates from the SQL domain and filter in Python by the canonical document date. Search candidates by either partner:

```python
pos_domain = [
    '|',
    ('partner_id', '=', self.id),
    ('account_move.partner_id', '=', self.id),
]
if not include_drafts:
    pos_domain.append(('state', 'in', ['paid', 'done', 'invoiced']))

groups = {}
for order in self.env['pos.order'].search(pos_domain, order='date_order, id'):
    inv = order.account_move
    if inv:
        if inv.state != 'posted':
            continue
        if inv.partner_id != self:
            continue
        if inv.invoice_date and not (date_from <= inv.invoice_date <= date_to):
            continue
        key = ('invoice', inv.id)
    else:
        order_date = order.date_order.date() if order.date_order else False
        if not order_date or not (date_from <= order_date <= date_to):
            continue
        if order.partner_id != self:
            continue
        key = ('order', order.id)
    groups.setdefault(key, []).append(order)
```

For each group:

- `cash_received` = sum of non-`pay_later` payments across all orders.
- Invoice group:
  - `amount = abs(inv.amount_total)`
  - `is_refund = inv.move_type == 'out_refund'`
  - `date = inv.invoice_date`
  - `create_date = min(order.create_date for order in orders)`
  - lines from invoice product lines
  - one order: `doc_name = primary.pos_reference or primary.name`, `doc_model='pos.order'`, note `Invoice <inv.name>`
  - multiple orders: `doc_name = inv.name`, `doc_model='account.move'`, `doc_id=inv.id`
- Order group: existing POS line/amount behavior and dates.
- Debit/credit:
  - sale: `debit = amount`, `credit = cash_received`
  - refund: `debit = abs(cash_received)`, `credit = amount`

- [ ] **Step 4: Run tests; expect pass**

- [ ] **Step 5: Commit**

```bash
git add addons/sfya_customer_statement
git commit -m "fix(statement): attribute invoiced POS rows to invoice customer"
```

---

### Task 2: Correction addon skeleton, security, and audit model

**Files:**
- Create: `addons/sfya_pos_order_correction/__init__.py`
- Create: `addons/sfya_pos_order_correction/__manifest__.py`
- Create: `addons/sfya_pos_order_correction/models/__init__.py`
- Create: `addons/sfya_pos_order_correction/models/sfya_pos_correction.py`
- Create: `addons/sfya_pos_order_correction/security/correction_security.xml`
- Create: `addons/sfya_pos_order_correction/security/ir.model.access.csv`
- Create: `addons/sfya_pos_order_correction/data/ir_sequence.xml`
- Create: `addons/sfya_pos_order_correction/views/correction_views.xml`

**Interfaces:**
- Produces: `sfya.pos.correction` with `name`, `order_id`, `invoice_id`, `correction_type`, `old_partner_id`, `new_partner_id`, `old_invoice_partner_id`, `old_total`, `new_total`, `currency_id`, `reason`, `user_id`, `company_id`.
- Produces: `group_sfya_pos_order_correction`.

- [ ] **Step 1: Create the manifest**

`depends`: `['point_of_sale', 'account']`. Data order: security XML, ACL, sequence, wizard views, correction views, POS order views.

- [ ] **Step 2: Add the audit model**

- `_name = 'sfya.pos.correction'`, `_order = 'id desc'`.
- `name` default `'New'`; `create` assigns `ir.sequence.next_by_code('sfya.pos.correction')`.
- `correction_type`: `customer` only for this phase.
- `currency_id` related to invoice, stored.
- `company_id` related to order, stored.
- `copy`, `write`, `unlink` raise `UserError('Correction records are append-only.')`.

- [ ] **Step 3: Add security**

Group `group_sfya_pos_order_correction` with implied `point_of_sale.group_pos_manager` and `account.group_account_invoice`. Add the admin user to the group.

ACL:

- correction: read/create, no write/unlink.
- wizard: read/write/create/unlink.
- wizard line? No line model in this phase.
- Add a multi-company record rule on `sfya.pos.correction`.

- [ ] **Step 4: Add correction list/form views**

List: name, create_date, order, invoice, old/new customer, old/new total, user.
Form: header/status, customer changes, invoice, reason, audit metadata.
No menu; the POS order smart button opens the list.

- [ ] **Step 5: Commit**

```bash
git add addons/sfya_pos_order_correction
git commit -m "feat(pos): add correction audit model and security"
```

---

### Task 3: POS helpers and posted-invoice guards

**Files:**
- Create: `addons/sfya_pos_order_correction/models/pos_order.py`
- Create: `addons/sfya_pos_order_correction/models/account_move.py`
- Modify: `addons/sfya_pos_order_correction/models/__init__.py`

**Interfaces:**
- `pos.order.sfya_invoice_customer_mismatch: bool`
- `pos.order.sfya_correction_count: int`
- `pos.order.action_view_sfya_corrections() -> dict`
- `account.move.write`, `account.move.line.write` guards.

- [ ] **Step 1: Add POS helpers**

- Computed mismatch: `inv.state == 'posted' and inv.partner_id != order.partner_id`.
- Computed correction count.
- `action_view_sfya_corrections` opens the list filtered by order.
- Do **not** add a `@api.constrains` equality rule; the historical state and draft-repost window must remain valid.

- [ ] **Step 2: Add guards**

`account.move.write`, before `super()`:

```python
if 'partner_id' in vals:
    for move in self:
        if (
            move.state == 'posted'
            and move.move_type == 'out_invoice'
            and move.pos_order_ids
            and vals['partner_id'] != move.partner_id.id
        ):
            raise UserError(_('Correct the customer from the linked POS order.'))
```

`account.move.line.write`, before `super()`:

```python
if 'partner_id' in vals:
    for line in self:
        move = line.move_id
        if (
            move.state == 'posted'
            and move.move_type == 'out_invoice'
            and move.pos_order_ids
            and line.account_id.account_type == 'asset_receivable'
            and vals['partner_id'] != line.partner_id.id
        ):
            raise UserError(_('Correct the customer from the linked POS order.'))
```

Do not add a context bypass. Document that partner-merge and bank-reconciliation
flows may need to use their standard mechanisms.

- [ ] **Step 3: Commit**

```bash
git add addons/sfya_pos_order_correction/models
git commit -m "feat(pos): guard posted POS invoice customer edits"
```

---

### Task 4: Customer correction wizard

**Files:**
- Create: `addons/sfya_pos_order_correction/wizards/__init__.py`
- Create: `addons/sfya_pos_order_correction/wizards/correction_wizard.py`
- Create: `addons/sfya_pos_order_correction/wizards/correction_wizard_views.xml`
- Modify: manifest data list

**Interfaces:**
- `sfya.pos.correction.wizard`: `order_id`, `invoice_id`, `old_partner_id`, `new_partner_id`, `payment_summary`, `reason`.
- `action_apply()` returns `{'type': 'ir.actions.act_window_close'}`.

- [ ] **Step 1: Add wizard fields**

- `order_id` required, readonly.
- `invoice_id` related.
- `old_partner_id` related.
- `new_partner_id` required; default to the posted invoice partner, else the order partner.
- `payment_summary` computed with method names and amounts.
- `reason` required.

- [ ] **Step 2: Validate**

`_validate()` raises `UserError` when:

- user lacks `group_sfya_pos_order_correction`;
- order state is not `invoiced`;
- invoice missing, not posted, not `out_invoice`, or not linked to exactly this order;
- order and invoice currency differ;
- `abs(invoice.amount_total - order.amount_total)` exceeds the currency rounding;
- any order line has `refunded_qty > 0` or `refunded_orderline_id`;
- target partner inactive, wrong company, or without a receivable account;
- target equals the order customer and the invoice customer (nothing to do).

For a **customer-only order alignment** (`target == invoice.partner_id` and no
invoice write needed), no payment/lock checks are required.

For an **invoice customer change** (`target != invoice.partner_id`), additionally:

- `payment_state == 'not_paid'`;
- `amount_residual == amount_total`;
- no reconciled line, no `matched_debit_ids`/`matched_credit_ids`, no
  `full_reconcile_id`;
- `matched_payment_ids` empty;
- `reversed_entry_id`, `reversal_move_ids`, `reversed_pos_order_id` empty;
- no `inalterable_hash`, no `need_cancel_request`;
- `_check_draftable()` succeeds;
- every POS payment is `pay_later`, or there are none.

- [ ] **Step 3: Apply**

1. `invoice_write_needed = target != invoice.partner_id`.
2. If invoice write needed:
   - `invoice.button_draft()`
   - `invoice.write({'partner_id': target.id})` — the inverse updates lines and
     the payment-term account; do not write `partner_shipping_id` (it is computed
     from `partner_id`) and do not write lines redundantly.
   - `order.write({'partner_id': target.id})` while the invoice is still draft.
   - `invoice.action_post()`.
3. If no invoice write: `order.write({'partner_id': target.id})`.
4. Create the correction record with old/new order and invoice partners, totals,
   reason, user, company.
5. Post chatter notes on order and invoice.
6. Return close action.

- [ ] **Step 4: Add the wizard view**

Form with order, invoice, current/new customer, payment summary, scope warning,
reason, Apply/Cancel. The warning explains that only customer changes are in
this phase.

- [ ] **Step 5: Commit**

```bash
git add addons/sfya_pos_order_correction
git commit -m "feat(pos): add manager customer correction wizard"
```

---

### Task 5: POS order views

**Files:**
- Create: `addons/sfya_pos_order_correction/views/pos_order_views.xml`
- Modify: manifest data list

- [ ] **Step 1: Add the button and warning**

Inherit `point_of_sale.view_pos_pos_form`:

- Header **Correct Order** button, group-only, `state == 'invoiced'`, context
  `{'default_order_id': id}`.
- **Corrections** smart button with `sfya_correction_count`.
- Mismatch warning after `div[@name='button_box']`, with
  `sfya_invoice_customer_mismatch` as an invisible field.
- A correction summary group showing `sfya_correction_count` and the latest
  correction link if present.

- [ ] **Step 2: Commit**

```bash
git add addons/sfya_pos_order_correction/views
git commit -m "feat(pos): expose correction action on POS orders"
```

---

### Task 6: Tests

**Files:**
- Create: `addons/sfya_pos_order_correction/tests/__init__.py`
- Create: `addons/sfya_pos_order_correction/tests/test_correction.py`

- [ ] **Step 1: Add fixtures**

Use `TestPoSCommon`; create a session, product, customer, and second customer.
Helpers `_order`, `_invoice`, `_link`, `_make_mismatch`, `_wizard`.

- [ ] **Step 2: Write tests**

```python
def test_aligns_order_to_existing_invoice_customer(self):
    # invoice on B, order still A; wizard target B updates order only.
    # Assert invoice unchanged and order becomes B.

def test_customer_correction_resets_and_reposts_invoice(self):
    # invoice/order A; wizard target B; invoice partner, lines,
    # payment-term account, and order all become B.
    # Assert invoice name and sequence number are unchanged.
    # Assert invoice still posted and account_move link survives.

def test_rejects_paid_invoice_customer_change(self):
    # real or fixture-paid invoice; expect UserError.

def test_rejects_cash_payment_customer_change(self):
    # add a Cash pos.payment; expect UserError.

def test_rejects_partial_invoice_customer_change(self):
    # partial residual fixture; expect UserError.

def test_rejects_refunded_pos_line(self):
    # order line refunded_qty > 0; expect UserError.

def test_rejects_multi_order_invoice(self):
    # invoice linked to two orders; expect UserError.

def test_rejects_wrong_currency_or_total(self):
    # currency/total mismatch; expect UserError.

def test_rejects_unauthorized_user(self):
    # POS manager without correction group; expect AccessError/UserError.

def test_rejects_empty_reason(self):
    # whitespace reason; expect UserError.

def test_blocks_posted_invoice_partner_write(self):
    # invoice.write partner raises UserError.

def test_blocks_posted_receivable_line_partner_write(self):
    # receivable line write raises UserError.

def test_correction_audit_is_append_only(self):
    # write/unlink/copy raise UserError.

def test_no_changes_to_order_lines_or_payments(self):
    # snapshot before/after.
```

- [ ] **Step 3: Run tests**

```bash
docker compose run --rm odoo odoo -d sfya_correction_test \
  -i sfya_customer_statement,sfya_pos_order_correction \
  --test-enable --test-tags /sfya_customer_statement,/sfya_pos_order_correction \
  --stop-after-init --no-http
```

- [ ] **Step 4: Commit**

```bash
git add addons/sfya_pos_order_correction/tests
git commit -m "test(pos): cover customer correction eligibility and audit"
```

---

### Task 7: Version bump, documentation, and verification

- [ ] **Step 1: Bump versions**

- `sfya_customer_statement`: `18.0.2.3.1` → `18.0.2.4.0`
- `sfya_pos_order_correction`: `18.0.1.0.0`

- [ ] **Step 2: Update docs**

Add a note describing the customer, price/discount, and per-line quantity correction scope and the deferred product/payment phase.

- [ ] **Step 3: Static checks**

```bash
python3 -m compileall addons/sfya_customer_statement addons/sfya_pos_order_correction
python3 - <<'PY'
from xml.etree import ElementTree
from pathlib import Path
for path in Path('addons/sfya_pos_order_correction').rglob('*.xml'):
    ElementTree.parse(str(path))
print('XML OK')
PY
```

- [ ] **Step 4: Staging verification**

1. Open `SFYA/0810`; Correct Order is visible to the group.
2. Apply the Lahore alignment; verify order customer changes.
3. Verify invoice is still posted, unpaid, residual Rs 48,000, same number.
4. Verify Lahore statement has one Rs 48,000 sale and ZM has none.
5. Verify picking, stock move, quantities, prices, and payments are unchanged.
6. Verify a cash-paid invoice customer change is rejected.
7. Verify a draft/cancelled linked invoice produces no statement row.

- [ ] **Step 5: Commit**

```bash
git add addons/sfya_customer_statement/__manifest__.py \
        addons/sfya_pos_order_correction/__manifest__.py README.md
git commit -m "docs(pos): document customer correction scope and rollout"
```

---

## Phase 2 — price/discount (implemented)

- The wizard lists invoice product lines directly; no POS-to-invoice line mapping
  is used.
- The manager edits `new_price_unit` and `new_discount`.
- The invoice is reset/reposted; invoice and statement show the new values.
- The POS order lines stay historical; the order form shows a correction group
  with the corrected invoice total.
- The statement does not read the correction banner fields.
- Price changes require the same open-credit eligibility as customer changes.
- Audit records store old/new price and discount per changed line.

## Phase 3 — per-line quantity (implemented)

- The manager edits `new_qty` on an invoice product line.
- Lower quantity returns the difference from the customer location to stock.
- Higher quantity checks available stock and creates an extra delivery.
- Quantity changes require exactly one completed stock move per product and
  reject lot/serial tracking, missing deliveries, duplicate lines, and
  insufficient stock.
- The invoice and statement show the new quantity; the POS order keeps its
  original line and correction banner.
- Stock adjustment pickings are linked to the correction record.

## Still deferred — product and paid cash/bank cases

- Product changes need a stock swap.
- Paid cash/bank price or quantity changes need a refund or extra charge.
- Statement consolidation for compensating documents remains future work.

## Rollout

1. Deploy the statement fix first; verify statements without changing data.
2. Deploy the correction addon; install/upgrade on staging.
3. Assign `POS Order Correction` to the intended managers.
4. Correct `SFYA/0810` through the wizard.
5. Verify statements, invoice, receivable, and audit.
6. Do not uninstall the addon if audit records must be retained.

## Rollback

- Revert code and upgrade the modules.
- Export audit records before any uninstall.
- Reversing a customer correction requires a new correction; audit records are
  append-only.
