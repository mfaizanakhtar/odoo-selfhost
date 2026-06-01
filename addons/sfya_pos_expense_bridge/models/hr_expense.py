from odoo import api, fields, models


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    affects_pos_cash = fields.Boolean(
        string='Deduct from POS cash drawer',
        compute='_compute_affects_pos_cash',
        store=True,
        readonly=False,
        copy=False,
        help='When checked, paying this expense creates a Cash Out line on '
             'the currently open POS session. If no session is open at '
             'payment time, the expense is queued and consumed when the '
             'next session opens.',
    )

    pos_cash_pending = fields.Boolean(
        string='POS Cash Out Pending',
        default=False,
        copy=False,
        readonly=True,
        help='True when expense is flagged to affect POS drawer but no '
             'session was open at payment time. Cleared when consumed by '
             'the next session opening.',
    )

    pos_cash_session_id = fields.Many2one(
        'pos.session',
        string='POS Session Deducted',
        readonly=True,
        copy=False,
        help='POS session where the Cash Out was registered for this '
             'expense.',
    )

    @api.depends('payment_mode')
    def _compute_affects_pos_cash(self):
        for rec in self:
            rec.affects_pos_cash = (rec.payment_mode == 'company_account')
