from odoo import fields, models

class ResPartner(models.Model):
    _inherit = 'res.partner'
    is_shareholder = fields.Boolean(
        string='Shareholder / Partner',
        default=False,
        help='If checked, this partner appears in the POS Partner Drawing flow.',
    )
