# Run: docker compose exec -T odoo odoo shell -d odoo --no-http  < verify/verify_task1.py
import sys, traceback
try:
    Exp = env['hr.expense']
    pos_cash = Exp._sfya_pos_cash_journal()
    print("POS cash journal:", pos_cash.id, pos_cash.name)  # expect 7 Shop Cash
    emp = env['hr.employee'].search([], limit=1)
    e = Exp.create({
        'name': 'VERIFY T1',
        'employee_id': emp.id,
        'payment_mode': 'company_account',
        'total_amount_currency': 100.0,
    })
    print("default source journal:", e.sfya_payment_source_journal_id.id, "== pos_cash?",
          e.sfya_payment_source_journal_id == pos_cash)   # expect True
    print("affects_pos_cash (cash):", e.affects_pos_cash)  # expect True
    bank = env['account.journal'].search([('type','=','bank')], limit=1)
    e.sfya_payment_source_journal_id = bank.id
    print("affects_pos_cash (bank):", e.affects_pos_cash)  # expect False
    e.payment_mode = 'own_account'
    print("source cleared on own_account:", not e.sfya_payment_source_journal_id)  # expect True
finally:
    env.cr.rollback()
    print("ROLLED BACK")
