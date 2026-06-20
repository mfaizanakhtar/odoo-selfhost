/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

export class DiscountPopup extends Component {
    static template = "sfya_pos_receipt.DiscountPopup";
    static components = { Dialog };
    static props = {
        close: Function,
    };

    setup() {
        this.pos = useService("pos");
        const order = this.pos.get_order();
        const lines = order ? order.get_orderlines() : [];
        let initialPct = 0;
        if (lines.length) {
            const first = lines[0].discount || 0;
            const allSame = lines.every((l) => (l.discount || 0) === first);
            if (allSame) initialPct = first;
        }
        this.state = useState({
            mode: "%",
            value: initialPct ? String(initialPct) : "",
        });
    }

    get order() {
        return this.pos.get_order();
    }

    get orderTotal() {
        return this.order ? this.order.get_total_with_tax() : 0;
    }

    setMode(mode) {
        this.state.mode = mode;
    }

    get isValid() {
        if (this.state.value === "" || this.state.value === null) return true; // empty = reset to 0
        const v = parseFloat(this.state.value);
        return Number.isFinite(v) && v >= 0;
    }

    confirm() {
        if (!this.isValid) return;
        const order = this.order;
        if (!order) {
            this.props.close();
            return;
        }
        const raw = this.state.value === "" ? 0 : parseFloat(this.state.value);
        let pct = 0;
        if (this.state.mode === "%") {
            pct = Math.min(100, Math.max(0, raw));
        } else {
            const total = this.orderTotal;
            if (total > 0) {
                pct = Math.min(100, Math.max(0, (raw / total) * 100));
            }
        }
        order.get_orderlines().forEach((line) => {
            line.set_discount(pct);
        });
        this.props.close();
    }
}
