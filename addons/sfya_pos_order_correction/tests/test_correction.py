from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install')
class TestPosOrderCorrection(TestPoSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({
            'name': 'Correction product',
            'available_in_pos': True,
            'taxes_id': [Command.clear()],
        })
        cls.stock_product = cls.env['product.product'].create({
            'name': 'Correction stock product',
            'available_in_pos': True,
            'is_storable': True,
            'taxes_id': [Command.clear()],
        })
        cls.stock_location = cls.company_data[
            'default_warehouse'
        ].lot_stock_id
        cls.customer_location = cls.env.ref(
            'stock.stock_location_customers'
        )
        cls.session = cls.env['pos.session'].create({
            'config_id': cls.basic_config.id,
        })

    def _order(self, partner, amount=1000, state='invoiced',
               refunded_line=None, product=None, qty=1,
               unit_price=None):
        product = product or self.product
        if amount < 0 and qty == 1:
            qty = -1
        if unit_price is None:
            unit_price = abs(amount) / abs(qty) if qty else abs(amount)
        return self.env['pos.order'].create({
            'session_id': self.session.id,
            'partner_id': partner.id,
            'date_order': fields.Datetime.now(),
            'state': state,
            'amount_tax': 0,
            'amount_total': amount,
            'amount_paid': amount,
            'amount_return': 0,
            'lines': [Command.create({
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'qty': qty,
                'price_unit': unit_price,
                'price_subtotal': amount,
                'price_subtotal_incl': amount,
                'refunded_orderline_id': (
                    refunded_line.id if refunded_line else False
                ),
            })],
        })

    def _invoice(self, partner, amount, state='posted', product=None,
                 qty=1, unit_price=None):
        product = product or self.product
        if unit_price is None:
            unit_price = abs(amount) / abs(qty) if qty else abs(amount)
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today(),
            'journal_id': self.invoice_journal.id,
            'invoice_line_ids': [Command.create({
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'quantity': qty,
                'price_unit': unit_price,
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

    def _deliver(self, order, product, qty):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.basic_config.picking_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'partner_id': order.partner_id.id,
            'origin': order.name,
            'pos_order_id': order.id,
            'move_ids': [Command.create({
                'name': product.display_name,
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'location_id': self.stock_location.id,
                'location_dest_id': self.customer_location.id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.write({'quantity': qty, 'picked': True})
        picking.with_context(
            skip_backorder=True,
            skip_sanity_check=True,
        ).button_validate()
        self.assertEqual(picking.state, 'done')
        return picking

    def _stock_order(self, qty=400, unit_price=120, stock=None):
        stock = qty if stock is None else stock
        self.env['stock.quant']._update_available_quantity(
            self.stock_product, self.stock_location, stock,
        )
        amount = qty * unit_price
        order = self._order(
            self.customer,
            amount=amount,
            product=self.stock_product,
            qty=qty,
            unit_price=unit_price,
        )
        invoice = self._invoice(
            self.customer,
            amount=amount,
            product=self.stock_product,
            qty=qty,
            unit_price=unit_price,
        )
        self._link(order, invoice)
        self._deliver(order, self.stock_product, qty)
        return order, invoice

    def _wizard(self, order, partner, reason='Test correction', price=None,
                qty=None):
        vals = {
            'order_id': order.id,
            'new_partner_id': partner.id,
            'reason': reason,
        }
        if price is not None or qty is not None:
            invoice_line = order.account_move.invoice_line_ids.filtered(
                lambda line: line.display_type == 'product'
            )[:1]
            vals['line_ids'] = [Command.create({
                'invoice_line_id': invoice_line.id,
                'new_qty': (
                    qty if qty is not None else invoice_line.quantity
                ),
                'new_price_unit': (
                    price if price is not None else invoice_line.price_unit
                ),
                'new_discount': 0.0,
            })]
        return self.env['sfya.pos.correction.wizard'].create(vals)

    def _mark_invoice(self, invoice, payment_state, residual):
        self.env.cr.execute(
            "UPDATE account_move SET payment_state=%s, amount_residual=%s "
            "WHERE id=%s",
            (payment_state, residual, invoice.id),
        )
        invoice.invalidate_recordset(
            ['payment_state', 'amount_residual'],
        )

    def test_aligns_order_to_existing_invoice_customer(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)

        invoice.button_draft()
        invoice.write({'partner_id': self.other_customer.id})
        invoice.action_post()

        wizard = self._wizard(order, self.other_customer)
        wizard.action_apply()

        self.assertEqual(order.partner_id, self.other_customer)
        self.assertEqual(invoice.partner_id, self.other_customer)
        self.assertEqual(invoice.state, 'posted')
        correction = self.env['sfya.pos.correction'].search([
            ('order_id', '=', order.id),
        ])
        self.assertEqual(len(correction), 1)
        self.assertEqual(correction.old_partner_id, self.customer)
        self.assertEqual(correction.new_partner_id, self.other_customer)

    def test_customer_correction_resets_and_reposts_invoice(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        old_name = invoice.name
        old_total = invoice.amount_total

        wizard = self._wizard(order, self.other_customer)
        wizard.action_apply()

        self.assertEqual(order.partner_id, self.other_customer)
        self.assertEqual(invoice.partner_id, self.other_customer)
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.name, old_name)
        self.assertEqual(invoice.amount_total, old_total)
        self.assertEqual(order.account_move, invoice)
        self.assertTrue(all(
            line.partner_id == self.other_customer
            for line in invoice.line_ids
        ))
        term = invoice.line_ids.filtered(
            lambda line: line.display_type == 'payment_term'
        )
        self.assertEqual(
            term.account_id,
            self.other_customer.property_account_receivable_id,
        )

    def test_rejects_paid_invoice_customer_change(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        self._mark_invoice(invoice, 'paid', 0.0)

        with self.assertRaises(UserError):
            self._wizard(order, self.other_customer).action_apply()

    def test_price_correction_updates_invoice_without_new_documents(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        order_line_price = order.lines[0].price_unit
        moves_before = self.env['account.move'].search_count([])

        self._wizard(order, self.customer, price=1100).action_apply()

        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.amount_total, 1100)
        invoice_line = invoice.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product'
        )
        self.assertEqual(invoice_line.price_unit, 1100)
        self.assertEqual(order.lines[0].price_unit, order_line_price)
        self.assertEqual(order.sfya_corrected_total, 1100)
        correction = order.sfya_latest_correction_id
        self.assertEqual(correction.correction_type, 'price')
        self.assertEqual(correction.line_ids.old_price_unit, 1000)
        self.assertEqual(correction.line_ids.new_price_unit, 1100)
        self.assertEqual(self.env['account.move'].search_count([]), moves_before)

    def test_customer_and_price_correction(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)

        self._wizard(
            order, self.other_customer, price=1100,
        ).action_apply()

        self.assertEqual(order.partner_id, self.other_customer)
        self.assertEqual(invoice.partner_id, self.other_customer)
        self.assertEqual(invoice.amount_total, 1100)
        correction = order.sfya_latest_correction_id
        self.assertEqual(correction.correction_type, 'both')
        self.assertEqual(correction.line_ids.new_price_unit, 1100)

    def test_rejects_cash_payment_price_change(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        self.env['pos.payment'].create({
            'pos_order_id': order.id,
            'amount': 10.0,
            'payment_method_id': self.cash_pm1.id,
            'payment_date': fields.Datetime.now(),
        })

        with self.assertRaises(UserError):
            self._wizard(order, self.customer, price=1100).action_apply()

    def test_rejects_paid_invoice_price_change(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        self._mark_invoice(invoice, 'paid', 0.0)

        with self.assertRaises(UserError):
            self._wizard(order, self.customer, price=1100).action_apply()

    def test_quantity_correction_returns_excess_to_stock(self):
        order, invoice = self._stock_order(
            qty=400, unit_price=120, stock=400,
        )

        self._wizard(order, self.customer, qty=350).action_apply()

        invoice_line = invoice.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product'
        )
        self.assertEqual(invoice_line.quantity, 350)
        self.assertEqual(invoice.amount_total, 42000)
        self.assertEqual(order.lines[0].qty, 400)
        correction = order.sfya_latest_correction_id
        self.assertEqual(correction.correction_type, 'quantity')
        self.assertEqual(correction.line_ids.old_qty, 400)
        self.assertEqual(correction.line_ids.new_qty, 350)
        self.assertEqual(len(correction.stock_picking_ids), 1)
        self.assertEqual(correction.stock_picking_ids.state, 'done')
        self.assertEqual(
            self.env['stock.quant']._get_available_quantity(
                self.stock_product, self.stock_location,
            ),
            50,
        )

    def test_quantity_correction_increases_delivery(self):
        order, invoice = self._stock_order(
            qty=400, unit_price=120, stock=500,
        )

        self._wizard(order, self.customer, qty=450).action_apply()

        invoice_line = invoice.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product'
        )
        self.assertEqual(invoice_line.quantity, 450)
        self.assertEqual(invoice.amount_total, 54000)
        self.assertEqual(order.lines[0].qty, 400)
        correction = order.sfya_latest_correction_id
        self.assertEqual(correction.correction_type, 'quantity')
        self.assertEqual(len(correction.stock_picking_ids), 1)
        self.assertEqual(
            self.env['stock.quant']._get_available_quantity(
                self.stock_product, self.stock_location,
            ),
            50,
        )

    def test_quantity_correction_rejects_insufficient_stock(self):
        order, invoice = self._stock_order(
            qty=400, unit_price=120, stock=400,
        )

        with self.assertRaises(UserError):
            self._wizard(order, self.customer, qty=450).action_apply()

        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.amount_total, 48000)
        self.assertEqual(order.lines[0].qty, 400)

    def test_quantity_correction_stacks_after_price_correction(self):
        order, invoice = self._stock_order(
            qty=400, unit_price=120, stock=400,
        )

        self._wizard(order, self.customer, price=125).action_apply()
        self._wizard(order, self.customer, qty=350).action_apply()

        self.assertEqual(invoice.amount_total, 43750)
        self.assertEqual(order.sfya_correction_count, 2)
        self.assertEqual(
            self.env['stock.quant']._get_available_quantity(
                self.stock_product, self.stock_location,
            ),
            50,
        )

    def test_quantity_correction_rejects_lot_tracked_product(self):
        product = self.stock_product.copy({
            'name': 'Correction lot product',
            'tracking': 'lot',
        })
        order = self._order(
            self.customer, amount=400, product=product, qty=4,
            unit_price=100,
        )
        invoice = self._invoice(
            self.customer, amount=400, product=product, qty=4,
            unit_price=100,
        )
        self._link(order, invoice)

        with self.assertRaises(UserError):
            self._wizard(order, self.customer, qty=3).action_apply()

    def test_rejects_reversed_invoice(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        invoice._reverse_moves([{
            'invoice_date': fields.Date.today(),
        }])

        with self.assertRaises(UserError):
            self._wizard(order, self.other_customer).action_apply()

    def test_rejects_partial_invoice_customer_change(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        self._mark_invoice(invoice, 'partial', 500.0)

        with self.assertRaises(UserError):
            self._wizard(order, self.other_customer).action_apply()

    def test_rejects_cash_payment_customer_change(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        self.env['pos.payment'].create({
            'pos_order_id': order.id,
            'amount': 10.0,
            'payment_method_id': self.cash_pm1.id,
            'payment_date': fields.Datetime.now(),
        })

        with self.assertRaises(UserError):
            self._wizard(order, self.other_customer).action_apply()

    def test_rejects_refunded_pos_line(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        self._order(
            self.customer, -1000, state='paid',
            refunded_line=order.lines[0],
        )
        self.assertEqual(order.lines[0].refunded_qty, 1)

        with self.assertRaises(UserError):
            self._wizard(order, self.other_customer).action_apply()

    def test_rejects_multi_order_invoice(self):
        first = self._order(self.customer, 1000)
        second = self._order(self.customer, 2000)
        invoice = self._invoice(self.other_customer, 3000)
        self._link(first, invoice)
        self._link(second, invoice)

        with self.assertRaises(UserError):
            self._wizard(first, self.other_customer).action_apply()

    def test_rejects_wrong_total(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1001)
        self._link(order, invoice)

        with self.assertRaises(UserError):
            self._wizard(order, self.other_customer).action_apply()

    def test_rejects_unauthorized_user(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        user = self.env['res.users'].with_context(
            no_reset_password=True,
        ).create({
            'name': 'POS manager without correction',
            'login': 'pos_manager_no_correction',
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'groups_id': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_manager').id,
            ])],
        })
        wizard = self._wizard(order, self.other_customer)

        with self.assertRaises((AccessError, UserError)):
            wizard.with_user(user).action_apply()

    def test_rejects_empty_reason(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)

        with self.assertRaises(UserError):
            self._wizard(
                order, self.other_customer, reason='   ',
            ).action_apply()

    def test_blocks_posted_invoice_partner_write(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)

        with self.assertRaises(UserError):
            invoice.write({'partner_id': self.other_customer.id})

    def test_blocks_posted_receivable_line_partner_write(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        receivable = invoice.line_ids.filtered(
            lambda line: line.account_id.account_type == 'asset_receivable'
        )

        with self.assertRaises(UserError):
            receivable.write({'partner_id': self.other_customer.id})

    def test_correction_audit_is_append_only(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        self._wizard(order, self.other_customer).action_apply()
        correction = self.env['sfya.pos.correction'].search([
            ('order_id', '=', order.id),
        ])

        with self.assertRaises(UserError):
            correction.write({'reason': 'changed'})
        with self.assertRaises(UserError):
            correction.unlink()
        with self.assertRaises(UserError):
            correction.copy()

    def test_no_changes_to_order_lines_or_payments(self):
        order = self._order(self.customer, 1000)
        invoice = self._invoice(self.customer, 1000)
        self._link(order, invoice)
        line_values = order.lines.read(['qty', 'price_unit'])
        payment_values = order.payment_ids.read(['amount'])

        self._wizard(order, self.other_customer).action_apply()

        self.assertEqual(order.lines.read(['qty', 'price_unit']), line_values)
        self.assertEqual(order.payment_ids.read(['amount']), payment_values)
