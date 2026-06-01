from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def action_pos_session_open(self):
        res = super().action_pos_session_open()
        for session in self.filtered(lambda s: s.state == 'opened'):
            session._sfya_sweep_pending_expenses()
        return res

    def _sfya_sweep_pending_expenses(self):
        """Consume any hr.expense rows queued while no session was open.

        Each pending expense flagged affects_pos_cash creates a Cash Out
        line on this newly opened session, then the queue flag is cleared.
        """
        self.ensure_one()
        pending = self.env['hr.expense'].sudo().search([
            ('pos_cash_pending', '=', True),
            ('pos_cash_session_id', '=', False),
            ('affects_pos_cash', '=', True),
        ])
        for exp in pending:
            self.try_cash_in_out(
                'out',
                exp.total_amount_currency,
                'Expense (queued): %s' % (exp.name or ''),
                {'translatedType': 'Cash Out'},
            )
            exp.write({
                'pos_cash_session_id': self.id,
                'pos_cash_pending': False,
            })
