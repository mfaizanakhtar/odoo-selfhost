from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    sfya_opening_balance_account_id = fields.Many2one(
        'account.account',
        string='Opening Balance Equity Account',
        help='Counterpart account used when seeding customer/vendor opening balances.',
        domain="[('account_type', 'in', ['equity', 'equity_unaffected'])]",
    )
