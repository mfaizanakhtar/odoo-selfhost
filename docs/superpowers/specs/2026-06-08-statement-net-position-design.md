# SFYA Customer Statement — Net Position View

**Date:** 2026-06-08
**Module:** `sfya_customer_statement`
**Manifest bump:** `18.0.1.14.0` → `18.0.2.0.0` (minor semver: balance semantics change from AR-only to net AR-AP)

## Problem

Current statement only tracks the customer-receivable side. Cases where the same partner sells to us (vendor bills from PO) and where we pay them (vendor payments) are invisible. User cannot see the net position — who owes whom.

Secondary: display sort is newest-first. User wants oldest→newest so the running balance reads naturally top to bottom.

Tertiary: aging block always renders; user wants it optional.

## Goals

1. Show vendor activity for the same partner inline with customer activity so the running balance reflects **net AR − AP**.
2. Display rows oldest → newest. Opening row pinned at top (chronologically pre-period).
3. Aging block hidden by default. Wizard checkbox to opt in.

## Non-goals

- Aging block does NOT include AP. Aging stays AR-only; out of scope.
- Negative-balance label tweak ("You owe customer X") — out of scope.
- Fix for AJ Mobile opening balance JE 70 (used Suspense 2226 instead of Opening Balance Equity 3999) — separate deferred issue, see `~/.claude/projects/-Users-faizanakhter/memory/project_sfya_statement_opening_balance.md`.
- Refactoring source-collection blocks into helpers. Keep current per-source inline pattern (option A1 from brainstorm).

## Design

### Data layer — `models/res_partner.py`

`get_statement_data(date_from, date_to, include_drafts=False, show_aging=False)`

**Sort change:**
- Remove `rows.reverse()` (line 157 today). Math already runs chronological; display now matches.

**New source #1 — Vendor bills:**
```python
bill_domain = [
    ('partner_id', '=', self.id),
    ('move_type', 'in', ['in_invoice', 'in_refund']),
    ('invoice_date', '>=', date_from),
    ('invoice_date', '<=', date_to),
    ('state', '=', 'posted'),
]
for bill in self.env['account.move'].search(bill_domain):
    sign = 1 if bill.move_type == 'in_invoice' else -1
    lines = [{
        'name': (l.product_id.display_name or l.name or ''),
        'qty': l.quantity,
        'price_unit': l.price_unit,
        'subtotal': l.price_total,
    } for l in bill.invoice_line_ids if l.display_type not in ('line_section', 'line_note')]
    rows.append({
        'date': bill.invoice_date,
        'create_date': bill.create_date,
        'kind': 'vendor_bill' if sign > 0 else 'vendor_refund',
        'kind_label': _('Vendor Bill') if sign > 0 else _('Vendor Refund'),
        'doc_name': bill.name,
        'doc_id': bill.id,
        'doc_model': 'account.move',
        'lines': lines,
        'note': '',
        'debit': sign * bill.amount_total if sign < 0 else 0.0,
        'credit': sign * bill.amount_total if sign > 0 else 0.0,
        'balance': 0.0,
    })
```

Sign convention (positive balance = they owe us):
- `in_invoice` → credit (they billed us; net owed to us drops)
- `in_refund` → debit (vendor credit note; net owed to us rises back)

**New source #2 — Vendor payments:**
```python
vpay_domain = [
    ('partner_id', '=', self.id),
    ('partner_type', '=', 'supplier'),
    ('date', '>=', date_from),
    ('date', '<=', date_to),
    ('state', '=', 'posted'),
]
for pay in self.env['account.payment'].search(vpay_domain):
    rows.append({
        'date': pay.date,
        'create_date': pay.create_date,
        'kind': 'vendor_payment',
        'kind_label': _('Vendor Payment'),
        'doc_name': pay.name,
        'doc_id': pay.id,
        'doc_model': 'account.payment',
        'lines': [],
        'note': _('Vendor Payment - %s', pay.journal_id.name) + (
            ' (%s)' % pay.ref if pay.ref else ''
        ),
        'debit': pay.amount,
        'credit': 0.0,
        'balance': 0.0,
    })
```

We paid them → our debt to them shrinks → debit (net owed by them rebounds toward positive).

**Aging gate:**
```python
'aging': self._compute_aging_buckets(date_to) if show_aging else [],
```

### Wizard — `wizards/statement_wizard.py`

Add field:
```python
show_aging = fields.Boolean('Show Aging', default=False)
```

No URL changes needed — `_get_report_values` already does `wizards.browse(docids)` and reads wizard fields, so `wizard.show_aging` is accessible.

### Report builder — `reports/statement_report.py`

In `_get_report_values`, change call:
```python
statement = wizard.partner_id.get_statement_data(
    wizard.date_from,
    wizard.date_to,
    include_drafts=wizard.include_drafts,
    show_aging=wizard.show_aging,
)
```

### Wizard view — `wizards/statement_wizard_views.xml`

Add checkbox next to existing `include_drafts`:
```xml
<field name="show_aging"/>
```

### Template — `reports/statement_report.xml`

**No change.** Aging block already wrapped in `t-if="data['aging']"` which auto-hides when list is empty.

## Sign math sanity check

Scenario: customer owes us 100 (AR). They sell us stock worth 30 (AP). We pay them 10 against that.

| Event | debit | credit | running | meaning |
|-------|-------|--------|---------|---------|
| (opening) | — | — | 100 | they owe us 100 |
| Vendor bill 30 | 0 | 30 | 70 | their net owed drops to 70 (we owe them 30, but net AR is 100-30) |
| Vendor payment 10 | 10 | 0 | 80 | we paid 10, our debt to them is now 20, so their net owed rises |

End: 80. Correct: AR 100 − (AP 30 − paid 10) = 100 − 20 = 80. ✓

## Files

### Modify
- `addons/sfya_customer_statement/__manifest__.py` — version `18.0.2.0.0`
- `addons/sfya_customer_statement/models/res_partner.py` — add 2 query blocks, drop `rows.reverse()`, accept `show_aging` param, gate aging
- `addons/sfya_customer_statement/wizards/statement_wizard.py` — add `show_aging` field
- `addons/sfya_customer_statement/wizards/statement_wizard_views.xml` — add `<field name="show_aging"/>`
- `addons/sfya_customer_statement/reports/statement_report.py` — pass `show_aging` into `get_statement_data`

### No change
- `addons/sfya_customer_statement/reports/statement_report.xml` — aging block already conditional

## Verification

1. **Sort** — render statement for AJ Mobile (id 17). First post-opening row dated 07-06-2025 area; last row dated near `date_to`. Opening row pinned top.
2. **Vendor bill** — create test vendor bill on AJ Mobile, post it. Re-render. Bill appears as new row with credit column populated. Running balance drops by bill amount.
3. **Vendor payment** — create supplier payment to AJ Mobile, post. Re-render. Appears as new row with debit. Running balance rises by payment amount.
4. **Vendor refund** — create vendor credit note on AJ Mobile. Re-render. Appears as debit row.
5. **Aging hidden by default** — wizard with `show_aging=False`. Statement renders. Aging block absent.
6. **Aging visible when checked** — same wizard, check Show Aging. Aging block renders with buckets as before.
7. **Closing balance** — equals sum of AR debits − AR credits − AP credits + AP debits + opening. Matches scenario in sign math above.
8. **Regression** — POS sale row format unchanged, customer payment row format unchanged, multi-line voucher vertical separators still present (v1.14.0 fix preserved).

## Deploy

1. Commit + push → CI/CD rebuild
2. SSH upgrade `sfya_customer_statement` via odoo shell `mod.button_immediate_upgrade()` + commit (version bump forces XML reload AND new wizard field registration)
3. Clear `/web/assets/%` ir.attachment (forces wizard view re-render in browser)
4. Hard refresh wizard form in browser

## Risk

- New AP queries may slow render for partners with thousands of vendor txns. Currently AR scan is the slow path; AP queries are additive. Mitigation: indexes on `account_move (partner_id, move_type, state, invoice_date)` already standard. Defer perf work unless flagged.
- Sign confusion: vendor bill as CREDIT is counter-intuitive at first glance. Mitigated by kind_label "Vendor Bill" + credit column placement matching customer payments. Document in commit message.
