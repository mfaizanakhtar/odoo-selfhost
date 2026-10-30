from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install')
class TestCustomerHistoryPrices(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.partner_id.tz = 'Asia/Karachi'
        cls.product = cls.env['product.product'].create({
            'name': 'History product', 'available_in_pos': True,
            'taxes_id': [Command.clear()],
        })
        cls.session = cls.env['pos.session'].create({'config_id': cls.basic_config.id})

    def _pos(self, price, date='2026-10-01 10:00:00', product=None,
             partner=None, state='paid', qty=1, discount=0):
        product = product or self.product
        return self.env['pos.order'].create({
            'session_id': self.session.id,
            'partner_id': (partner or self.customer).id,
            'date_order': date, 'state': state,
            'amount_tax': 0, 'amount_total': price * qty,
            'amount_paid': price * qty, 'amount_return': 0,
            'lines': [Command.create({
                'product_id': product.id, 'qty': qty,
                'price_unit': price, 'discount': discount,
                'price_subtotal': price * qty,
                'price_subtotal_incl': price * qty,
            })],
        })

    def _invoice(self, price, date='2026-10-02', product=None, partner=None,
                 state='posted', qty=1, discount=0, move_type='out_invoice',
                 uom=None, currency=None, company_data=None):
        data = company_data or self.company_data
        company = data['company']
        product = product or self.product
        move = self.env['account.move'].with_company(company).create({
            'move_type': move_type, 'company_id': company.id,
            'journal_id': data['default_journal_sale'].id,
            'partner_id': (partner or self.customer).id,
            'invoice_date': date,
            'currency_id': (currency or company.currency_id).id,
            'invoice_line_ids': [Command.create({
                'product_id': product.id, 'quantity': qty,
                'product_uom_id': (uom or product.uom_id).id,
                'price_unit': price, 'discount': discount,
                'account_id': data['default_account_revenue'].id,
                'tax_ids': [Command.clear()],
            })],
        })
        if state == 'posted':
            move.action_post()
        return move

    def _prices(self, products=None, partner=None, pricelist=None):
        return self.env['res.partner'].get_pos_customer_history_prices(
            (partner or self.customer).id,
            (products or self.product).ids,
            (pricelist or self.currency_pricelist).id,
        )

    def _assert_price(self, price):
        self.assertEqual(self._prices(), {str(self.product.id): float(price)})

    def _created_at(self, records, value):
        # SQL is limited to fixture timestamps; the resolver remains read-only.
        records.flush_recordset()
        self.env.cr.execute(
            f'UPDATE {records._table} SET create_date = %s WHERE id IN %s',
            (value, tuple(records.ids)),
        )
        records.invalidate_recordset(['create_date'])

    def test_latest_price_wins_across_pos_and_standalone_invoice(self):
        pos = self._pos(100)
        invoice = self._invoice(125)
        self._assert_price(125)
        pos.date_order = '2026-10-02 10:00:00'
        invoice.button_draft()
        invoice.invoice_date = '2026-10-01'
        invoice.action_post()
        self._assert_price(100)

    def test_linked_pos_invoice_is_not_a_second_candidate(self):
        pos = self._pos(110, '2026-10-02 10:00:00')
        linked = self._invoice(130, '2026-10-03')
        pos.account_move = linked
        self._invoice(90, '2026-10-01')
        self._assert_price(110)

    def test_only_completed_pos_and_posted_standalone_invoice_count(self):
        self._pos(150)
        for state in ('draft', 'cancel'):
            self._pos(400, '2026-10-03 10:00:00', state=state)
        self._invoice(400, state='draft')
        self._assert_price(150)
        for state in ('done', 'invoiced'):
            with self.subTest(state=state):
                self._pos(160, '2026-10-04 10:00:00', state=state)
                self._assert_price(160)

    def test_exact_partner_and_product_variant_are_required(self):
        attribute = self.env['product.attribute'].create({'name': 'History size'})
        values = self.env['product.attribute.value'].create([
            {'name': 'Small', 'attribute_id': attribute.id},
            {'name': 'Large', 'attribute_id': attribute.id},
        ])
        template = self.env['product.template'].create({
            'name': 'History variants', 'available_in_pos': True,
            'attribute_line_ids': [Command.create({
                'attribute_id': attribute.id, 'value_ids': [Command.set(values.ids)],
            })],
        })
        exact, other = template.product_variant_ids
        self._pos(100, product=exact)
        self._invoice(400, product=other)
        self._invoice(400, product=exact, partner=self.other_customer)
        # A commercial parent's history must not leak into a selected contact.
        contact = self.env['res.partner'].create({
            'name': 'Customer contact', 'parent_id': self.customer.id,
        })
        self.assertEqual(self._prices(exact), {str(exact.id): 100.0})
        self.assertEqual(self._prices(exact, partner=contact), {})

    def test_historical_discount_is_ignored(self):
        self._pos(120, discount=25)
        self._assert_price(120)
        self._invoice(120, discount=25)
        self._assert_price(120)

    def test_refund_lines_do_not_replace_original_sale(self):
        original = self._pos(120)
        refund = self._pos(300, '2026-10-03 10:00:00', qty=-1)
        refund.lines.refunded_orderline_id = original.lines
        self._invoice(300, move_type='out_refund')
        negative = self._invoice(300, qty=-1, state='draft')
        negative.write({'invoice_line_ids': [Command.create({
            'product_id': self.env['product.product'].create({'name': 'Offset sale'}).id,
            'quantity': 1, 'price_unit': 400,
            'account_id': self.company_data['default_account_revenue'].id,
            'tax_ids': [Command.clear()],
        })]})
        negative.action_post()
        self._pos(400, '2026-10-04 10:00:00', qty=0)
        self._invoice(400, '2026-10-04', qty=0)
        self._assert_price(120)

    def test_company_local_date_and_stable_ties(self):
        pos = self._pos(100, '2026-10-01 22:00:00')  # Oct 2 in Karachi
        invoice = self._invoice(125, '2026-10-01')
        self._created_at(pos, '2026-10-01 10:00:00')
        self._created_at(invoice, '2026-10-03 10:00:00')
        self._assert_price(100)
        invoice.button_draft()
        invoice.invoice_date = '2026-10-02'
        invoice.action_post()
        self._assert_price(125)  # Same business date, later source creation.
        self._created_at(invoice, '2026-10-01 10:00:00')
        self._assert_price(100)  # pos.order sorts after account.move.
        newer_pos = self._pos(140, '2026-10-02 10:00:00')
        self._created_at(newer_pos, '2026-10-01 10:00:00')
        self._assert_price(140)  # Same model/time, higher source ID.
        # Cashier/user timezone must not affect the company's business date.
        self.assertEqual(
            self.env['res.partner'].with_context(tz='America/Los_Angeles')
            .get_pos_customer_history_prices(
                self.customer.id, self.product.ids, self.currency_pricelist.id,
            ), {str(self.product.id): 140.0},
        )

    def test_multiple_lines_choose_latest_line(self):
        pos = self._pos(100)
        second = pos.lines.copy({'price_unit': 115})
        self._created_at(pos.lines, '2026-10-01 10:00:00')
        self._assert_price(115)  # line ID breaks equal creation timestamps.
        self._created_at(second, '2026-10-01 09:00:00')
        self._assert_price(100)  # line creation time takes precedence over ID.
        invoice = self._invoice(1200, state='draft',
                                uom=self.env.ref('uom.product_uom_dozen'))
        invoice.invoice_line_ids.copy({'move_id': invoice.id, 'price_unit': 1380})
        invoice.action_post()
        self._created_at(invoice.invoice_line_ids, '2026-10-02 10:00:00')
        self._assert_price(115)

    def test_unit_and_currency_are_converted(self):
        usd = self.env.ref('base.USD')
        pkr = self.env.ref('base.PKR')
        (usd | pkr).active = True
        # Set absolute rates relative to the fixture's company currency.
        self.env['res.currency.rate'].search([
            ('currency_id', 'in', (usd | pkr).ids),
            ('company_id', '=', self.company.id),
        ]).unlink()
        self.env['res.currency.rate'].create([
            {'currency_id': usd.id, 'company_id': self.company.id,
             'name': '2026-10-01', 'rate': 1},
            {'currency_id': pkr.id, 'company_id': self.company.id,
             'name': '2026-10-01', 'rate': 280},
            {'currency_id': pkr.id, 'company_id': self.company.id,
             'name': '2026-10-03', 'rate': 300},
        ])
        pricelist = self.currency_pricelist.copy({'currency_id': pkr.id})
        self._invoice(12, currency=usd, uom=self.env.ref('uom.product_uom_dozen'))
        self.assertEqual(self._prices(pricelist=pricelist), {str(self.product.id): 280.0})

    def test_missing_history_is_omitted(self):
        other = self.env['product.product'].create({'name': 'No history'})
        self._pos(100)
        self.assertEqual(self._prices(self.product | other), {str(self.product.id): 100.0})
        self.assertEqual(self._prices(other), {})

    def test_other_company_history_is_excluded(self):
        self._pos(120)
        data = self.setup_other_company()
        self._invoice(400, '2026-10-04', company_data=data)
        self._assert_price(120)

    def test_rpc_inputs_are_validated(self):
        resolver = self.env['res.partner'].get_pos_customer_history_prices
        for partner, products, pricelist in (
            (True, self.product.ids, self.currency_pricelist.id),
            (self.customer.id, 'all', self.currency_pricelist.id),
            (self.customer.id, [True], self.currency_pricelist.id),
            (self.customer.id, [0], self.currency_pricelist.id),
            (self.customer.id, self.product.ids, -1),
        ):
            with self.subTest(partner=partner, products=products, pricelist=pricelist):
                with self.assertRaises(ValidationError):
                    resolver(partner, products, pricelist)
        self.assertEqual(resolver(self.customer.id, [], self.currency_pricelist.id), {})
        foreign = self.env['res.company'].create({'name': 'Foreign history company'})
        foreign_partner = self.customer.copy({'company_id': foreign.id})
        foreign_product = self.env['product.product'].create({'name': 'Foreign product', 'company_id': foreign.id})
        foreign_pricelist = self.currency_pricelist.copy({'company_id': foreign.id})
        for partner, products, pricelist in (
            (foreign_partner.id, self.product.ids, self.currency_pricelist.id),
            (self.customer.id, foreign_product.ids, self.currency_pricelist.id),
            (self.customer.id, self.product.ids, foreign_pricelist.id),
            (2147483647, self.product.ids, self.currency_pricelist.id),
        ):
            with self.subTest(partner=partner, products=products, pricelist=pricelist):
                with self.assertRaises(AccessError):
                    resolver(partner, products, pricelist)

    def test_pos_cashier_can_read_only_requested_history(self):
        invoice = self._invoice(125)
        other = self.env['product.product'].create({'name': 'Unrequested history'})
        self._invoice(400, product=other)
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'History cashier', 'login': 'history_cashier',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'groups_id': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })
        self.assertFalse(invoice.with_user(cashier).has_access('read'))
        self.assertEqual(
            self.env['res.partner'].with_user(cashier).get_pos_customer_history_prices(
                self.customer.id, self.product.ids, self.currency_pricelist.id,
            ), {str(self.product.id): 125.0},
        )
        internal_user = cashier.copy({
            'name': 'History non-POS user', 'login': 'history_internal',
            'groups_id': [Command.set([self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(internal_user).get_pos_customer_history_prices(
                self.customer.id, self.product.ids, self.currency_pricelist.id,
            )
