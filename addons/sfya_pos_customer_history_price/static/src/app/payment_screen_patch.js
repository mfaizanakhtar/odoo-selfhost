/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { evictCustomerHistoryPrices, waitForCustomerHistoryPrices } from "./history_price_service";

patch(PaymentScreen.prototype, {
    async addNewPaymentLine(paymentMethod) {
        const order = this.currentOrder;
        await waitForCustomerHistoryPrices(order);
        if (this.currentOrder !== order) {
            return;
        }
        return super.addNewPaymentLine(paymentMethod);
    },

    async validateOrder(isForceValidate) {
        const order = this.currentOrder;
        await waitForCustomerHistoryPrices(order);
        if (this.currentOrder !== order) {
            return;
        }
        const result = await super.validateOrder(isForceValidate);
        // Upstream also returns undefined on rejected validation. Check the captured
        // order, as successful validation may already have selected the next order.
        if (["paid", "done", "invoiced"].includes(order.state) && typeof order.id === "number") {
            evictCustomerHistoryPrices(this.pos, order);
        }
        return result;
    },
});
