from odoo import fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'
    sfya_owner_drawing_account_id = fields.Many2one(
        'account.account',
        string="Owner's Drawing Account",
        help='Equity account debited when partners withdraw cash/bank funds.',
        domain="[('account_type', 'in', ['equity', 'equity_unaffected'])]",
    )
    sfya_partner_transfer_journal_id = fields.Many2one(
        'account.journal',
        string='Partner Transfer Journal',
        help='Miscellaneous-operations journal used to post POS Pay Out '
             '"settle via another partner" transfers. These entries have no '
             'cash/bank leg, so any type=General journal works; set this '
             'explicitly if the company has more than one.',
        domain="[('type', '=', 'general')]",
    )
    sfya_internal_transfer_account_id = fields.Many2one(
        'account.account',
        string='Internal Transfer Clearing Account',
        help='Counterpart account used on both legs of a POS-initiated '
             'journal-to-journal transfer (e.g. shop cash till to a bank '
             'account). Both legs post together, so this account always '
             'nets to zero.',
        domain="[('account_type', '=', 'asset_current')]",
    )
    sfya_salary_expense_account_id = fields.Many2one(
        'account.account',
        string='Salary Expense Account',
        help='Expense account debited when salary is paid to an employee via POS.',
        domain="[('account_type', '=', 'expense')]",
    )
    sfya_employee_advance_account_id = fields.Many2one(
        'account.account',
        string='Employee Advance Account',
        help='Asset account debited when an employee is given a salary '
             'advance via POS, and credited when that advance is later '
             'offset against a salary payment.',
        domain="[('account_type', '=', 'asset_current')]",
    )
    sfya_salary_journal_id = fields.Many2one(
        'account.journal',
        string='Salary Offset Journal',
        help='Miscellaneous-operations journal used to post the cash-free '
             'portion of a POS salary payment that offsets a prior advance. '
             'Dedicated (not shared with Partner Transfer) so its move-name '
             'sequence is specific to salary entries.',
        domain="[('type', '=', 'general')]",
    )
