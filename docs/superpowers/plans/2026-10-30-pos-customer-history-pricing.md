# POS Customer History Pricing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the latest original unit price charged to a POS customer for each product, using completed POS sales and standalone posted customer invoices.

**Architecture:** Add `sfya_pos_customer_history_price`, with a read-only batched Odoo model method that resolves a customer's latest product prices across POS and standalone invoice history. POS order patches apply those prices after customer or product changes, use an in-memory cache scoped to the active POS session, ignore stale async responses, and restore standard pricelist prices when no history is found or a lookup fails.

**Tech Stack:** Odoo 18 Community ORM and `TransactionCase`; Odoo POS OWL/JavaScript model patches; the `point_of_sale._assets_pos` asset bundle.

**Spec:** `docs/superpowers/specs/2026-10-30-pos-customer-history-pricing-design.md`

## Global Constraints

- Install as a new addon at `addons/sfya_pos_customer_history_price/`, version `18.0.1.0.0`, depending on `point_of_sale` and `account`.
- Use completed POS orders in `paid`, `done`, or `invoiced` state and posted customer invoices (`out_invoice`) with no `pos_order_ids`; never use `sale.order`.
- Match the exact customer partner and exact product variant, within the active company.
- Validate RPC inputs before any elevated history search. Use `sudo()` only where POS users lack accounting read access, and return only the requested product prices for the requested customer/company.
- Use source-line `price_unit`; ignore historical discount; preserve the current order line's discount.
- Exclude refund documents and non-positive quantity lines as candidates. A later refund does not remove the original positive sale line from history.
- Compare POS `date_order` in the company timezone with invoice `invoice_date`. For equal business dates, order source transactions by source-record `create_date`, then stable source model and record ID. Within one source transaction, order matching product lines by line `create_date`, then line ID.
- Convert historical unit and currency to the product's POS UoM and active order pricelist currency using Odoo's conversion methods at the source transaction date. If no pricelist is active (`pricelist_id=False`), use the active company currency as the target.
- Apply history only to ordinary positive product lines; leave refunds, combo pricing lines, and the configured tip product unchanged.
- On missing history, customer clear, or lookup failure, set eligible lines to the active POS standard price and `price_type = "original"`: the pricelist price when one is active, or product list price in company currency when pricelists are disabled. For a historical price, set `price_type = "manual"` so quantity edits do not recalculate it from the pricelist.
- Refresh history when the active order pricelist changes so unit prices remain in the current POS currency.
- Evict history cache after a completed order is successfully synchronized, including an upload deferred after offline completion.
- Never change historical transactions, invoices, products, or pricelists. Production installation/deployment requires separate explicit authorization.

## Review Focus

- Partner or pricelist changes while a lookup is in flight: stale responses must not overwrite the newer order state, and the new state must schedule a replacement lookup; cover in Task 2.
- No history, offline lookup, and clearing the customer after a history price was applied: all must restore the current pricelist price and keep checkout usable; cover in Task 2.
- A new sale completed in the same POS session: invalidate its old cache after successful upload so the next order can use the newly posted price; include orders uploaded later after offline completion and cover in Task 2.
- POS-linked invoices and refunds: do not double-count a POS sale, do not use refund lines, and keep the original positive line eligible; cover in Task 1.
- Same-day history, multiple matching lines, currency, and UoM differences: choose deterministically and normalize before returning the price; cover in Task 1.

---

## File Structure

- `addons/sfya_pos_customer_history_price/__init__.py` — import the addon's `models` package.
- `addons/sfya_pos_customer_history_price/__manifest__.py` — module metadata, dependencies, version, and POS asset registration.
- `addons/sfya_pos_customer_history_price/models/__init__.py` — import the partner extension.
- `addons/sfya_pos_customer_history_price/models/res_partner.py` — batched, read-only history lookup and source normalization.
- `addons/sfya_pos_customer_history_price/static/src/app/history_price_service.js` — cache, batched lookup, fallback, and stale-response handling.
- `addons/sfya_pos_customer_history_price/static/src/app/pos_order_patch.js` — trigger price refresh when the order's customer or active pricelist changes; immediately restore the standard POS price on customer clear.
- `addons/sfya_pos_customer_history_price/static/src/app/pos_store_patch.js` — register the active store for model callbacks, refresh after line additions, and invalidate completed-order history after successful synchronization.
- `addons/sfya_pos_customer_history_price/static/src/app/payment_screen_patch.js` — wait for pending history pricing before payment input/validation; invalidate customer/product cache after successful order completion.
- `addons/sfya_pos_customer_history_price/tests/__init__.py` — import the history test class.
- `addons/sfya_pos_customer_history_price/tests/test_history_prices.py` — Odoo transaction tests for source selection and conversion.

## Odoo 18 API References

- `PosOrder.set_partner()` calls `updatePricelistAndFiscalPosition(partner)`, so apply historical prices after the core partner/pricelist update: [Odoo 18 `pos_order.js`](https://github.com/odoo/odoo/blob/18.0/addons/point_of_sale/static/src/app/models/pos_order.js).
- `PosStore.addLineToCurrentOrder(vals, opts, configure)` is async and used by normal product additions: [Odoo 18 `pos_store.js`](https://github.com/odoo/odoo/blob/18.0/addons/point_of_sale/static/src/app/store/pos_store.js).
- `PosOrderline.set_unit_price()` updates the price and marks the line dirty; quantity changes recalculate only lines whose `price_type` is `original`: [Odoo 18 `pos_order_line.js`](https://github.com/odoo/odoo/blob/18.0/addons/point_of_sale/static/src/app/models/pos_order_line.js).
- `PaymentScreen.addNewPaymentLine()` and `validateOrder()` are async: [Odoo 18 `payment_screen.js`](https://github.com/odoo/odoo/blob/18.0/addons/point_of_sale/static/src/app/screens/payment_screen/payment_screen.js).
- Reuse Odoo's POS test fixture patterns from [Odoo 18 `point_of_sale/tests/common.py`](https://github.com/odoo/odoo/blob/18.0/addons/point_of_sale/tests/common.py).

---

### Task 1: Add the batched backend price-history resolver

**Files:**
- Create: `addons/sfya_pos_customer_history_price/__init__.py`
- Create: `addons/sfya_pos_customer_history_price/__manifest__.py`
- Create: `addons/sfya_pos_customer_history_price/models/__init__.py`
- Create: `addons/sfya_pos_customer_history_price/models/res_partner.py`
- Create: `addons/sfya_pos_customer_history_price/tests/__init__.py`
- Create: `addons/sfya_pos_customer_history_price/tests/test_history_prices.py`

**Interfaces:**
- Produces `res.partner.get_pos_customer_history_prices(partner_id: int, product_ids: list[int], pricelist_id: int | False) -> dict[str, float]`.
- The result maps stringified product IDs to prices converted to the active pricelist currency (or active company currency when `pricelist_id=False`) and product POS UoM. A missing key means no qualifying history.
- The method is `@api.model`, read-only, validates the supplied partner/products and numeric pricelist against the active company, accepts explicit `False` only as the no-pricelist sentinel, and returns no unrelated partner or product data.

- [ ] **Step 1: Add backend tests for the resolver**

Create `TestCustomerHistoryPrices` using Odoo's `TestPoSCommon` fixture. Add helpers that create a posted standalone customer invoice and a completed POS order with a dated product line and an optional discount. Pin each case to these assertions:

- `test_latest_price_wins_across_pos_and_standalone_invoice`: POS price `100` on October 1 plus invoice price `125` on October 2 returns `{"<product_id>": 125.0}`; swapping dates returns `100.0`.
- `test_linked_pos_invoice_is_not_a_second_candidate`: a later dated POS-linked invoice at `130` does not replace the POS line at `110`; an older standalone invoice at `90` also loses, so the result is `110.0`.
- `test_only_completed_pos_and_posted_standalone_invoice_count`: draft/cancelled POS orders and draft invoices at `400` are ignored; a completed POS line at `150` is returned.
- `test_exact_partner_and_product_variant_are_required`: a newer line for another customer and a newer line for another variant are omitted; the exact customer/variant returns its own price.
- `test_historical_discount_is_ignored`: line `price_unit=120`, `discount=25` returns `120.0`.
- `test_refund_lines_do_not_replace_original_sale`: a refund at `300` is ineligible; the earlier original positive sale at `120` remains the result.
- `test_company_local_date_and_stable_ties`: a POS datetime that is October 1 UTC but October 2 in the company timezone compares as October 2; equal-date candidates resolve by `create_date`, then source model, record ID, and line ID.
- `test_multiple_lines_choose_latest_line`: matching lines in one transaction are ordered by line `create_date`, then line ID; the latest line returns `115.0` after UoM normalization.
- `test_no_pricelist_uses_company_currency_at_source_date`: with `pricelist_id=False`, a non-company-currency historical price is converted to active company currency using the source date.
- `test_unit_and_currency_are_converted`: a sale at USD `12` per box of 12 items, with source-date rate `1 USD = 280 PKR`, returns PKR `280.0` per POS unit.
- `test_missing_history_is_omitted`: a requested product with no sale line is absent from the returned mapping.

Add a company-boundary assertion: a newer matching transaction in another company must not replace the active company's result, even when the method uses `sudo()` for accounting reads.

- [ ] **Step 2: Run the backend tests against an isolated Odoo 18 test database**

Run: `docker compose run --rm odoo odoo -d odoo_customer_history_test -i sfya_pos_customer_history_price --test-enable --test-tags /sfya_pos_customer_history_price --stop-after-init --no-http`

Expected: all `sfya_pos_customer_history_price` tests pass. Do not point this command at the production database.

- [ ] **Step 3: Implement `get_pos_customer_history_prices` in `models/res_partner.py`**

Search the POS line and account invoice line models in batches for the requested products, exact partner, active company, and allowed document states. Exclude moves linked to POS orders. Select the winning line per product with the design's company-local date and deterministic tie-break rules. Normalize source UoM and currency to the POS product UoM and supplied pricelist currency, or active company currency when `pricelist_id=False`, using Odoo conversion methods at the source date. Return only `{str(product_id): converted_price}`; never include the old discount.

- [ ] **Step 4: Run the backend tests and module syntax check**

Run: `docker compose run --rm odoo odoo -d odoo_customer_history_test -u sfya_pos_customer_history_price --test-enable --test-tags /sfya_pos_customer_history_price --stop-after-init --no-http`

Run: `python -m compileall addons/sfya_pos_customer_history_price`

Expected: all resolver tests pass and every Python file compiles.

- [ ] **Step 5: Commit the backend resolver**

```bash
git add addons/sfya_pos_customer_history_price
git commit -m "feat: add POS customer price history lookup"
```

---

### Task 2: Apply customer history prices in the POS

**Files:**
- Create: `addons/sfya_pos_customer_history_price/static/src/app/history_price_service.js`
- Create: `addons/sfya_pos_customer_history_price/static/src/app/pos_order_patch.js`
- Create: `addons/sfya_pos_customer_history_price/static/src/app/pos_store_patch.js`
- Create: `addons/sfya_pos_customer_history_price/static/src/app/payment_screen_patch.js`
- Modify: `addons/sfya_pos_customer_history_price/__manifest__.py`

**Interfaces:**
- Produces `applyCustomerHistoryPrices(posStore, order) -> Promise<void>` in `history_price_service.js`.
- Stores the active lookup as `order._sfyaPricePromise` and a monotonically increasing `order._sfyaPricingRevision`; only the newest revision may update lines.
- Uses `posStore.data.call("res.partner", "get_pos_customer_history_prices", [], {partner_id, product_ids, pricelist_id})`. Send explicit `false` when the order has no active pricelist; the backend then targets active company currency.
- Stores the in-memory result cache on the active `PosStore`; cache keys include session, partner, product, and pricelist. Cache missing-history results, but do not cache transport errors. Invalidate after successful order upload, including deferred offline synchronization.

- [ ] **Step 1: Add POS patches and helper to the manifest asset bundle**

Register `history_price_service.js`, `pos_order_patch.js`, `pos_store_patch.js`, and `payment_screen_patch.js` under `point_of_sale._assets_pos`.

- [ ] **Step 2: Implement the pricing helper and its line-update rules**

Implement `applyCustomerHistoryPrices(posStore, order)`. Batch all eligible order product IDs for the current customer. On a history hit, call `line.set_unit_price(price)` and set `line.price_type = "manual"`. On no history, customer clear, or a caught lookup error, set `line.price_type = "original"` and recompute with `line.product_id.get_price(order.pricelist_id, line.get_quantity(), line.get_price_extra())`. Never change `line.discount`. Skip refund, combo, and tip lines. Ignore a response when its captured revision or customer no longer matches the order.

- [ ] **Step 3: Trigger refresh on customer and product changes**

Patch `PosStore.setup()` to initialize the session cache and expose the active store through the `pos.order` model collection. Patch `PosOrder.set_partner(partner)` to call `super`, then schedule the helper for a non-empty partner; for a cleared partner, invalidate in-flight requests and synchronously restore eligible lines to the current standard POS price. Patch `PosOrder.set_pricelist(pricelist)` to call `super`, then schedule a replacement history lookup for a customer order in the new pricelist context. Patch `PosStore.addLineToCurrentOrder(vals, opts, configure)` to call `super`, then schedule a batched refresh for the line's order if it has a customer. Store the resulting promise on that order.

- [ ] **Step 4: Keep payment amounts in sync and prevent stale cache reuse**

Patch `PaymentScreen.addNewPaymentLine(paymentMethod)` and `PaymentScreen.validateOrder(isForceValidate)` to await the current order's `_sfyaPricePromise` before calling `super`. After successful immediate synchronization, evict cached entries for that order's customer and products. Patch `PosStore.postSyncAllOrders()` to evict entries for completed orders returned after successful upload, including orders completed while offline.

- [ ] **Step 5: Verify frontend behavior in an Odoo 18 POS session**

Use a customer/product pair with existing history and confirm each result:

1. Select the customer, add the product, and verify the latest historical original price appears before payment.
2. Add the product first, select the customer, and verify the existing line changes to that price.
3. Change to a customer with no history and verify normal pricelist pricing replaces a prior historical or manual price.
4. Keep a current line discount and verify it is unchanged while its unit price changes.
5. Clear the customer and verify every eligible line returns to the current pricelist price.
6. Simulate a failed history lookup and verify checkout remains available at the active standard POS price.
7. With POS pricelists disabled, verify historical prices use company currency and no-history lines retain product list price.
8. Change the active pricelist while a customer history lookup is delayed; verify the response for the old pricelist is discarded and a new lookup applies history in the current pricelist.
9. Select customer A, quickly change to customer B while the first lookup is delayed, and verify A's late response cannot overwrite B's price.
10. Complete a sale, start another order in the same session for the same customer/product, and verify the refreshed latest sale price is used.
11. Complete a sale while offline, allow it to synchronize successfully later, and verify the next same-session order uses that newly synchronized sale price.

- [ ] **Step 6: Run static checks and commit POS integration**

Run: `python -m compileall addons/sfya_pos_customer_history_price`

Expected: all Python files compile; the POS asset bundle loads without a JavaScript error during the browser checks above.

```bash
git add addons/sfya_pos_customer_history_price
git commit -m "feat: apply customer history prices in POS"
```

---

### Task 3: Release and verify the new addon

**Files:**
- No source files; release and verification only.

**Interfaces:**
- Uses the existing `main` branch CI flow to back up the database, sync addons, rebuild the Odoo stack, and check `/web/login` health.
- Installs the new module once with `-i sfya_pos_customer_history_price`; subsequent code-only revisions use `-u`.

- [ ] **Step 1: Run the isolated Odoo test suite and inspect the final diff**

Run the Task 1 isolated-database test command, `python -m compileall addons/sfya_pos_customer_history_price`, and `git diff --check`.

Expected: all automated tests pass, no Python syntax errors or whitespace errors, all feature source changes are confined to the new addon, and the approved design/spec and plan artifacts are versioned alongside it.

- [ ] **Step 2: Commit the complete implementation**

If the implementation includes any final review fixes, commit them separately with a message describing the fix.

- [ ] **Step 3: Deploy only after the user explicitly authorizes production installation**

Push `main` to trigger the existing CI backup/deploy workflow. After CI succeeds, install the addon with the documented maintenance flow:

```bash
docker compose stop odoo
docker compose run --rm odoo odoo -d odoo --no-http --stop-after-init -i sfya_pos_customer_history_price
docker compose up -d odoo
```

Expected: module install and registry initialization succeed, the Odoo health check returns a successful login response, and the POS assets compile.

- [ ] **Step 4: Verify live behavior without posting a sale**

Open POS using a customer/product pair with known history. Confirm the selected price, unchanged discount, customer-switch behavior, and clear-customer fallback in the draft cart. Do not finalize a verification sale unless separately requested.

---

## Self-Review

- **Spec coverage:** all sources, exclusions, latest selection, original `price_unit`, discount behavior, customer/product selection order, manual-price override, fallback, clear-customer reset, conversions, caching, failure behavior, and same-session refresh are assigned to Tasks 1–3.
- **Step scan:** each test, implementation, verification, and commit step names its target and expected result; no task depends on an undefined backend method or result shape.
- **Type consistency:** the backend returns string product ID keys to numeric prices; the frontend consumes that shape through the single `applyCustomerHistoryPrices(posStore, order)` helper.
- **Review focus:** async races, fallback, cache invalidation, invoice/refund filtering, tie-breaking, and conversions each have a named verification.
- **Proportion:** the plan specifies repository files and Odoo interfaces without writing the feature implementation itself.
