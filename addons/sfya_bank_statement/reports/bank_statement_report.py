from odoo import api, models


class ReportBankStatement(models.AbstractModel):
    _name = 'report.sfya_bank_statement.report_bank_statement'
    _description = 'Bank Statement Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env['sfya.bank.statement.wizard'].browse(docids)
        lines_by_wizard = {}
        opening_by_wizard = {}
        closing_by_wizard = {}
        AML = self.env['account.move.line']
        for w in wizards:
            acct = w.journal_id.default_account_id
            if not acct:
                lines_by_wizard[w.id] = []
                opening_by_wizard[w.id] = 0.0
                closing_by_wizard[w.id] = 0.0
                continue
            base_domain = [
                ('account_id', '=', acct.id),
                ('parent_state', '=', 'posted'),
            ]
            prior = AML.search(base_domain + [('date', '<', w.date_from)])
            opening = sum(l.debit - l.credit for l in prior)
            in_range = AML.search(
                base_domain + [
                    ('date', '>=', w.date_from),
                    ('date', '<=', w.date_to),
                ],
                order='date asc, id asc',
            )
            running = opening
            line_dicts = []
            for line in in_range:
                running += line.debit - line.credit
                line_dicts.append({
                    'date': line.date,
                    'ref': line.move_id.ref or line.move_id.name or '',
                    'partner_name': line.partner_id.name or '',
                    'label': line.name or '',
                    'debit': line.debit,
                    'credit': line.credit,
                    'running_balance': running,
                })
            lines_by_wizard[w.id] = line_dicts
            opening_by_wizard[w.id] = opening
            closing_by_wizard[w.id] = running
        return {
            'doc_ids': docids,
            'doc_model': 'sfya.bank.statement.wizard',
            'docs': wizards,
            'company': self.env.company,
            'lines_by_wizard': lines_by_wizard,
            'opening_by_wizard': opening_by_wizard,
            'closing_by_wizard': closing_by_wizard,
        }
