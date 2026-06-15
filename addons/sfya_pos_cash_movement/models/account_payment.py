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
    def sfya_pos_collect(self, session_id, partner_id, amount, journal_id, memo='', date=None):
        """RPC: cashier collects cash/bank payment from a customer or vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, journal_id, memo, payment_type='inbound', date=date,
        )

    @api.model
    def sfya_pos_payout(self, session_id, partner_id, amount, journal_id, memo='', date=None):
        """RPC: cashier pays out cash/bank to a vendor."""
        return self._sfya_pos_create_payment(
            session_id, partner_id, amount, journal_id, memo, payment_type='outbound', date=date,
        )

    def _sfya_pos_create_payment(self, session_id, partner_id, amount, journal_id, memo, payment_type, date=None):
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
        if not journal_id:
            raise UserError(_('Account is required.'))
        journal = self.env['account.journal'].sudo().browse(journal_id).exists()
        if not journal:
            raise UserError(_('Account not found.'))
        if journal.type not in ('cash', 'bank'):
            raise UserError(_('Selected account is not a cash or bank journal.'))
        if journal.company_id.id != session.company_id.id:
            raise UserError(_("Account does not belong to this POS's company."))
        resolved_date = fields.Date.today()
        if journal.type == 'bank' and date:
            try:
                resolved_date = fields.Date.from_string(date)
            except (ValueError, TypeError):
                raise UserError(_("Invalid date format."))
            if resolved_date > fields.Date.today():
                raise UserError(_("Date cannot be in the future."))
        # cash journal: ignore passed date; resolved_date stays today
        partner_type = 'supplier' if payment_type == 'outbound' else 'customer'
        payment = self.sudo().create({
            'partner_id': partner.id,
            'partner_type': partner_type,
            'payment_type': payment_type,
            'amount': amount,
            'journal_id': journal.id,
            'date': resolved_date,
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
            'journal_id': journal.id,
            'journal_name': journal.name,
            'journal_type': journal.type,
        }
