from odoo import api, models


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

    @api.model
    def get_sfya_allowed_journals(self, session_id):
        """Return cash + bank journals selectable from the Cash Movement modal.

        Filters by session company. Cash journals are listed first (so the
        default selection — first row — is the POS till), then banks sorted
        by name.
        """
        session = self.sudo().browse(session_id).exists()
        if not session:
            return []
        journals = self.env['account.journal'].sudo().search([
            ('type', 'in', ['cash', 'bank']),
            ('company_id', '=', session.company_id.id),
        ])
        cash = journals.filtered(lambda j: j.type == 'cash').sorted('name')
        banks = journals.filtered(lambda j: j.type == 'bank').sorted('name')
        return [{'id': j.id, 'name': j.name, 'type': j.type} for j in (cash + banks)]

    def get_closing_control_data(self):
        data = super().get_closing_control_data()
        movements = self.get_sfya_cash_movements()
        adjustment = (movements['collects_total'] or 0.0) - (movements['payouts_total'] or 0.0)
        if data.get('default_cash_details') and adjustment:
            data['default_cash_details']['amount'] = (
                data['default_cash_details'].get('amount', 0.0) + adjustment
            )
        return data
