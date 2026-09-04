from odoo import models


class HrExpenseSheet(models.Model):
    _inherit = 'hr.expense.sheet'

    def _compute_state(self):
        # `state` is a stored compute that flips to 'done' when the entries
        # are posted (company_account) / payment registered. Direct write()
        # hooks don't fire on recomputes, so we wrap the compute instead.
        prev = {s.id: s.state for s in self}
        super()._compute_state()
        for sheet in self:
            if prev.get(sheet.id) != 'done' and sheet.state == 'done':
                sheet._sfya_push_pos_cash_out()
                sheet._sfya_pay_bank_expenses()

    def _sfya_push_pos_cash_out(self):
        """Mirror POS-cash-routed expense lines as POS Cash Out on open session.

        Only affects lines where affects_pos_cash is True (i.e. Payment
        Source is the POS cash journal). Either creates a cash-out on a
        currently open session or queues it (pos_cash_pending) for the next
        session opening.
        """
        self.ensure_one()
        flagged = self.expense_line_ids.filtered(
            lambda e: e.affects_pos_cash and not e.pos_cash_session_id
        )
        if not flagged:
            return

        session = self.env['pos.session'].sudo().search(
            [('state', '=', 'opened')],
            limit=1,
            order='start_at desc',
        )

        if not session:
            flagged.write({'pos_cash_pending': True})
            return

        for exp in flagged:
            session.try_cash_in_out(
                'out',
                exp.total_amount_currency,
                'Expense: %s' % (exp.name or ''),
                {'translatedType': 'Cash Out'},
            )
            exp.write({
                'pos_cash_session_id': session.id,
                'pos_cash_pending': False,
            })

    def _sfya_pay_bank_expenses(self):
        """Post a reconciled bank entry for each bank-routed company expense."""
        self.ensure_one()
        bank_lines = self.expense_line_ids.filtered(
            lambda e: e.payment_mode == 'company_account'
            and not e.affects_pos_cash
            and e.sfya_payment_source_journal_id
            and not e.sfya_bank_move_id
        )
        for exp in bank_lines:
            exp._sfya_create_bank_payment_move()
