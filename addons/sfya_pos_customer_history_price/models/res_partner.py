from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def get_pos_customer_history_prices(self, partner_id, product_ids, pricelist_id):
        """Return original sale unit prices for this POS customer and company.

        Accounting history is deliberately read with elevated access because a
        cashier cannot read standalone invoices. Validate every requested record
        under the caller's access rules first, and return only requested prices.
        """
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only Point of Sale users can look up customer prices.'))

        def valid_id(value):
            return type(value) is int and value > 0

        if (
            not valid_id(partner_id)
            or not valid_id(pricelist_id)
            or not isinstance(product_ids, list)
            or any(not valid_id(product_id) for product_id in product_ids)
        ):
            raise ValidationError(_('Expected a customer, product IDs, and pricelist ID.'))

        company = self.env.company
        company_domain = [('company_id', 'in', [False, company.id])]
        partner = self.env['res.partner'].search(
            [('id', '=', partner_id)] + company_domain, limit=1,
        )
        pricelist = self.env['product.pricelist'].search(
            [('id', '=', pricelist_id)] + company_domain, limit=1,
        )
        products = self.env['product.product'].search(
            [('id', 'in', list(set(product_ids)))] + company_domain,
        )
        if not partner or not pricelist or set(products.ids) != set(product_ids):
            raise AccessError(_('The requested customer, products, or pricelist are unavailable.'))
        if not products:
            return {}

        # Never use the cashier's timezone to decide the company's business day.
        company_clock = self.with_context(tz=company.partner_id.tz or 'UTC')
        winners = {}

        def consider(line, source, business_date):
            key = (
                business_date, source.create_date or datetime.min,
                source._name, source.id, line.id,
            )
            product_id = line.product_id.id
            if product_id not in winners or key > winners[product_id][0]:
                winners[product_id] = (key, line, business_date)

        pos_lines = self.env['pos.order.line'].search([
            ('company_id', '=', company.id),
            ('order_id.partner_id', '=', partner.id),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
            ('product_id', 'in', products.ids),
            ('qty', '>', 0),
            ('refunded_orderline_id', '=', False),
        ])
        for line in pos_lines:
            order = line.order_id
            business_date = fields.Datetime.context_timestamp(
                company_clock, order.date_order,
            ).date()
            consider(line, order, business_date)

        invoice_lines = self.env['account.move.line'].sudo().search([
            ('company_id', '=', company.id),
            ('move_id.partner_id', '=', partner.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.move_type', '=', 'out_invoice'),
            ('move_id.pos_order_ids', '=', False),
            ('move_id.invoice_date', '!=', False),
            ('display_type', '=', 'product'),
            ('product_id', 'in', products.ids),
            ('quantity', '>', 0),
        ])
        for line in invoice_lines:
            consider(line, line.move_id, line.move_id.invoice_date)

        products_by_id = {product.id: product for product in products}
        prices = {}
        for product_id, (_key, line, business_date) in winners.items():
            price = line.product_uom_id._compute_price(
                line.price_unit, products_by_id[product_id].uom_id,
            )
            prices[str(product_id)] = line.currency_id._convert(
                price, pricelist.currency_id, company, business_date, round=False,
            )
        return prices
