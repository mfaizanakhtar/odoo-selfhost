# POS Customer Overview — Tag Filter and Print Design

## Status

Approved by the user on 2026-10-30. This describes the behavior reviewed in the browser mockup; no product code has been changed.

## Intent

Let POS staff view outstanding balances and collections for a group of customers selected by an existing Odoo Contact Tag, then print the view they are currently using. Tags are assigned on the customer record in Odoo, not edited in the POS overview.

## Goals

- Filter both Customer Overview tabs by one Contact Tag at a time.
- Keep the filter while switching between Outstanding Balances and Recent Collections.
- Preserve the current balance calculations, collection date range, and payment source labels.
- Print only the currently selected tab, including the active filters and a total for the rows shown.
- Preserve the existing tap-a-balance-row-to-collect flow.

## User-facing behavior

### Tag filter

- Add a shared Customer Tag selector above the tab content. It is available on both tabs.
- Default to **All Customers**, which includes tagged and untagged customers.
- List existing Odoo Contact Tags (`res.partner.category`) and allow one selected tag at a time.
- Changing the tag reloads both tab datasets. Switching tabs keeps the selected tag.
- Tags are created and assigned through the normal Odoo customer/contact record form. The POS overview does not add or edit tags.
- A matching tag on either a contact or its commercial parent includes that contact's balance or collection. This supports transactions recorded against a child contact when the tag is on the main customer record.

### Outstanding Balances tab

- Show the same Customer and Balance (PKR) columns and the same balance data as today, limited to partners matching the selected tag.
- Keep current sorting and existing signed balance values; do not change receivable/payable calculation.
- Keep rows clickable to open Collect Payment with the customer preselected.
- Show the existing empty state when no matching balances remain.

### Recent Collections tab

- Keep the current From and To date controls and Refresh action.
- Keep all current inbound collection sources. Continue displaying the POS or Invoice/Manual source label on each row.
- Filter collections by the tag of the payment partner or its commercial parent, in addition to the existing company, state, date, and limit rules.
- Include partner ID in the collection result so filtering is tied to the partner record, not its display name.
- Keep the current newest-first order and 500-row limit. Any printed total is the sum of the rows displayed.

### Print

- Add a **Print view** button to the overview, available on both tabs.
- Clicking it opens the browser's normal print dialog for only the currently open tab; it does not print both tabs together or use the POS receipt printer.
- Print the currently applied tag. For Recent Collections, also print the applied date range and each row's source.
- Print a title, the filtered table, a generated date/time, and a total of the rows shown. Use a regular page layout suitable for a normal printer or Save as PDF.
- The printout follows the current filter values and the data currently loaded in the overview.

## Data and implementation scope

- Extend the existing `sfya_pos_cash_movement` addon. Do not add an addon, custom tag model, or database table.
- Use standard Odoo Contact Tags.
- Extend the existing `res.partner.get_customer_balances()` and `account.payment.get_recent_collections()` POS RPCs, or add a small companion RPC if tag choices cannot be sourced safely through the existing POS data service.
- Apply tag matching on the server before returning rows, so the existing collection limit applies after filtering.
- Add partner ID to collection rows and add print-only layout/styling to the current POS overview.
- Stay scoped to the active Odoo company, as the existing overview methods do.

## Non-goals

- Creating, assigning, or editing Contact Tags from POS.
- Combining both tabs into a single report.
- Adding a POS/Invoice/Manual source filter.
- Changing which payments count as collections, the collection date defaults, the 500-row cap, or the balance calculation.
- Changing how the Collect Payment flow works.

## Builder decisions

- Exact RPC shape, tag lookup mechanism, and print rendering mechanism are implementation choices, provided the behavior above is met.
- For a balance total, use the signed balance values already returned by the existing method; do not reinterpret or recompute them in the print layer.
- Preserve the existing overview styling and POS conventions where they do not conflict with legible page printing.

## Review mockup

The approved mockup is a temporary browser artifact with sample data. It shows the shared tag selector, both tabs, and a print layout for each tab. The final feature does not use its sample names or amounts.
