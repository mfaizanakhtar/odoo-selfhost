# Posted POS Order Correction — Design

**Date:** 2026-11-22
**Project:** Odoo 18 Community, SFYA POS
**Modules:** `sfya_customer_statement`, new `sfya_pos_order_correction`

## Problem

A completed POS order can have the wrong customer. Odoo locks the posted order,
so staff change the linked invoice instead. The POS order keeps its old customer,
and the customer statement (which reads the POS order) disagrees with the
receivable ledger.

Return-plus-replacement is the accounting-safe workaround for quantity and stock
changes, but it produces visible sale/refund/replacement rows on the customer
statement. The client wants one clean corrected sale.

## Scope of this phase

### Statement fix

For a POS order with a **posted** linked invoice, the statement owner is the
invoice's `partner_id`. Otherwise the owner is the POS order's `partner_id`.
Statement rows are grouped by posted invoice so one invoice produces one row.

A POS order linked to a draft or cancelled invoice is omitted from the statement:
there is no posted receivable to report, so showing the order amount would
inflate the balance.

Invoiced rows use the invoice date as the statement date, so the row period
matches the receivable ledger. Non-invoiced rows keep the POS order date.

Refund rows use the absolute invoice total and the invoice `move_type` to decide
debit/credit direction.

### Customer correction

A manager opens a posted order and chooses **Correct Order**.

Two safe paths:

1. **Align the order to the existing invoice customer.** This only changes the
   POS order's `partner_id`. It is allowed even if the invoice is paid or
   partially paid, because no accounting document is changed. The invoice
   customer is already the statement owner.
2. **Change the invoice customer.** This resets the posted invoice to draft,
   changes the customer, updates the order while the invoice is draft, and
   reposts. It is allowed only when:
   - the invoice is an `out_invoice`;
   - it is fully unpaid and unreconciled;
   - it has no payments, credit notes, reversals, lock, hash, or tax-cash-basis
     restriction;
   - every POS payment is `pay_later` (Customer Account), or there are no
     payments;
   - the order has no refunded lines;
   - the invoice is linked to exactly this one POS order;
   - order and invoice currencies and totals agree.

If the invoice already has the target customer, only path 1 runs.

## Non-goals

- Price, discount, quantity, product, or tax changes.
- Paid/partial invoice customer changes.
- Cash/bank-settled invoice customer changes.
- Uninvoiced POS orders.
- Credit notes, refunds, returns, or replacement orders.
- Customer portal visibility changes.
- Rewriting closed-session reports or previously printed documents.

Price/discount correction is a later phase because the review found that editing
the invoice price leaves the posted POS line stale, and mapping order lines to
invoice lines is unsafe when combo sections or note lines are present.

## Data model

`sfya.pos.correction`

- `name`, `order_id`, `invoice_id`, `correction_type`
- `old_partner_id`, `new_partner_id`
- `old_invoice_partner_id`
- `old_total`, `new_total`, `currency_id`
- `reason`, `user_id`, `company_id`

The model is append-only: no write, no unlink, no copy.

`button_draft()` removes analytic distributions and detaches the stored invoice
PDF; the correction record and chatter remain the audit trail, and the invoice is
reposted immediately in the same transaction.

## Guards

- A posted POS-linked invoice `partner_id` cannot be changed directly; direct
  `account.move.line` receivable-partner changes are also blocked.
- There is no `pos.order` constraint requiring equality: the historical
  `SFYA/0810` state and the draft-invoice correction window must remain valid.
- A computed `sfya_invoice_customer_mismatch` flag on the POS order warns staff.
- The wizard validates eligibility; no context bypass is used.

## Acceptance

- `SFYA/0810` can be aligned from ZM to ZM Zone (Lahore) without touching the
  invoice, stock, or payments.
- The Lahore statement shows one Rs 48,000 sale; ZM shows none.
- A linked invoice is not duplicated on the statement.
- A draft or cancelled linked invoice produces no statement row.
- Paid, partial, cash/bank, locked, reversed, refunded, multi-order, and
  mismatched cases are rejected with a clear message.
- Every correction is audited; the audit record cannot be edited, deleted, or
  copied.
