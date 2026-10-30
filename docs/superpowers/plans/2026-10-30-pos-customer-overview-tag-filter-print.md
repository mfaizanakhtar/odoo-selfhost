# POS Customer Overview Tag Filter and Print Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shared Contact Tag filter and current-tab print action to the POS Customer Overview.

**Architecture:** Extend the existing `sfya_pos_cash_movement` RPCs to return Contact Tags and filter balance and payment rows server-side. Extend the existing OWL modal with a shared one-tag selector and a print-only view that uses the browser's print dialog. Keep balance calculations, collection sources, date controls, and collect flow unchanged.

**Tech Stack:** Odoo 18, Python ORM/raw SQL, POS OWL, QWeb XML, SCSS, `pos.data.call`.

**Spec:** `docs/superpowers/specs/2026-10-30-pos-customer-overview-tag-filter-print-design.md`

## Global Constraints

- Extend `sfya_pos_cash_movement`; do not add an addon, custom tag model, or database table.
- Use standard Odoo Contact Tags (`res.partner.category`).
- Default to **All Customers**, including tagged and untagged customers; allow one tag at a time.
- Match a tag on the payment/balance partner or its `commercial_partner_id`.
- Keep all current inbound collection sources and their POS or Invoice/Manual labels.
- Filter on the server before applying the existing 500-row collections limit.
- Print only the currently selected tab with its applied filters through the browser print dialog, not the POS receipt printer.
- Stay scoped to the active Odoo company and preserve current collection and balance semantics.

## Review Focus

- No selected tag must preserve today's results and include untagged partners.
- A tag on a commercial customer must also match entries recorded against its child contacts.
- The selected tag must filter before the 500-payment cap, preserving the newest matching rows.
- Changing tags, dates, tabs, or refresh state must not mismatch the printed filter summary and loaded rows.
- Browser printing must show only the selected tab's report and hide the POS screen and modal controls.

---

## File Map

| File | Responsibility |
|---|---|
| `addons/sfya_pos_cash_movement/models/res_partner.py` | Return Contact Tag options and optionally filter balance rows. |
| `addons/sfya_pos_cash_movement/models/account_payment.py` | Optionally filter recent collections and include partner ID. |
| `addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.js` | Load tags, manage selected/applied filters, and prepare the current-tab print action. |
| `addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.xml` | Add the shared selector and print-only report markup. |
| `addons/sfya_pos_cash_movement/static/src/app/customer_overview_print.scss` | Hide POS UI and style the report for the browser print dialog. |
| `addons/sfya_pos_cash_movement/__manifest__.py` | Load print styles and bump the addon version. |

### Task 1: Add Server-Side Tag Data and Filtering

**Files:**
- Modify: `addons/sfya_pos_cash_movement/models/res_partner.py`
- Modify: `addons/sfya_pos_cash_movement/models/account_payment.py`

**Interfaces:**
- Produces `res.partner.get_customer_overview_tags() -> list[{id: int, name: str}]`, sorted by tag name.
- Produces `res.partner.get_customer_balances(tag_id: int | None = None) -> list[{partner_id: int, partner_name: str, balance: float}]`.
- Produces `account.payment.get_recent_collections(date_from: str, date_to: str, tag_id: int | None = None) -> list[{id: int, partner_id: int | None, date: str, partner_name: str, amount: float, source: str}]`.
- `tag_id=None` means unfiltered results. Raise a clear `UserError` for a deleted or invalid non-empty tag ID; never fall back to unfiltered results.

- [ ] **Step 1: Add the tag-options RPC**

Add `get_customer_overview_tags()` to `res.partner`. Return existing `res.partner.category` records as `{id, name}`, sorted by name, using the same active Odoo connection context as the POS overview.

- [ ] **Step 2: Add optional tag filtering to balances**

Add optional `tag_id=None` to `get_customer_balances()`. Preserve its existing posted-move, company, account-type, grouping, threshold, and sort logic. When a tag is selected, include a balance partner only when the tag is assigned directly to that partner or to its commercial parent.

- [ ] **Step 3: Add optional tag filtering and partner IDs to collections**

Add optional `tag_id=None` to `get_recent_collections(date_from, date_to, tag_id=None)`. Preserve its current payment type, states, date range, company, order, and limit. Apply direct-partner/commercial-parent tag matching in the search domain before the 500-row limit. Include `partner_id` in each returned row; keep the current POS versus Invoice/Manual source calculation.

- [ ] **Step 4: Review the backend result behavior**

Review the query paths against current behavior: unfiltered results remain unchanged, a tag matches both direct and commercial-parent assignments, and a nonexistent ID raises `UserError` rather than returning unfiltered rows. Do not execute RPCs or add or run automated tests in this task.

- [ ] **Step 5: Commit the backend task**

```bash
git add addons/sfya_pos_cash_movement/models/res_partner.py \
        addons/sfya_pos_cash_movement/models/account_payment.py
git commit -m "feat: filter POS customer overview by contact tag"
```

### Task 2: Add the Shared POS Tag Filter

**Files:**
- Modify: `addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.xml`

**Interfaces:**
- Consumes Task 1 tag and filtered-data RPCs.
- Keeps `state.tab`, `state.dateFrom`, and `state.dateTo`; adds `tagOptions`, `selectedTagId`, `appliedTagId`, `appliedDateFrom`, and `appliedDateTo` for the filters associated with loaded rows.

- [ ] **Step 1: Load tag options and initial data**

On modal start, call `get_customer_overview_tags()`, default `selectedTagId` to `null` (All Customers), and request balances plus collections with the selected tag and current date range.

- [ ] **Step 2: Add the shared selector above both tabs**

Add an All Customers option and one option per returned Contact Tag. Selecting a tag reloads both tabs and preserves the active tab. Keep the selector in a shared location so the selected tag remains visible on either tab.

- [ ] **Step 3: Carry the selected tag through collection refreshes**

Pass the selected tag ID from `refreshCollections()` along with the current date range. Record `appliedTagId`, `appliedDateFrom`, and `appliedDateTo` only after the corresponding result loads successfully. Do not present old rows as if they match a newly selected tag after a failed request.

- [ ] **Step 4: Review the POS filter flow**

Check All Customers, a selected tag, a tag with no matching rows, switching tabs, refreshing collections with a tag, and the existing tap-to-collect flow. Confirm date inputs still require the existing Refresh action before their new range is applied.

- [ ] **Step 5: Commit the filter UI task**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.js \
        addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.xml
git commit -m "feat: add contact tag filter to POS customer overview"
```

### Task 3: Print the Currently Selected Tab

**Files:**
- Modify: `addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.js`
- Modify: `addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.xml`
- Create: `addons/sfya_pos_cash_movement/static/src/app/customer_overview_print.scss`
- Modify: `addons/sfya_pos_cash_movement/__manifest__.py`

**Interfaces:**
- Consumes Task 2's loaded rows and applied filter values.
- Adds `printCurrentView()` to `CustomerOverviewModal`.

- [ ] **Step 1: Add print-only markup for balances and collections**

Render a print report for `state.tab` only. Include the report title, selected tag or All Customers, generation time, and a total of the displayed rows. For collections, include the applied date range and each row's source. Sum the balance rows with their existing signs; sum the displayed collection amounts.

- [ ] **Step 2: Add the Print view action**

Add a Print view button on both tabs and implement `printCurrentView()` with `window.print()`. Disable it while data is loading, when the selected tag differs from `appliedTagId`, or, on the collections tab, when date inputs differ from `appliedDateFrom`/`appliedDateTo`; the cashier must use Refresh to apply new collection dates before printing.

- [ ] **Step 3: Add print-only styling and manifest entry**

Create `customer_overview_print.scss` with `@media print` rules that show the report and hide the POS screen, dialog chrome, controls, and the non-selected tab. Set the print page to A4 portrait with 12 mm margins, overriding the thermal-receipt page rule in `sfya_pos_receipt`. Add the stylesheet to `point_of_sale._assets_pos` and bump the manifest from `18.0.6.0.9` to `18.0.6.0.10`.

- [ ] **Step 4: Review both print paths**

Check printing balances and collections separately. Each printout must contain only the active tab, carry its applied tag and date information, preserve source labels, show totals for the displayed rows, and omit POS controls. Do not add or run automated tests in this task.

- [ ] **Step 5: Commit the print task**

```bash
git add addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.js \
        addons/sfya_pos_cash_movement/static/src/app/customer_overview_modal.xml \
        addons/sfya_pos_cash_movement/static/src/app/customer_overview_print.scss \
        addons/sfya_pos_cash_movement/__manifest__.py
git commit -m "feat: print filtered POS customer overview"
```

## Execution Notes

- Implement tasks sequentially because the UI consumes the exact RPC response defined in Task 1 and printing consumes the filter state from Task 2.
- Use the previously chosen subagent-driven workflow, with low-cost Sol reviews between tasks and a final branch review.
- This plan stops at reviewed feature code and commits. Production deployment and module upgrade are not included until explicitly authorized for this feature.
- The plan does not add or run automated tests; it records manual review checks for a later implementation pass.
