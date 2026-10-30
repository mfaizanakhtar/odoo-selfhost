// Run with: node --test addons/sfya_pos_customer_history_price/tests/history_price.test.mjs
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sourceUrl = new URL("../static/src/app/history_price_service.js", import.meta.url);
let service = { applyCustomerHistoryPrices: async () => {} };
try {
    service = await import(`data:text/javascript;base64,${Buffer.from(await readFile(sourceUrl)).toString("base64")}`);
} catch (error) {
    if (error.code !== "ENOENT") throw error;
}
const { applyCustomerHistoryPrices: apply } = service;
const deferred = () => {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
};
function fixture(call = async () => ({ "11": 120 })) {
    const calls = [];
    const pos = {
        session: { id: 7 }, config: { tip_product_id: { id: 99 } },
        _sfyaHistoryPriceCache: new Map(),
        data: { call: (...args) => { calls.push(args); return call(...args); } },
    };
    const order = { partner_id: { id: 1 }, pricelist_id: { id: 3 }, lines: [] };
    const add = (id = 11, extra = {}) => {
        const line = {
            product_id: { id, get_price: (pricelist, quantity, priceExtra) => pricelist.id * 10 + quantity + priceExtra },
            order_id: order, price_unit: 400, price_type: "manual", discount: 25,
            qty: 2, price_extra: 3,
            get_quantity() { return this.qty; }, get_price_extra() { return this.price_extra; },
            set_unit_price(price) { this.price_unit = price; }, ...extra,
        };
        order.lines.push(line);
        return line;
    };
    return { pos, order, add, calls };
}

test("history replaces manual price, batches variants, preserves discounts and free prices", async () => {
    const f = fixture(async () => ({ "11": 120, "12": 0 }));
    const a = f.add(); const b = f.add(12); f.add();
    await apply(f.pos, f.order);
    assert.equal(a.price_unit, 120); assert.equal(a.price_type, "manual");
    assert.equal(a.discount, 25); assert.equal(b.price_unit, 0);
    assert.deepEqual(f.calls, [["res.partner", "get_pos_customer_history_prices", [], {
        partner_id: 1, product_ids: [11, 12], pricelist_id: 3,
    }]]);
});
test("missing history restores quantity and extra aware pricelist price and caches misses", async () => {
    const f = fixture(async () => ({})); const line = f.add();
    await apply(f.pos, f.order); line.price_unit = 999;
    await apply(f.pos, f.order);
    assert.equal(line.price_unit, 35); assert.equal(line.price_type, "original");
    assert.equal(line.discount, 25); assert.equal(f.calls.length, 1);
});
test("transport failures restore pricing, resolve checkout promise and are retried", async () => {
    const f = fixture(async () => { throw new Error("offline"); }); const line = f.add();
    await apply(f.pos, f.order);
    assert.equal(line.price_unit, 35); assert.equal(line.price_type, "original");
    await apply(f.pos, f.order); assert.equal(f.calls.length, 2);
});
test("clearing customer restores synchronously and invalidates a delayed lookup", async () => {
    const pending = deferred(); const f = fixture(() => pending.promise); const line = f.add();
    const old = apply(f.pos, f.order); await Promise.resolve();
    f.order.partner_id = false;
    const clear = apply(f.pos, f.order);
    assert.equal(line.price_unit, 35); assert.equal(line.price_type, "original");
    pending.resolve({ "11": 120 }); await Promise.all([old, clear]);
    assert.equal(line.price_unit, 35);
});
test("late customer A response cannot overwrite B, even with a new active promise", async () => {
    const a = deferred(); const b = deferred();
    const f = fixture((model, method, args, kwargs) => kwargs.partner_id === 1 ? a.promise : b.promise);
    const line = f.add(); const old = apply(f.pos, f.order); await Promise.resolve();
    f.order.partner_id = { id: 2 }; const latest = apply(f.pos, f.order);
    assert.equal(f.order._sfyaPricePromise, latest);
    b.resolve({ "11": 160 }); await latest;
    a.resolve({ "11": 120 }); await old;
    assert.equal(line.price_unit, 160); assert.equal(f.order._sfyaPricingRevision, 2);
});
test("same turn product additions coalesce into one request", async () => {
    const f = fixture(async () => ({ "11": 120, "12": 130 }));
    f.add(); const first = apply(f.pos, f.order); f.add(12);
    const second = apply(f.pos, f.order); await Promise.all([first, second]);
    assert.equal(f.calls.length, 1);
    assert.deepEqual(f.calls[0][3].product_ids, [11, 12]);
});
test("refunds, combo roots/children and configured tip lines remain untouched", async () => {
    const f = fixture();
    const skipped = [f.add(11, { qty: -1 }), f.add(11, { refunded_orderline_id: { id: 9 } }),
        f.add(11, { combo_parent_id: { id: 8 } }), f.add(11, { combo_line_ids: [{}] }),
        f.add(99), f.add(11, { product_id: { id: 11, isCombo: () => true } })];
    const eligible = f.add(); await apply(f.pos, f.order);
    assert.equal(eligible.price_unit, 120);
    for (const line of skipped) { assert.equal(line.price_unit, 400); assert.equal(line.discount, 25); }
});
test("cache is separated by customer, product, pricelist and session", async () => {
    const f = fixture(); f.add(); await apply(f.pos, f.order); await apply(f.pos, f.order);
    f.order.partner_id = { id: 2 }; await apply(f.pos, f.order);
    f.order.pricelist_id = { id: 4 }; await apply(f.pos, f.order);
    f.pos.session.id = 8; await apply(f.pos, f.order);
    f.add(12); await apply(f.pos, f.order);
    assert.equal(f.calls.length, 5); assert.deepEqual(f.calls[4][3].product_ids, [12]);
});
test("completed-sale eviction refreshes the same customer's products in all pricelists", async () => {
    let price = 120; const f = fixture(async () => ({ "11": price })); const line = f.add();
    await apply(f.pos, f.order);
    f.order.pricelist_id = { id: 4 }; await apply(f.pos, f.order);
    service.evictCustomerHistoryPrices(f.pos, f.order);
    price = 180; f.order.pricelist_id = { id: 3 }; await apply(f.pos, f.order);
    assert.equal(line.price_unit, 180); assert.equal(f.calls.length, 3);
});

test("payment wait follows a replacement pricing promise", async () => {
    const first = deferred(); const second = deferred();
    const order = { _sfyaPricePromise: first.promise };
    let ready = false;
    const wait = service.waitForCustomerHistoryPrices(order).then(() => { ready = true; });
    order._sfyaPricePromise = second.promise;
    first.resolve(); await Promise.resolve(); await Promise.resolve();
    assert.equal(ready, false);
    second.resolve(); await wait; assert.equal(ready, true);
});

test("a delayed response cannot change removed or newly refunded lines", async () => {
    const pending = deferred(); const f = fixture(() => pending.promise);
    const removed = f.add(); const refunded = f.add(12);
    const wait = apply(f.pos, f.order); await Promise.resolve();
    f.order.lines.splice(0, 1); refunded.qty = -1;
    pending.resolve({ "11": 120, "12": 130 }); await wait;
    assert.equal(removed.price_unit, 400); assert.equal(refunded.price_unit, 400);
});

// Odoo's patch boundary: preserve the original prototype so super calls stay real.
function patch(target, extension) {
    const parent = Object.create(Object.getPrototypeOf(target));
    Object.defineProperties(parent, Object.getOwnPropertyDescriptors(target));
    Object.setPrototypeOf(extension, parent);
    Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
}
async function loadPatch(name, classes) {
    const source = await readFile(new URL(`../static/src/app/${name}.js`, import.meta.url), "utf8");
    const body = source.replace(/^import .*;\n/gm, "");
    Function("patch", "PosStore", "PosOrder", "PaymentScreen", "applyCustomerHistoryPrices", "evictCustomerHistoryPrices", "waitForCustomerHistoryPrices", body)(
        patch, classes.PosStore, classes.PosOrder, classes.PaymentScreen,
        apply, service.evictCustomerHistoryPrices, service.waitForCustomerHistoryPrices
    );
}

test("customer and product hooks preserve upstream returns and refresh the line's own order", async () => {
    const f = fixture(); const line = f.add();
    class PosStore {
        async setup() { this.data.models = { "pos.order": {} }; return "setup-result"; }
        async addLineToCurrentOrder() { return line; }
    }
    class PosOrder {
        set_partner(partner) { this.partner_id = partner; return "partner-result"; }
    }
    await loadPatch("pos_store_patch", { PosStore });
    await loadPatch("pos_order_patch", { PosOrder });
    Object.setPrototypeOf(f.pos, PosStore.prototype);
    assert.equal(await f.pos.setup(), "setup-result");
    assert.equal(f.pos.data.models["pos.order"]._sfyaPosStore, f.pos);
    Object.setPrototypeOf(f.order, PosOrder.prototype); f.order.models = f.pos.data.models;
    assert.equal(f.order.set_partner({ id: 1 }), "partner-result");
    await f.order._sfyaPricePromise; assert.equal(line.price_unit, 120);
    line.price_unit = 555;
    assert.equal(await f.pos.addLineToCurrentOrder({}), line);
    await f.order._sfyaPricePromise; assert.equal(line.price_unit, 120);
    f.order.set_partner(false); assert.equal(line.price_unit, 35);
});

test("payment hooks wait for prices and evict only after completed validation", async () => {
    const f = fixture(); const line = f.add();
    f.order.id = 55; f.order.state = "draft";
    const pending = deferred(); f.order._sfyaPricePromise = pending.promise;
    let paymentAmount; let validated = false;
    class PaymentScreen {
        addNewPaymentLine(method) { paymentAmount = line.price_unit; return method; }
        async validateOrder(force) { validated = true; if (force) this.currentOrder.state = "paid"; }
    }
    await loadPatch("payment_screen_patch", { PaymentScreen });
    const screen = Object.assign(new PaymentScreen(), { currentOrder: f.order, pos: f.pos });
    const payment = screen.addNewPaymentLine("cash"); const validation = screen.validateOrder(false);
    await Promise.resolve(); assert.equal(paymentAmount, undefined); assert.equal(validated, false);
    line.price_unit = 120; pending.resolve();
    assert.equal(await payment, "cash"); await validation; assert.equal(paymentAmount, 120);
    await apply(f.pos, f.order); assert.equal(f.pos._sfyaHistoryPriceCache.size, 1);
    await screen.validateOrder(false); assert.equal(f.pos._sfyaHistoryPriceCache.size, 1);
    await screen.validateOrder(true); assert.equal(f.pos._sfyaHistoryPriceCache.size, 0);
});

test("no active pricelist sends explicit false and applies company-currency history", async () => {
    const f = fixture(async () => ({ "11": 120 }));
    f.order.pricelist_id = false;
    const line = f.add();
    await apply(f.pos, f.order);
    assert.equal(f.calls[0][3].pricelist_id, false);
    assert.equal(line.price_unit, 120);
});

test("pricelist hook replaces a pending lookup and ignores its stale response", async () => {
    const first = deferred(); const second = deferred();
    const f = fixture((model, method, args, kwargs) => kwargs.pricelist_id === 3 ? first.promise : second.promise);
    const line = f.add();
    class PosOrder {
        set_pricelist(pricelist) { this.pricelist_id = pricelist; return "updated"; }
    }
    await loadPatch("pos_order_patch", { PosOrder });
    Object.setPrototypeOf(f.order, PosOrder.prototype);
    f.order.models = { "pos.order": { _sfyaPosStore: f.pos } };
    const old = apply(f.pos, f.order); await Promise.resolve();
    assert.equal(f.order.set_pricelist({ id: 4 }), "updated");
    const current = f.order._sfyaPricePromise;
    assert.notEqual(current, old);
    await Promise.resolve();
    second.resolve({ "11": 160 }); await current;
    first.resolve({ "11": 120 }); await old;
    assert.equal(line.price_unit, 160);
    assert.deepEqual(f.calls.map((call) => call[3].pricelist_id), [3, 4]);
});

test("deferred synchronization evicts only completed successfully uploaded orders", async () => {
    let price = 120; const f = fixture(async () => ({ "11": price })); const line = f.add();
    await apply(f.pos, f.order);
    f.order.state = "paid"; f.order.id = "temporary";
    class PosStore {
        async postSyncAllOrders(orders) { this.postCalls = (this.postCalls || 0) + 1; return "done"; }
        async upload(orders, fail) { if (fail) throw new Error("offline"); return this.postSyncAllOrders(orders); }
    }
    await loadPatch("pos_store_patch", { PosStore });
    Object.setPrototypeOf(f.pos, PosStore.prototype);
    await assert.rejects(f.pos.upload([f.order], true), /offline/);
    assert.equal(f.pos._sfyaHistoryPriceCache.size, 1);
    const draft = { ...f.order, state: "draft" };
    assert.equal(await f.pos.upload([draft], false), "done");
    assert.equal(f.pos._sfyaHistoryPriceCache.size, 1);
    const uploaded = { ...f.order, id: 99 };
    assert.equal(await f.pos.upload([uploaded], false), "done");
    assert.equal(f.pos._sfyaHistoryPriceCache.size, 0);
    f.order.state = "draft"; price = 180;
    await apply(f.pos, f.order); assert.equal(line.price_unit, 180);
});
