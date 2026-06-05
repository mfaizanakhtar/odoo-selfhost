from odoo import api, fields, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    prev_balance = fields.Monetary(
        compute='_compute_prev_balance',
        currency_field='currency_id',
        help="Customer balance BEFORE this order. "
             "partner.credit minus this order's own pay_later contribution.",
    )

    @api.depends('partner_id', 'partner_id.credit',
                 'payment_ids.amount', 'payment_ids.payment_method_id')
    def _compute_prev_balance(self):
        for order in self:
            if not order.partner_id:
                order.prev_balance = 0.0
                continue
            this_order_on_credit = sum(
                p.amount for p in order.payment_ids
                if p.payment_method_id.type == 'pay_later'
            )
            order.prev_balance = (order.partner_id.credit or 0.0) - this_order_on_credit

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if 'prev_balance' not in fields_list:
            fields_list.append('prev_balance')
        return fields_list
