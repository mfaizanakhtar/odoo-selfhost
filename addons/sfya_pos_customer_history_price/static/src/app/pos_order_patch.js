/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { applyCustomerHistoryPrices } from "./history_price_service";

patch(PosOrder.prototype, {
    set_pricelist(pricelist) {
        const result = super.set_pricelist(pricelist);
        const posStore = this.models["pos.order"]._sfyaPosStore;
        if (posStore && this.partner_id) {
            applyCustomerHistoryPrices(posStore, this);
        }
        return result;
    },

    set_partner(partner) {
        const result = super.set_partner(partner);
        const posStore = this.models["pos.order"]._sfyaPosStore;
        if (posStore) {
            applyCustomerHistoryPrices(posStore, this);
        }
        return result;
    },
});
