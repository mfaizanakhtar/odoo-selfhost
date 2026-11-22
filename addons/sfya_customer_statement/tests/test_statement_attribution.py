from datetime import date, timedelta

from odoo import Command, fields
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install')
class TestStatementAttribution(TestPoSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({
            'name': 'Statement product',
            'available_in_pos': True,
            'taxes_id': [Command.clear()],
        })
        cls.session = cls.env['pos.session'].create({
            'config_id': cls.basic_config.id,
        })

    def _order(self, partner, amount=48000, state='invoiced', date_order=None):
        return self.env['pos.order'].create({
            'session_id': self.session.id,
            'partner_id': partner.id,
            'date_order': date_order or fields.Datetime.now(),
            'state': state,
            'amount_tax': 0,
            'amount_total': amount,
            'amount_paid': amount,
            'amount_return': 0,
            'lines': [Command.create({
                'product_id': self.product.id,
                'qty': 1,
                'price_unit': amount,
                'price_subtotal': amount,
                'price_subtotal_incl': amount,
            })],
        })

    def _invoice(self, partner, amount, move_type='out_invoice',
                 state='posted', invoice_date=None):
        invoice = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': partner.id,
            'invoice_date': invoice_date or fields.Date.today(),
            'journal_id': self.invoice_journal.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': amount,
                'account_id': self.sales_account.id,
                'tax_ids': [Command.clear()],
            })],
        })
        if state == 'posted':
            invoice.action_post()
        return invoice

    def _link(self, order, invoice):
        order.write({'account_move': invoice.id, 'state': 'invoiced'})
        return order

    def _rows(self, partner, date_from=None, date_to=None):
        date_from = date_from or fields.Date.today() - timedelta(days=1)
        date_to = date_to or fields.Date.today() + timedelta(days=1)
        return partner.get_statement_data(date_from, date_to)['rows']

    def _pos_rows(self, partner, date_from=None, date_to=None):
        return [
            row for row in self._rows(partner, date_from, date_to)
            if row['kind'] in ('pos', 'pos_refund')
        ]

    def test_invoiced_order_belongs_to_invoice_customer(self):
        order = self._order(self.customer, 48000)
        invoice = self._invoice(self.other_customer, 48000)
        self._link(order, invoice)

        self.assertFalse(self._pos_rows(self.customer))
        rows = self._pos_rows(self.other_customer)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['debit'], 48000)
        self.assertEqual(rows[0]['credit'], 0)

    def test_linked_invoice_is_not_a_second_statement_row(self):
        order = self._order(self.customer, 48000)
        invoice = self._invoice(self.other_customer, 48000)
        self._link(order, invoice)

        rows = self._rows(self.other_customer)
        self.assertEqual(len([r for r in rows if r['kind'] == 'pos']), 1)
        self.assertEqual(len([r for r in rows if r['kind'] == 'invoice']), 0)

    def test_uninvoiced_order_keeps_order_customer(self):
        self._order(self.customer, 1000, state='paid')
        rows = self._pos_rows(self.customer)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['debit'], 1000)

    def test_multi_order_invoice_emits_one_row(self):
        first = self._order(self.customer, 1000)
        second = self._order(self.customer, 2000)
        invoice = self._invoice(self.other_customer, 3000)
        self._link(first, invoice)
        self._link(second, invoice)

        self.assertFalse(self._pos_rows(self.customer))
        rows = self._pos_rows(self.other_customer)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['debit'], 3000)

    def test_cancelled_or_draft_invoice_is_omitted(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.other_customer, 1000, state='draft')
        self._link(order, invoice)
        self.assertFalse(self._pos_rows(self.customer))
        self.assertFalse(self._pos_rows(self.other_customer))

        invoice.action_post()
        invoice.button_draft()
        invoice.button_cancel()
        self.assertFalse(self._pos_rows(self.customer))
        self.assertFalse(self._pos_rows(self.other_customer))

    def test_invoiced_row_uses_invoice_date(self):
        order = self._order(
            self.customer, 1000,
            date_order='2025-12-15 10:00:00',
        )
        invoice = self._invoice(
            self.other_customer, 1000,
            invoice_date=date(2026, 1, 10),
        )
        self._link(order, invoice)

        december = self._pos_rows(
            self.other_customer,
            date_from=date(2025, 12, 1),
            date_to=date(2025, 12, 31),
        )
        january = self._pos_rows(
            self.other_customer,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
        )
        self.assertFalse(december)
        self.assertEqual(len(january), 1)
        self.assertEqual(january[0]['debit'], 1000)

    def test_refund_uses_absolute_amount(self):
        order = self._order(self.customer, -1450)
        invoice = self._invoice(
            self.other_customer, 1450, move_type='out_refund',
        )
        self._link(order, invoice)

        rows = self._pos_rows(self.other_customer)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['kind'], 'pos_refund')
        self.assertEqual(rows[0]['debit'], 0)
        self.assertEqual(rows[0]['credit'], 1450)
