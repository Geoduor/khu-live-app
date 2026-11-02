// Run: node worker.test.mjs   (no install needed; Safaricom, Turnstile and the API are simulated)
import worker, { retryPending } from "./worker.js";

let fails = 0;
const check = (label, ok, detail = "") => { console.log(`  [${ok ? "PASS" : "FAIL"}] ${label}${detail ? " — " + detail : ""}`); if (!ok) fails++; };

const kvStore = new Map();
const RETRY = {
  async put(k, v) { kvStore.set(k, v); }, async get(k) { return kvStore.has(k) ? kvStore.get(k) : null; }, async delete(k) { kvStore.delete(k); },
  async list({ prefix }) { return { keys: [...kvStore.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })) }; },
};
const counter = (limit) => { const seen = new Map(); return { async limit({ key }) { const n = (seen.get(key) || 0) + 1; seen.set(key, n); return { success: n <= limit }; } }; };
const mkEnv = (extra = {}) => ({ BACKEND_URL: "https://api.test", EDGE_KEY: "edge-key", CALLBACK_SECRET: "cb-secret", ALLOWED_ORIGINS: "https://app.test",
  RETRY, RL_LOGIN: counter(3), RL_ORDER: counter(2), RL_API: counter(10), ...extra });

let backendUp = true, turnstileOk = true;
const log = [];
globalThis.fetch = async (input, init) => {
  const req = input instanceof Request ? input : new Request(input, init);
  const u = new URL(req.url);
  if (u.host === "challenges.cloudflare.com") return new Response(JSON.stringify({ success: turnstileOk }));
  log.push({ path: u.pathname, key: req.headers.get("x-edge-key"), ip: req.headers.get("x-edge-client-ip"), fwd: req.headers.get("x-forwarded-for"), spoof: req.headers.get("x-edge-fake") });
  if (!backendUp) throw new Error("Render is restarting");
  return new Response(JSON.stringify({ ok: true }), { status: 200 });
};
const call = (env, path, { method = "GET", ip = "1.2.3.4", headers = {}, body } = {}) =>
  worker.fetch(new Request("https://edge.test" + path, { method, headers: { "CF-Connecting-IP": ip, ...headers }, body }), env);

console.log("Normal traffic");
let r = await call(mkEnv(), "/api/leagues");
check("a normal request reaches the API", r.status === 200);
check("the API is told the real visitor address and the secret key", log.at(-1).ip === "1.2.3.4" && log.at(-1).key === "edge-key");
r = await call(mkEnv(), "/api/leagues", { headers: { "x-edge-key": "forged", "x-edge-client-ip": "6.6.6.6", "x-forwarded-for": "7.7.7.7", "x-edge-fake": "1" } });
check("a visitor cannot forge the Worker's headers", log.at(-1).key === "edge-key" && log.at(-1).ip === "1.2.3.4" && log.at(-1).fwd === null && log.at(-1).spoof === null);
check("anything outside /api is refused", (await call(mkEnv(), "/secret")).status === 404);
check("odd methods are refused", (await call(mkEnv(), "/api/leagues", { method: "PUT" })).status === 405);

console.log("Floods and password guessing");
let env = mkEnv();
let codes = [];
for (let i = 0; i < 5; i++) codes.push((await call(env, "/api/admin/login", { method: "POST", body: "{}" })).status);
check("login attempts are cut off after 3 a minute, before reaching the API", JSON.stringify(codes) === JSON.stringify([200, 200, 200, 429, 429]), codes.join(","));
const before = log.length;
await call(env, "/api/agent/login", { method: "POST", body: "{}", ip: "1.2.3.4" });
check("a blocked visitor costs the API nothing", log.length === before);
r = await call(env, "/api/admin/login", { method: "POST", body: "{}", ip: "5.5.5.5" });
check("other visitors are not affected", r.status === 200);
r = await call(mkEnv(), "/api/admin/login", { method: "POST", body: "{}", ip: "9.9.9.9" }); 
env = mkEnv(); codes = [];
for (let i = 0; i < 4; i++) codes.push((await call(env, "/api/shop/orders", { method: "POST", body: "{}" })).status);
check("shop orders are cut off after 2 a minute", JSON.stringify(codes) === JSON.stringify([200, 200, 429, 429]), codes.join(","));
env = mkEnv(); codes = [];
for (let i = 0; i < 12; i++) codes.push((await call(env, "/api/standings/all")).status);
check("general floods are cut off", codes.filter((c) => c === 429).length === 2, codes.join(","));
r = await call(env, "/api/standings/all", { headers: { Origin: "https://app.test" } });
check("blocked replies still carry CORS so the app can show the message", r.status === 429 && r.headers.get("access-control-allow-origin") === "https://app.test");
r = await call(env, "/api/standings/all", { headers: { Origin: "https://evil.test" } });
check("other websites get no CORS permission", r.headers.get("access-control-allow-origin") === null);

console.log("Human check (Turnstile)");
env = mkEnv({ TURNSTILE_SECRET: "ts-secret" });
check("login without a token is refused", (await call(env, "/api/admin/login", { method: "POST", body: "{}" })).status === 403);
check("login with a good token passes", (await call(mkEnv({ TURNSTILE_SECRET: "ts" }), "/api/admin/login", { method: "POST", body: "{}", headers: { "x-turnstile-token": "tok" } })).status === 200);
turnstileOk = false;
check("login with a failed token is refused", (await call(mkEnv({ TURNSTILE_SECRET: "ts" }), "/api/admin/login", { method: "POST", body: "{}", headers: { "x-turnstile-token": "bad" } })).status === 403);
check("orders also need the human check", (await call(mkEnv({ TURNSTILE_SECRET: "ts" }), "/api/shop/orders", { method: "POST", body: "{}", headers: { "x-turnstile-token": "bad" } })).status === 403);
turnstileOk = true;
check("normal browsing never needs it", (await call(mkEnv({ TURNSTILE_SECRET: "ts" }), "/api/leagues")).status === 200);

console.log("M-Pesa callback");
const cbBody = JSON.stringify({ Body: { stkCallback: { CheckoutRequestID: "ws_CO_1", ResultCode: 0 } } });
r = await call(mkEnv(), "/api/shop/mpesa/callback/wrong", { method: "POST", body: cbBody });
check("a wrong secret is refused", r.status === 404);
kvStore.clear();
r = await call(mkEnv(), "/api/shop/mpesa/callback/cb-secret", { method: "POST", body: cbBody });
check("Safaricom gets its acknowledgement and the API gets the report", r.status === 200 && log.at(-1).path === "/api/shop/mpesa/callback/cb-secret" && kvStore.size === 0);
backendUp = false;
r = await call(mkEnv(), "/api/shop/mpesa/callback/cb-secret", { method: "POST", body: cbBody });
check("when Render is down Safaricom is still answered and the report is saved", r.status === 200 && kvStore.size === 1);
const res1 = await retryPending(mkEnv());
check("still down: the saved report is kept", kvStore.size === 1 && res1.delivered === 0);
backendUp = true;
const res2 = await retryPending(mkEnv());
check("Render is back: the saved report is delivered and removed", kvStore.size === 0 && res2.delivered === 1 && log.at(-1).path === "/api/shop/mpesa/callback/cb-secret");
check("callbacks skip the flood limits (Safaricom must always get through)", (await call(mkEnv({ RL_API: counter(0) }), "/api/shop/mpesa/callback/cb-secret", { method: "POST", body: cbBody })).status === 200);

console.log("\nRESULT:", fails ? `${fails} FAILURE(S)` : "all checks passed");
process.exit(fails ? 1 : 0);
