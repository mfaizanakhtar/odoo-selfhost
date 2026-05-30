        if (floatIsZero(remaining, this.currency.decimal_places)) {
            return 0;
        }
        return roundPrecision(remaining, rounding, method);
    }

    export_for_printing(baseUrl, headerData) {
        const paymentlines = this.payment_ids
            .filter((p) => !p.is_change)
            .map((p) => p.export_for_printing());

        const taxTotals = this.taxTotals;

        const order_rounding = taxTotals.order_rounding;
        const order_change = -this.get_change();

        return {
            orderlines: this.getSortedOrderlines().map((l) =>
                omit(l.getDisplayData(), "internalNote")
            ),
            taxTotals: taxTotals,
            label_total: _t("TOTAL"),
            label_rounding: _t("Rounding"),
            label_change: _t("CHANGE"),
            label_discounts: _t("Discounts"),
            show_rounding: !floatIsZero(order_rounding, this.currency.decimal_places),
            order_rounding: order_rounding,
            show_change: !floatIsZero(order_change, this.currency.decimal_places) && this.finalized,
            order_change: order_change,
            paymentlines,
            amount_total: this.get_total_with_tax(),
            total_without_tax: this.get_total_without_tax(),
            amount_tax: this.get_total_tax(),
            total_paid: this.get_total_paid(),
            total_discount: this.get_total_discount(),
            tax_details: this.get_tax_details(),
            change: this.amount_return,
            name: this.pos_reference,
            generalNote: this.general_note || "",
            invoice_id: null, //TODO
            cashier: this.getCashierName(),
            date: formatDateTime(parseUTCString(this.date_order)),
            pos_qr_code:
                this.company.point_of_sale_use_ticket_qr_code &&
                this.finalized &&
                qrCodeSrc(`${baseUrl}/pos/ticket/`),
            ticket_code: this.ticket_code,
            base_url: baseUrl,
            footer: this.config.receipt_footer,
            // FIXME: isn't there a better way to handle this date?
            shippingDate: this.shipping_date && formatDate(DateTime.fromSQL(this.shipping_date)),
            headerData: {
                ...headerData,
                trackingNumber: this.tracking_number,
            },
            screenName: "ReceiptScreen",
        };
    }
    getCashierName() {
        return this.user_id?.name;
    }
    canPay() {
        return this.lines.length;
    }
    recomputeOrderData() {
        this.amount_paid = this.get_total_paid();
        this.amount_tax = this.get_total_tax();
        this.amount_total = this.get_total_with_tax();
        this.amount_return = this.get_change();
        this.lines.forEach((line) => {
            line.setLinePrice();
