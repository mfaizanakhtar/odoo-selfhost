from odoo import _, api, fields, models
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

    @api.model
    def sfya_pos_collect(self, session_id, partner_id, amount, memo=''):
        """RPC: cashier collects cash from a customer or vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, memo, payment_type='inbound',
        )

    @api.model
    def sfya_pos_payout(self, session_id, partner_id, amount, memo=''):
        """RPC: cashier pays cash out to a vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, memo, payment_type='outbound',
        )

    def _sfya_pos_create_payment(self, session_id, partner_id, amount, memo, payment_type):
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        partner = self.env['res.partner'].sudo().browse(partner_id).exists()
        if not partner:
            raise UserError(_('Partner not found.'))
        if payment_type == 'outbound' and not partner.supplier_rank:
            raise UserError(_('Pay Out is only allowed for vendor partners.'))
        if amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))
        partner_type = 'supplier' if payment_type == 'outbound' else 'customer'
        cash_pm = session.config_id.payment_method_ids.filtered(
            lambda m: m.type == 'cash'
        )[:1]
        if not cash_pm or not cash_pm.journal_id:
            raise UserError(_('No cash journal configured on this POS.'))
        payment = self.sudo().create({
            'partner_id': partner.id,
            'partner_type': partner_type,
            'payment_type': payment_type,
            'amount': amount,
            'journal_id': cash_pm.journal_id.id,
            'date': fields.Date.today(),
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
        }
