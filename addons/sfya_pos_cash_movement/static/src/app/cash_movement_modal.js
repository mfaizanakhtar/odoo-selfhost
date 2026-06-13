/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";

export class CashMovementModal extends Component {
    static template = "sfya_pos_cash_movement.CashMovementModal";
    static components = { Dialog };
    static props = {
        mode: { type: String, validate: (v) => ["collect", "payout"].includes(v) },
        close: Function,
    };

    setup() {
        this.pos = useService("pos");
        this.notification = useService("notification");
        this.state = useState({
            partner: null,
            amount: "",
            memo: "",
            print: false,
            submitting: false,
            error: "",
        });
    }

    get title() {
        return this.props.mode === "collect" ? _t("Collect Payment") : _t("Pay Out");
    }

    get confirmLabel() {
        return this.props.mode === "collect" ? _t("Collect") : _t("Pay Out");
    }

    get confirmClass() {
        return this.props.mode === "collect" ? "btn-success" : "btn-warning";
    }

    get isValid() {
        const amt = parseFloat(this.state.amount);
        return !!this.state.partner && Number.isFinite(amt) && amt > 0 && !this.state.submitting;
    }

    async pickPartner() {
        const partner = await makeAwaitable(
            this.pos.dialog,
            PartnerList,
            this.state.partner ? { partner: this.state.partner } : {},
        );
        if (!partner) return;
        if (this.props.mode === "payout" && !partner.supplier_rank) {
            this.state.error = _t("Pay Out is only allowed for vendors.");
            return;
        }
        this.state.partner = partner;
        this.state.error = "";
    }

    async confirm() {
        if (!this.isValid) return;
        this.state.submitting = true;
        this.state.error = "";
        const rpcName = this.props.mode === "collect" ? "sfya_pos_collect" : "sfya_pos_payout";
        try {
            const result = await this.pos.data.call(
                "account.payment",
                rpcName,
                [],
                {
                    session_id: this.pos.session.id,
                    partner_id: this.state.partner.id,
                    amount: parseFloat(this.state.amount),
                    memo: this.state.memo || "",
                },
            );
            this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
            this.pos.sfyaCashMovements.push(result);
            this.notification.add(
                this.props.mode === "collect"
                    ? _t("Collected %s from %s", result.amount, result.partner_name)
                    : _t("Paid %s to %s", result.amount, result.partner_name),
                { type: "success" },
            );
            if (this.state.print) {
                await this._printSlip(result);
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
