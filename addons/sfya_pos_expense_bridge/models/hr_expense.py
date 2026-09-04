from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


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

    def _sfya_create_bank_payment_move(self):
        """Post a reconciled bank entry for a bank-routed company expense.

        Dr <expense move's clearing account> / Cr <bank journal account>,
        memo 'Expense: <name>', then reconcile the clearing leg against the
        expense move's credit leg so nothing dangles. Idempotent.
        """
        self.ensure_one()
        if self.sfya_bank_move_id:
            return
        journal = self.sfya_payment_source_journal_id
        bank_account = journal.default_account_id
        if not bank_account:
            raise UserError(_(
                "Bank journal '%s' has no default account configured, so "
                "expense '%s' cannot be paid from it. Set the journal's bank "
                "account or choose a different Payment Source."
            ) % (journal.display_name, self.name or ''))

        exp_line = self.env['account.move.line'].sudo().search([
            ('expense_id', '=', self.id),
            ('parent_state', '=', 'posted'),
        ], limit=1)
        exp_move = exp_line.move_id
        if not exp_move:
            raise UserError(_(
                "No posted accounting entry found for expense '%s'; cannot "
                "post its bank payment."
            ) % (self.name or ''))

        clearing_lines = exp_move.line_ids.filtered(
            lambda l: l.credit > 0 and not l.reconciled
        )
        if len(clearing_lines) != 1:
            raise UserError(_(
                "Expected exactly one unreconciled payable line on the entry "
                "for expense '%s', found %s. Its bank payment must be handled "
                "manually."
            ) % (self.name or '', len(clearing_lines)))
        clearing_line = clearing_lines
        clearing_account = clearing_line.account_id
        amount = clearing_line.credit

        currency = self.company_id.currency_id
        if float_compare(amount, self.total_amount_currency,
                         precision_rounding=currency.rounding) != 0:
            raise UserError(_(
                "Bank payment amount (%s) does not match expense total (%s) "
                "for '%s'; refusing to post a mismatched bank entry."
            ) % (amount, self.total_amount_currency, self.name or ''))
        memo = 'Expense: %s' % (self.name or '')
        partner = self.employee_id.sudo().work_contact_id

        pay_move = self.env['account.move'].sudo().create({
            'journal_id': journal.id,
            'date': fields.Date.context_today(self),
            'ref': memo,
            'line_ids': [
                (0, 0, {
                    'account_id': clearing_account.id,
                    'debit': amount,
                    'credit': 0.0,
                    'name': memo,
                }),
                (0, 0, {
                    'account_id': bank_account.id,
                    'debit': 0.0,
                    'credit': amount,
                    'name': memo,
                    'partner_id': partner.id if partner else False,
                }),
            ],
        })
        pay_move.action_post()

        pay_clearing_line = pay_move.line_ids.filtered(
            lambda l: l.account_id == clearing_account
        )
        (clearing_line + pay_clearing_line).reconcile()

        self.sfya_bank_move_id = pay_move.id
