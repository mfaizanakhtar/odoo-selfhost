from odoo import api, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def get_sfya_cash_movements(self):
        """Return SFYA POS-recorded cash + bank payments for this session.

        Returns:
            {
                'cash': {collects, collects_total, payouts, payouts_total},
                'banks': [
                    {journal_id, journal_name, collects, collects_total,
                     payouts, payouts_total},
                    ...
                ],
            }

        Banks list contains only journals that had at least one movement
        this session, sorted by journal name.
        """
        self.ensure_one()
        payments = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('state', 'in', ['paid', 'in_process']),
            ('journal_id.type', 'in', ['cash', 'bank']),
        ], order='create_date asc')

        def _row(p):
            return {
                'id': p.id,
                'name': p.name,
                'partner_id': p.partner_id.id,
                'partner_name': p.partner_id.name,
                'amount': p.amount,
                'memo': p.memo or '',
            }

        cash_collects, cash_payouts = [], []
        bank_buckets = {}
        for p in payments:
            row = _row(p)
            j = p.journal_id
            if j.type == 'cash':
                (cash_collects if p.payment_type == 'inbound' else cash_payouts).append(row)
            else:  # bank
                bucket = bank_buckets.setdefault(j.id, {
                    'journal_id': j.id,
                    'journal_name': j.name,
                    'collects': [],
                    'payouts': [],
                })
                (bucket['collects'] if p.payment_type == 'inbound' else bucket['payouts']).append(row)

        banks = []
        for b in sorted(bank_buckets.values(), key=lambda b: b['journal_name']):
            b['collects_total'] = sum(r['amount'] for r in b['collects'])
            b['payouts_total'] = sum(r['amount'] for r in b['payouts'])
            banks.append(b)

        return {
            'cash': {
                'collects': cash_collects,
                'collects_total': sum(r['amount'] for r in cash_collects),
                'payouts': cash_payouts,
                'payouts_total': sum(r['amount'] for r in cash_payouts),
            },
            'banks': banks,
        }

    @api.model
    def get_sfya_allowed_journals(self, session_id):
        """Return cash + bank journals selectable from the Cash Movement modal.

        Filters by session company. Cash journals are listed first, then
        banks; both groups sorted by name. The frontend modal picks the
        default selection.
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
