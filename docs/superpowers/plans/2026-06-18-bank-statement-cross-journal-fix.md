# Bank Statement — Cross-Journal Contamination Fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix bank statement report so each bank journal only shows its own outstanding-account lines, while preserving opening-balance detection from entries posted via non-bank journals (e.g., General/MISC).

**Architecture:** Hybrid AML filter domain — `default_account_id` stays journal-unfiltered (catches opening JEs from MISC journal); outstanding-account lines scoped by `journal_id`. One-commit change to `_get_report_values` domain logic in `bank_statement_report.py`.

**Tech Stack:** Odoo 18 Community, Python, account.move.line ORM search domain

## Global Constraints

- Module version bump: `sfya_bank_statement` from 18.0.1.1.0 to 18.0.1.2.0
- Deploy: push to main → GitHub Actions → rsync → `docker compose up -d --build`
- Module upgrade on VPS: `button_immediate_upgrade()` via odoo shell
- Report tested via wizard UI (not test framework)
- `account.account.code` NOT available as DB column — use ORM only for field access

---
## File Structure

**Modify (1 file):**
- `addons/sfya_bank_statement/reports/bank_statement_report.py` — hybrid domain logic + `_get_journal_money_accounts` returns dict per account source

**No new files.**

## Background (from VPS probe 2026-06-18)

Bank journals and their accounts:

| id | Name | Code | Default Account |
|----|------|------|----------------|
| 6  | Meezan bank | BNK1 | 1126001 (id=85) |
| 7  | Shop Cash | RCV | 1126002 (id=86) |
| 11 | HMB | BNK2 | 1126006 (id=96) |
| 12 | BANK 3 | BNK3 | 1126007 (id=97) |

**Outstanding accounts (shared):**
- `1126004 Outstanding Receipts (id=90)` — used by Meezan (1 line), Shop Cash (5 lines), HMB (3 lines)
- `1126005 Outstanding Payments (id=91)` — used by Shop Cash only (60 lines)

**Other findings:**
- Payment method lines have NO `payment_account_id` set — all outstanding accounts come from actual `account.payment` records
- Opening JE (id=141, ref=OPENING-BAL-23) posted via MISC journal
- Each bank's `default_account_id` only has lines from its own journal — no cross-journal leakage via default accounts
- `account.account.internal_type` field does not exist in this Odoo build

**Root cause:** `_get_report_values()` builds domain with `account_id IN (default_acct, 1126004)` but NO `journal_id` filter. Shared 1126004 leaks every bank's payments into every other bank's report.

---

### Task 1: Hybrid domain filter in report

**Files:**
- Modify: `addons/sfya_bank_statement/reports/bank_statement_report.py`

**Interfaces:**
- Consumes: `_get_journal_money_accounts(self, journal)` — current method, will refactor
- Produces: Updated `_get_report_values` + `_get_journal_money_accounts` returning per-source dict

- [ ] **Step 1: Read current file to confirm baseline**

```bash
cat /Users/faizanakhter/odoo-selfhost/addons/sfya_bank_statement/reports/bank_statement_report.py
```

- [ ] **Step 2: Refactor `_get_journal_money_accounts` to return per-source account data**

Change return from flat `set(int)` to `dict` with two keys:
- `'default'`: journal.default_account_id.id (or None)
- `'outstanding_ids'`: set of outstanding account IDs

```python
def _get_journal_money_accounts(self, journal):
    """Return dict with 'default' account id and 'outstanding_ids' set.

    default: the journal's default_account_id (settled side).
      Kept journal-unfiltered so opening JEs posted via General/MISC
      journal that hit this account still appear in the statement.
    outstanding_ids: outstanding accounts from account_payment records.
      Scoped by journal_id downstream to prevent cross-journal leakage.
    """
    result = {
        'default': journal.default_account_id.id if journal.default_account_id else None,
        'outstanding_ids': set(),
    }
    self.env.cr.execute(
        "SELECT DISTINCT outstanding_account_id FROM account_payment "
        "WHERE journal_id = %s AND outstanding_account_id IS NOT NULL",
        (journal.id,),
    )
    result['outstanding_ids'].update(r[0] for r in self.env.cr.fetchall())
    return result
```

- [ ] **Step 3: Update `_get_report_values` to use hybrid domain**

Replace the flat `acct_ids` usage with two-part domain: default account (no journal filter) + outstanding accounts (with journal filter).

```python
@api.model
def _get_report_values(self, docids, data=None):
    wizards = self.env['sfya.bank.statement.wizard'].browse(docids)
    lines_by_wizard = {}
    opening_by_wizard = {}
    closing_by_wizard = {}
    accounts_by_wizard = {}
    AML = self.env['account.move.line']
    for w in wizards:
        money = self._get_journal_money_accounts(w.journal_id)
        # Build per-journal account records for display
        all_acct_ids = set()
        if money['default']:
            all_acct_ids.add(money['default'])
        all_acct_ids.update(money['outstanding_ids'])
        accounts_by_wizard[w.id] = self.env['account.account'].browse(
            sorted(all_acct_ids)
        )
        if not all_acct_ids:
            lines_by_wizard[w.id] = []
            opening_by_wizard[w.id] = 0.0
            closing_by_wizard[w.id] = 0.0
            continue

        # Build domains — two-tier: default account unfiltered, outstanding scoped
        posted_domain = [('parent_state', '=', 'posted')]

        # Part 1: Lines on the journal's default account (any journal — catches opening JEs)
        default_domain = posted_domain.copy()
        if money['default']:
            default_domain.append(('account_id', '=', money['default']))

        # Part 2: Lines on outstanding accounts (scoped by journal_id)
        outstanding_domain = posted_domain.copy()
        if money['outstanding_ids']:
            outstanding_domain.append(('account_id', 'in', list(money['outstanding_ids'])))
            outstanding_domain.append(('journal_id', '=', w.journal_id.id))

        # Combine: prior (date < date_from)
        prior_domain_components = posted_domain.copy()
        prior_date_cond = [('date', '<', w.date_from)]
        prior_or_clauses = []
        if money['default']:
            prior_or_clauses.append([
                ('account_id', '=', money['default']),
            ] + prior_date_cond)
        if money['outstanding_ids']:
            prior_or_clauses.append([
                ('account_id', 'in', list(money['outstanding_ids'])),
                ('journal_id', '=', w.journal_id.id),
            ] + prior_date_cond)

        # Use Odoo OR syntax: ['|', domain1, domain2] for 2 or more alternatives
        prior_domain = posted_domain.copy()
        if len(prior_or_clauses) == 1:
            prior_domain += prior_or_clauses[0]
        elif len(prior_or_clauses) >= 2:
            # Build nested OR chain
            for clause in prior_or_clauses:
                prior_domain = ['|'] + [prior_domain, clause]
            # The final prior_domain has extra nesting, simplify below
            pass

        # Simpler approach: flat OR in domain
        if money['default'] and money['outstanding_ids']:
            prior = AML.search(
                [('parent_state', '=', 'posted'),
                 '|',
                 ('account_id', '=', money['default']),
                 '&',
                 ('account_id', 'in', list(money['outstanding_ids'])),
                 ('journal_id', '=', w.journal_id.id),
                 ('date', '<', w.date_from)]
            )
            in_range = AML.search(
                [('parent_state', '=', 'posted'),
                 '|',
                 ('account_id', '=', money['default']),
                 '&',
                 ('account_id', 'in', list(money['outstanding_ids'])),
                 ('journal_id', '=', w.journal_id.id),
                 ('date', '>=', w.date_from),
                 ('date', '<=', w.date_to)],
                order='date asc, id asc',
            )
        elif money['default']:
            prior = AML.search(default_domain + [('date', '<', w.date_from)])
            in_range = AML.search(
                default_domain + [('date', '>=', w.date_from), ('date', '<=', w.date_to)],
                order='date asc, id asc',
            )
        elif money['outstanding_ids']:
            prior = AML.search(outstanding_domain + [('date', '<', w.date_from)])
            in_range = AML.search(
                outstanding_domain + [('date', '>=', w.date_from), ('date', '<=', w.date_to)],
                order='date asc, id asc',
            )
        else:
            prior = AML.search([('id', '=', 0)])
            in_range = AML.search([('id', '=', 0)])

        opening = sum(prior.mapped('debit')) - sum(prior.mapped('credit'))
        running = opening
        line_dicts = []
        for line in in_range:
            running += line.debit - line.credit
            line_dicts.append({
                'date': line.date,
                'ref': line.move_id.ref or line.move_id.name or '',
                'partner_name': line.partner_id.name or '',
                'label': line.name or '',
                'account_code': line.account_id.code,
                'debit': line.debit,
                'credit': line.credit,
                'running_balance': running,
            })
        lines_by_wizard[w.id] = line_dicts
        opening_by_wizard[w.id] = opening
        closing_by_wizard[w.id] = running
    return {
        'doc_ids': docids,
        'doc_model': 'sfya.bank.statement.wizard',
        'docs': wizards,
        'company': self.env.company,
        'lines_by_wizard': lines_by_wizard,
        'opening_by_wizard': opening_by_wizard,
        'closing_by_wizard': closing_by_wizard,
        'accounts_by_wizard': accounts_by_wizard,
    }
```

- [ ] **Step 4: Bump module version**

Edit `addons/sfya_bank_statement/__manifest__.py`, change `'version': '18.0.1.1.0'` → `'version': '18.0.1.2.0'`

- [ ] **Step 5: Commit**

```bash
git add addons/sfya_bank_statement/__manifest__.py addons/sfya_bank_statement/reports/bank_statement_report.py
git commit -m "fix: scope outstanding-account lines by journal_id to stop cross-journal leakage

1126004 Outstanding Receipts is company-wide, shared across all bank
journals. Prior domain filtered by account_id only, leaking every
bank's payments into every report.

Hybrid approach:
- default_account_id kept journal-unfiltered (catches opening JEs
  posted via General/MISC journal)
- outstanding-account lines scoped by journal_id (prevents leakage)
"
```

- [ ] **Step 6: Push and deploy**

```bash
git push origin main
```

Monitor CI via:

```bash
gh run list --limit 3 --repo mfaizanakhtar/odoo-selfhost
```

Wait for deploy job success.

- [ ] **Step 7: Upgrade module on VPS**

```bash
ssh deploy@46.224.228.181 'docker exec -i odoo-stack-odoo-1 odoo shell -d odoo --no-http --stop-after-init' <<'EOF'
mod = env['ir.module.module'].search([('name','=','sfya_bank_statement')])
mod.button_immediate_upgrade()
env.cr.commit()
EOF
```

- [ ] **Step 8: Verify on live data**

Test Meezan bank (id=6): should show opening + BNK1 lines + closing. NO HMB/RCV line from 1126004.

Test HMB (id=11): should show opening + BNK2 lines + closing. NO Meezan/RCV line from 1126004.

Test Shop Cash (id=7): should show opening + RCV lines + closing, including 1126005 Outstanding Payments lines.

Can verify via odoo shell:

```bash
ssh deploy@46.224.228.181 'docker exec -i odoo-stack-odoo-1 odoo shell -d odoo --no-http --stop-after-init' <<'EOF'
from datetime import date
wiz = env['sfya.bank.statement.wizard'].create({
    'journal_id': 6,
    'date_from': date(2025, 6, 1),
    'date_to': date(2026, 6, 18),
})
report = env['report.sfya_bank_statement.report_bank_statement']
vals = report._get_report_values([wiz.id])
lines = vals['lines_by_wizard'][wiz.id]
print("Meezan lines: %s" % len(lines))
print("Opening: %s  Closing: %s" % (vals['opening_by_wizard'][wiz.id], vals['closing_by_wizard'][wiz.id]))
# Check no HMB or RCV refs leak in
for l in lines:
    if 'HMB' in (l['ref'] or '') or 'BNK2' in (l['ref'] or ''):
        print("LEAK: HMB line in Meezan report: %s" % l)
    if 'RCV' in (l['ref'] or '') or 'Shop Cash' in (l['partner_name'] or ''):
        print("LEAK: RCV line in Meezan report: %s" % l)
print("Done Meezan check")

wiz2 = env['sfya.bank.statement.wizard'].create({
    'journal_id': 11,
    'date_from': date(2025, 6, 1),
    'date_to': date(2026, 6, 18),
})
vals2 = report._get_report_values([wiz2.id])
lines2 = vals2['lines_by_wizard'][wiz2.id]
print("\nHMB lines: %s" % len(lines2))
print("Opening: %s  Closing: %s" % (vals2['opening_by_wizard'][wiz2.id], vals2['closing_by_wizard'][wiz2.id]))
for l in lines2:
    if 'Meezan' in (l['ref'] or '') or 'BNK1' in (l['ref'] or ''):
        print("LEAK: Meezan line in HMB report: %s" % l)
print("Done HMB check")
env.cr.rollback()
EOF
```

Expected:
- Meezan: opening ≈ whatever balance, lines only from BNK1, no HMB/RCV lines
- HMB: lines only from BNK2, no Meezan/RCV lines
- No "LEAK" print lines

- [ ] **Step 9: Print report via browser to verify PDF renders correctly**

Navigate to Invoicing → Reporting → Bank Statements → select Meezan bank, set date range, click Print. Verify PDF shows correct account header, account column, and correct running balance.