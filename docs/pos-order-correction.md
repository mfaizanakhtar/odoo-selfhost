# Posted POS Order Correction

**Status:** Merged to `main` in PR #4 and active on production. `sfya_customer_statement` is upgraded; `sfya_pos_order_correction` is installed. `SFYA/0810` was aligned to **ZM Zone (Lahore)** with audit record `CORR/2026/0001`.
**Date:** 2026-11-22
**Modules:** `sfya_customer_statement` (18.0.2.4.1), `sfya_pos_order_correction` (18.0.1.2.1)

## Why this exists

A completed POS order can have the wrong customer, price, discount, or quantity.
Odoo locks the posted order. The previous workaround was to change the linked
invoice, which left the POS order and the customer statement disagreeing with the
receivable ledger.

The correction feature keeps the customer statement clean: one corrected sale,
with no return/replacement rows and no correction banner.

## What is implemented

### 1. Customer statement attribution

`sfya_customer_statement` now:

- Uses the **posted invoice customer** as the owner of an invoiced POS row.
- Falls back to the POS order customer only when there is no posted invoice.
- Groups rows by invoice, so a multi-order invoice is shown once.
- Uses the **invoice date** for invoiced rows, matching the receivable ledger.
- Omits POS orders whose linked invoice is draft or cancelled.
- Does not duplicate a linked invoice in the separate invoice section.
- Handles refunds with the absolute invoice amount and the invoice direction.
- Omits a refund of an invoiced sale when the refund has no invoice and no
  payment, because it has no financial effect. This prevents a voided POS
  refund from appearing as a second refund row.

### 2. Manager-only Correct Order action

New addon `sfya_pos_order_correction` adds **Correct Order** to invoiced POS
orders. It is visible only to the `POS Order Correction` group.

Supported corrections:

| Correction | Behavior |
|---|---|
| Customer | Align the order to an existing invoice customer, or reset/repost a fully unpaid Customer Account invoice under a new customer |
| Price / discount | Edit the invoice product lines; invoice and statement show the new values |
| Quantity | Edit the invoice product line quantity per line; adjust stock only for the difference |

The original POS order lines are kept for audit. The POS order form shows a
correction group with the corrected invoice total. The **customer statement does
not read or display that banner**.

### 3. Quantity and stock adjustment

Quantity is corrected **per invoice product line**, only for open Customer Account
invoices.

- Lower quantity: the excess is returned from the customer location to stock.
- Higher quantity: available stock is checked, and an extra delivery is created.
- Stock adjustment pickings are linked to the correction audit record.
- The invoice and statement show the new quantity.

Quantity correction is rejected for:

- lot or serial tracked products;
- products with no completed stock delivery;
- duplicate product lines or multiple completed stock moves;
- insufficient stock when increasing;
- paid, partial, cash, or bank-settled invoices;
- refunded, reversed, locked, draft, cancelled, or multi-order invoices.

### 4. Eligibility and safety

Customer, price, and quantity changes that touch the invoice require:

- an invoiced POS order;
- a posted `out_invoice`;
- invoice linked to exactly this POS order;
- fully unpaid and unreconciled;
- no matched payments, credit notes, reversals, hash, cancel request, tax cash
  basis restriction, or fiscal/tax lock that prevents reset;
- Customer Account (`pay_later`) POS payments only, or no payments;
- no refunded POS lines;
- same company and currency.

A customer-only alignment to the **existing invoice customer** is allowed even if
the invoice is paid or partially paid, because no accounting document is changed.

### 5. Audit and guards

Every correction creates an append-only `sfya.pos.correction` record with:

- order, invoice, correction type;
- old/new order customer and old invoice customer;
- old/new total;
- reason, user, company, timestamp;
- per-line old/new quantity, price, and discount;
- linked stock adjustment pickings.

The correction and correction-line records cannot be edited, deleted, or copied.

Direct customer edits on posted POS-linked invoices and receivable journal items
are blocked with a message directing staff to the POS correction action.

## What is not included

These are intentionally outside the current implementation:

1. **Product changes.** Swapping the product on a posted order needs a stock
   swap, return, and replacement delivery.
2. **Paid cash/bank corrections.** If the customer already paid cash or bank,
   changing price or quantity requires a refund or extra charge, or a credit
   note/reissue. The current action rejects these.
3. **Uninvoiced POS orders.** The Correct Order button is only on invoiced
   orders.
4. **Lot or serial tracked quantity changes.** These need lot/serial selection
   and are rejected.
5. **Partial-line/quantity corrections with credit notes.** Compensating
   documents and statement consolidation are not built.
6. **Customer portal changes.** The feature does not change what the portal
   displays.
7. **Rewriting old printed receipts/statements or closed-session reports.**
   Those remain historical; current records and newly generated statements show
   the correction.
8. **Automatic production deployment or module upgrade.** Merging code does not
   install/upgrade the modules on production.

## How staff use it

1. Open an invoiced POS order.
2. Click **Correct Order**.
3. Choose the corrected customer, price/discount, and/or quantity.
4. Review the change and enter a reason.
5. Apply.
6. The invoice and statement show the corrected values; the POS order shows the
   correction banner and links to the audit record.

For `SFYA/0810`, the invoice is already under **ZM Zone (Lahore)** and unpaid.
The correction aligns the POS order from **ZM** to **Lahore**. No invoice reset,
stock movement, refund, or replacement is created.

## Production activation

The production database was backed up before the module work to
`~/odoo-pre-module-20261122T142612.dump` on the Odoo server.

- `sfya_customer_statement` upgraded to `18.0.2.4.1`, including the voided-refund
  statement fix.
- `sfya_pos_order_correction` installed and visible to the `POS Order Correction`
  group; the administrator is a member.
- The Lahore statement showed one Rs 48,000 POS sale for `SFYA/0810`; the ZM
  statement did not show that order.
- `SFYA/0810` was then aligned from ZM to ZM Zone (Lahore) with audit record
  `CORR/2026/0001`.
- The invoice remained `INV/2026/00800`, posted and unpaid, with residual
  Rs 48,000. No stock or payment was changed.

## Verification status

Static checks pass:

```bash
python3 -m compileall addons/sfya_customer_statement addons/sfya_pos_order_correction
python3 - <<'PY'
from xml.etree import ElementTree
from pathlib import Path
for base in ('addons/sfya_customer_statement', 'addons/sfya_pos_order_correction'):
    for path in Path(base).rglob('*.xml'):
        ElementTree.parse(str(path))
print('XML OK')
PY
```

The merge deploy workflow completed the code rsync and container restart, but
its final Cloudflare health check received HTTP 403 from the GitHub runner. The
Odoo container itself returned HTTP 200 for `/web/login` when checked from
inside the server. No application error was found.

The Odoo test suite was run on a fresh scratch database on the production host:
**11 tests, 0 failures**. The scratch database and its filestore were then
dropped. The new regression test covers a refund of an invoiced sale with no
invoice and no payment.

For reference, the test command is:

```bash
docker compose run --rm odoo odoo -d sfya_correction_test \
  -i sfya_customer_statement,sfya_pos_order_correction \
  --test-enable --test-tags /sfya_customer_statement,/sfya_pos_order_correction \
  --stop-after-init --no-http
```

### SFYA/0922 voided refund

`SFYA/0922` had two POS refund orders for the same Rs 47,800 sale:

- order 1030: no invoice, no payment, no journal entry; its stock return was
  reversed;
- order 1032: invoiced as `RINV/2026/00101`, the valid refund.

The statement counted both, so it closed at Rs 84,900 while the receivable
ledger was Rs 132,700. After the fix, the statement shows one sale, the corrected
sale `SFYA/0923`, and one refund, closing at **Rs 132,700**.

## Related documents

- `docs/superpowers/specs/2026-11-22-pos-order-correction-design.md`
- `docs/superpowers/plans/2026-11-22-pos-order-correction.md`
- `docs/ARCHITECTURE.md`

## Commit history

- `ace6c61` — statement attribution fix
- `598f161` — customer correction and audit
- `734effd` — invoice price/discount correction with POS-only banner
- `4e7a69a` — per-line quantity correction with stock adjustment
- `a213a19` — omit voided uninvoiced refunds from the statement (PR #6)
