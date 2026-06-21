# Partner/Shareholder Cash Withdrawals (Owner's Drawing)

## Status: DEPLOYED (2026-06-21)

Module `sfya_pos_cash_movement` v18.0.4.0.0 — 6 commits (403dc49..6a4ccd6)

## What was built

Partners/shareholders can withdraw cash or bank funds from POS. Creates proper journal entries:
- **DR:** Owner's Drawing account (equity, code 3100)
- **CR:** Cash or Bank journal account

### Components
- `res.partner.is_shareholder` — boolean flag to tag partners
- `res.company.sfya_owner_drawing_account_id` — equity account (auto-created as 3100 on fresh install)
- `sfya_pos_partner_drawing()` RPC — validates shareholder, creates payment with destination_account_id override
- POS "Partner Drawing" button on product screen (alongside Collect/Pay Out)
- Reuses same modal (partner picker + journal + amount + memo)
- Closing popup: "Partner Drawings (Cash)" collapsible section
- Drawings reduce expected cash in closing (like payouts)
- Print slip shows "Partner Drawing" type and "Withdrawn by" signature line

### Current shareholders
- Administrator (faizan.ac@yahoo.com)
- Sufyan (accesology@gmail.com)

## Known limitations / future improvements

1. **Partner picker shows all partners** — server validates `is_shareholder` on submit, but UX would be better with client-side filtering (requires loading `is_shareholder` into POS partner data)
2. **No partner drawing reports/summaries** — can query via accounting reports filtering on account 3100, but no dedicated report
3. **No withdrawal limits** — any shareholder can withdraw any amount
4. **Bank section header doesn't show drawings total** — drawing rows appear in table body but total missing from collapsed header
5. **`sfyaCashAdjustment` getter** — includes drawings now but is unused in template (informational)
6. **`post_init_hook` only runs on fresh install** — for upgrades, account 3100 must be created manually via odoo shell (done for current deployment)
7. **Backend-only withdrawals** — partners can use standard Odoo payments for non-POS withdrawals, no custom UI needed

## Key files (all under addons/sfya_pos_cash_movement/)

| File | Purpose |
|------|---------|
| models/res_partner.py | `is_shareholder` boolean |
| models/res_company.py | `sfya_owner_drawing_account_id` field |
| models/pos_config.py | related field for POS config form |
| models/account_payment.py | `sfya_pos_partner_drawing()` RPC |
| models/pos_session.py | `get_sfya_cash_movements()` with drawings separation |
| views/res_partner_views.xml | Shareholder checkbox on partner form |
| views/pos_config_views.xml | Drawing account in POS config |
| static/src/app/product_screen_buttons.js/xml | Partner Drawing button |
| static/src/app/cash_movement_modal.js/xml | Drawing mode in modal + print slip |
| static/src/app/closing_dialog_patch.js/xml | Drawings section in closing popup |

## How to mark a partner as shareholder (UI)

Contacts > open partner > scroll to bottom > "SFYA Shareholder" section > check "Shareholder / Partner" > Save
