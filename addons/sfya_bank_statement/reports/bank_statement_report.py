from odoo import api, models


class ReportBankStatement(models.AbstractModel):
    _name = 'report.sfya_bank_statement.report_bank_statement'
    _description = 'Bank Statement Report'

    def _get_journal_money_accounts(self, journal):
        """Return dict with 'default' account id and 'outstanding_ids' set.

        default: the journal's default_account_id (settled side).
          Kept journal-unfiltered so opening JEs posted via General/MISC
          journal that hit this account still appear in the statement.
        outstanding_ids: outstanding accounts from account_payment records.
          Scoped by journal_id downstream to prevent cross-journal leakage.
        """
        result = {
            'default': journal.default_account_id.id if journal.default_account_id else None,
            'outstanding_ids': set(),
        }
        self.env.cr.execute(
            "SELECT DISTINCT outstanding_account_id FROM account_payment "
            "WHERE journal_id = %s AND outstanding_account_id IS NOT NULL",
            (journal.id,),
        )
        result['outstanding_ids'].update(r[0] for r in self.env.cr.fetchall())
        return result

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env['sfya.bank.statement.wizard'].browse(docids)
        lines_by_wizard = {}
        opening_by_wizard = {}
        closing_by_wizard = {}
        accounts_by_wizard = {}
        AML = self.env['account.move.line']
        for w in wizards:
            money = self._get_journal_money_accounts(w.journal_id)
            # Build per-journal account records for display
            all_acct_ids = set()
            if money['default']:
                all_acct_ids.add(money['default'])
            all_acct_ids.update(money['outstanding_ids'])
            accounts_by_wizard[w.id] = self.env['account.account'].browse(
                sorted(all_acct_ids)
            )
            if not all_acct_ids:
                lines_by_wizard[w.id] = []
                opening_by_wizard[w.id] = 0.0
                closing_by_wizard[w.id] = 0.0
                continue

            # Build domains — two-tier: default account unfiltered, outstanding scoped
            posted_domain = [('parent_state', '=', 'posted')]

            # Part 1: Lines on the journal's default account (any journal — catches opening JEs)
            default_domain = posted_domain.copy()
            if money['default']:
                default_domain.append(('account_id', '=', money['default']))

            # Part 2: Lines on outstanding accounts (scoped by journal_id)
            outstanding_domain = posted_domain.copy()
            if money['outstanding_ids']:
                outstanding_domain.append(('account_id', 'in', list(money['outstanding_ids'])))
                outstanding_domain.append(('journal_id', '=', w.journal_id.id))

            # Combine: prior (date < date_from)
            if money['default'] and money['outstanding_ids']:
                prior = AML.search(
                    [('parent_state', '=', 'posted'),
                     '|',
                     ('account_id', '=', money['default']),
                     '&',
                     ('account_id', 'in', list(money['outstanding_ids'])),
                     ('journal_id', '=', w.journal_id.id),
                     ('date', '<', w.date_from)]
                )
                in_range = AML.search(
                    [('parent_state', '=', 'posted'),
                     '|',
                     ('account_id', '=', money['default']),
                     '&',
                     ('account_id', 'in', list(money['outstanding_ids'])),
                     ('journal_id', '=', w.journal_id.id),
                     ('date', '>=', w.date_from),
                     ('date', '<=', w.date_to)],
                    order='date asc, id asc',
                )
            elif money['default']:
                prior = AML.search(default_domain + [('date', '<', w.date_from)])
                in_range = AML.search(
                    default_domain + [('date', '>=', w.date_from), ('date', '<=', w.date_to)],
                    order='date asc, id asc',
                )
            elif money['outstanding_ids']:
                prior = AML.search(outstanding_domain + [('date', '<', w.date_from)])
                in_range = AML.search(
                    outstanding_domain + [('date', '>=', w.date_from), ('date', '<=', w.date_to)],
                    order='date asc, id asc',
                )
            else:
                prior = AML.search([('id', '=', 0)])
                in_range = AML.search([('id', '=', 0)])

            opening = sum(prior.mapped('debit')) - sum(prior.mapped('credit'))
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
