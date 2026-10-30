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
            tagOptions: [],
            selectedTagId: null,
            appliedTagId: undefined,
            appliedDateFrom: null,
            appliedDateTo: null,
            dateFrom: this._defaultFrom(),
            dateTo: this._todayStr(),
            loading: true,
            error: "",
        });
        this._requestId = 0;
        this._tagsLoaded = false;
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
        const requestId = ++this._requestId;
        const tagId = this.state.selectedTagId;
        const dateFrom = this.state.dateFrom;
        const dateTo = this.state.dateTo;
        this.state.loading = true;
        this.state.error = "";
        try {
            const [balances, collections, tagOptions] = await Promise.all([
                this.pos.data.call("res.partner", "get_customer_balances", [], {
                    tag_id: tagId,
                }),
                this.pos.data.call("account.payment", "get_recent_collections", [], {
                    date_from: dateFrom,
                    date_to: dateTo,
                    tag_id: tagId,
                }),
                this._tagsLoaded
                    ? Promise.resolve(this.state.tagOptions)
                    : this.pos.data.call("res.partner", "get_customer_overview_tags", []),
            ]);
            if (requestId !== this._requestId) return;
            this.state.balances = balances || [];
            this.state.collections = collections || [];
            this.state.tagOptions = tagOptions || [];
            this._tagsLoaded = true;
            this.state.appliedTagId = tagId;
            this.state.appliedDateFrom = dateFrom;
            this.state.appliedDateTo = dateTo;
        } catch (e) {
            if (requestId !== this._requestId) return;
            this.state.balances = [];
            this.state.collections = [];
            this.state.appliedTagId = undefined;
            this.state.appliedDateFrom = null;
            this.state.appliedDateTo = null;
            this.state.error = e?.data?.message || e?.message || _t("Failed to load data.");
        } finally {
            if (requestId === this._requestId) this.state.loading = false;
        }
    }

    async onTagChange(event) {
        const value = event.target.value;
        this.state.selectedTagId = value ? Number(value) : null;
        await this._loadAll();
    }

    async refreshCollections() {
        // Recover both datasets if the selected tag has not loaded successfully.
        if (this.state.selectedTagId !== this.state.appliedTagId) {
            return this._loadAll();
        }
        const requestId = ++this._requestId;
        const tagId = this.state.selectedTagId;
        const dateFrom = this.state.dateFrom;
        const dateTo = this.state.dateTo;
        this.state.loading = true;
        this.state.error = "";
        try {
            const collections = await this.pos.data.call(
                "account.payment", "get_recent_collections", [],
                { date_from: dateFrom, date_to: dateTo, tag_id: tagId },
            );
            if (requestId !== this._requestId) return;
            this.state.collections = collections || [];
            this.state.appliedDateFrom = dateFrom;
            this.state.appliedDateTo = dateTo;
        } catch (e) {
            if (requestId !== this._requestId) return;
            this.state.collections = [];
            this.state.appliedDateFrom = null;
            this.state.appliedDateTo = null;
            this.state.error = e?.data?.message || e?.message || _t("Failed to load collections.");
        } finally {
            if (requestId === this._requestId) this.state.loading = false;
        }
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
