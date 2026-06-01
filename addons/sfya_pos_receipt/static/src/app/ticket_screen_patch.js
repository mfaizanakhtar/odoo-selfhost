import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

patch(TicketScreen.prototype, {
    async reprintOrder(order) {
        await this.pos.printReceipt({ order });
    },
});
