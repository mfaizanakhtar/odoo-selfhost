# POS Cash Movement — Bank Payment Backdating

**Status:** Approved 2026-06-15
**Addon:** `sfya_pos_cash_movement`
**Version target:** `18.0.3.0.0`
**Predecessor spec:** `docs/superpowers/specs/2026-06-14-pos-cash-movement-journals-design.md`

---

## Goal

Let cashiers backdate POS-recorded bank payments to the date the bank transfer actually happened. Cash payments stay locked to today (they hit the till in real time). Future dates rejected.

## Motivation

Bank transfers lag — customer sends Rs to bank yesterday, cashier records via POS today. Today the payment auto-dates to today, which breaks bank-statement reconciliation and shows the wrong date in customer statements. Cashier needs to set `account.payment.date` to the actual transfer date at posting time.

## Scope

**In scope:**
- Optional `Date` input in the Cash Movement modal, visible only when the selected journal is a bank journal.
- Default value = today. Maximum = today (HTML5 `max` attr + backend gate).
- Applies to both Collect Payment (inbound) and Pay Out (outbound) when journal is bank.
- Backend `_sfya_pos_create_payment` accepts `date` kwarg; cash journal forces today regardless.

**Out of scope:**
- Lower-bound date limit beyond Odoo's built-in period locks (no "current month only" rule).
- Time-of-day input — date granularity only (matches bank-statement granularity).
- Bulk backdating utility — one payment per modal flow.
- Auto-match against bank-statement lines (no live bank API integration).
- Date field for cash receipts/payouts — deliberately blocked.

## Architecture

In-place extension of `sfya_pos_cash_movement`. Three files modified:

| File | Change shape |
|---|---|
| `models/account_payment.py` | `_sfya_pos_create_payment` gains `date=None` kwarg; resolves to today for cash, validates not-future for bank; assigns to `account.payment.date`. |
| `static/src/app/cash_movement_modal.js` | `state.date` initialized to today (YYYY-MM-DD); `selectedJournalIsBank` getter; `todayStr` getter; `confirm()` adds `date` to payload only when bank journal. |
| `static/src/app/cash_movement_modal.xml` | New row between Account select and Partner input, wrapped in `t-if="selectedJournalIsBank"`, with `t-att-max="todayStr"`. |
| `__manifest__.py` | Bump to `18.0.3.0.0`. |

### Data flow

```
Cashier picks bank journal in modal
  → selectedJournalIsBank getter returns true
  → Date row renders, defaults to today, max attr = today
  → Cashier optionally edits to a past date (e.g., yesterday)
  → Cashier picks partner, enters amount, clicks Collect
  → RPC sfya_pos_collect(..., journal_id=bank_id, date="2026-06-14", memo)
  → Backend validates date ≤ today
  → account.payment created with date=2026-06-14, posted
  → action_post triggers Odoo's own period-lock check (free guard)
  → Modal closes, toast confirms

Cashier picks cash journal
  → selectedJournalIsBank getter returns false
  → Date row not rendered
  → RPC payload omits date kwarg
  → Backend resolves to today; if a date IS sent (defensive caller),
    backend silently forces today for cash journal type
```

### Frontend details

**State:**
```js
this.state = useState({
    partner: null,
    journal_id: null,
    amount: "",
    memo: "",
    date: this._todayStr(),  // NEW
    submitting: false,
    error: null,
    journals: [],
});
```

**Getters:**
```js
get selectedJournalIsBank() {
    const j = this.state.journals.find(x => x.id === this.state.journal_id);
    return j?.type === "bank";
}

get todayStr() {
    return this._todayStr();
}

_todayStr() {
    const d = new Date();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${d.getFullYear()}-${m}-${day}`;
}
```

**Template insertion** (between existing Account select block and Partner input block):
```xml
<div class="mb-2" t-if="selectedJournalIsBank">
    <label class="form-label fw-bold">Date</label>
    <input type="date"
           class="form-control"
           t-model="state.date"
           t-att-max="todayStr"/>
    <small class="text-muted">Date the bank transfer actually happened. Today by default.</small>
</div>
```

**Payload conditional** (inside `confirm()`):
```js
const kwargs = {
    session_id: this.pos.session.id,
    partner_id: this.state.partner.id,
    amount: parseFloat(this.state.amount),
    journal_id: this.state.journal_id,
    memo: this.state.memo || "",
};
if (this.selectedJournalIsBank) {
    kwargs.date = this.state.date;
}
```

**isValid unchanged.** Date field always has a default value of today (initialised in state), so the empty-date case is unreachable via normal flow. Invalid date strings fall through to backend UserError.

### Backend RPC contract

**`sfya_pos_collect(session_id, partner_id, amount, journal_id, memo='', date=None)`**
**`sfya_pos_payout(session_id, partner_id, amount, journal_id, memo='', date=None)`**

Both forward to `_sfya_pos_create_payment(..., date=date)`.

**Validation order in `_sfya_pos_create_payment`:**

| # | Gate | Error |
|---|---|---|
| 1 | amount > 0 | (existing) `"Amount must be greater than zero."` |
| 2 | partner exists | (existing) `"Customer is required."` / `"Vendor is required."` |
| 3 | session id valid + open | (existing) `"POS session not found / closed."` |
| 4 | journal_id missing / not found / wrong type / wrong company | (existing 4 errors) |
| 5 | (payout only) partner has `supplier_rank > 0` | (existing) `"Pay Out is only allowed to vendor partners."` |
| 6 | (bank journal + date supplied) date string parseable | `"Invalid date format."` |
| 7 | (bank journal + date supplied) parsed date ≤ today | `"Date cannot be in the future."` |
| 8 | (after action_post) date inside locked period | Odoo built-in `UserError` from `account.move` |

**Resolution logic:**
```python
resolved_date = fields.Date.today()
if journal.type == 'bank' and date:
    try:
        resolved_date = fields.Date.from_string(date)
    except (ValueError, TypeError):
        raise UserError(_("Invalid date format."))
    if resolved_date > fields.Date.today():
        raise UserError(_("Date cannot be in the future."))
# cash journal: ignore passed date; resolved_date stays today
```

**Cash override is deliberate belt-and-suspenders.** A future RPC caller that sends `journal_id=cash + date=past` gets today silently — no error, no surprise. The frontend never sends date for cash, so this branch is unreachable from our own UI.

### Migration

- No DB migration. `account.payment.date` is stock Odoo and already populated on existing rows.
- Existing payments unchanged — keep whatever date they currently have.
- RPC signature gains optional kwarg only. Callers omitting `date` get today exactly like before. No breaking change for any hypothetical external caller.

### Error matrix (full)

| Condition | Behavior |
|---|---|
| Date input left at default (today) | Posts with today, normal flow |
| Date set to past date inside open period | Posts with that date |
| Date set to past date inside locked period | Odoo `UserError`: "You cannot create journal items on a locked period." (surfaces in modal) |
| Date set to future date | UserError: "Date cannot be in the future." |
| Date string malformed (impossible via HTML5 date input, but defensive) | UserError: "Invalid date format." |
| Journal switched bank → cash, date populated | Field hides, state.date kept but not sent, backend uses today |
| Journal switched cash → bank | Field reappears with last-typed value (or today) |
| All existing gates | Unchanged |

## Testing

Verification-only (no Python test infra). Browser smoke + odoo shell after deploy:

| Check | How |
|---|---|
| Bank journal shows Date field | Open modal, pick bank journal, see Date row |
| Cash journal hides Date field | Open modal, pick cash journal, no Date row |
| Switching journal toggles field | bank → cash → bank, verify show/hide |
| Date defaults to today | Open modal with bank journal, value = today |
| Date max = today | HTML5 date picker disables future days |
| Past bank receipt posts | Pick bank, set date = today-3, partner, amount, confirm → toast, payment.date = today-3 |
| Future bank receipt blocked | DevTools: clear `max`, set tomorrow, confirm → UserError surfaces in modal |
| Cash always today (defensive) | Via odoo shell: call sfya_pos_collect with journal_id=cash + date=past → payment.date = today |
| Customer statement reflects backdated date | Open customer statement for that partner, row appears under correct date |
| Pay Out backdating works | Same flow with sfya_pos_payout to vendor partner |
| Vendor-only-payout gate still applies | Bank payout to customer (non-vendor) → existing UserError |

## Risks / Tradeoffs

- **No lower-bound limit beyond period locks.** Cashier could enter date from years ago. Mitigated by Odoo's period locks for closed years and accountant review during reconciliation. Adding a "previous fiscal period only" gate would be a hard constraint without business justification — left as future work if needed.
- **HTML5 `date` input UX varies by browser.** Safari iPad shows native iOS picker; Chrome desktop shows dropdown. Functionally identical — value sent is always YYYY-MM-DD.
- **No timezone consideration.** Server uses company's accounting date in UTC; modal builds today-string from browser local time. For SFYA (single PKT timezone), no edge case. Multi-timezone deployment would need server-side today comparison instead of trusting frontend.
- **Defensive cash override is silent.** If a future bug in the modal sends `date` for cash, backend forces today without warning. Acceptable because frontend is the only caller and its conditional is well-tested; logging the override is overkill.

## Out of scope (future work, not in this release)

- "Backdated only within current fiscal period" gate.
- Reason/justification text field for backdated entries.
- Audit trail / report of all backdated entries for accountant review.
- Time-of-day input for bank transfers.
- Auto-match backdated payment against existing bank statement lines.

## Acceptance

Plan complete when all of:
- Bank journal in modal shows Date field; cash hides it.
- Past-dated bank receipt posts and shows on customer statement at the backdated date.
- Future-dated bank receipt rejected with `"Date cannot be in the future."`
- Cash receipts unaffected — always today, no date field surfaces.
- All prior gates (amount>0, partner, session, journal type/company, vendor-only-payout) still in force.
- Manifest at `18.0.3.0.0` and module upgraded on VPS.
