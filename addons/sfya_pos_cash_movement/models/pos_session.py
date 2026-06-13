from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def get_sfya_cash_movements(self):
        """Return cash collected / paid out via POS Cash Movement during this session.

        Returns:
            {
                'collects':       [{id, name, partner_id, partner_name, amount, memo}, ...],
                'collects_total': float,
                'payouts':        [{...}, ...],
                'payouts_total':  float,
            }
        """
        self.ensure_one()
        payments = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('state', 'in', ['paid', 'in_process']),
        ], order='create_date asc')
        collects, payouts = [], []
        for p in payments:
            row = {
                'id': p.id,
                'name': p.name,
                'partner_id': p.partner_id.id,
                'partner_name': p.partner_id.name,
                'amount': p.amount,
                'memo': p.memo or '',
            }
            (collects if p.payment_type == 'inbound' else payouts).append(row)
        return {
            'collects': collects,
            'collects_total': sum(r['amount'] for r in collects),
            'payouts': payouts,
            'payouts_total': sum(r['amount'] for r in payouts),
        }
