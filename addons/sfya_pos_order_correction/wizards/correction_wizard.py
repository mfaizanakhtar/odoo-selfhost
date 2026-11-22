from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class SfyaPosCorrectionWizard(models.TransientModel):
    _name = 'sfya.pos.correction.wizard'
    _description = 'POS Order Correction'

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
    line_ids = fields.One2many(
        'sfya.pos.correction.wizard.line',
        'wizard_id',
        string='Line Changes',
    )

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
            if invoice:
                res['line_ids'] = [
                    (0, 0, self._line_defaults(line))
                    for line in invoice.invoice_line_ids
                    if line.display_type == 'product'
                ]
        return res

    @api.model
    def _line_defaults(self, invoice_line):
        return {
            'invoice_line_id': invoice_line.id,
            'new_qty': invoice_line.quantity,
            'new_price_unit': invoice_line.price_unit,
            'new_discount': invoice_line.discount,
        }

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

    def _qty_changed(self, line):
        return float_compare(
            line.new_qty,
            line.old_qty,
            precision_rounding=line.invoice_line_id.product_uom_id.rounding,
        ) != 0

    def _price_changed(self, line):
        return (
            float_compare(
                line.new_price_unit,
                line.old_price_unit,
                precision_rounding=line.invoice_line_id.currency_id.rounding,
            ) != 0
            or float_compare(
                line.new_discount,
                line.old_discount,
                precision_digits=2,
            ) != 0
        )

    def _changed_lines(self):
        self.ensure_one()
        invoice = self.invoice_id
        changed = self.env['sfya.pos.correction.wizard.line']
        for line in self.line_ids:
            if line.invoice_line_id.move_id != invoice:
                raise UserError(_(
                    'A line does not belong to the linked invoice.'
                ))
            if line.new_qty <= 0:
                raise UserError(_(
                    'Quantity must be greater than zero. Use the product '
                    'correction process to remove a line.'
                ))
            if line.new_price_unit < 0:
                raise UserError(_('The corrected price cannot be negative.'))
            if line.new_discount < 0 or line.new_discount > 100:
                raise UserError(_(
                    'The corrected discount must be between 0 and 100.'
                ))
            if self._qty_changed(line) or self._price_changed(line):
                changed |= line
        return changed

    def _qty_plans(self, invoice, order, changed_lines):
        plans = []
        seen_products = self.env['product.product']
        for line in changed_lines:
            if not self._qty_changed(line):
                continue
            invoice_line = line.invoice_line_id
            product = invoice_line.product_id
            if not product:
                raise UserError(_(
                    'A corrected invoice line has no product.'
                ))
            if product in seen_products:
                raise UserError(_(
                    'The same product appears more than once in this '
                    'correction. Correct one product line at a time.'
                ))
            seen_products |= product

            order_lines = order.lines.filtered(
                lambda order_line: order_line.product_id == product
            )
            if len(order_lines) != 1:
                raise UserError(_(
                    'The POS order must contain exactly one line for %s.',
                    product.display_name,
                ))
            order_line = order_lines
            if order_line.product_uom_id != invoice_line.product_uom_id:
                raise UserError(_(
                    'The order and invoice units differ for %s.',
                    product.display_name,
                ))

            diff = line.new_qty - invoice_line.quantity
            if float_compare(
                diff,
                0.0,
                precision_rounding=invoice_line.product_uom_id.rounding,
            ) == 0:
                continue
            plans.append({
                'line': line,
                'invoice_line': invoice_line,
                'order_line': order_line,
                'product': product,
                'diff': diff,
                'move': False,
            })
            if not product.is_storable:
                continue

            if product.tracking != 'none':
                raise UserError(_(
                    'Quantity correction is not available for lot or serial '
                    'tracked products yet: %s',
                    product.display_name,
                ))

            done_moves = order.picking_ids.filtered(
                lambda picking: picking.state == 'done'
            ).move_ids.filtered(
                lambda move: (
                    move.product_id == product and move.state == 'done'
                )
            )
            if len(done_moves) != 1:
                raise UserError(_(
                    'Quantity correction needs exactly one completed stock '
                    'move for %s. Found %s.',
                    product.display_name,
                    len(done_moves),
                ))
            move = done_moves
            if diff > 0:
                available = self.env['stock.quant']._get_available_quantity(
                    product, move.location_id,
                )
                if float_compare(
                    available,
                    diff,
                    precision_rounding=product.uom_id.rounding,
                ) < 0:
                    raise UserError(_(
                        'Not enough stock for %(product)s. Need %(need)s, '
                        'available %(have)s.',
                        product=product.display_name,
                        need=diff,
                        have=available,
                    ))
            plans[-1]['move'] = move
        return plans

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
        has_prior_correction = self.env[
            'sfya.pos.correction'
        ].sudo().search_count([('order_id', '=', order.id)])
        if not has_prior_correction and not order.currency_id.is_zero(
            invoice.amount_total - order.amount_total
        ):
            raise UserError(_(
                'The order and invoice totals do not match.'
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

        changed_lines = self._changed_lines()
        price_changed = any(
            self._price_changed(line) for line in changed_lines
        )
        qty_changed = any(self._qty_changed(line) for line in changed_lines)
        if (
            target == order.partner_id
            and target == invoice.partner_id
            and not changed_lines
        ):
            raise UserError(_('Nothing has changed on this order.'))
        if (
            target != invoice.partner_id
            or price_changed
            or qty_changed
        ):
            self._validate_invoice_write(invoice, order)
        if qty_changed:
            self._qty_plans(invoice, order, changed_lines)

    def _validate_invoice_write(self, invoice, order):
        if invoice.payment_state != 'not_paid':
            raise UserError(_(
                'Only a fully unpaid invoice can be corrected in this phase.'
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
                'Only Customer Account payments can be corrected here. '
                'Cash or bank payments require a separate refund process.'
            ))

    def _create_stock_adjustment(self, order, plan):
        move = plan['move']
        product = plan['product']
        qty = abs(plan['diff'])
        if plan['diff'] < 0:
            source = move.location_dest_id
            destination = move.location_id
        else:
            source = move.location_id
            destination = move.location_dest_id

        picking = self.env['stock.picking'].create({
            'picking_type_id': move.picking_id.picking_type_id.id,
            'location_id': source.id,
            'location_dest_id': destination.id,
            'partner_id': order.partner_id.id,
            'origin': _('Correction of %s', order.name),
            'move_ids': [Command.create({
                'name': product.display_name,
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': plan['order_line'].product_uom_id.id,
                'location_id': source.id,
                'location_dest_id': destination.id,
            })],
        })
        picking.action_confirm()
        if plan['diff'] > 0:
            picking.action_assign()
            if float_compare(
                picking.move_ids.quantity,
                qty,
                precision_rounding=product.uom_id.rounding,
            ) < 0:
                raise UserError(_(
                    'Stock changed while correcting %s. Please retry.',
                    product.display_name,
                ))
        picking.move_ids.write({'quantity': qty, 'picked': True})
        picking.with_context(
            skip_backorder=True,
            skip_sanity_check=True,
        ).button_validate()
        if picking.state != 'done':
            raise UserError(_(
                'The stock adjustment for %s did not complete.',
                product.display_name,
            ))
        return picking

    def action_apply(self):
        self.ensure_one()
        self._validate()

        order = self.order_id
        invoice = self.invoice_id
        target = self.new_partner_id
        old_order_partner = order.partner_id
        old_invoice_partner = invoice.partner_id
        old_total = invoice.amount_total
        changed_lines = self._changed_lines()
        line_snapshots = [{
            'invoice_line_id': line.invoice_line_id.id,
            'product_id': line.product_id.id,
            'old_qty': line.old_qty,
            'new_qty': line.new_qty,
            'old_price_unit': line.old_price_unit,
            'new_price_unit': line.new_price_unit,
            'old_discount': line.old_discount,
            'new_discount': line.new_discount,
        } for line in changed_lines]
        price_changed = any(
            self._price_changed(line) for line in changed_lines
        )
        qty_changed = any(self._qty_changed(line) for line in changed_lines)
        qty_plans = (
            self._qty_plans(invoice, order, changed_lines)
            if qty_changed else []
        )
        customer_changed = (
            target != old_order_partner
            or target != old_invoice_partner
        )
        invoice_write_needed = (
            target != old_invoice_partner
            or price_changed
            or qty_changed
        )
        stock_pickings = self.env['stock.picking']

        if invoice_write_needed:
            invoice.button_draft()
            if target != old_invoice_partner:
                invoice.write({'partner_id': target.id})
            for snapshot in line_snapshots:
                self.env['account.move.line'].browse(
                    snapshot['invoice_line_id']
                ).write({
                    'quantity': snapshot['new_qty'],
                    'price_unit': snapshot['new_price_unit'],
                    'discount': snapshot['new_discount'],
                })
            for plan in qty_plans:
                if plan['move']:
                    stock_pickings |= self._create_stock_adjustment(
                        order, plan,
                    )
            if target != old_order_partner:
                order.write({'partner_id': target.id})
            invoice.action_post()
        else:
            order.write({'partner_id': target.id})

        if customer_changed and price_changed and qty_changed:
            correction_type = 'all'
        elif customer_changed and price_changed:
            correction_type = 'both'
        elif customer_changed and qty_changed:
            correction_type = 'customer_quantity'
        elif price_changed and qty_changed:
            correction_type = 'price_quantity'
        elif customer_changed:
            correction_type = 'customer'
        elif price_changed:
            correction_type = 'price'
        else:
            correction_type = 'quantity'

        correction = self.env['sfya.pos.correction'].create({
            'order_id': order.id,
            'invoice_id': invoice.id,
            'correction_type': correction_type,
            'old_partner_id': old_order_partner.id or False,
            'new_partner_id': target.id,
            'old_invoice_partner_id': old_invoice_partner.id or False,
            'old_total': old_total,
            'new_total': invoice.amount_total,
            'reason': self.reason.strip(),
            'line_ids': [(0, 0, {
                'product_id': snapshot['product_id'],
                'old_qty': snapshot['old_qty'],
                'new_qty': snapshot['new_qty'],
                'old_price_unit': snapshot['old_price_unit'],
                'new_price_unit': snapshot['new_price_unit'],
                'old_discount': snapshot['old_discount'],
                'new_discount': snapshot['new_discount'],
            }) for snapshot in line_snapshots],
            'stock_picking_ids': [(6, 0, stock_pickings.ids)],
        })

        changes = []
        if customer_changed:
            changes.append(_('customer'))
        if price_changed:
            changes.append(_('price/discount'))
        if qty_changed:
            changes.append(_('quantity'))
        body = _(
            'Corrected %(changes)s. Total: %(old_total).2f to '
            '%(new_total).2f. Reason: %(reason)s. Correction: %(name)s',
            changes=', '.join(changes),
            old_total=old_total,
            new_total=invoice.amount_total,
            reason=self.reason.strip(),
            name=correction.name,
        )
        order.message_post(body=body)
        if invoice_write_needed:
            invoice.message_post(body=body)
        order.invalidate_recordset([
            'sfya_correction_count',
            'sfya_latest_correction_id',
            'sfya_corrected_total',
        ])
        return {'type': 'ir.actions.act_window_close'}


class SfyaPosCorrectionWizardLine(models.TransientModel):
    _name = 'sfya.pos.correction.wizard.line'
    _description = 'POS Order Correction Line'

    wizard_id = fields.Many2one(
        'sfya.pos.correction.wizard',
        required=True,
        ondelete='cascade',
    )
    invoice_line_id = fields.Many2one(
        'account.move.line', required=True, readonly=True,
    )
    product_id = fields.Many2one(
        'product.product',
        related='invoice_line_id.product_id',
        readonly=True,
    )
    old_qty = fields.Float(
        related='invoice_line_id.quantity',
        readonly=True,
        digits='Product Unit of Measure',
    )
    old_price_unit = fields.Float(
        related='invoice_line_id.price_unit',
        readonly=True,
        digits='Product Price',
    )
    old_discount = fields.Float(
        related='invoice_line_id.discount',
        readonly=True,
        digits='Discount',
    )
    new_qty = fields.Float(
        required=True,
        digits='Product Unit of Measure',
    )
    new_price_unit = fields.Float(
        required=True,
        digits='Product Price',
    )
    new_discount = fields.Float(
        required=True,
        digits='Discount',
    )
