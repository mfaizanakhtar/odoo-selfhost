# Run via odoo shell. Creates a bank-paid expense, drives it to done, asserts the bank JE, rolls back.
import sys, traceback
try:
    Exp = env['hr.expense']
    Sheet = env['hr.expense.sheet']
    emp = env['hr.employee'].search([('user_id', '!=', False)], limit=1)
    bank = env['account.journal'].search([('type', '=', 'bank')], limit=1)
    bank_acct = bank.default_account_id
    print("bank:", bank.name, "acct:", bank_acct.code)

    e = Exp.create({
        'name': 'VERIFY T2 BANK',
        'employee_id': emp.id,
        'payment_mode': 'company_account',
        'total_amount_currency': 250.0,
    })
    e.sfya_payment_source_journal_id = bank.id
    print("affects_pos_cash:", e.affects_pos_cash)  # expect False

    sheet = Sheet.create({
        'name': 'VERIFY T2 SHEET',
        'employee_id': emp.id,
        'expense_line_ids': [(6, 0, e.ids)],
    })
    sheet.action_submit_sheet()
    sheet.action_approve_expense_sheets()
    sheet.action_sheet_move_post()  # posts entries -> state done

    print("sheet state:", sheet.state)                    # expect 'done'
    print("bank_move set:", bool(e.sfya_bank_move_id))     # expect True
    print("pos session set:", bool(e.pos_cash_session_id)) # expect False (no POS)
    m = e.sfya_bank_move_id
    print("bank move journal:", m.journal_id.name, "ref:", m.ref, "state:", m.state)
    for l in m.line_ids:
        print("  line", l.account_id.code, "dr", l.debit, "cr", l.credit,
              "name:", l.name, "reconciled:", l.reconciled)
    # bank account must be credited 250 with memo; clearing leg reconciled
    bank_line = m.line_ids.filtered(lambda l: l.account_id == bank_acct)
    print("bank credited 250:", bank_line.credit == 250.0)  # expect True
    clr_line = m.line_ids.filtered(lambda l: l.account_id != bank_acct)
    print("clearing leg reconciled:", clr_line.reconciled)  # expect True
finally:
    env.cr.rollback()
    print("ROLLED BACK")
