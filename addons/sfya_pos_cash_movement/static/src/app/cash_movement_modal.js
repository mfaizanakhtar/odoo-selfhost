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
        mode: { type: String, validate: (v) => ["collect", "payout", "drawing", "transfer", "salary_advance", "salary_payment"].includes(v) },
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
            fromJournalId: null,
            toJournalId: null,
            employeeId: null,
            employees: [],
            advanceOffset: "0",
            outstandingAdvance: 0,
            amount: "",
            memo: "",
            date: this._todayStr(),
            print: false,
            submitting: false,
            error: "",
            destination: "journal", // "journal" | "partner" (payout mode only)
            fundingPartner: null,
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
                    if (this.props.mode === "transfer") {
                        this.state.fromJournalId = this.state.journals[0].id;
                        this.state.toJournalId = this.state.journals.length > 1
                            ? this.state.journals[1].id
                            : null;
                    }
                } else {
                    this.state.error = _t("No cash or bank journal configured for this company.");
                }
            } catch (e) {
                this.state.error = e?.data?.message || e?.message || _t("Failed to load accounts.");
            }
            if (this.props.mode === "salary_advance" || this.props.mode === "salary_payment") {
                try {
                    const employees = await this.pos.data.call(
                        "pos.session",
                        "get_sfya_pos_employees",
                        [],
                        { session_id: this.pos.session.id },
                    );
                    this.state.employees = employees || [];
                    if (this.state.employees.length > 0) {
                        this.state.employeeId = this.state.employees[0].id;
                        if (this.props.mode === "salary_payment") {
                            await this._fetchOutstandingAdvance();
                        }
                    } else if (!this.state.error) {
                        this.state.error = _t("No employees configured for this company.");
                    }
                } catch (e) {
                    this.state.error = e?.data?.message || e?.message || _t("Failed to load employees.");
                }
            }
        });
    }

    get title() {
        if (this.props.mode === "collect") return _t("Collect Payment");
        if (this.props.mode === "drawing") return _t("Partner Drawing");
        if (this.props.mode === "transfer") return _t("Transfer Funds");
        if (this.props.mode === "salary_advance") return _t("Salary Advance");
        if (this.props.mode === "salary_payment") return _t("Pay Salary");
        return _t("Pay Out");
    }

    get confirmLabel() {
        if (this.props.mode === "collect") return _t("Collect");
        if (this.props.mode === "drawing") return _t("Record Drawing");
        if (this.props.mode === "transfer") return _t("Transfer");
        if (this.props.mode === "salary_advance") return _t("Give Advance");
        if (this.props.mode === "salary_payment") return _t("Pay Salary");
        return _t("Pay Out");
    }

    get confirmClass() {
        if (this.props.mode === "collect") return "btn-success";
        if (this.props.mode === "drawing") return "btn-info";
        if (this.props.mode === "transfer") return "btn-primary";
        if (this.props.mode === "salary_advance") return "btn-info";
        if (this.props.mode === "salary_payment") return "btn-warning";
        return "btn-warning";
    }

    get canUsePartnerDestination() {
        return this.props.mode === "payout";
    }

    get isPartnerDestination() {
        return this.canUsePartnerDestination && this.state.destination === "partner";
    }

    get isValid() {
        const amt = parseFloat(this.state.amount);
        if (!Number.isFinite(amt) || amt <= 0 || this.state.submitting) {
            return false;
        }
        if (this.props.mode === "transfer") {
            return (
                !!this.state.fromJournalId &&
                !!this.state.toJournalId &&
                this.state.fromJournalId !== this.state.toJournalId
            );
        }
        if (this.props.mode === "salary_advance") {
            return !!this.state.employeeId && !!this.state.journal_id;
        }
        if (this.props.mode === "salary_payment") {
            const offset = parseFloat(this.state.advanceOffset || 0);
            return (
                !!this.state.employeeId &&
                !!this.state.journal_id &&
                Number.isFinite(offset) &&
                offset >= 0 &&
                offset <= this.state.outstandingAdvance &&
                offset <= amt
            );
        }
        if (!this.state.partner) {
            return false;
        }
        if (this.isPartnerDestination) {
            return !!this.state.fundingPartner && this.state.fundingPartner.id !== this.state.partner.id;
        }
        return !!this.state.journal_id;
    }

    get selectedJournalIsBank() {
        const j = this.state.journals.find((x) => x.id === this.state.journal_id);
        return j?.type === "bank";
    }

    get eitherJournalIsBank() {
        const from = this.state.journals.find((x) => x.id === this.state.fromJournalId);
        const to = this.state.journals.find((x) => x.id === this.state.toJournalId);
        return from?.type === "bank" || to?.type === "bank";
    }

    get netToPay() {
        const amt = parseFloat(this.state.amount) || 0;
        const offset = parseFloat(this.state.advanceOffset) || 0;
        return Math.max(0, amt - offset);
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

    async pickFundingPartner() {
        const partner = await makeAwaitable(
            this.pos.dialog,
            PartnerList,
            this.state.fundingPartner ? { partner: this.state.fundingPartner } : {},
        );
        if (!partner) return;
        if (this.state.partner && partner.id === this.state.partner.id) {
            this.state.error = _t("Funding partner must be different from the recipient partner.");
            return;
        }
        this.state.fundingPartner = partner;
        this.state.error = "";
    }

    async _fetchOutstandingAdvance() {
        try {
            this.state.outstandingAdvance = await this.pos.data.call(
                "account.payment",
                "get_sfya_salary_advance_balance",
                [],
                { employee_id: this.state.employeeId },
            );
        } catch (e) {
            this.state.outstandingAdvance = 0;
        }
    }

    async onEmployeeChange(ev) {
        this.state.employeeId = parseInt(ev.target.value, 10);
        this.state.error = "";
        if (this.props.mode === "salary_payment") {
            this.state.advanceOffset = "0";
            await this._fetchOutstandingAdvance();
        }
    }

    async confirm() {
        if (!this.isValid) return;
        this.state.submitting = true;
        this.state.error = "";
        const sessionId = this.pos.session.id;
        const amount = parseFloat(this.state.amount);
        const memo = this.state.memo || "";

        if (this.props.mode === "transfer") {
            try {
                const kwargs = {
                    session_id: sessionId,
                    from_journal_id: this.state.fromJournalId,
                    to_journal_id: this.state.toJournalId,
                    amount,
                    memo,
                };
                if (this.eitherJournalIsBank) kwargs.date = this.state.date;
                const result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_internal_transfer",
                    [],
                    kwargs,
                );
                this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
                this.pos.sfyaCashMovements.push(result);
                this.notification.add(
                    _t("Transferred %s from %s to %s", result.amount, result.from_journal_name, result.to_journal_name),
                    { type: "success" },
                );
                if (this.state.print) {
                    await this._printSlip({
                        direction: "internal_transfer",
                        name: `${result.out_name} / ${result.in_name}`,
                        from_journal_name: result.from_journal_name,
                        to_journal_name: result.to_journal_name,
                        amount: result.amount,
                        memo: result.memo,
                    });
                }
                this.props.close();
            } catch (e) {
                this.state.error = e?.data?.message || e?.message || _t("Failed to record transfer.");
                this.state.submitting = false;
            }
            return;
        }

        if (this.props.mode === "salary_advance") {
            try {
                const kwargs = {
                    session_id: sessionId,
                    employee_id: this.state.employeeId,
                    amount,
                    journal_id: this.state.journal_id,
                    memo,
                };
                if (this.selectedJournalIsBank) kwargs.date = this.state.date;
                const result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_salary_advance",
                    [],
                    kwargs,
                );
                this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
                this.pos.sfyaCashMovements.push(result);
                this.notification.add(
                    _t("Advance of %s given to %s", result.amount, result.employee_name),
                    { type: "success" },
                );
                if (this.state.print) {
                    await this._printSlip({
                        direction: "salary_advance",
                        name: result.name,
                        employee_name: result.employee_name,
                        amount: result.amount,
                        memo: result.memo,
                    });
                }
                this.props.close();
            } catch (e) {
                this.state.error = e?.data?.message || e?.message || _t("Failed to record advance.");
                this.state.submitting = false;
            }
            return;
        }

        if (this.props.mode === "salary_payment") {
            try {
                const advanceOffset = parseFloat(this.state.advanceOffset || 0);
                const kwargs = {
                    session_id: sessionId,
                    employee_id: this.state.employeeId,
                    gross_amount: amount,
                    advance_offset: advanceOffset,
                    journal_id: this.state.journal_id,
                    memo,
                };
                if (this.selectedJournalIsBank) kwargs.date = this.state.date;
                const result = await this.pos.data.call(
                    "account.payment",
                    "sfya_pos_salary_payment",
                    [],
                    kwargs,
                );
                this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
                this.pos.sfyaCashMovements.push(result);
                this.notification.add(
                    result.advance_offset > 0
                        ? _t("Paid %s salary to %s (net %s after %s advance offset)", result.gross_amount, result.employee_name, result.net_cash, result.advance_offset)
                        : _t("Paid %s salary to %s", result.gross_amount, result.employee_name),
                    { type: "success" },
                );
                if (this.state.print) {
                    await this._printSlip({
                        direction: "salary_payment",
                        name: result.payment_name || result.move_name,
                        employee_name: result.employee_name,
                        amount: result.gross_amount,
                        gross_amount: result.gross_amount,
                        advance_offset: result.advance_offset,
                        net_cash: result.net_cash,
                        memo: result.memo,
                    });
                }
                this.props.close();
            } catch (e) {
                this.state.error = e?.data?.message || e?.message || _t("Failed to record salary payment.");
                this.state.submitting = false;
            }
            return;
        }

        const partnerId = this.state.partner.id;
        const journalId = this.state.journal_id;
        const dateVal = this.isPartnerDestination
            ? undefined
            : this.selectedJournalIsBank ? this.state.date : undefined;
        try {
            let result;
            if (this.isPartnerDestination) {
                const kwargs = {
                    session_id: sessionId,
                    from_partner_id: this.state.fundingPartner.id,
                    to_partner_id: partnerId,
                    amount,
                    memo,
                };
                result = await this.pos.data.call(
                    "account.move",
                    "sfya_pos_partner_transfer",
                    [],
                    kwargs,
                );
                this.pos.sfyaCashMovements = this.pos.sfyaCashMovements || [];
                this.pos.sfyaCashMovements.push(result);
                this.notification.add(
                    _t("Paid %s to %s, funded by %s", result.amount, result.to_partner_name, result.from_partner_name),
                    { type: "success" },
                );
                if (this.state.print) {
                    await this._printSlip({
                        direction: "transfer",
                        name: result.name,
                        partner_name: result.to_partner_name,
                        funding_partner_name: result.from_partner_name,
                        amount: result.amount,
                        memo: result.memo,
                        date: new Date().toLocaleString(),
                        cashier: this.pos.get_cashier()?.name || "",
                    });
                }
                this.props.close();
                return;
            }
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
                    funding_partner_name: result.funding_partner_name || "",
                    from_journal_name: result.from_journal_name || "",
                    to_journal_name: result.to_journal_name || "",
                    employee_name: result.employee_name || "",
                    gross_amount: result.gross_amount || 0,
                    advance_offset: result.advance_offset || 0,
                    net_cash: result.net_cash != null ? result.net_cash : (result.amount || 0),
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
