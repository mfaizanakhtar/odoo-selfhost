from odoo import api, models


class ReportBankStatement(models.AbstractModel):
    _name = 'report.sfya_bank_statement.report_bank_statement'
    _description = 'Bank Statement Report'

    def _get_journal_money_accounts(self, journal):
        """Return the set of GL accounts that represent money in this journal.

        Includes:
          - default_account_id (settled / reconciled side)
          - payment_account_id from inbound/outbound payment method lines
            (outstanding receipts/payments — where pre-reconciliation funds live)
          - Distinct outstanding_account_id from existing posted payments
            (catches company-default fallback that isn't on the method line)
        """
        ids = set()
        if journal.default_account_id:
            ids.add(journal.default_account_id.id)
        for pml in (
            journal.inbound_payment_method_line_ids
            | journal.outbound_payment_method_line_ids
        ):
            if pml.payment_account_id:
                ids.add(pml.payment_account_id.id)
        self.env.cr.execute(
            "SELECT DISTINCT outstanding_account_id FROM account_payment "
            "WHERE journal_id = %s AND outstanding_account_id IS NOT NULL",
            (journal.id,),
        )
        ids.update(r[0] for r in self.env.cr.fetchall())
        return ids

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env['sfya.bank.statement.wizard'].browse(docids)
        lines_by_wizard = {}
        opening_by_wizard = {}
        closing_by_wizard = {}
        accounts_by_wizard = {}
        AML = self.env['account.move.line']
        for w in wizards:
            acct_ids = self._get_journal_money_accounts(w.journal_id)
            accounts_by_wizard[w.id] = self.env['account.account'].browse(
                sorted(acct_ids)
            )
            if not acct_ids:
                lines_by_wizard[w.id] = []
                opening_by_wizard[w.id] = 0.0
                closing_by_wizard[w.id] = 0.0
                continue
            base_domain = [
                ('account_id', 'in', list(acct_ids)),
                ('parent_state', '=', 'posted'),
            ]
            prior = AML.search(base_domain + [('date', '<', w.date_from)])
            opening = sum(prior.mapped('debit')) - sum(prior.mapped('credit'))
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
                    'account_code': line.account_id.code,
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
            'accounts_by_wizard': accounts_by_wizard,
        }
