/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";

export class CashMovementModal extends Component {
    static template = "sfya_pos_cash_movement.CashMovementModal";
    static components = { Dialog };
    static props = {
        mode: { type: String, validate: (v) => ["collect", "payout", "drawing"].includes(v) },
        initialPartner: { type: Object, optional: true },
        close: Function,
    };

    setup() {
        this.pos = useService("pos");
        this.notification = useService("notification");
        this.state = useState({
            partner: this.props.initialPartner || null,
            journal_id: null,
            journals: [],
            amount: "",
            memo: "",
            date: this._todayStr(),
            print: false,
            submitting: false,
            error: "",
        });
        onWillStart(async () => {
            try {
                const journals = await this.pos.data.call(
                    "pos.session",
                    "get_sfya_allowed_journals",
                    [],
                    { session_id: this.pos.session.id },
                );
                this.state.journals = journals || [];
                if (this.state.journals.length > 0) {
                    this.state.journal_id = this.state.journals[0].id;
                } else {
                    this.state.error = _t("No cash or bank journal configured for this company.");
                }
            } catch (e) {
                this.state.error = e?.data?.message || e?.message || _t("Failed to load accounts.");
            }
        });
    }

    get title() {
        if (this.props.mode === "collect") return _t("Collect Payment");
        if (this.props.mode === "drawing") return _t("Partner Drawing");
        return _t("Pay Out");
    }

    get confirmLabel() {
        if (this.props.mode === "collect") return _t("Collect");
        if (this.props.mode === "drawing") return _t("Record Drawing");
        return _t("Pay Out");
    }

    get confirmClass() {
        if (this.props.mode === "collect") return "btn-success";
        if (this.props.mode === "drawing") return "btn-info";
        return "btn-warning";
    }

    get isValid() {
        const amt = parseFloat(this.state.amount);
        return (
            !!this.state.partner &&
            !!this.state.journal_id &&
            Number.isFinite(amt) && amt > 0 &&
            !this.state.submitting
        );
    }

    get selectedJournalIsBank() {
        const j = this.state.journals.find((x) => x.id === this.state.journal_id);
        return j?.type === "bank";
    }

    get todayStr() {
        return this._todayStr();
    }

    _todayStr() {
        const d = new Date();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return `${d.getFullYear()}-${m}-${day}`;
    }

    async pickPartner() {
        const partner = await makeAwaitable(
            this.pos.dialog,
            PartnerList,
            this.state.partner ? { partner: this.state.partner } : {},
        );
        if (!partner) return;
        this.state.partner = partner;
        this.state.error = "";
    }

    async confirm() {
        if (!this.isValid) return;
        this.state.submitting = true;
        this.state.error = "";
        const sessionId = this.pos.session.id;
        const partnerId = this.state.partner.id;
        const amount = parseFloat(this.state.amount);
        const journalId = this.state.journal_id;
        const memo = this.state.memo || "";
        const dateVal = this.selectedJournalIsBank ? this.state.date : undefined;
        try {
            let result;
            if (this.props.mode === "drawing") {
                const kwargs = {
                    session_id: sessionId,
                    partner_id: partnerId,
                    amount,
                    journal_id: journalId,
                    memo,
                };
                if (dateVal !== undefined) kwargs.date = dateVal;
                result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_partner_drawing",
                    [],
                    kwargs,
                );
            } else if (this.props.mode === "collect") {
                const kwargs = {
                    session_id: sessionId,
                    partner_id: partnerId,
                    amount,
                    journal_id: journalId,
                    memo,
                };
                if (dateVal !== undefined) kwargs.date = dateVal;
                result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_collect",
                    [],
                    kwargs,
                );
            } else {
                const kwargs = {
                    session_id: sessionId,
                    partner_id: partnerId,
                    amount,
                    journal_id: journalId,
                    memo,
                };
                if (dateVal !== undefined) kwargs.date = dateVal;
                result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_payout",
                    [],
                    kwargs,
                );
            }
            this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
            this.pos.sfyaCashMovements.push(result);
            if (this.props.mode === "drawing") {
                this.notification.add(
                    _t("Drawing of %s recorded for %s", result.amount, result.partner_name),
                    { type: "success" },
                );
            } else {
                this.notification.add(
                    this.props.mode === "collect"
                        ? _t("Collected %s from %s", result.amount, result.partner_name)
                        : _t("Paid %s to %s", result.amount, result.partner_name),
                    { type: "success" },
                );
            }
            if (this.state.print) {
                const slipData = { ...result };
                if (this.props.mode === "drawing") slipData.direction = "drawing";
                await this._printSlip(slipData);
            }
            this.props.close();
        } catch (e) {
            this.state.error = e?.data?.message || e?.message || _t("Failed to record payment.");
            this.state.submitting = false;
        }
    }

    async _printSlip(result) {
        try {
            await this.pos.printer.print(
                "sfya_pos_cash_movement.PaymentSlip",
                {
                    direction: result.direction,
                    name: result.name,
                    partner_name: result.partner_name,
                    amount: result.amount,
                    memo: result.memo,
                    date: new Date().toLocaleString(),
                    cashier: this.pos.get_cashier()?.name || "",
                },
            );
        } catch (e) {
            this.notification.add(_t("Payment recorded but print failed."), { type: "warning" });
        }
    }
}
