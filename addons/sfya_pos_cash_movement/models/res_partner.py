from odoo import api, fields, models


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
    def get_customer_balances(self):
        """Return partners with non-zero net balance (AR - AP) for POS overview."""
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
        return [
            {'partner_id': r[0], 'partner_name': r[1], 'balance': round(r[2], 2)}
            for r in self.env.cr.fetchall()
        ]
