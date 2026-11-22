from odoo import api, fields, models, _


class PosOrder(models.Model):
    _inherit = 'pos.order'

    sfya_invoice_customer_mismatch = fields.Boolean(
        compute='_compute_sfya_invoice_customer_mismatch',
    )
    sfya_correction_count = fields.Integer(
        compute='_compute_sfya_correction_count',
    )
    sfya_latest_correction_id = fields.Many2one(
        'sfya.pos.correction',
        compute='_compute_sfya_latest_correction',
    )
    sfya_corrected_total = fields.Monetary(
        compute='_compute_sfya_corrected_total',
        currency_field='currency_id',
    )

    @api.depends('partner_id', 'account_move.partner_id', 'account_move.state')
    def _compute_sfya_invoice_customer_mismatch(self):
        for order in self:
            invoice = order.account_move
            order.sfya_invoice_customer_mismatch = bool(
                invoice
                and invoice.state == 'posted'
                and invoice.partner_id
                and order.partner_id
                and invoice.partner_id != order.partner_id
            )

    def _compute_sfya_correction_count(self):
        for order in self:
            order.sfya_correction_count = self.env[
                'sfya.pos.correction'
            ].sudo().search_count([('order_id', '=', order.id)])

    def _compute_sfya_latest_correction(self):
        for order in self:
            order.sfya_latest_correction_id = self.env[
                'sfya.pos.correction'
            ].sudo().search(
                [('order_id', '=', order.id)],
                order='id desc',
                limit=1,
            )

    def _compute_sfya_corrected_total(self):
        # The correction records are append-only, so no stored dependency is
        # needed; the field is invalidated after each correction.
        for order in self:
            order.sfya_corrected_total = (
                order.sfya_latest_correction_id.new_total
            )

    def action_view_sfya_corrections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Corrections'),
            'res_model': 'sfya.pos.correction',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'create': False},
        }
