# POS Cash Movement — Multi-Journal Extension

**Status:** Approved 2026-06-14
**Addon:** `sfya_pos_cash_movement`
**Version target:** `18.0.2.0.0`
**Predecessor spec:** `docs/superpowers/specs/2026-06-13-pos-cash-movement-design.md`

---

## Goal

Extend the existing POS Collect Payment / Pay Out flow so cashiers can record payments hitting any of the company's cash or bank journals — not just the POS cash till. Bank payments are commonly bank-transfer receipts from customers (or rare outbound transfers to vendors) that today get backfilled in Accounting after the fact. Recording them at the POS shortens reconciliation and surfaces them in customer/vendor statements same day.

## Motivation

Today the module hardcodes the POS cash payment method's journal:

```python
cash_pm = session.config_id.payment_method_ids.filtered(
    lambda m: m.type == 'cash'
)[:1]
...
'journal_id': cash_pm.journal_id.id,
```

SFYA receives most non-sale payments via bank transfer to one of several bank accounts (Alfalah, Meezan, HBL, …). These cannot be recorded at the POS today and must be entered in Accounting separately.

## Scope

**In scope:**
- Account dropdown in the Cash Movement modal listing cash + bank journals of the session's company.
- Backend RPC takes `journal_id` (replaces hardcoded cash lookup).
- Closing dialog: cash math unchanged; banks render as informational sections per journal with no till impact.
- One major version bump (`18.0.2.0.0`); no external callers of the RPCs, safe break.

**Out of scope:**
- New journal types beyond `cash` / `bank`.
- Cross-company / multi-currency selection in the modal (single currency at SFYA, single company per POS).
- Journal whitelist per `pos.config` — every cash/bank journal of the company is selectable. If SFYA wants to restrict later, add a `m2m` on `pos.config` in a follow-up.
- Migration of historical payments — existing rows already have a journal; they self-classify as cash or bank based on `journal.type`.
- Settings UI for default journal — modal defaults to the POS cash journal (existing behavior).

## Architecture

One in-place extension of `sfya_pos_cash_movement`. No new addon. Major version bump (`18.0.2.0.0`) so the upgrade is forced on next deploy and all clients hard-reload assets.

### Components touched

| File | Responsibility | Change shape |
|---|---|---|
| `models/account_payment.py` | RPC payment creation | `_sfya_pos_create_payment` signature gains `journal_id`; resolves & validates journal; drops cash auto-lookup. |
| `models/pos_session.py` | Session-scoped data for closing dialog | `get_sfya_cash_movements` returns split structure `{cash, banks}`. `get_closing_control_data` adjusts till by cash net only. New method `get_sfya_allowed_journals()` returning the dropdown options. |
| `static/src/app/cash_movement_modal.js` | UI state | Loads allowed journals at mount; state adds `journal_id`; RPC payload includes it. |
| `static/src/app/cash_movement_modal.xml` | UI template | Adds `<select>` "Account" above Partner. |
| `static/src/app/closing_dialog_patch.js` | Closing dialog data | Reads new `{cash, banks}` shape into state. |
| `static/src/app/closing_dialog_patch.xml` | Closing dialog template | Renders per-bank sections after the cash section. |
| `__manifest__.py` | Version bump | `18.0.2.0.0`. |

### Data flow

```
Cashier clicks "Collect Payment" on POS ProductScreen
  → CashMovementModal opens
  → onWillStart fetches allowed journals via get_sfya_allowed_journals(session_id)
  → dropdown populated; default = POS cash journal
  → Cashier picks "Bank Alfalah", picks partner, enters amount, clicks Collect
  → RPC sfya_pos_collect(session_id, partner_id, amount, journal_id=bank_alfalah_id, memo)
  → Backend validates journal (type + company), creates+posts account.payment
  → pos_session_id field set for audit linkage
  → Modal closes; toast confirms

Cashier closes session
  → ClosePosPopup opens
  → onWillStart fetches get_sfya_cash_movements(session_id)
  → Returns {cash: {...}, banks: [{...}, {...}, ...]}
  → Frontend renders cash section (matches today) + N bank sections (new)
  → Expected cash already includes cash adjustments (via get_closing_control_data override)
  → Bank sections are informational; no till math impact
```

### RPC contracts

**`get_sfya_allowed_journals(session_id) -> [{id, name, type}]`**
- New `@api.model` method on `pos.session`.
- Returns journals where `type in ('cash','bank')` AND `company_id == session.company_id`.
- Order: cash first, then banks alphabetically.

**`sfya_pos_collect(session_id, partner_id, amount, journal_id, memo='')`**
- Signature changes (breaking): `journal_id` added as required positional arg before `memo`.
- Same for `sfya_pos_payout`.
- Backend validates: journal exists, type in {cash, bank}, company matches session, vendor-only-payout still enforced.

**`get_sfya_cash_movements(session_id) -> {cash, banks}`**
- Return shape changes (breaking):
  ```python
  {
      'cash': {
          'collects': [{id, name, partner_id, partner_name, amount, memo}, ...],
          'collects_total': float,
          'payouts': [{...}, ...],
          'payouts_total': float,
      },
      'banks': [
          {
              'journal_id': int,
              'journal_name': str,
              'collects': [{...}, ...],
              'collects_total': float,
              'payouts': [{...}, ...],
              'payouts_total': float,
          },
          ...
      ],
  }
  ```
- `banks` only contains journals that had at least one movement this session.

**`get_closing_control_data` override**
- Unchanged math source: only `cash.collects_total - cash.payouts_total` adjusts `default_cash_details.amount`.
- Bank movements never appear in cash-drawer math.

### Error paths

| Condition | Behavior |
|---|---|
| `journal_id` missing or 0 | `UserError("Account is required.")` |
| Journal not found | `UserError("Account not found.")` |
| Journal type ∉ {cash, bank} | `UserError("Selected account is not a cash or bank journal.")` |
| Journal company ≠ session company | `UserError("Account does not belong to this POS's company.")` |
| No allowed journals on company | Modal shows error banner on open; dropdown empty; Confirm disabled. |
| All existing gates (amount, partner, session, vendor-only) | Unchanged. |

### Migration

- No DB migration. `pos_session_id` field unchanged.
- Existing posted payments self-classify by `journal.type` — all current payments are on the cash journal, so they appear in the cash section of `get_sfya_cash_movements` exactly as today.
- RPC signature break is internal — only the addon's own frontend calls these. No third-party callers.

### Closing dialog visual model

```
[Counted: 50000]
[Expected: 50300]   ← cash collects (300) added; bank receipts NOT included

▼ Customer Receipts (Cash)
   - Accesology   PCSH1/2026/00045   300.00   task8 smoke collect
   Total: +300.00

▼ Vendor Pay-outs (Cash)
   (none)
   Total: 0.00

▼ Bank Alfalah
   - Walk-In       PCSH1/2026/00050   5000.00   Bank transfer JS123
   Receipts: +5000.00
   Pay-outs:  0.00

▼ Meezan Bank
   - FS Brothers   PCSH1/2026/00051   2000.00   Refund of advance
   Receipts: 0.00
   Pay-outs:  2000.00
```

Bank sections are collapsible like the cash ones. Sign convention in summary lines: receipts positive, pay-outs displayed as positive magnitude under "Pay-outs" line.

## Testing

Verification-only (no Python test infra in repo). Each task ends with a smoke sequence via odoo shell + browser:

| Check | How |
|---|---|
| Allowed-journals RPC returns expected list | odoo shell on open session |
| Cash collect still adjusts expected cash | Create via RPC, render closing dialog, diff |
| Bank collect does NOT adjust expected cash | Same, with bank journal |
| Multiple bank journals → multiple sections | Create receipts on 2+ journals; close dialog renders 2+ sections |
| Vendor-only-payout gate still applies for bank | Try `sfya_pos_payout` to non-vendor partner via bank → UserError |
| Statement still picks up bank payments | Render `get_statement_data` for partner used in bank receipt → row appears as "Payment Received" with the bank journal's name in the note |
| Invalid journal rejected | Pass a sales-type journal id → UserError |

## Risks / Tradeoffs

- **Breaking RPC signature.** Acceptable because no external callers. The major version bump signals the break; frontend is updated in the same release.
- **No journal whitelist per POS config.** Any cashier with POS access can post to any cash/bank journal of the company. SFYA is single-shop with a small staff; acceptable today. Adding a whitelist later is one new field + one filter line.
- **Default journal is POS cash.** Cashier must explicitly switch to bank for transfers — slight extra click but matches today's flow and prevents accidental bank posts.
- **Closing dialog adds N sections.** With many banks the popup could grow tall; mitigated by collapsibility and the existing scroll on the dialog body.

## Out of scope (future work, not in this release)

- Per-POS journal whitelist.
- Receipt slip printing for bank receipts (current print slip works as-is but says "PKR" — fine).
- Reconciling the recorded bank payment against an existing bank statement line.
- Reports / dashboards aggregating SFYA POS-recorded movements across journals.

## Acceptance

Plan complete when all of:
- Modal lists cash + bank journals (verified for AJ Mobile shop config).
- Bank receipt posts to chosen bank journal, visible in `account.payment` list and in customer statement.
- Closing dialog shows cash section + one section per bank journal with movements.
- Expected-cash math matches `Opening cash + cash collects − cash payouts` (banks excluded).
- Vendor-only-payout gate, amount>0 gate, session-open gate still in force.
