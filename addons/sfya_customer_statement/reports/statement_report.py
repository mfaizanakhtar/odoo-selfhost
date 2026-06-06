from odoo import api, models


class CustomerStatementReport(models.AbstractModel):
    _name = 'report.sfya_customer_statement.report_customer_statement'
    _description = 'Customer Statement Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env['sfya.statement.wizard'].browse(docids)
        wizard = wizards[:1]
        if not wizard or not wizard.partner_id:
            return {
                'doc_ids': docids,
                'doc_model': 'sfya.statement.wizard',
                'docs': wizards,
                'data': {},
            }
        statement = wizard.partner_id.get_statement_data(
            wizard.date_from,
            wizard.date_to,
            include_drafts=wizard.include_drafts,
        )
        return {
            'doc_ids': docids,
            'doc_model': 'sfya.statement.wizard',
            'docs': wizards,
            'data': statement,
        }
