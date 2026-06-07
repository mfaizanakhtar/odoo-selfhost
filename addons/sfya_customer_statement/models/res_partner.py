from collections import OrderedDict

from odoo import api, models, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def get_statement_data(self, date_from, date_to, include_drafts=False):
        """Return chronological statement rows + meta for QWeb/screen rendering.

        Display order: latest first. Running balance computed in chronological
        (asc) order then rows are reversed so the newest sits at top.
        """
        self.ensure_one()
        rows = []
        opening = self._compute_opening_balance(date_from)

        # POS orders
        pos_domain = [
            ('partner_id', '=', self.id),
            ('date_order', '>=', date_from),
            ('date_order', '<=', date_to),
        ]
        if not include_drafts:
            pos_domain.append(('state', 'in', ['paid', 'done', 'invoiced']))
        for order in self.env['pos.order'].search(pos_domain):
            cash_received = sum(
                p.amount for p in order.payment_ids
                if p.payment_method_id.type != 'pay_later'
            )
            lines = [{
                'name': l.product_id.display_name or l.full_product_name,
                'qty': l.qty,
                'price_unit': l.price_unit,
                'subtotal': l.price_subtotal_incl,
            } for l in order.lines]
            rows.append({
                'date': order.date_order.date() if hasattr(order.date_order, 'date') else order.date_order,
                'create_date': order.create_date,
                'kind': 'pos',
                'kind_label': _('POS Sale'),
                'doc_name': order.pos_reference or order.name,
                'doc_id': order.id,
                'doc_model': 'pos.order',
                'lines': lines,
                'note': '',
                'debit': order.amount_total,
                'credit': cash_received,
                'balance': 0.0,
            })

        # Customer invoices/refunds (skip those already represented by pos.order)
        inv_domain = [
            ('partner_id', '=', self.id),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('invoice_date', '>=', date_from),
            ('invoice_date', '<=', date_to),
            ('state', '=', 'posted'),
        ]
        for inv in self.env['account.move'].search(inv_domain):
            if inv.pos_order_ids:
                continue
            sign = 1 if inv.move_type == 'out_invoice' else -1
            lines = [{
                'name': (l.product_id.display_name or l.name or ''),
                'qty': l.quantity,
                'price_unit': l.price_unit,
                'subtotal': l.price_total,
            } for l in inv.invoice_line_ids if l.display_type not in ('line_section', 'line_note')]
            rows.append({
                'date': inv.invoice_date,
                'create_date': inv.create_date,
                'kind': 'invoice' if sign > 0 else 'refund',
                'kind_label': _('Invoice') if sign > 0 else _('Refund'),
                'doc_name': inv.name,
                'doc_id': inv.id,
                'doc_model': 'account.move',
                'lines': lines,
                'note': '',
                'debit': sign * inv.amount_total if sign > 0 else 0.0,
                'credit': -sign * inv.amount_total if sign < 0 else 0.0,
                'balance': 0.0,
            })

        # Customer payments
        pay_domain = [
            ('partner_id', '=', self.id),
            ('partner_type', '=', 'customer'),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('state', '=', 'posted'),
        ]
        for pay in self.env['account.payment'].search(pay_domain):
            rows.append({
                'date': pay.date,
                'create_date': pay.create_date,
                'kind': 'payment',
                'kind_label': _('Payment'),
                'doc_name': pay.name,
                'doc_id': pay.id,
                'doc_model': 'account.payment',
                'lines': [],
                'note': _('Payment - %s', pay.journal_id.name) + (
                    ' (%s)' % pay.ref if pay.ref else ''
                ),
                'debit': 0.0,
                'credit': pay.amount,
                'balance': 0.0,
            })

        # Manual journal entries on partner's AR account (excludes auto-generated
        # invoice/payment moves which are move_type != 'entry')
        ar = self.property_account_receivable_id
        if ar:
            je_domain = [
                ('partner_id', '=', self.id),
                ('account_id', '=', ar.id),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
                ('parent_state', '=', 'posted'),
                ('move_id.move_type', '=', 'entry'),
                ('move_id.ref', 'not like', 'OPENING-BAL-%'),
            ]
            for ml in self.env['account.move.line'].search(je_domain):
                rows.append({
                    'date': ml.date,
                    'create_date': ml.create_date,
                    'kind': 'misc',
                    'kind_label': _('Journal Entry'),
                    'doc_name': ml.move_id.name,
                    'doc_id': ml.move_id.id,
                    'doc_model': 'account.move',
                    'lines': [],
                    'note': ml.name or ml.move_id.ref or _('Journal Entry'),
                    'debit': ml.debit,
                    'credit': ml.credit,
                    'balance': 0.0,
                })

        # Chronological for balance math
        rows.sort(key=lambda r: (r['date'], r['create_date']))
        running = opening
        for r in rows:
            running += r['debit'] - r['credit']
            r['balance'] = running
            r['date_str'] = r['date'].strftime('%d-%m-%Y') if r['date'] else ''
        closing = running

        # Reverse for display (latest first)
        rows.reverse()

        opening_row = {
            'date_str': date_from.strftime('%d-%m-%Y'),
            'doc_name': _('OPEN'),
            'note': _('Opening Balance'),
            'debit': opening if opening >= 0 else 0.0,
            'credit': -opening if opening < 0 else 0.0,
            'balance': opening,
        }

        return {
            'partner': {
                'id': self.id,
                'name': self.name,
                'street': self.street or '',
                'phone': self.phone or self.mobile or '',
                'email': self.email or '',
                'vat': self.vat or '',
            },
            'company': {
                'name': self.env.company.name,
                'street': self.env.company.street or '',
                'phone': self.env.company.phone or '',
            },
            'date_from': date_from,
            'date_to': date_to,
            'date_from_str': date_from.strftime('%d-%m-%Y'),
            'date_to_str': date_to.strftime('%d-%m-%Y'),
            'opening_balance': opening,
            'opening_row': opening_row,
            'rows': rows,
            'closing_balance': closing,
            'aging': self._compute_aging_buckets(date_to),
            'currency_symbol': self.env.company.currency_id.symbol or '',
        }

    def _compute_opening_balance(self, date_from):
        """Pre-period AR balance + all OPENING-BAL-* JEs (any date).

        Opening-balance JEs created via the wizard represent the customer's
        migrated starting balance regardless of their posting date, so they
        belong in the opening figure even if dated inside the statement
        period. They are excluded from the in-period JE listing.
        """
        self.ensure_one()
        ar = self.property_account_receivable_id
        if not ar:
            return 0.0
        self.env.cr.execute(
            """
            SELECT COALESCE(SUM(aml.debit), 0) - COALESCE(SUM(aml.credit), 0)
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            WHERE aml.partner_id = %s
              AND aml.account_id = %s
              AND am.state = 'posted'
              AND (
                aml.date < %s
                OR am.ref LIKE 'OPENING-BAL-%%'
              )
            """,
            (self.id, ar.id, date_from),
        )
        return float(self.env.cr.fetchone()[0] or 0.0)

    def _compute_aging_buckets(self, date_ref):
        """Aging on OPEN AR balance (residual) at date_ref."""
        self.ensure_one()
        ar = self.property_account_receivable_id
        if not ar:
            return []
        buckets = OrderedDict([
            ('0-30', 0.0),
            ('31-60', 0.0),
            ('61-90', 0.0),
            ('90+', 0.0),
        ])
        lines = self.env['account.move.line'].search([
            ('partner_id', '=', self.id),
            ('account_id', '=', ar.id),
            ('date', '<=', date_ref),
            ('parent_state', '=', 'posted'),
            ('reconciled', '=', False),
        ])
        for ml in lines:
            residual = (ml.amount_residual or 0.0)
            if not residual:
                continue
            days = (date_ref - ml.date).days
            if days <= 30:
                buckets['0-30'] += residual
            elif days <= 60:
                buckets['31-60'] += residual
            elif days <= 90:
                buckets['61-90'] += residual
            else:
                buckets['90+'] += residual
        return [{'label': k, 'amount': v} for k, v in buckets.items()]
