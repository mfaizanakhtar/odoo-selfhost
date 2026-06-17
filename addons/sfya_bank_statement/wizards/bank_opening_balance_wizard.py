from odoo import api, fields, models, _
from odoo.exceptions import UserError


class BankOpeningBalanceWizard(models.TransientModel):
    _name = 'sfya.bank.opening.balance.wizard'
    _description = 'Set Bank/Cash Opening Balance'

    journal_id = fields.Many2one(
        'account.journal', required=True,
        domain="[('type', 'in', ['bank', 'cash'])]",
        default=lambda self: self.env.context.get('active_id'),
    )
    amount = fields.Monetary(
        required=True,
        help='Positive = bank/cash has money. Negative = overdraft / shortage.',
    )
    date = fields.Date(required=True, default=fields.Date.today)
    description = fields.Char(default='Opening balance — migrated')
    opening_journal_id = fields.Many2one(
        'account.journal', required=True,
        domain="[('type', '=', 'general')]",
        default=lambda self: self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.env.company.id)], limit=1,
        ),
        help='Journal that posts the opening JE (Miscellaneous / General).',
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id.id,
    )
    force = fields.Boolean(
        string='Override existing (Admin)',
        help='Allow creating another opening JE even if one already exists.',
    )
    is_admin = fields.Boolean(compute='_compute_is_admin')

    def _compute_is_admin(self):
        for w in self:
            w.is_admin = self.env.user.has_group('base.group_system')

    def action_create_move(self):
        self.ensure_one()
        journal = self.journal_id
        if not journal.default_account_id:
            raise UserError(_(
                'Journal %s has no default account configured.', journal.name,
            ))
        equity = self.env.company.sfya_opening_balance_account_id
        if not equity:
            raise UserError(_(
                "Opening Balance Equity account not set. "
                "Go to Settings → Companies → %s and set it.",
                self.env.company.name,
            ))
        if not self.amount:
            raise UserError(_('Amount must be non-zero.'))

        ref = f'BANK-OPENING-BAL-{journal.id}'
        existing = self.env['account.move'].search([
            ('ref', '=', ref),
            ('state', '=', 'posted'),
        ], limit=1)
        if existing and not self.force:
            raise UserError(_(
                "Opening balance already posted for %(j)s (move %(m)s). "
                "Tick Override to add another (Admin only).",
                j=journal.name, m=existing.name,
            ))
        if self.force and not self.is_admin:
            raise UserError(_("Only administrators can override an existing opening balance."))

        amt = self.amount
        sign_positive = amt > 0
        line_bank = {
            'account_id': journal.default_account_id.id,
            'name': self.description or _('Opening balance'),
            'debit': abs(amt) if sign_positive else 0.0,
            'credit': abs(amt) if not sign_positive else 0.0,
        }
        line_equity = {
            'account_id': equity.id,
            'name': self.description or _('Opening balance'),
            'debit': 0.0 if sign_positive else abs(amt),
            'credit': abs(amt) if sign_positive else 0.0,
        }
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.date,
            'journal_id': self.opening_journal_id.id,
            'ref': ref,
            'line_ids': [(0, 0, line_bank), (0, 0, line_equity)],
        })
        move.action_post()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Opening balance set'),
                'message': _(
                    'Created %(m)s for %(j)s (%(a)s).',
                    m=move.name, j=journal.name, a=amt,
                ),
                'type': 'success',
                'sticky': False,
            },
        }
