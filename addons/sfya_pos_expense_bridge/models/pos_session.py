from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def action_pos_session_open(self):
        res = super().action_pos_session_open()
        for session in self.filtered(lambda s: s.state == 'opened'):
            session._sfya_sweep_pending_expenses()
        return res

    def _sfya_sweep_pending_expenses(self):
        """Consume any flagged hr.expense rows that haven't been mirrored.

        Picks up both expenses explicitly queued (pos_cash_pending=True)
        and any paid expenses with affects_pos_cash=True that never got
        attached to a session (e.g. paid before this addon was installed
        or while no session was open).
        """
        self.ensure_one()
        pending = self.env['hr.expense'].sudo().search([
            ('state', '=', 'done'),
            ('affects_pos_cash', '=', True),
            ('pos_cash_session_id', '=', False),
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
