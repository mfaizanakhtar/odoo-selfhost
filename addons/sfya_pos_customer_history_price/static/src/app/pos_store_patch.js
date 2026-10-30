/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { applyCustomerHistoryPrices, evictCustomerHistoryPrices } from "./history_price_service";

patch(PosStore.prototype, {
    async setup() {
        this._sfyaHistoryPriceCache = new Map();
        const result = await super.setup(...arguments);
        this.data.models["pos.order"]._sfyaPosStore = this;
        return result;
    },

    async postSyncAllOrders(orders) {
        const result = await super.postSyncAllOrders(...arguments);
        for (const order of orders) {
            if (["paid", "done", "invoiced"].includes(order.state)) {
                evictCustomerHistoryPrices(this, order);
            }
        }
        return result;
    },

    async addLineToCurrentOrder(vals, opts, configure) {
        const line = await super.addLineToCurrentOrder(vals, opts, configure);
        const order = line?.order_id;
        if (order?.partner_id) {
            applyCustomerHistoryPrices(this, order);
        }
        return line;
    },
});
