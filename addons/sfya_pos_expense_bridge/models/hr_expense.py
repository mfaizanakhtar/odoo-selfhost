from odoo import api, fields, models


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    sfya_payment_source_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Source',
        domain="[('type', 'in', ('cash', 'bank')), ('company_id', '=', company_id)]",
        compute='_compute_sfya_payment_source_journal_id',
        store=True,
        readonly=False,
        copy=False,
        help='Where the money for this company-paid expense comes from. '
             'The POS cash journal deducts from the open POS session; a bank '
             'journal posts a reconciled bank payment instead.',
    )

    affects_pos_cash = fields.Boolean(
        string='Deduct from POS cash drawer',
        compute='_compute_affects_pos_cash',
        store=True,
        readonly=True,
        copy=False,
        help='Derived: true when Payment Source is the POS cash journal. '
             'Paying such an expense creates a Cash Out on the open POS '
             'session (queued if none is open).',
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

    sfya_bank_move_id = fields.Many2one(
        'account.move',
        string='Bank Payment Entry',
        readonly=True,
        copy=False,
        help='Journal entry created when this expense was paid from a bank '
             'journal instead of the POS cash drawer.',
    )

    @api.model
    def _sfya_pos_cash_journal(self):
        """The account.journal behind the POS cash payment method (may be empty)."""
        pm = self.env['pos.payment.method'].sudo().search(
            [('is_cash_count', '=', True)], limit=1
        )
        return pm.journal_id

    @api.depends('payment_mode')
    def _compute_sfya_payment_source_journal_id(self):
        pos_cash = self._sfya_pos_cash_journal()
        for rec in self:
            if rec.payment_mode == 'company_account':
                if not rec.sfya_payment_source_journal_id:
                    rec.sfya_payment_source_journal_id = pos_cash
            else:
                rec.sfya_payment_source_journal_id = False

    @api.depends('payment_mode', 'sfya_payment_source_journal_id')
    def _compute_affects_pos_cash(self):
        pos_cash = self._sfya_pos_cash_journal()
        for rec in self:
            rec.affects_pos_cash = (
                rec.payment_mode == 'company_account'
                and bool(pos_cash)
                and rec.sfya_payment_source_journal_id == pos_cash
            )
