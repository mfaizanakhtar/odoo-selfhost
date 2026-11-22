from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SfyaPosCorrectionWizard(models.TransientModel):
    _name = 'sfya.pos.correction.wizard'
    _description = 'POS Order Customer Correction'

    order_id = fields.Many2one(
        'pos.order', required=True, readonly=True,
    )
    invoice_id = fields.Many2one(
        'account.move', related='order_id.account_move', readonly=True,
    )
    old_partner_id = fields.Many2one(
        'res.partner', related='order_id.partner_id', readonly=True,
    )
    old_invoice_partner_id = fields.Many2one(
        'res.partner',
        related='order_id.account_move.partner_id',
        readonly=True,
    )
    new_partner_id = fields.Many2one(
        'res.partner',
        required=True,
        domain=[('active', '=', True)],
    )
    payment_summary = fields.Char(compute='_compute_payment_summary')
    reason = fields.Text(required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order_id = res.get('order_id') or self.env.context.get('default_order_id')
        if order_id:
            order = self.env['pos.order'].browse(order_id)
            res['order_id'] = order.id
            invoice = order.account_move
            default_partner = (
                invoice.partner_id
                if invoice and invoice.state == 'posted'
                else order.partner_id
            )
            res['new_partner_id'] = default_partner.id
        return res

    @api.depends(
        'order_id.payment_ids.amount',
        'order_id.payment_ids.payment_method_id',
    )
    def _compute_payment_summary(self):
        for wizard in self:
            parts = [
                '%s: %.2f' % (
                    payment.payment_method_id.name or _('Unknown'),
                    payment.amount,
                )
                for payment in wizard.order_id.payment_ids
            ]
            wizard.payment_summary = ', '.join(parts) or _('No POS payment')

    def _validate(self):
        self.ensure_one()
        if not self.env.su and not self.env.user.has_group(
            'sfya_pos_order_correction.group_sfya_pos_order_correction'
        ):
            raise UserError(_('You are not allowed to correct POS orders.'))

        order = self.order_id
        invoice = self.invoice_id
        if order.state != 'invoiced':
            raise UserError(_('Only invoiced POS orders can be corrected.'))
        if (
            not invoice
            or invoice.state != 'posted'
            or invoice.move_type != 'out_invoice'
        ):
            raise UserError(_(
                'The linked document must be a posted customer invoice.'
            ))
        if (
            len(invoice.pos_order_ids) != 1
            or invoice.pos_order_ids.id != order.id
        ):
            raise UserError(_(
                'This correction only supports an invoice linked to exactly '
                'this POS order.'
            ))
        if invoice.company_id != order.company_id:
            raise UserError(_('The order and invoice companies must match.'))
        if order.currency_id != invoice.currency_id:
            raise UserError(_('The order and invoice currencies must match.'))
        if not order.currency_id.is_zero(
            invoice.amount_total - order.amount_total
        ):
            raise UserError(_(
                'The order and invoice totals must match before correcting '
                'the customer.'
            ))
        if order.lines.filtered(
            lambda line: line.refunded_qty or line.refunded_orderline_id
        ):
            raise UserError(_(
                'A partially refunded POS order cannot be corrected.'
            ))

        target = self.new_partner_id
        if not target.active:
            raise UserError(_('The new customer must be active.'))
        if target.company_id and target.company_id != order.company_id:
            raise UserError(_(
                'The new customer must belong to the same company.'
            ))
        if target.commercial_partner_id != target:
            raise UserError(_(
                'Select the commercial customer, not a child contact.'
            ))
        if not target.with_company(
            order.company_id
        ).property_account_receivable_id:
            raise UserError(_(
                'The new customer has no receivable account.'
            ))
        if not self.reason or not self.reason.strip():
            raise UserError(_('A correction reason is required.'))
        if target == order.partner_id and target == invoice.partner_id:
            raise UserError(_(
                'The order and invoice already use this customer.'
            ))

        if target != invoice.partner_id:
            self._validate_invoice_write(invoice, order)

    def _validate_invoice_write(self, invoice, order):
        if invoice.payment_state != 'not_paid':
            raise UserError(_(
                'Only a fully unpaid invoice can be reassigned in this phase.'
            ))
        if not invoice.currency_id.is_zero(
            invoice.amount_residual - invoice.amount_total
        ):
            raise UserError(_(
                'The invoice has a payment or residual balance.'
            ))
        if invoice.matched_payment_ids:
            raise UserError(_('The invoice has matched payments.'))
        if (
            invoice.reversed_entry_id
            or invoice.reversal_move_ids
            or invoice.reversed_pos_order_id
        ):
            raise UserError(_('The invoice is linked to a reversal.'))
        if invoice.inalterable_hash or invoice.need_cancel_request:
            raise UserError(_('The invoice is locked and cannot be reset.'))
        if any(
            line.reconciled
            or line.matched_debit_ids
            or line.matched_credit_ids
            or line.full_reconcile_id
            for line in invoice.line_ids
        ):
            raise UserError(_(
                'The invoice has reconciled journal items.'
            ))
        invoice._check_draftable()
        if order.payment_ids.filtered(
            lambda payment: payment.payment_method_id.type != 'pay_later'
        ):
            raise UserError(_(
                'Only Customer Account payments can be reassigned here. '
                'Cash or bank payments require a separate refund process.'
            ))

    def action_apply(self):
        self.ensure_one()
        self._validate()

        order = self.order_id
        invoice = self.invoice_id
        target = self.new_partner_id
        old_order_partner = order.partner_id
        old_invoice_partner = invoice.partner_id
        old_total = invoice.amount_total
        invoice_write_needed = target != invoice.partner_id

        if invoice_write_needed:
            invoice.button_draft()
            invoice.write({'partner_id': target.id})
            order.write({'partner_id': target.id})
            invoice.action_post()
        else:
            order.write({'partner_id': target.id})

        correction = self.env['sfya.pos.correction'].create({
            'order_id': order.id,
            'invoice_id': invoice.id,
            'correction_type': 'customer',
            'old_partner_id': old_order_partner.id or False,
            'new_partner_id': target.id,
            'old_invoice_partner_id': old_invoice_partner.id or False,
            'old_total': old_total,
            'new_total': invoice.amount_total,
            'reason': self.reason.strip(),
        })

        if invoice_write_needed:
            body = _(
                'Invoice and POS order customer corrected from %(old)s to '
                '%(new)s. Reason: %(reason)s. Correction: %(name)s',
                old=(
                    old_invoice_partner.display_name
                    or old_order_partner.display_name
                    or _('None')
                ),
                new=target.display_name,
                reason=self.reason.strip(),
                name=correction.name,
            )
            order.message_post(body=body)
            invoice.message_post(body=body)
        else:
            body = _(
                'POS order customer aligned from %(old)s to %(new)s. '
                'Reason: %(reason)s. Correction: %(name)s',
                old=old_order_partner.display_name or _('None'),
                new=target.display_name,
                reason=self.reason.strip(),
                name=correction.name,
            )
            order.message_post(body=body)
        return {'type': 'ir.actions.act_window_close'}
