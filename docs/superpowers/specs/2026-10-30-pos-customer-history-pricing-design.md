# POS Customer History Pricing — Design

**Date:** 2026-10-30
**Project:** Odoo 18 Community, SFYA POS
**Status:** Draft for user approval

## Intent

When a customer is assigned to a POS order, use the original unit price most
recently charged to that exact customer for each product. This keeps customer
specific negotiated product prices available to cashiers without changing the
company's normal pricelist. The rule must work whether the cashier selects the
customer before or after adding products.

## Current data and existing behavior

- Odoo has `sale`, `sale_management`, and `account` installed, but currently has
  no `sale.order` records.
- The last Odoo MCP check found no `sale.order` records, but did find completed
  POS sales and posted customer invoices, including a standalone invoice with
  product lines.
- The customer statement already reads completed POS orders and posted
  customer invoices, skipping invoices linked to POS so they are not counted
  twice. See `sfya_customer_statement/models/res_partner.py`.
- `sfya_pos_receipt` has an order-level discount popup. Discounts are
  transaction-specific and must not become the remembered product price.

## Agreed behavior

### Price history sources

For the selected customer and exact product variant, compare:

1. Positive-quantity product lines from completed POS orders in `paid`, `done`,
   or `invoiced` state, using the POS order date.
2. Product lines from posted customer invoices (`out_invoice`) that are not
   linked to a POS order, using the invoice date.

Use the newest matching sale across both sources. Exclude cancelled/draft
documents and refund documents/negative-quantity lines as price candidates.
If a sale is later fully refunded, its original positive sale line remains
eligible; the refund itself does not set or erase the remembered price. Do not
use `sale.order` records in this feature; there are none in the current
database and a confirmed order may still not represent a completed sale.

Compare POS datetimes as company-local business dates with invoice dates. If
two candidates share a date, use source-record creation time and then stable
record/line IDs as deterministic tie-breakers. If a single transaction has
multiple matching product lines, normalize their units and use its latest
line by creation time, then line ID.

### Price value

- Reuse the original `price_unit` recorded on the winning POS or invoice line.
- Ignore the historical line discount when calculating the remembered price.
- Preserve any discount on the current POS order as a separate, current-sale
  adjustment.
- Match the exact selected customer and product variant. Use Odoo's unit
  conversion if the historical line's unit differs from the POS unit. Convert
  from the source line currency to the active POS currency using Odoo's
  currency conversion at the source transaction date. If POS pricelists are
  disabled and the order has no active pricelist, the POS currency is the active
  company currency; the backend accepts explicit `pricelist_id=False` and uses
  that currency. The currently observed posted customer invoice history is all PKR.
- If no history exists, use the order's standard Odoo POS price: the active
  pricelist price, or the product list price in company currency when POS
  pricelists are disabled.

### POS interaction

- If the customer is selected first, apply the resolved price as each product
  is added.
- If products are already on the order, selecting or changing the customer
  recalculates every existing line.
- The historical price replaces an existing manually entered unit price when
  a customer is selected. Current discounts remain separate.
- Clearing the customer returns the lines to the standard POS price behavior.
- Changing the active pricelist re-resolves customer history in the new pricelist currency; a late lookup for the old pricelist cannot replace that result.
- When an order is completed offline and uploaded later, successful synchronization invalidates the cached prices for its customer and products so the next order sees the newly posted sale.

## Goals

- Apply the same customer/product price regardless of selection order.
- Choose the latest original unit price across POS and non-POS posted invoices.
- Keep current-sale discounts separate from stored sale history.
- Avoid double-counting POS invoices.
- Keep POS usable if a history lookup is unavailable; use the regular pricelist
  for that lookup and continue checkout.

## Non-goals

- Use quotations or sales orders as price history.
- Change pricelists, customer records, historic transactions, or accounting
  entries.
- Infer a remembered product price from discounts or order totals.
- Change customer statement reports.

## Implementation direction

This is POS pricing behavior with read-only accounting history. Implement it in
a dedicated SFYA POS addon using the repository's Odoo 18 Python and OWL/JS
patterns. Fetch history by exact customer/product when needed, batch lookups for
existing cart lines after customer, product, or pricelist changes, and cache
resolved pairs for the active POS session. Invalidate cache after successful
order upload, including a deferred upload after offline completion. A lookup
failure must leave the POS order usable at its standard POS price.

## Acceptance examples

- Customer selected, then product added: newest historical original unit price
  is used.
- Product added, then customer selected: the existing line is updated to that
  customer's newest historical original unit price.
- Newest source is a standalone posted invoice: use that invoice's `price_unit`.
- Newest source is a POS sale with a discount: use its `price_unit`; do not
  import its discount.
- POS order has a linked invoice: consider the POS line once, not twice.
- No matching history or a failed lookup: keep the normal POS pricelist price.
- Customer changes after a manual unit-price edit: apply the new customer's
  historical price to that existing line.
- The active pricelist changes during a lookup: the latest-pricelist result
  applies, and the stale response cannot overwrite it.
- An offline-completed order uploads later: successful sync invalidates its
  customer/product cache so the following order uses the new sale history.

## Builder choices

- Implement async lookup and POS session caching using this repository's
  pinned Odoo 18 interfaces. The builder review found an existing pattern in
  `point_of_sale._assets_pos` and `this.pos.data.call`.
- Apply the specified date, line, unit, and currency normalization rules in the
  implementation plan.
