from odoo import api, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def get_sfya_cash_movements(self):
        """Return SFYA POS-recorded cash + bank payments for this session.

        Returns:
            {
                'cash': {collects, collects_total, payouts, payouts_total,
                         drawings, drawings_total,
                         transfers_in_total, transfers_out_total},
                'banks': [
                    {journal_id, journal_name, collects, collects_total,
                     payouts, payouts_total, drawings, drawings_total},
                    ...
                ],
            }

        Banks list contains only journals that had at least one movement
        this session, sorted by journal name. Internal-transfer payments
        (sfya_is_internal_transfer=True) are excluded from all of the
        above and totalled separately into cash.transfers_in_total /
        transfers_out_total, restricted to the cash journal only - that's
        the only leg that affects the physically-counted till.
        """
        self.ensure_one()
        payments = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('state', 'in', ['paid', 'in_process']),
            ('journal_id.type', 'in', ['cash', 'bank']),
            ('sfya_is_internal_transfer', '=', False),
        ], order='create_date asc')

        def _row(p):
            return {
                'id': p.id,
                'name': p.name,
                'partner_id': p.partner_id.id,
                'partner_name': p.partner_id.name or '',
                'amount': p.amount,
                'memo': p.memo or '',
            }

        drawing_account = self.company_id.sfya_owner_drawing_account_id

        cash_collects, cash_payouts, cash_drawings = [], [], []
        bank_buckets = {}
        for p in payments:
            row = _row(p)
            j = p.journal_id
            is_drawing = bool(drawing_account and p.destination_account_id == drawing_account)
            if j.type == 'cash':
                if p.payment_type == 'inbound':
                    cash_collects.append(row)
                elif is_drawing:
                    cash_drawings.append(row)
                else:
                    cash_payouts.append(row)
            else:  # bank
                bucket = bank_buckets.setdefault(j.id, {
                    'journal_id': j.id,
                    'journal_name': j.name,
                    'collects': [],
                    'payouts': [],
                    'drawings': [],
                })
                if p.payment_type == 'inbound':
                    bucket['collects'].append(row)
                elif is_drawing:
                    bucket['drawings'].append(row)
                else:
                    bucket['payouts'].append(row)

        banks = []
        for b in sorted(bank_buckets.values(), key=lambda b: b['journal_name']):
            b['collects_total'] = sum(r['amount'] for r in b['collects'])
            b['payouts_total'] = sum(r['amount'] for r in b['payouts'])
            b['drawings_total'] = sum(r['amount'] for r in b['drawings'])
            banks.append(b)

        transfers = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('state', 'in', ['paid', 'in_process']),
            ('sfya_is_internal_transfer', '=', True),
            ('journal_id.type', '=', 'cash'),
        ])
        transfers_in_total = sum(p.amount for p in transfers if p.payment_type == 'inbound')
        transfers_out_total = sum(p.amount for p in transfers if p.payment_type == 'outbound')

        return {
            'cash': {
                'collects': cash_collects,
                'collects_total': sum(r['amount'] for r in cash_collects),
                'payouts': cash_payouts,
                'payouts_total': sum(r['amount'] for r in cash_payouts),
                'drawings': cash_drawings,
                'drawings_total': sum(r['amount'] for r in cash_drawings),
                'transfers_in_total': transfers_in_total,
                'transfers_out_total': transfers_out_total,
            },
            'banks': banks,
        }

    def get_sfya_partner_transfers(self):
        """Return this session's partner-transfer entries, informational only.

        These never touch cash/bank (no journal leg at all), so they carry
        no till impact and aren't part of get_sfya_cash_movements.
        """
        self.ensure_one()
        moves = self.env['account.move'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('sfya_is_partner_transfer', '=', True),
            ('state', '=', 'posted'),
        ], order='create_date asc')
        return [{
            'id': m.id,
            'name': m.name,
            'from_partner_name': m.sfya_transfer_from_partner_id.name or '',
            'to_partner_name': m.sfya_transfer_to_partner_id.name or '',
            'amount': m.sfya_transfer_amount,
            'memo': m.ref or '',
        } for m in moves]

    def get_sfya_internal_transfers(self):
        """Return this session's journal-to-journal transfers, one row per
        pair (via the outbound leg), informational for the closing dialog.

        Only the cash-journal leg (if any) affects the till count, and
        that's already folded into get_sfya_cash_movements's cash dict -
        this listing is purely for display.
        """
        self.ensure_one()
        payments = self.env['account.payment'].sudo().search([
            ('pos_session_id', '=', self.id),
            ('sfya_is_internal_transfer', '=', True),
            ('payment_type', '=', 'outbound'),
            ('state', 'in', ['paid', 'in_process']),
        ], order='create_date asc')
        return [{
            'id': p.id,
            'name': p.name,
            'from_journal_name': p.journal_id.name,
            'to_journal_name': p.sfya_transfer_pair_id.journal_id.name if p.sfya_transfer_pair_id else '',
            'amount': p.amount,
            'memo': p.memo or '',
        } for p in payments]

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
        cash = movements.get('cash') or {}
        adjustment = (
            (cash.get('collects_total') or 0.0) - (cash.get('payouts_total') or 0.0) - (cash.get('drawings_total') or 0.0)
            + (cash.get('transfers_in_total') or 0.0) - (cash.get('transfers_out_total') or 0.0)
        )
        if data.get('default_cash_details') and adjustment:
            data['default_cash_details']['amount'] = (
                data['default_cash_details'].get('amount', 0.0) + adjustment
            )
        return data
