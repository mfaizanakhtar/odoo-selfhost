from odoo import _, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def write(self, vals):
        # Also blocks partner-merge/reconciliation writes on posted POS
        # invoices; those flows must use the standard reset-to-draft path.
        if 'partner_id' in vals:
            new_partner_id = vals['partner_id']
            for move in self:
                if (
                    move.state == 'posted'
                    and move.move_type == 'out_invoice'
                    and move.pos_order_ids
                    and new_partner_id != move.partner_id.id
                ):
                    raise UserError(_(
                        'Correct the customer from the linked POS order, '
                        'not from the invoice.'
                    ))
        return super().write(vals)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def write(self, vals):
        if 'partner_id' in vals:
            new_partner_id = vals['partner_id']
            for line in self:
                move = line.move_id
                if (
                    move.state == 'posted'
                    and move.move_type == 'out_invoice'
                    and move.pos_order_ids
                    and line.account_id
                    and line.account_id.account_type == 'asset_receivable'
                    and new_partner_id != line.partner_id.id
                ):
                    raise UserError(_(
                        'Correct the customer from the linked POS order, '
                        'not from the journal items.'
                    ))
        return super().write(vals)
