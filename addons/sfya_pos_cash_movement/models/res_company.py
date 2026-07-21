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
