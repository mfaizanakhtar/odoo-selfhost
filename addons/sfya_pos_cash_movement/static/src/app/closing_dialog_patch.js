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
            cash: {
                collects: [],
                collects_total: 0,
                payouts: [],
                payouts_total: 0,
                drawings: [],
                drawings_total: 0,
            },
            banks: [],
            cashCollectsOpen: true,
            cashPayoutsOpen: true,
            drawingsOpen: true,
            banksOpen: {}, // journal_id -> boolean
            loaded: false,
            closeError: null,
        });
        onWillStart(async () => {
            try {
                const data = await this.pos.data.call(
                    "pos.session",
                    "get_sfya_cash_movements",
                    [[this.pos.session.id]],
                );
                if (data?.cash) {
                    Object.assign(this.sfya.cash, data.cash);
                }
                this.sfya.banks = data?.banks || [];
                for (const b of this.sfya.banks) {
                    this.sfya.banksOpen[b.journal_id] = true;
                }
                this.sfya.loaded = true;
            } catch (e) {
                console.warn("[SFYA] Failed to load cash movements:", e);
                this.sfya.loaded = true;
            }
        });
    },

    get sfyaCashAdjustment() {
        return (this.sfya.cash.collects_total || 0) - (this.sfya.cash.payouts_total || 0) - (this.sfya.cash.drawings_total || 0);
    },

    toggleSfyaBank(journalId) {
        this.sfya.banksOpen[journalId] = !this.sfya.banksOpen[journalId];
    },

    async closeSession() {
        try {
            const cashId = this.props.default_cash_details?.id;
            const counted = parseFloat(
                cashId != null ? (this.state.payments[cashId]?.counted || 0) : 0
            );
            const expected = this.props.default_cash_details?.amount || 0;
            const maxDiff = this.pos.config.sfya_max_cash_difference ?? 500;

            if (counted === 0) {
                this.sfya.closeError = "Please enter actual cash count before closing.";
                return;
            }
            const diff = Math.abs(counted - expected);
            if (maxDiff > 0 && diff > maxDiff) {
                this.sfya.closeError = `Cash difference of Rs ${diff.toFixed(0)} exceeds allowed limit of Rs ${maxDiff.toFixed(0)}. Please recount or adjust.`;
                return;
            }
            this.sfya.closeError = null;
        } catch (e) {
            // Defensive: never block close on internal guard failure.
            console.warn("[SFYA] close validation failed, falling through:", e);
            this.sfya.closeError = null;
        }
        return super.closeSession(...arguments);
    }
});
