# POS Expense Payment Source — Design

**Date:** 2026-09-04
**Addon:** `sfya_pos_expense_bridge`
**Status:** Approved (design)

## Goal

Let the user choose, per company-paid expense, where the money comes from: the
POS cash drawer (today's only behavior) or a bank account. Replace the current
"Deduct from POS cash drawer" checkbox with a **"Payment Source"** dropdown of
cash/bank journals. Bank-paid expenses must reduce the chosen bank account with
a line memo'd as the expense name, reconciled so it matches the real bank
statement.

## Background — current behavior

`sfya_pos_expense_bridge` mirrors company-paid `hr.expense` into POS cash:

- `hr.expense.affects_pos_cash` — boolean, computed `= (payment_mode == 'company_account')`, stored, `readonly=False`. Rendered as a checkbox on the expense form (`views/hr_expense_views.xml`).
- On `hr.expense.sheet` reaching `state == 'done'` (payment registered), `_compute_state` override calls `_sfya_push_pos_cash_out()`, which for each flagged, not-yet-pushed line calls `session.try_cash_in_out('out', amount, 'Expense: <name>', ...)` on the open POS session — or queues (`pos_cash_pending`) for the next session open (`pos_session._sfya_sweep_pending_expenses`).

Observed GL per POS-cash expense (verified on prod, expense 272 "Shopping Bag" 1100):

- **Expense move** (sheet journal = Shop Cash, id 7): `Dr <expense acct>` / `Cr 1126005 Outstanding Payments` — left **unreconciled**.
- **POS cash-out move** (`try_cash_in_out`): `Cr 1126002 Cash` / `Dr 2226000 Suspense Account` — left **unreconciled**.

Net cash + P&L correct; two clearing accounts (`1126005` credit, `2226000`
debit) accumulate and never reconcile. This is a pre-existing mess, **out of
scope** here (see Non-Goals).

**POS cash journal identity:** the journal of the POS cash payment method —
`env['pos.payment.method'].search([('is_cash_count','=',True)]).journal_id`.
Currently journal id 7 (Shop Cash). Detected dynamically, not hardcoded.

## Design

### 1. Field: Payment Source dropdown

Add to `hr.expense`:

- `sfya_payment_source_journal_id` — `Many2one('account.journal')`, domain
  `[('type','in',('cash','bank')), ('company_id','=', company)]`, `copy=False`.
- Default (compute, `store=True`, `readonly=False`): the POS cash journal
  (detected as above). So a company-paid expense created and left untouched
  behaves exactly as today.
- Recomputes its default only while unset / when `payment_mode` changes to
  `company_account`; user override persists.

Keep `affects_pos_cash` as a **computed helper** (stored, readonly) so the
existing queue/sweep logic and old records keep working:

- `affects_pos_cash = (payment_mode == 'company_account' and
  sfya_payment_source_journal_id == <POS cash journal>)`.

`affects_pos_cash` is no longer user-editable; it is derived from the dropdown.

### 2. Form view

- Remove the `affects_pos_cash` checkbox widget.
- Add the `sfya_payment_source_journal_id` dropdown in its place (after
  `payment_mode`), visible only when `payment_mode == 'company_account'`.
- Keep the read-only `pos_cash_pending` / `pos_cash_session_id` indicators
  (still meaningful for the POS-cash path).

### 3. Routing on sheet → done

Generalize `_sfya_push_pos_cash_out` to `_sfya_route_company_payments`. For
each company-paid line not yet routed (`not pos_cash_session_id` for the cash
path; a new guard for the bank path — see below):

- **Journal is the POS cash journal** → existing `try_cash_in_out('out', …)`
  mirror + queue-if-no-session. Unchanged.
- **Journal is a bank/other cash journal** → create a reconciled outbound
  payment (below). No POS session, no queue.

### 4. Bank path — reconciled payment

For a bank-routed line:

1. Create an outbound `account.payment`:
   - `payment_type='outbound'`, `partner_type='supplier'`,
     `partner_id` = the expense's vendor/employee partner (fallback: the
     employee's `work_contact_id`/related partner),
   - `journal_id` = chosen bank journal,
   - `amount` = `total_amount_currency`,
   - `memo` = `'Expense: <name>'`.
2. Post it. Result: `Cr <bank account>` (bank ledger shows the memo'd line,
   matches the statement) / `Dr <bank outstanding/payable>`.
3. Reconcile the payment's outstanding/payable leg against the expense move's
   `Cr 1126005 Outstanding Payments` leg so nothing dangles.
   - Both legs must sit on the **same account** to reconcile. The
     implementation plan resolves the exact account: either (a) set the bank
     payment's destination to `1126005 Outstanding Payments`, or (b) post the
     expense move's credit to the bank journal's outstanding account. The plan
     picks whichever Odoo 18 supports cleanly for `hr.expense` and documents
     it. The invariant for review: **after routing, the expense's Outstanding
     Payments (or chosen clearing) leg is fully reconciled and the bank GL
     account is reduced by the exact amount with memo `Expense: <name>`.**

Add a guard field to make the bank push idempotent (mirrors
`pos_cash_session_id` for the cash path), e.g.
`sfya_bank_payment_id = Many2one('account.payment', readonly, copy=False)`.
A line is "already routed" if it has either `pos_cash_session_id` or
`sfya_bank_payment_id`.

### 5. Backfill (one-time)

On module upgrade, a post-init / migration step sets
`sfya_payment_source_journal_id` = POS cash journal for all existing
`hr.expense` with `payment_mode == 'company_account'` and the field unset.
Display-only — creates/touches **no** accounting moves. Existing
`affects_pos_cash` values remain consistent (still true for these).

## Non-Goals

- **Not** fixing the pre-existing POS-cash clearing mess (`1126005` +
  `2226000` dangling entries). Kept as a separate future task per user
  decision.
- **Not** changing the employee-reimbursement (`own_account`) flow.
- **Not** repairing/reconciling the ~267 historical POS-cash expense pairs.

## Testing

- **Default:** new `company_account` expense → `sfya_payment_source_journal_id`
  defaults to POS cash journal; `affects_pos_cash` computes True.
- **POS-cash path unchanged:** pick POS cash journal, pay → one POS cash-out on
  the open session (or queued when none open), same GL as today.
- **Bank path:** pick a bank journal, pay → no POS cash-out; an
  `account.payment` posted on that bank journal, memo `Expense: <name>`, bank
  GL reduced by amount; expense clearing leg fully reconciled;
  `sfya_bank_payment_id` set; idempotent on re-trigger.
- **Visibility:** dropdown hidden when `payment_mode == 'own_account'`.
- **Backfill:** after upgrade, all pre-existing company-paid expenses carry the
  POS cash journal in the new field; no new moves created (move count
  unchanged).

## Files

- `models/hr_expense.py` — new field, default compute, `affects_pos_cash`
  recompute.
- `models/hr_expense_sheet.py` — generalize routing; bank payment + reconcile.
- `views/hr_expense_views.xml` — checkbox → dropdown.
- `models/pos_session.py` — sweep unchanged (cash path only); verify it ignores
  bank-routed lines (`affects_pos_cash` now false for bank).
- `migrations/18.0.2.0.0/post-migrate.py` (or post_init_hook) — backfill.
- `__manifest__.py` — version bump `18.0.1.0.0` → `18.0.2.0.0`.
