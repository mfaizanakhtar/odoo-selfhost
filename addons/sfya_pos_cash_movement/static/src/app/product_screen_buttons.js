/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { CashMovementModal } from "./cash_movement_modal";

patch(ControlButtons.prototype, {
    openCollect() {
        this.dialog.add(CashMovementModal, { mode: "collect" });
    },
    openPayout() {
        this.dialog.add(CashMovementModal, { mode: "payout" });
    },
});
