from odoo import api, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def get_pos_prev_balance(self, partner_id, exclude_order_pay_later=0.0):
        """Return partner's pre-sale net balance for POS receipt.

        Net position = AR (partner.credit) minus AP (partner.debit).
        Subtract exclude_order_pay_later (this order's pay_later amount)
        to back out the current sale, leaving the TRUE pre-sale balance.

        Positive => customer owes us. Negative => we owe them or advance.
        Sudo'd so cashiers without accounting groups still get the value.
        """
        partner = self.sudo().browse(partner_id).exists()
        if not partner:
            return 0.0
        net = (partner.credit or 0.0) - (partner.debit or 0.0)
        return net - (exclude_order_pay_later or 0.0)
