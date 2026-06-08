from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class StatementWizard(models.TransientModel):
    _name = 'sfya.statement.wizard'
    _description = 'Customer Statement Wizard'

    partner_id = fields.Many2one(
        'res.partner', required=True,
        default=lambda self: self.env.context.get('active_id'),
    )
    date_from = fields.Date(
        required=True,
        default=lambda self: fields.Date.today() - timedelta(days=180),
    )
    date_to = fields.Date(required=True, default=fields.Date.today)
    include_drafts = fields.Boolean(
        string='Include draft POS orders',
        default=False,
    )
    show_aging = fields.Boolean(
        string='Show Aging',
        default=False,
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for w in self:
            if w.date_from > w.date_to:
                raise UserError(_('Date From must be before Date To.'))

    def action_print_pdf(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Pick a customer.'))
        report_ref = 'sfya_customer_statement.action_report_customer_statement'
        return self.env.ref(report_ref).report_action(self, config=False)

    def action_view_html(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Pick a customer.'))
        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/report/html/sfya_customer_statement.report_customer_statement/'
                f'{self.id}'
            ),
            'target': 'new',
        }
