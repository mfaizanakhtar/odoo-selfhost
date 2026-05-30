import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

patch(PosOrder.prototype, {
    /**
     * Cashier name with employee fallback.
     * Upstream returns this.user_id?.name only.
     * We try employee_id first (when "Use Employees in POS" is enabled)
     * then fall back to user_id, then empty string.
     */
    getCashierName() {
        return this.employee_id?.name || this.user_id?.name || "";
    },

    /**
     * Extend printing payload with SFYA-specific fields.
     * Preserves all upstream fields; only adds new ones.
     */
    export_for_printing(baseUrl, headerData) {
        const data = super.export_for_printing(baseUrl, headerData);

        const total = this.get_total_with_tax();
        const paid = this.get_total_paid();
        const balanceDue = total - paid;

        let dateOnly = "";
        let timeOnly = "";
        if (this.date_order) {
            const d = new Date(this.date_order.replace(" ", "T") + "Z");
            const dd = String(d.getDate()).padStart(2, "0");
            const mm = String(d.getMonth() + 1).padStart(2, "0");
            const yyyy = d.getFullYear();
            dateOnly = `${dd}/${mm}/${yyyy}`;

            let h = d.getHours();
            const m = String(d.getMinutes()).padStart(2, "0");
            const ampm = h >= 12 ? "PM" : "AM";
            h = h % 12 || 12;
            timeOnly = `${String(h).padStart(2, "0")}:${m} ${ampm}`;
        }

        const totalQty = (this.lines || []).reduce(
            (sum, l) => sum + (l.qty || 0),
            0
        );

        return {
            ...data,
            partnerName: this.partner_id?.name || "",
            dateOnly,
            timeOnly,
            totalQty,
            balanceDue,
            invoiceNo: (this.pos_reference || "").replace(/^Order\s+/, "").trim(),
        };
    },
});
