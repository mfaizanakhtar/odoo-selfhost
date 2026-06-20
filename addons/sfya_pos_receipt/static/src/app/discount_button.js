/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { DiscountPopup } from "./discount_popup";

patch(ControlButtons.prototype, {
    openDiscountPopup() {
        this.dialog.add(DiscountPopup, {});
    },
});
