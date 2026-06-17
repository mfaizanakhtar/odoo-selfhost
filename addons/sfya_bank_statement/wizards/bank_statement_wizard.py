from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class BankStatementWizard(models.TransientModel):
    _name = 'sfya.bank.statement.wizard'
    _description = 'Bank/Cash Statement Wizard'

    journal_id = fields.Many2one(
        'account.journal', required=True,
        domain="[('type', 'in', ['bank', 'cash'])]",
        default=lambda self: self.env.context.get('active_id'),
    )
    date_from = fields.Date(
        required=True,
        default=lambda self: fields.Date.today() - timedelta(days=180),
    )
    date_to = fields.Date(required=True, default=fields.Date.today)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for w in self:
            if w.date_from > w.date_to:
                raise UserError(_('Date From must be before Date To.'))

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            'sfya_bank_statement.action_report_bank_statement'
        ).report_action(self, config=False)

    def action_view_html(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/report/html/sfya_bank_statement.report_bank_statement/'
                f'{self.id}'
            ),
            'target': 'new',
        }
