import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { onWillStart } from "@odoo/owl";

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup();
        onWillStart(async () => {
            const order = this.currentOrder;
            if (!order || !order.partner_id) {
                return;
            }
            const onCredit = (order.payment_ids || [])
                .filter((p) => p.payment_method_id?.type === "pay_later")
                .reduce((s, p) => s + (p.amount || 0), 0);
            try {
                const val = await this.pos.data.call(
                    "res.partner",
                    "get_pos_prev_balance",
                    [],
                    {
                        partner_id: order.partner_id.id,
                        exclude_order_pay_later: onCredit,
                    }
                );
                order.prev_balance_cached = val ?? 0;
            } catch (e) {
                order.prev_balance_cached = 0;
            }
        });
    },
});
