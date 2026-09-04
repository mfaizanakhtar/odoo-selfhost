from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Backfill Payment Source = POS cash journal on existing company-paid
    expenses. Display-only: writes the field, creates no accounting moves."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    pos_pm = env['pos.payment.method'].search(
        [('is_cash_count', '=', True)], limit=1
    )
    journal = pos_pm.journal_id
    if not journal:
        return
    expenses = env['hr.expense'].search([
        ('payment_mode', '=', 'company_account'),
        ('sfya_payment_source_journal_id', '=', False),
    ])
    if expenses:
        expenses.write({'sfya_payment_source_journal_id': journal.id})
