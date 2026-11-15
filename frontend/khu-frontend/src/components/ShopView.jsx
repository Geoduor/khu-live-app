import React, { useCallback, useEffect, useRef, useState } from "react";
import { getShopStores, getShopStore, shopImageUrl, shopLogoUrl, createShopOrder, getShopOrder } from "../api";
import LoadingState from "./LoadingState";
import ErrorState from "./ErrorState";
import HumanCheck, { humanCheckOn } from "./HumanCheck";

const kes = (n) => `KES ${Number(n || 0).toLocaleString("en-KE")}`;
const CART_KEY = "khu_cart";
const ORDERS_KEY = "khu_shop_orders";
const ME_KEY = "khu_shop_me";

function load(key, fallback) {
  try { const v = JSON.parse(localStorage.getItem(key) || "null"); return v == null ? fallback : v; } catch (e) { return fallback; }
}
function save(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode: the shop still works */ }
}
const STATUS_TEXT = {
  pending_payment: "Waiting for your M-Pesa payment", paid: "Paid. The store is preparing your order", processing: "Being prepared",
  shipped: "On the way to you", delivered: "Delivered", failed: "Payment did not go through", expired: "Payment timed out", cancelled: "Cancelled. Your refund is being arranged",
};

function StoreLogo({ store, size = 44 }) {
  const [failed, setFailed] = useState(false);
  if (store.has_logo && !failed) {
    return <img className="shop-logo" style={{ width: size, height: size }} src={shopLogoUrl(store.store_id)} alt="" onError={() => setFailed(true)} />;
  }
  return <div className="shop-logo shop-logo-fallback" style={{ width: size, height: size }} aria-hidden="true">{(store.name || "?").slice(0, 1).toUpperCase()}</div>;
}

function ProductCard({ p, qtyInCart, onAdd }) {
  const [open, setOpen] = useState(false);
  const [img, setImg] = useState(0);
  const images = p.images || [];
  return (
    <div className="shop-product">
      <button className="shop-product-main" onClick={() => setOpen(!open)} aria-expanded={open}>
        {images.length ? <img className="shop-product-img" src={shopImageUrl(images[0])} alt={p.name} loading="lazy" /> : <div className="shop-product-img shop-product-noimg" aria-hidden="true">🏑</div>}
        <div className="shop-product-info">
          {p.brand && <div className="shop-brand">{p.brand}</div>}
          <div className="shop-product-name">{p.name}</div>
          {p.category && <div className="shop-cat">{p.category}</div>}
          <div className="shop-price">{kes(p.price)}</div>
        </div>
      </button>
      {open && (
        <div className="shop-product-more">
          {images.length > 1 && (
            <div className="shop-thumbs">
              {images.map((id, i) => (
                <img key={id} className={`shop-thumb ${i === img ? "on" : ""}`} src={shopImageUrl(id)} alt={`${p.name} view ${i + 1}`} onClick={() => setImg(i)} />
              ))}
            </div>
          )}
          {images.length > 1 && <img className="shop-big" src={shopImageUrl(images[img])} alt={p.name} />}
          {p.description && <p className="shop-desc">{p.description}</p>}
        </div>
      )}
      <div className="shop-product-actions">
        {p.in_stock ? (
          <button className="shop-btn" onClick={() => onAdd(p)}>{qtyInCart ? `Add another (${qtyInCart} in bag)` : "Add to bag"}</button>
        ) : <span className="shop-soldout">Sold out</span>}
      </div>
    </div>
  );
}

/**
 * The shop: stores -> products -> bag -> checkout -> pay with M-Pesa -> order status.
 * The server works out every price; this screen only shows them. Orders are remembered on this phone
 * (code + phone number) so a fan can check on them again.
 */
export default function ShopView({ onBack }) {
  const [screen, setScreen] = useState("stores"); // stores | store | bag | checkout | pay | orders
  const [stores, setStores] = useState(null);
  const [paymentsReady, setPaymentsReady] = useState(true);
  const [error, setError] = useState(false);
  const [store, setStore] = useState(null);
  const [products, setProducts] = useState([]);
  const [cart, setCart] = useState(() => load(CART_KEY, { storeId: "", lines: {} }));
  const [me, setMe] = useState(() => load(ME_KEY, { name: "", phone: "", town: "", address: "" }));
  const [note, setNote] = useState("");
  const [formError, setFormError] = useState("");
  const [placing, setPlacing] = useState(false);
  const [humanToken, setHumanToken] = useState("");
  const [humanReset, setHumanReset] = useState(0);
  const [order, setOrder] = useState(null); // current order being paid / tracked
  const [myOrders, setMyOrders] = useState(() => load(ORDERS_KEY, []));
  const [orderStates, setOrderStates] = useState({});
  const timer = useRef(null);

  useEffect(() => { save(CART_KEY, cart); }, [cart]);

  const loadStores = useCallback(() => {
    setError(false);
    getShopStores().then((d) => { setStores(d.stores || []); setPaymentsReady(!!d.payments_ready); }).catch(() => setError(true));
  }, []);
  useEffect(() => { loadStores(); }, [loadStores]);
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  const openStore = (id) => {
    setScreen("store"); setStore(null); setProducts([]);
    getShopStore(id).then((d) => { setStore(d.store); setProducts(d.products || []); setPaymentsReady(!!d.payments_ready); }).catch(() => setError(true));
  };

  const lineCount = Object.values(cart.lines).reduce((n, l) => n + l.qty, 0);
  const subtotal = Object.values(cart.lines).reduce((n, l) => n + l.qty * l.price, 0);
  const cartStoreId = cart.storeId;

  const addToBag = (p) => {
    if (cartStoreId && cartStoreId !== p.store_id && lineCount > 0 && !window.confirm("Your bag has items from another store. Start a new bag with this item?")) return;
    setCart((c) => {
      const base = c.storeId === p.store_id ? c : { storeId: p.store_id, lines: {} };
      const cur = base.lines[p.product_id];
      return { storeId: p.store_id, lines: { ...base.lines, [p.product_id]: { name: p.name, brand: p.brand, price: p.price, qty: Math.min(10, (cur ? cur.qty : 0) + 1) } } };
    });
  };
  const setQty = (id, qty) => setCart((c) => {
    const lines = { ...c.lines };
    if (qty <= 0) delete lines[id]; else lines[id] = { ...lines[id], qty: Math.min(10, qty) };
    return { ...c, lines };
  });

  const bagStore = (stores || []).find((s) => s.store_id === cartStoreId) || store;
  const fee = bagStore ? bagStore.delivery_fee || 0 : 0;

  const startPolling = (o, phone) => {
    if (timer.current) clearInterval(timer.current);
    let tries = 0;
    timer.current = setInterval(async () => {
      tries += 1;
      try {
        const st = await getShopOrder(o.order_id, phone);
        setOrder(st);
        setOrderStates((s) => ({ ...s, [o.order_id]: st.status }));
        if (st.status !== "pending_payment" || tries > 40) { clearInterval(timer.current); timer.current = null; }
      } catch (e) { /* keep trying; the payment may still arrive */ }
    }, 4000);
  };

  const placeOrder = async () => {
    setFormError("");
    if (me.name.trim().length < 2) return setFormError("Enter your name.");
    if (!me.phone.trim()) return setFormError("Enter the Safaricom number that will pay.");
    if (!me.town.trim() || me.address.trim().length < 3) return setFormError("Enter the town and where to deliver.");
    if (humanCheckOn() && !humanToken) return setFormError("Please tick the box to show you are not a robot.");
    setPlacing(true);
    try {
      const res = await createShopOrder({
        store_id: cart.storeId, customer_name: me.name, phone: me.phone, town: me.town, address: me.address, note,
        items: Object.entries(cart.lines).map(([product_id, l]) => ({ product_id, qty: l.qty })),
      }, humanToken);
      save(ME_KEY, me);
      const entry = { order_id: res.order_id, phone: me.phone };
      const list = [entry, ...myOrders.filter((o) => o.order_id !== res.order_id)].slice(0, 20);
      setMyOrders(list); save(ORDERS_KEY, list);
      setCart({ storeId: "", lines: {} });
      setOrder({ order_id: res.order_id, status: "pending_payment", total: res.total, items: [], phone: me.phone });
      setScreen("pay");
      startPolling(res, me.phone);
    } catch (e) {
      const d = e && e.response && e.response.data && e.response.data.detail;
      setFormError(typeof d === "string" ? d : "We could not place the order. Please try again.");
      setHumanToken(""); setHumanReset((n) => n + 1);
    } finally { setPlacing(false); }
  };

  const openOrders = () => {
    setScreen("orders");
    myOrders.forEach(async (o) => {
      try { const st = await getShopOrder(o.order_id, o.phone); setOrderStates((s) => ({ ...s, [o.order_id]: st.status })); } catch (e) { /* skip */ }
    });
  };
  const trackOrder = async (o) => {
    try { const st = await getShopOrder(o.order_id, o.phone); setOrder({ ...st, phone: o.phone }); setScreen("pay"); if (st.status === "pending_payment") startPolling(o, o.phone); }
    catch (e) { /* ignore */ }
  };

  // ── screens ──
  const back = () => {
    if (screen === "stores") return onBack();
    if (screen === "store") return setScreen("stores");
    if (screen === "bag") return setScreen(store ? "store" : "stores");
    if (screen === "checkout") return setScreen("bag");
    if (screen === "pay") { if (timer.current) { clearInterval(timer.current); timer.current = null; } return setScreen("stores"); }
    return setScreen("stores");
  };

  const topBar = (
    <div className="shop-top">
      <button className="back-btn" onClick={back}>← Back</button>
      <div className="shop-top-right">
        {myOrders.length > 0 && screen !== "orders" && <button className="shop-link" onClick={openOrders}>My orders</button>}
        {lineCount > 0 && screen !== "bag" && screen !== "checkout" && screen !== "pay" && (
          <button className="shop-bag-btn" onClick={() => setScreen("bag")}>🛍 {lineCount} · {kes(subtotal)}</button>
        )}
      </div>
    </div>
  );

  if (error && stores === null) return <div>{topBar}<ErrorState title="Shop unavailable" message="We could not load the shop. Check your connection and try again." compact /></div>;

  if (screen === "stores") {
    return (
      <div className="shop">
        {topBar}
        <h2 className="shop-h">Shop</h2>
        <p className="shop-sub">Hockey gear from our partner stores. Pay with M-Pesa and get it delivered. Stores are independent sellers: they are not the Kenya Hockey Union.</p>
        {!paymentsReady && <div className="shop-note">Ordering opens soon. You can look around in the meantime.</div>}
        {stores === null ? <LoadingState message="Loading stores..." /> : stores.length === 0 ? <div className="shop-empty">No stores yet. Check back soon.</div> : (
          <div className="shop-stores">
            {stores.map((s) => (
              <button key={s.store_id} className="shop-store" onClick={() => openStore(s.store_id)}>
                <StoreLogo store={s} size={56} />
                <div className="shop-store-text">
                  <div className="shop-store-name">{s.name}</div>
                  {s.tagline && <div className="shop-store-tag">{s.tagline}</div>}
                  <div className="shop-store-meta">{s.product_count} product{s.product_count === 1 ? "" : "s"} · delivery {s.delivery_fee ? kes(s.delivery_fee) : "free"}</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (screen === "store") {
    return (
      <div className="shop">
        {topBar}
        {!store ? <LoadingState message="Loading store..." /> : (
          <>
            <div className="shop-store-head">
              <StoreLogo store={store} size={56} />
              <div>
                <h2 className="shop-h" style={{ margin: 0 }}>{store.name}</h2>
                {store.tagline && <div className="shop-store-tag">{store.tagline}</div>}
              </div>
            </div>
            <div className="shop-note">
              Delivery {store.delivery_fee ? kes(store.delivery_fee) : "is free"}{store.delivery_note ? ` · ${store.delivery_note}` : ""}
              {store.whatsapp && <> · <a href={`https://wa.me/${store.whatsapp}`} target="_blank" rel="noopener noreferrer">Ask the store on WhatsApp</a></>}
            </div>
            {!paymentsReady && <div className="shop-note">Ordering opens soon.</div>}
            {products.length === 0 ? <div className="shop-empty">No products yet.</div> : products.map((p) => (
              <ProductCard key={p.product_id} p={p} qtyInCart={cart.lines[p.product_id] ? cart.lines[p.product_id].qty : 0} onAdd={addToBag} />
            ))}
          </>
        )}
      </div>
    );
  }

  if (screen === "bag") {
    return (
      <div className="shop">
        {topBar}
        <h2 className="shop-h">Your bag</h2>
        {lineCount === 0 ? <div className="shop-empty">Your bag is empty.</div> : (
          <>
            {Object.entries(cart.lines).map(([id, l]) => (
              <div key={id} className="shop-line">
                <div className="shop-line-name">{l.brand ? `${l.brand} ` : ""}{l.name}<div className="shop-store-meta">{kes(l.price)} each</div></div>
                <div className="shop-qty">
                  <button aria-label={`Fewer ${l.name}`} onClick={() => setQty(id, l.qty - 1)}>−</button>
                  <span>{l.qty}</span>
                  <button aria-label={`More ${l.name}`} onClick={() => setQty(id, l.qty + 1)}>+</button>
                </div>
                <div className="shop-line-total">{kes(l.price * l.qty)}</div>
              </div>
            ))}
            <div className="shop-totals">
              <div><span>Items</span><span>{kes(subtotal)}</span></div>
              <div><span>Delivery</span><span>{fee ? kes(fee) : "Free"}</span></div>
              <div className="shop-total"><span>Total</span><span>{kes(subtotal + fee)}</span></div>
            </div>
            <button className="shop-btn shop-btn-wide" disabled={!paymentsReady} onClick={() => setScreen("checkout")}>{paymentsReady ? "Checkout" : "Ordering opens soon"}</button>
          </>
        )}
      </div>
    );
  }

  if (screen === "checkout") {
    const set = (k) => (e) => setMe({ ...me, [k]: e.target.value });
    return (
      <div className="shop">
        {topBar}
        <h2 className="shop-h">Delivery and payment</h2>
        <div className="shop-form">
          <label>Your name<input value={me.name} onChange={set("name")} maxLength={80} autoComplete="name" /></label>
          <label>M-Pesa phone number<input value={me.phone} onChange={set("phone")} maxLength={20} inputMode="tel" placeholder="0712345678" autoComplete="tel" /></label>
          <label>Town<input value={me.town} onChange={set("town")} maxLength={60} placeholder="e.g. Kisumu" /></label>
          <label>Where to deliver<input value={me.address} onChange={set("address")} maxLength={200} placeholder="Road, building, landmark" autoComplete="street-address" /></label>
          <label>Note for the store (optional)<input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} /></label>
        </div>
        <div className="shop-totals"><div className="shop-total"><span>You pay</span><span>{kes(subtotal + fee)}</span></div></div>
        <p className="shop-fine">
          We will send an M-Pesa request to this number: enter your PIN on your phone to pay. Your name, phone and address are shared only with the store so it can deliver, and are kept
          for order records. See the <a href="/privacy.html" target="_blank" rel="noopener noreferrer">privacy notice</a>.
        </p>
        <HumanCheck onToken={setHumanToken} resetKey={humanReset} />
        {formError && <div className="shop-error" role="alert">{formError}</div>}
        <button className="shop-btn shop-btn-wide" disabled={placing} onClick={placeOrder}>{placing ? "Sending the M-Pesa request..." : `Pay ${kes(subtotal + fee)} with M-Pesa`}</button>
      </div>
    );
  }

  if (screen === "pay" && order) {
    const st = order.status;
    return (
      <div className="shop">
        {topBar}
        <h2 className="shop-h">Order {order.order_id}</h2>
        <div className={`shop-status shop-status-${st}`}>
          {st === "pending_payment" && <div className="spinner" style={{ margin: "0 auto 8px" }} />}
          <div className="shop-status-text">{STATUS_TEXT[st] || st}</div>
          {st === "pending_payment" && <div className="shop-fine">Check your phone and enter your M-Pesa PIN. This page updates by itself.</div>}
          {(st === "failed" || st === "expired") && order.failure_reason && <div className="shop-fine">{order.failure_reason}</div>}
          {order.mpesa_receipt && <div className="shop-fine">M-Pesa receipt {order.mpesa_receipt}</div>}
        </div>
        {order.items && order.items.length > 0 && (
          <div className="shop-totals">
            {order.items.map((i) => <div key={i.product_id}><span>{i.qty} × {i.name}</span><span>{kes(i.price * i.qty)}</span></div>)}
            <div><span>Delivery</span><span>{order.delivery_fee ? kes(order.delivery_fee) : "Free"}</span></div>
            <div className="shop-total"><span>Total</span><span>{kes(order.total)}</span></div>
          </div>
        )}
        <p className="shop-fine">Keep your order code <b>{order.order_id}</b>. You can check this order again any time under “My orders”.</p>
        {(st === "failed" || st === "expired") && <button className="shop-btn shop-btn-wide" onClick={() => setScreen("stores")}>Back to the shop</button>}
      </div>
    );
  }

  if (screen === "orders") {
    return (
      <div className="shop">
        {topBar}
        <h2 className="shop-h">My orders</h2>
        {myOrders.length === 0 ? <div className="shop-empty">No orders yet on this phone.</div> : myOrders.map((o) => (
          <button key={o.order_id} className="shop-line shop-line-btn" onClick={() => trackOrder(o)}>
            <div className="shop-line-name">{o.order_id}<div className="shop-store-meta">{STATUS_TEXT[orderStates[o.order_id]] || "Checking..."}</div></div>
            <div className="shop-line-total">›</div>
          </button>
        ))}
      </div>
    );
  }
  return <div className="shop">{topBar}<LoadingState /></div>;
}
