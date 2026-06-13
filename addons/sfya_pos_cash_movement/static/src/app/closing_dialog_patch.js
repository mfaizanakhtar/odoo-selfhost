/** @odoo-module **/

/**
 * Patch ClosePosPopup (Odoo 18 closing popup) with SFYA cash movement sections.
 *
 * Step 1 findings:
 *  - Component class: ClosePosPopup (NOT ClosingPosDialog)
 *  - Template name: point_of_sale.ClosePosPopup
 *  - Import path: @point_of_sale/app/navbar/closing_popup/closing_popup
 *  - this.pos is available directly from usePos() in setup()
 *  - Expected cash is props.default_cash_details.amount (a prop, NOT a getter)
 *    getDifference() = parseFloat(counted) - props.default_cash_details.amount
 *  - Expected-cash adjustment (collects_total - payouts_total) is applied on the
 *    Python side by overriding get_closing_control_data() in pos_session.py, so
 *    props.default_cash_details.amount already includes the SFYA movements.
 */

import { patch } from "@web/core/utils/patch";
import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { onWillStart, useState } from "@odoo/owl";

patch(ClosePosPopup.prototype, {
    setup() {
        super.setup();
        this.sfya = useState({
            collects: [],
            collects_total: 0,
            payouts: [],
            payouts_total: 0,
            collectsOpen: true,
            payoutsOpen: true,
            loaded: false,
        });
        onWillStart(async () => {
            try {
                const data = await this.pos.data.call(
                    "pos.session",
                    "get_sfya_cash_movements",
                    [[this.pos.session.id]],
                );
                Object.assign(this.sfya, data, { loaded: true });
            } catch (e) {
                console.warn("[SFYA] Failed to load cash movements:", e);
                this.sfya.loaded = true;
            }
        });
    },

    /**
     * Net adjustment for display purposes (informational label in template).
     * The actual expected-cash amount is already corrected by the Python override.
     */
    get sfyaExpectedAdjustment() {
        return (this.sfya.collects_total || 0) - (this.sfya.payouts_total || 0);
    },
});
