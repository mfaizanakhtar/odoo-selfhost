from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    pos_session_id = fields.Many2one(
        'pos.session',
        string='POS Session',
        index=True,
        copy=False,
        help='If set, payment originated from POS Collect/Pay-Out flow during this session.',
    )
    sfya_is_internal_transfer = fields.Boolean(
        default=False,
        copy=False,
        help='True for both legs of a POS-initiated journal-to-journal '
             'transfer (e.g. shop cash till to a bank account). Used to '
             'exclude these from the generic Collect/Pay Out/Drawing '
             'listings and total them separately for the till '
             'expected-cash adjustment.',
    )
    sfya_transfer_pair_id = fields.Many2one(
        'account.payment',
        string='Paired Transfer Leg',
        copy=False,
        help='The other leg of this internal transfer (out<->in).',
    )
    sfya_salary_kind = fields.Selection(
        [('advance', 'Advance'), ('payment', 'Payment')],
        copy=False,
        help='Set for POS-originated salary legs only. "advance" = money '
             'given ahead of payday (destination is the Employee Advance '
             'account). "payment" = actual salary expense recognized '
             '(destination is the Salary Expense account); amount is the '
             'NET cash paid, after any advance offset. Used to exclude '
             'these legs from the generic Collect/Pay Out/Drawing listings '
             'and total them separately for the till expected-cash '
             'adjustment.',
    )
    sfya_employee_id = fields.Many2one('hr.employee', string='Employee', copy=False)
    sfya_salary_gross_amount = fields.Monetary(
        string='Gross Salary Amount', copy=False,
        help='Only set when sfya_salary_kind="payment". Full salary amount '
             'for the period, before any advance offset. Equal to `amount` '
             'when no offset was applied.',
    )
    sfya_salary_advance_offset = fields.Monetary(
        string='Advance Offset Applied', copy=False,
        help='Only set when sfya_salary_kind="payment". Portion of gross '
             'salary that was cleared against a prior advance instead of '
             'paid in cash/bank.',
    )
    sfya_salary_offset_move_id = fields.Many2one(
        'account.move', string='Salary Offset Entry', copy=False,
        help='The cash-free journal entry (if any) that cleared the '
             'advance offset alongside this payment.',
    )

    @api.model
    def sfya_pos_collect(self, session_id, partner_id, amount, journal_id, memo='', date=None):
        """RPC: cashier collects cash/bank payment from a customer or vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, journal_id, memo, payment_type='inbound', date=date,
        )

    @api.model
    def sfya_pos_payout(self, session_id, partner_id, amount, journal_id, memo='', date=None):
        """RPC: cashier pays out cash/bank to a vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, journal_id, memo, payment_type='outbound', date=date,
        )

    @api.model
    def sfya_pos_partner_drawing(self, session_id, partner_id, amount, journal_id, memo='', date=None):
        """RPC: shareholder/partner withdraws cash/bank funds."""
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        partner = self.env['res.partner'].sudo().browse(partner_id).exists()
        if not partner:
            raise UserError(_('Partner not found.'))
        if not partner.is_shareholder:
            raise UserError(_('Partner Drawing is only allowed for shareholders.'))
        if amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        if not journal_id:
            raise UserError(_('Account is required.'))
        journal = self.env['account.journal'].sudo().browse(journal_id).exists()
        if not journal:
            raise UserError(_('Account not found.'))
        if journal.type not in ('cash', 'bank'):
            raise UserError(_('Selected account is not a cash or bank journal.'))
        if journal.company_id.id != session.company_id.id:
            raise UserError(_("Account does not belong to this POS's company."))
        drawing_account = session.company_id.sfya_owner_drawing_account_id
        if not drawing_account:
            raise UserError(_('Owner Drawing account is not configured for this company.'))
        resolved_date = fields.Date.today()
        if journal.type == 'bank' and date:
            try:
                resolved_date = fields.Date.from_string(date)
            except (ValueError, TypeError):
                raise UserError(_("Invalid date format."))
            if resolved_date > fields.Date.today():
                raise UserError(_("Date cannot be in the future."))
        # cash journal: ignore passed date; resolved_date stays today
        payment = self.sudo().create({
            'partner_id': partner.id,
            'partner_type': 'supplier',
            'payment_type': 'outbound',
            'amount': amount,
            'journal_id': journal.id,
            'date': resolved_date,
            'memo': memo or False,
            'pos_session_id': session.id,
            'destination_account_id': drawing_account.id,
        })
        payment.action_post()
        return {
            'id': payment.id,
            'name': payment.name,
            'partner_id': partner.id,
            'partner_name': partner.name,
            'amount': payment.amount,
            'memo': payment.memo or '',
            'direction': 'outbound',
            'journal_id': journal.id,
            'journal_name': journal.name,
            'journal_type': journal.type,
        }

    @api.model
    def sfya_pos_internal_transfer(self, session_id, from_journal_id, to_journal_id, amount, memo='', date=None):
        """RPC: move funds directly between two of the company's own cash/bank
        journals (e.g. shop cash till to a bank account, or bank to bank).

        Posts two linked account.payment records with no partner, using a
        dedicated clearing account as the counterpart on both legs so the
        pair always nets to zero. Till expected-cash math is adjusted
        separately in pos_session.get_sfya_cash_movements.
        """
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        if from_journal_id == to_journal_id:
            raise UserError(_('Source and destination account must be different.'))
        from_journal = self.env['account.journal'].sudo().browse(from_journal_id).exists()
        to_journal = self.env['account.journal'].sudo().browse(to_journal_id).exists()
        if not from_journal or not to_journal:
            raise UserError(_('Account not found.'))
        if from_journal.type not in ('cash', 'bank') or to_journal.type not in ('cash', 'bank'):
            raise UserError(_('Both accounts must be a cash or bank journal.'))
        if from_journal.company_id.id != session.company_id.id or to_journal.company_id.id != session.company_id.id:
            raise UserError(_("Account does not belong to this POS's company."))
        if amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        clearing_account = session.company_id.sfya_internal_transfer_account_id
        if not clearing_account:
            raise UserError(_('Internal Transfer Clearing Account is not configured for this company.'))

        resolved_date = fields.Date.today()
        if (from_journal.type == 'bank' or to_journal.type == 'bank') and date:
            try:
                resolved_date = fields.Date.from_string(date)
            except (ValueError, TypeError):
                raise UserError(_("Invalid date format."))
            if resolved_date > fields.Date.today():
                raise UserError(_("Date cannot be in the future."))
        # both journals cash: ignore passed date; resolved_date stays today

        payment_out = self.sudo().create({
            'payment_type': 'outbound',
            'journal_id': from_journal.id,
            'amount': amount,
            'date': resolved_date,
            'memo': memo or False,
            'pos_session_id': session.id,
            'destination_account_id': clearing_account.id,
            'sfya_is_internal_transfer': True,
        })
        payment_in = self.sudo().create({
            'payment_type': 'inbound',
            'journal_id': to_journal.id,
            'amount': amount,
            'date': resolved_date,
            'memo': memo or False,
            'pos_session_id': session.id,
            'destination_account_id': clearing_account.id,
            'sfya_is_internal_transfer': True,
        })
        payment_out.sfya_transfer_pair_id = payment_in.id
        payment_in.sfya_transfer_pair_id = payment_out.id
        payment_out.action_post()
        payment_in.action_post()
        return {
            'out_id': payment_out.id,
            'out_name': payment_out.name,
            'in_id': payment_in.id,
            'in_name': payment_in.name,
            'from_journal_id': from_journal.id,
            'from_journal_name': from_journal.name,
            'to_journal_id': to_journal.id,
            'to_journal_name': to_journal.name,
            'amount': amount,
            'memo': memo or '',
            'direction': 'internal_transfer',
        }

    @api.model
    def sfya_pos_salary_advance(self, session_id, employee_id, amount, journal_id, memo='', date=None):
        """RPC: cashier gives an employee a cash/bank advance against future salary."""
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        employee = self.env['hr.employee'].sudo().browse(employee_id).exists()
        if not employee or not employee.active:
            raise UserError(_('Employee not found.'))
        if employee.company_id.id != session.company_id.id:
            raise UserError(_("Employee does not belong to this POS's company."))
        if amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        if not journal_id:
            raise UserError(_('Account is required.'))
        journal = self.env['account.journal'].sudo().browse(journal_id).exists()
        if not journal:
            raise UserError(_('Account not found.'))
        if journal.type not in ('cash', 'bank'):
            raise UserError(_('Selected account is not a cash or bank journal.'))
        if journal.company_id.id != session.company_id.id:
            raise UserError(_("Account does not belong to this POS's company."))
        advance_account = session.company_id.sfya_employee_advance_account_id
        if not advance_account:
            raise UserError(_('Employee Advance account is not configured for this company.'))
        resolved_date = fields.Date.today()
        if journal.type == 'bank' and date:
            try:
                resolved_date = fields.Date.from_string(date)
            except (ValueError, TypeError):
                raise UserError(_("Invalid date format."))
            if resolved_date > fields.Date.today():
                raise UserError(_("Date cannot be in the future."))
        # cash journal: ignore passed date; resolved_date stays today
        payment = self.sudo().create({
            'partner_id': employee.work_contact_id.id,
            'partner_type': 'supplier',
            'payment_type': 'outbound',
            'amount': amount,
            'journal_id': journal.id,
            'date': resolved_date,
            'memo': memo or False,
            'pos_session_id': session.id,
            'destination_account_id': advance_account.id,
            'sfya_salary_kind': 'advance',
            'sfya_employee_id': employee.id,
        })
        payment.action_post()
        return {
            'id': payment.id,
            'name': payment.name,
            'employee_id': employee.id,
            'employee_name': employee.name,
            'amount': payment.amount,
            'memo': payment.memo or '',
            'direction': 'salary_advance',
            'journal_id': journal.id,
            'journal_name': journal.name,
            'journal_type': journal.type,
        }

    @api.model
    def sfya_pos_salary_payment(self, session_id, employee_id, gross_amount, advance_offset, journal_id, memo='', date=None):
        """RPC: cashier pays an employee's salary, optionally offsetting a prior advance.

        net_cash = gross_amount - advance_offset is posted as an
        account.payment against the Salary Expense account (skipped
        entirely if net_cash is 0). If advance_offset > 0, a cash-free
        2-line account.move recognizes that portion of the expense and
        clears the same amount off the Employee Advance account - same
        construction pattern as sfya_pos_partner_transfer.
        """
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        employee = self.env['hr.employee'].sudo().browse(employee_id).exists()
        if not employee or not employee.active:
            raise UserError(_('Employee not found.'))
        if employee.company_id.id != session.company_id.id:
            raise UserError(_("Employee does not belong to this POS's company."))
        if gross_amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        advance_offset = advance_offset or 0.0
        if advance_offset < 0:
            raise UserError(_('Advance offset cannot be negative.'))
        tol = 0.005  # float-rounding tolerance, matches _sfya_resolve_partner_type
        if advance_offset > gross_amount + tol:
            raise UserError(_('Advance offset cannot exceed gross salary amount.'))
        advance_offset = min(advance_offset, gross_amount)
        if not journal_id:
            raise UserError(_('Account is required.'))
        journal = self.env['account.journal'].sudo().browse(journal_id).exists()
        if not journal:
            raise UserError(_('Account not found.'))
        if journal.type not in ('cash', 'bank'):
            raise UserError(_('Selected account is not a cash or bank journal.'))
        if journal.company_id.id != session.company_id.id:
            raise UserError(_("Account does not belong to this POS's company."))
        salary_account = session.company_id.sfya_salary_expense_account_id
        if not salary_account:
            raise UserError(_('Salary Expense account is not configured for this company.'))
        if advance_offset > 0:
            advance_account = session.company_id.sfya_employee_advance_account_id
            salary_journal = session.company_id.sfya_salary_journal_id
            if not advance_account:
                raise UserError(_('Employee Advance account is not configured for this company.'))
            if not salary_journal:
                raise UserError(_('Salary Offset Journal is not configured for this company.'))
            outstanding_balance = self.get_sfya_salary_advance_balance(employee.id)
            if advance_offset > outstanding_balance + tol:
                raise UserError(_(
                    "Advance offset exceeds this employee's outstanding advance balance of %s.",
                    outstanding_balance,
                ))
            advance_offset = min(advance_offset, outstanding_balance)

        resolved_date = fields.Date.today()
        if journal.type == 'bank' and date:
            try:
                resolved_date = fields.Date.from_string(date)
            except (ValueError, TypeError):
                raise UserError(_("Invalid date format."))
            if resolved_date > fields.Date.today():
                raise UserError(_("Date cannot be in the future."))
        # cash journal: ignore passed date; resolved_date stays today

        net_cash = gross_amount - advance_offset
        payment = self.browse()
        if net_cash > 0:
            payment = self.sudo().create({
                'partner_id': employee.work_contact_id.id,
                'partner_type': 'supplier',
                'payment_type': 'outbound',
                'amount': net_cash,
                'journal_id': journal.id,
                'date': resolved_date,
                'memo': memo or False,
                'pos_session_id': session.id,
                'destination_account_id': salary_account.id,
                'sfya_salary_kind': 'payment',
                'sfya_employee_id': employee.id,
                'sfya_salary_gross_amount': gross_amount,
                'sfya_salary_advance_offset': advance_offset,
            })
            payment.action_post()

        move = self.env['account.move']
        if advance_offset > 0:
            move = self.env['account.move'].sudo().create({
                'move_type': 'entry',
                'journal_id': session.company_id.sfya_salary_journal_id.id,
                'date': resolved_date,
                'ref': memo or _('Salary advance offset: %s', employee.name),
                'pos_session_id': session.id,
                'sfya_is_salary_offset': True,
                'sfya_salary_offset_employee_id': employee.id,
                'sfya_salary_offset_amount': advance_offset,
                'line_ids': [
                    Command.create({
                        'partner_id': employee.work_contact_id.id,
                        'account_id': salary_account.id,
                        'debit': advance_offset,
                        'credit': 0.0,
                        'name': memo or _('Salary (advance offset) - %s', employee.name),
                    }),
                    Command.create({
                        'partner_id': employee.work_contact_id.id,
                        'account_id': session.company_id.sfya_employee_advance_account_id.id,
                        'debit': 0.0,
                        'credit': advance_offset,
                        'name': memo or _('Advance cleared - %s', employee.name),
                    }),
                ],
            })
            move.action_post()
            if net_cash > 0:
                payment.sfya_salary_offset_move_id = move.id

        return {
            'payment_id': payment.id if net_cash > 0 else None,
            'payment_name': payment.name if net_cash > 0 else None,
            'move_id': move.id if advance_offset > 0 else None,
            'move_name': move.name if advance_offset > 0 else None,
            'employee_id': employee.id,
            'employee_name': employee.name,
            'gross_amount': gross_amount,
            'advance_offset': advance_offset,
            'net_cash': net_cash,
            'memo': memo or '',
            'journal_id': journal.id,
            'journal_name': journal.name,
            'journal_type': journal.type,
            'direction': 'salary_payment',
        }

    @api.model
    def get_sfya_salary_advance_balance(self, employee_id):
        """Return an employee's outstanding advance balance (company-wide,
        not session-scoped): total advances given minus total already
        cleared via a salary-payment offset.
        """
        employee = self.env['hr.employee'].sudo().browse(employee_id).exists()
        if not employee:
            return 0.0
        advances_given = sum(self.sudo().search([
            ('sfya_employee_id', '=', employee.id),
            ('sfya_salary_kind', '=', 'advance'),
            ('state', 'in', ['paid', 'in_process']),
            ('company_id', '=', self.env.company.id),
        ]).mapped('amount'))
        offsets_cleared = sum(self.env['account.move'].sudo().search([
            ('sfya_salary_offset_employee_id', '=', employee.id),
            ('sfya_is_salary_offset', '=', True),
            ('state', '=', 'posted'),
            ('company_id', '=', self.env.company.id),
        ]).mapped('sfya_salary_offset_amount'))
        return advances_given - offsets_cleared

    def _sfya_resolve_partner_type(self, partner, payment_type):
        """Detect whether a POS cash movement should post against the
        partner's payable (vendor) or receivable (customer) account.

        Partners are often both customer and vendor, so this uses live
        balances rather than a static rank. On a tie (owed on both sides
        at once) supplier wins - Pay Out originally exists to settle
        vendor bills. Falls back to rank when there's no balance on
        either side (e.g. first-ever payment to a new partner).
        """
        payable = partner.debit or 0.0      # we owe them
        receivable = partner.credit or 0.0  # they owe us
        tol = 0.005  # ignore floating-point noise around a zero balance

        if payment_type == 'outbound':
            if payable > tol:
                return 'supplier'
            if receivable < -tol:
                return 'customer'
        else:
            if receivable > tol:
                return 'customer'
            if payable < -tol:
                return 'supplier'

        if partner.supplier_rank:
            return 'supplier'
        if partner.customer_rank:
            return 'customer'
        return None

    @api.model
    def get_recent_collections(self, date_from, date_to):
        """Return inbound payments in date range for POS overview.

        Not filtered by partner_type: a dual-role partner's inbound
        payment can resolve to 'supplier' (e.g. a vendor returning cash
        to us), and that's still cash collected worth showing here.
        """
        try:
            d_from = fields.Date.from_string(date_from)
            d_to = fields.Date.from_string(date_to)
        except (ValueError, TypeError):
            raise UserError(_("Invalid date format."))
        payments = self.sudo().search([
            ('payment_type', '=', 'inbound'),
            ('state', 'in', ['posted', 'paid', 'in_process']),
            ('date', '>=', d_from),
            ('date', '<=', d_to),
            ('company_id', '=', self.env.company.id),
        ], order='date desc, id desc', limit=500)
        return [{
            'id': p.id,
            'date': p.date.strftime('%d-%m-%Y'),
            'partner_name': p.partner_id.name or '',
            'amount': p.amount,
            'source': 'POS' if p.pos_session_id else 'Invoice/Manual',
        } for p in payments]

    def _sfya_pos_create_payment(self, session_id, partner_id, amount, journal_id, memo, payment_type, date=None):
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        partner = self.env['res.partner'].sudo().browse(partner_id).exists()
        if not partner:
            raise UserError(_('Partner not found.'))
        partner_type = self._sfya_resolve_partner_type(partner, payment_type)
        if not partner_type:
            raise UserError(
                _('This partner has no outstanding vendor bill or customer credit to pay out.')
                if payment_type == 'outbound'
                else _('This partner has no customer or vendor relationship to collect from.')
            )
        if amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        if not journal_id:
            raise UserError(_('Account is required.'))
        journal = self.env['account.journal'].sudo().browse(journal_id).exists()
        if not journal:
            raise UserError(_('Account not found.'))
        if journal.type not in ('cash', 'bank'):
            raise UserError(_('Selected account is not a cash or bank journal.'))
        if journal.company_id.id != session.company_id.id:
            raise UserError(_("Account does not belong to this POS's company."))
        resolved_date = fields.Date.today()
        if journal.type == 'bank' and date:
            try:
                resolved_date = fields.Date.from_string(date)
            except (ValueError, TypeError):
                raise UserError(_("Invalid date format."))
            if resolved_date > fields.Date.today():
                raise UserError(_("Date cannot be in the future."))
        # cash journal: ignore passed date; resolved_date stays today
        payment = self.sudo().create({
            'partner_id': partner.id,
            'partner_type': partner_type,
            'payment_type': payment_type,
            'amount': amount,
            'journal_id': journal.id,
            'date': resolved_date,
            'memo': memo or False,
            'pos_session_id': session.id,
        })
        payment.action_post()
        return {
            'id': payment.id,
            'name': payment.name,
            'partner_id': partner.id,
            'partner_name': partner.name,
            'amount': payment.amount,
            'memo': payment.memo or '',
            'direction': payment_type,
            'journal_id': journal.id,
            'journal_name': journal.name,
            'journal_type': journal.type,
        }
