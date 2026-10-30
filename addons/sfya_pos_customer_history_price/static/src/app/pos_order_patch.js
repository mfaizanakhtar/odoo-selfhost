/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { applyCustomerHistoryPrices } from "./history_price_service";

patch(PosOrder.prototype, {
    set_partner(partner) {
        const result = super.set_partner(partner);
        const posStore = this.models["pos.order"]._sfyaPosStore;
        if (posStore) {
            applyCustomerHistoryPrices(posStore, this);
        }
        return result;
    },
});
