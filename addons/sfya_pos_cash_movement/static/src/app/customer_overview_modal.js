/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { CashMovementModal } from "./cash_movement_modal";

export class CustomerOverviewModal extends Component {
    static template = "sfya_pos_cash_movement.CustomerOverviewModal";
    static components = { Dialog };
    static props = {
        close: Function,
    };

    setup() {
        this.pos = useService("pos");
        this.state = useState({
            tab: "balances",
            balances: [],
            collections: [],
            dateFrom: this._defaultFrom(),
            dateTo: this._todayStr(),
            loading: true,
            error: "",
        });
        onWillStart(() => this._loadAll());
    }

    _todayStr() {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    }

    _defaultFrom() {
        const d = new Date();
        d.setDate(d.getDate() - 15);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    }

    async _loadAll() {
        this.state.loading = true;
        this.state.error = "";
        try {
            const [balances, collections] = await Promise.all([
                this.pos.data.call("res.partner", "get_customer_balances", []),
                this.pos.data.call("account.payment", "get_recent_collections", [], {
                    date_from: this.state.dateFrom,
                    date_to: this.state.dateTo,
                }),
            ]);
            this.state.balances = balances || [];
            this.state.collections = collections || [];
        } catch (e) {
            this.state.error = e?.data?.message || e?.message || _t("Failed to load data.");
        }
        this.state.loading = false;
    }

    async refreshCollections() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.collections = await this.pos.data.call(
                "account.payment", "get_recent_collections", [],
                { date_from: this.state.dateFrom, date_to: this.state.dateTo },
            ) || [];
        } catch (e) {
            this.state.error = e?.data?.message || e?.message || _t("Failed to load collections.");
        }
        this.state.loading = false;
    }

    setTab(tab) {
        this.state.tab = tab;
    }

    collectFromPartner(row) {
        if (!row.partner_id) return;
        this.props.close();
        this.pos.dialog.add(CashMovementModal, {
            mode: "collect",
            initialPartner: { id: row.partner_id, name: row.partner_name },
        });
    }
}
