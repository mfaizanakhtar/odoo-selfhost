from odoo import fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'
    sfya_owner_drawing_account_id = fields.Many2one(
        'account.account',
        string="Owner's Drawing Account",
        help='Equity account debited when partners withdraw cash/bank funds.',
        domain="[('account_type', 'in', ['equity', 'equity_unaffected'])]",
    )
