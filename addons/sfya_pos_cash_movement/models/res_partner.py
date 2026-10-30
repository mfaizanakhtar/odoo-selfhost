from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'
    is_shareholder = fields.Boolean(
        string='Shareholder / Partner',
        default=False,
        help='If checked, this partner appears in the POS Partner Drawing flow.',
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields = super()._load_pos_data_fields(config_id)
        fields += ['supplier_rank', 'is_shareholder']
        return fields

    @api.model
    def get_customer_overview_tags(self):
        """Return the existing Contact Tags available in this POS context."""
        return [
            {'id': tag.id, 'name': tag.name}
            for tag in self.env['res.partner.category'].search([], order='name, id')
        ]

    @api.model
    def _validate_customer_overview_tag(self, tag_id):
        """Resolve an optional tag without silently widening invalid filters."""
        if tag_id is None or tag_id is False or tag_id == '':
            return None
        if type(tag_id) is not int or tag_id <= 0:
            raise UserError(_('Invalid customer tag. Please select an existing Contact Tag.'))
        tag = self.env['res.partner.category'].search([('id', '=', tag_id)], limit=1)
        if not tag:
            raise UserError(_('Customer tag is no longer available. Please select another Contact Tag.'))
        return tag.id

    @api.model
    def get_customer_balances(self, tag_id=None):
        """Return partners with non-zero net balance (AR - AP) for POS overview."""
        tag_id = self._validate_customer_overview_tag(tag_id)
        self.env.cr.execute("""
            SELECT
                aml.partner_id,
                rp.name,
                SUM(aml.debit) - SUM(aml.credit) AS balance
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN account_account aa ON aa.id = aml.account_id
            JOIN res_partner rp ON rp.id = aml.partner_id
            WHERE aa.account_type IN ('asset_receivable', 'liability_payable')
              AND am.state = 'posted'
              AND aml.partner_id IS NOT NULL
              AND aml.company_id = %s
            GROUP BY aml.partner_id, rp.name
            HAVING ABS(SUM(aml.debit) - SUM(aml.credit)) > 0.005
            ORDER BY balance DESC
        """, (self.env.company.id,))
        rows = self.env.cr.fetchall()
        if tag_id is not None:
            # Keep archived balance partners and the existing SQL visibility.
            matching_partner_ids = set(self.sudo().with_context(active_test=False).search([
                ('id', 'in', [row[0] for row in rows]),
                '|',
                ('category_id', 'in', [tag_id]),
                ('commercial_partner_id.category_id', 'in', [tag_id]),
            ]).ids)
            rows = [row for row in rows if row[0] in matching_partner_ids]
        return [
            {'partner_id': r[0], 'partner_name': r[1], 'balance': round(r[2], 2)}
            for r in rows
        ]
