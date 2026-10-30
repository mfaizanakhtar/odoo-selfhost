/** @odoo-module **/

function eligibleLines(posStore, order) {
    const tipProductId = posStore.config.tip_product_id?.id;
    return order.lines.filter(
        (line) =>
            line.get_quantity() > 0 &&
            !line.refunded_orderline_id &&
            !line.combo_parent_id &&
            !line.combo_line_ids?.length &&
            !line.product_id.isCombo?.() &&
            line.product_id.id !== tipProductId
    );
}

function restorePricelistPrice(order, line) {
    line.price_type = "original";
    line.set_unit_price(
        line.product_id.get_price(
            order.pricelist_id,
            line.get_quantity(),
            line.get_price_extra()
        )
    );
}

// Missing history is represented by null; transport failures never enter the cache.
function cacheKey(sessionId, partnerId, productId, pricelistId) {
    return JSON.stringify([sessionId, partnerId, productId, pricelistId]);
}

export function applyCustomerHistoryPrices(posStore, order) {
    const revision = (order._sfyaPricingRevision || 0) + 1;
    order._sfyaPricingRevision = revision;
    const partnerId = order.partner_id?.id;
    const pricelistId = order.pricelist_id?.id || false;
    const sessionId = posStore.session.id;
    const isCurrent = () =>
        order._sfyaPricingRevision === revision &&
        order.partner_id?.id === partnerId &&
        (order.pricelist_id?.id || false) === pricelistId &&
        posStore.session.id === sessionId &&
        !order.finalized;

    if (!partnerId) {
        // Customer clearing must take effect before returning to the cashier.
        for (const line of eligibleLines(posStore, order)) {
            restorePricelistPrice(order, line);
        }
        order._sfyaPricePromise = Promise.resolve();
        return order._sfyaPricePromise;
    }

    // Coalesce same-turn additions/customer changes into one latest-revision batch.
    const promise = Promise.resolve().then(async () => {
        if (!isCurrent()) {
            return;
        }
        const lines = eligibleLines(posStore, order);
        const productIds = [...new Set(lines.map((line) => line.product_id.id))];
        const cache = posStore._sfyaHistoryPriceCache;
        const key = (id) => cacheKey(sessionId, partnerId, id, pricelistId);
        const missingIds = productIds.filter((id) => !cache.has(key(id)));
        let failed = false;
        if (missingIds.length) {
            try {
                const prices = await posStore.data.call(
                    "res.partner", "get_pos_customer_history_prices", [],
                    { partner_id: partnerId, product_ids: missingIds, pricelist_id: pricelistId }
                );
                if (!isCurrent()) {
                    return;
                }
                for (const id of missingIds) {
                    const price = prices[String(id)];
                    cache.set(key(id), typeof price === "number" && Number.isFinite(price) ? price : null);
                }
            } catch {
                // Fall back for this whole refresh, including any already cached products.
                failed = true;
            }
        }
        if (!isCurrent()) {
            return;
        }
        // Re-read live lines: removed/refunded/combo lines must not be mutated after the RPC.
        for (const line of eligibleLines(posStore, order)) {
            const price = failed ? null : cache.get(key(line.product_id.id));
            if (typeof price === "number") {
                line.set_unit_price(price);
                line.price_type = "manual";
            } else {
                restorePricelistPrice(order, line);
            }
        }
    });
    order._sfyaPricePromise = promise;
    return promise;
}

export async function waitForCustomerHistoryPrices(order) {
    // A customer/product change while awaiting may have replaced the active request.
    let pending;
    do {
        pending = order._sfyaPricePromise;
        await pending;
    } while (pending !== order._sfyaPricePromise);
}

export function evictCustomerHistoryPrices(posStore, order) {
    const partnerId = order.partner_id?.id;
    const productIds = new Set(order.lines.map((line) => line.product_id.id));
    for (const key of posStore._sfyaHistoryPriceCache.keys()) {
        const [sessionId, cachedPartnerId, productId] = JSON.parse(key);
        if (sessionId === posStore.session.id && cachedPartnerId === partnerId && productIds.has(productId)) {
            posStore._sfyaHistoryPriceCache.delete(key);
        }
    }
}
