from odoo import api, fields, models, _
from odoo.exceptions import UserError


class OpeningBalanceWizard(models.TransientModel):
    _name = 'sfya.opening.balance.wizard'
    _description = 'Set Customer Opening Balance'

    partner_id = fields.Many2one(
        'res.partner', required=True,
        default=lambda self: self.env.context.get('active_id'),
    )
    amount = fields.Monetary(
        required=True,
        help='Positive = customer owes. Negative = customer has advance with us.',
    )
    date = fields.Date(required=True, default=fields.Date.today)
    description = fields.Char(default='Opening balance — migrated')
    journal_id = fields.Many2one(
        'account.journal', required=True,
        domain="[('type', '=', 'general')]",
        default=lambda self: self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.env.company.id)], limit=1,
        ),
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id.id,
    )
    force = fields.Boolean(
        string='Override existing',
        help='Allow creating another opening balance even if one already exists.',
    )

    @api.constrains('partner_id')
    def _check_partner(self):
        for w in self:
            if not w.partner_id:
                raise UserError(_('Pick a customer first.'))

    def action_create_move(self):
        self.ensure_one()
        if not self.partner_id.property_account_receivable_id:
            raise UserError(_(
                'Partner %s has no receivable account configured.',
                self.partner_id.name,
            ))
        ar = self.partner_id.property_account_receivable_id
        equity = self.env.company.sfya_opening_balance_account_id
        if not equity:
            raise UserError(_(
                "Opening Balance Equity account not set. "
                "Go to Settings → Companies → %s and set it.",
                self.env.company.name,
            ))

        if not self.force:
            existing = self.env['account.move'].search([
                ('partner_id', '=', self.partner_id.id),
                ('ref', '=like', 'OPENING-BAL-%'),
                ('state', '=', 'posted'),
            ], limit=1)
            if existing:
                raise UserError(_(
                    "Opening balance already posted for %(p)s (move %(m)s). "
                    "Check 'Override existing' to add another.",
                    p=self.partner_id.name, m=existing.name,
                ))

        amt = self.amount
        if not amt:
            raise UserError(_('Amount must be non-zero.'))
        sign_owes = amt > 0
        line_ar = {
            'account_id': ar.id,
            'partner_id': self.partner_id.id,
            'name': self.description or _('Opening balance'),
            'debit': abs(amt) if sign_owes else 0.0,
            'credit': abs(amt) if not sign_owes else 0.0,
        }
        line_equity = {
            'account_id': equity.id,
            'partner_id': self.partner_id.id,
            'name': self.description or _('Opening balance'),
            'debit': 0.0 if sign_owes else abs(amt),
            'credit': abs(amt) if sign_owes else 0.0,
        }
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.date,
            'journal_id': self.journal_id.id,
            'partner_id': self.partner_id.id,
            'ref': f'OPENING-BAL-{self.partner_id.id}',
            'line_ids': [(0, 0, line_ar), (0, 0, line_equity)],
        })
        move.action_post()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Opening balance set'),
                'message': _(
                    'Created %(m)s for %(p)s (%(a)s).',
                    m=move.name, p=self.partner_id.name, a=amt,
                ),
                'type': 'success',
                'sticky': False,
            },
        }
