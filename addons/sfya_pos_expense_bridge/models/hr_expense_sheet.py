from odoo import models


class HrExpenseSheet(models.Model):
    _inherit = 'hr.expense.sheet'

    def _compute_state(self):
        # `state` is a stored compute that flips to 'done' when payment is
        # registered (via account_move_ids.payment_state). Direct write()
        # hooks don't fire on recomputes, so we wrap the compute instead.
        prev = {s.id: s.state for s in self}
        super()._compute_state()
        for sheet in self:
            if prev.get(sheet.id) != 'done' and sheet.state == 'done':
                sheet._sfya_push_pos_cash_out()

    def _sfya_push_pos_cash_out(self):
        """Mirror flagged expense lines as POS Cash Out on open session.

        For each line where affects_pos_cash is True and that hasn't
        already been pushed, either create a cash-out on a currently
        open session or queue it (pos_cash_pending) for the next session
        opening.
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
