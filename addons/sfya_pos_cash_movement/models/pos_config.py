from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    sfya_max_cash_difference = fields.Float(
        string='Max Allowed Cash Difference (Rs)',
        default=500.0,
        help='Block session closing if cash difference (|counted - expected|) exceeds this amount. '
             'Set to 0 to disable the threshold check (zero-count check still applies).',
    )
    sfya_owner_drawing_account_id = fields.Many2one(
        related='company_id.sfya_owner_drawing_account_id',
        readonly=False,
        string='Owner Drawing Account',
    )
    sfya_partner_transfer_journal_id = fields.Many2one(
        related='company_id.sfya_partner_transfer_journal_id',
        readonly=False,
        string='Partner Transfer Journal',
    )
    sfya_internal_transfer_account_id = fields.Many2one(
        related='company_id.sfya_internal_transfer_account_id',
        readonly=False,
        string='Internal Transfer Clearing Account',
    )
