from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SfyaPosCorrection(models.Model):
    _name = 'sfya.pos.correction'
    _description = 'POS Order Customer Correction'
    _order = 'id desc'

    name = fields.Char(default='New', readonly=True, copy=False)
    order_id = fields.Many2one(
        'pos.order', required=True, ondelete='restrict', index=True,
    )
    invoice_id = fields.Many2one(
        'account.move', required=True, ondelete='restrict', index=True,
    )
    correction_type = fields.Selection(
        [
            ('customer', 'Customer'),
            ('price', 'Price / Discount'),
            ('both', 'Customer and Price / Discount'),
        ],
        required=True,
        default='customer',
    )
    old_partner_id = fields.Many2one(
        'res.partner', string='Old Order Customer', ondelete='restrict',
    )
    new_partner_id = fields.Many2one(
        'res.partner', required=True, string='New Customer',
        ondelete='restrict',
    )
    old_invoice_partner_id = fields.Many2one(
        'res.partner', string='Old Invoice Customer', ondelete='restrict',
    )
    currency_id = fields.Many2one(
        'res.currency', related='invoice_id.currency_id', store=True,
    )
    old_total = fields.Monetary(currency_field='currency_id')
    new_total = fields.Monetary(currency_field='currency_id')
    reason = fields.Text(required=True)
    user_id = fields.Many2one(
        'res.users',
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
        ondelete='restrict',
    )
    company_id = fields.Many2one(
        'res.company', related='order_id.company_id', store=True, index=True,
    )
    line_ids = fields.One2many(
        'sfya.pos.correction.line', 'correction_id', string='Price Changes',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('sfya.pos.correction')
                    or 'New'
                )
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_('Correction records are append-only.'))

    def unlink(self):
        raise UserError(_('Correction records are append-only.'))

    def copy(self, default=None):
        raise UserError(_('Correction records cannot be copied.'))


class SfyaPosCorrectionLine(models.Model):
    _name = 'sfya.pos.correction.line'
    _description = 'POS Order Correction Price Line'
    _order = 'id'

    correction_id = fields.Many2one(
        'sfya.pos.correction',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='restrict',
    )
    old_price_unit = fields.Float(digits='Product Price')
    new_price_unit = fields.Float(digits='Product Price')
    old_discount = fields.Float(digits='Discount')
    new_discount = fields.Float(digits='Discount')

    def write(self, vals):
        raise UserError(_('Correction lines are append-only.'))

    def unlink(self):
        raise UserError(_('Correction lines are append-only.'))

    def copy(self, default=None):
        raise UserError(_('Correction lines cannot be copied.'))
