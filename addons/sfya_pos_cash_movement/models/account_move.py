from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    pos_session_id = fields.Many2one(
        'pos.session',
        string='POS Session',
        index=True,
        copy=False,
        help='If set, this journal entry originated from a POS Pay Out '
             '"settle via another partner" transfer during this session.',
    )
    sfya_is_partner_transfer = fields.Boolean(
        default=False,
        copy=False,
        help='True for the 2-line journal entries created by the POS partner '
             'transfer flow (funder settles a payout on our behalf, no cash '
             'moves). Used to route these into their own statement rows and '
             'keep them out of the generic manual-journal-entry listing.',
    )
    sfya_transfer_from_partner_id = fields.Many2one(
        'res.partner',
        string='Transfer Funder',
        copy=False,
        help='Partner whose debt to us was reduced to fund this transfer.',
    )
    sfya_transfer_to_partner_id = fields.Many2one(
        'res.partner',
        string='Transfer Recipient',
        copy=False,
        help='Partner whose debt owed by us was settled by this transfer.',
    )
    sfya_transfer_amount = fields.Monetary(
        string='Transfer Amount',
        copy=False,
    )
    sfya_is_salary_offset = fields.Boolean(default=False, copy=False)
    sfya_salary_offset_employee_id = fields.Many2one('hr.employee', copy=False)
    sfya_salary_offset_amount = fields.Monetary(copy=False)

    @api.model
    def sfya_pos_partner_transfer(self, session_id, from_partner_id, to_partner_id, amount, memo='', date=None):
        """RPC: settle a POS Pay Out via another partner instead of cash/bank.

        Posts a 2-line journal entry with no cash/bank leg: the funder's
        debt to us is credited (reduced) and the recipient's debt owed by
        us is debited (reduced), for the same amount. Till is untouched.
        """
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session or session.state != 'opened':
            raise UserError(_('POS session not found or not open.'))
        if from_partner_id == to_partner_id:
            raise UserError(_('Funding partner and recipient partner must be different.'))
        from_partner = self.env['res.partner'].sudo().browse(from_partner_id).exists()
        to_partner = self.env['res.partner'].sudo().browse(to_partner_id).exists()
        if not from_partner or not to_partner:
            raise UserError(_('Partner not found.'))
        if amount <= 0:
            raise UserError(_('Amount must be greater than zero.'))

        AccountPayment = self.env['account.payment']
        from_type = AccountPayment._sfya_resolve_partner_type(from_partner, 'inbound')
        if not from_type:
            raise UserError(_('The funding partner has no customer or vendor relationship to draw from.'))
        to_type = AccountPayment._sfya_resolve_partner_type(to_partner, 'outbound')
        if not to_type:
            raise UserError(_('The recipient partner has no outstanding vendor bill or customer credit to pay out.'))

        from_account = (
            from_partner.property_account_receivable_id if from_type == 'customer'
            else from_partner.property_account_payable_id
        )
        to_account = (
            to_partner.property_account_receivable_id if to_type == 'customer'
            else to_partner.property_account_payable_id
        )
        if not from_account or not to_account:
            raise UserError(_('Partner is missing a receivable/payable account.'))

        journal = session.company_id.sfya_partner_transfer_journal_id
        if not journal:
            general_journals = self.env['account.journal'].sudo().search([
                ('type', '=', 'general'),
                ('company_id', '=', session.company_id.id),
            ])
            if len(general_journals) == 1:
                journal = general_journals
            elif not general_journals:
                raise UserError(_('No Miscellaneous Operations journal configured for this company.'))
            else:
                raise UserError(_(
                    'Multiple Miscellaneous Operations journals found for this company. '
                    'Set "Partner Transfer Journal" in POS Settings to pick one.'
                ))

        resolved_date = fields.Date.today()
        if date:
            try:
                resolved_date = fields.Date.from_string(date)
            except (ValueError, TypeError):
                raise UserError(_("Invalid date format."))
            if resolved_date > fields.Date.today():
                raise UserError(_("Date cannot be in the future."))

        move = self.sudo().create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': resolved_date,
            'ref': memo or _('Partner Transfer: %s -> %s', from_partner.name, to_partner.name),
            'pos_session_id': session.id,
            'sfya_is_partner_transfer': True,
            'sfya_transfer_from_partner_id': from_partner.id,
            'sfya_transfer_to_partner_id': to_partner.id,
            'sfya_transfer_amount': amount,
            'line_ids': [
                Command.create({
                    'partner_id': from_partner.id,
                    'account_id': from_account.id,
                    'credit': amount,
                    'debit': 0.0,
                    'name': memo or _('Settled via %s', to_partner.name),
                }),
                Command.create({
                    'partner_id': to_partner.id,
                    'account_id': to_account.id,
                    'debit': amount,
                    'credit': 0.0,
                    'name': memo or _('Paid via %s', from_partner.name),
                }),
            ],
        })
        move.action_post()
        return {
            'id': move.id,
            'name': move.name,
            'from_partner_id': from_partner.id,
            'from_partner_name': from_partner.name,
            'to_partner_id': to_partner.id,
            'to_partner_name': to_partner.name,
            'amount': amount,
            'memo': memo or '',
            'direction': 'transfer',
        }
