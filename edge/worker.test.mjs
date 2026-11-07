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
await call(mkEnv(), "/api/analytics/hit", { method: "POST", body: JSON.stringify({ view: "home" }), headers: { "Content-Type": "application/json" } });
check("visitor counting (POST /api/analytics/hit) reaches the API through the Worker", log.at(-1).path === "/api/analytics/hit" && log.at(-1).key === "edge-key" && log.at(-1).ip === "1.2.3.4");
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

console.log("Short-lived cache for public pages");
const store = new Map();
globalThis.caches = { default: {
  async match(req) { const k = typeof req === "string" ? req : req.url; const v = store.get(k); return v ? v.clone() : undefined; },
  async put(req, res) { const k = typeof req === "string" ? req : req.url; store.set(k, res.clone()); },
} };
let clock = 1_800_000_000_000; const realNow = Date.now; Date.now = () => clock;
let hits = {}, version = 1, apiDown = false, nextStatus = 200, nextHeaders = {};
globalThis.fetch = async (input, init) => {
  const req = input instanceof Request ? input : new Request(input, init);
  const u = new URL(req.url);
  hits[u.pathname] = (hits[u.pathname] || 0) + 1;
  if (apiDown) throw new Error("Render is down");
  return new Response(JSON.stringify({ v: version }), { status: nextStatus, headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "https://app.test", ...nextHeaders } });
};
const pending = [];
const ctx = { waitUntil: (p) => pending.push(p) };
const get = (path, headers = {}) => worker.fetch(new Request("https://edge.test" + path, { headers: { "CF-Connecting-IP": "1.1.1.1", ...headers } }), cenv, ctx);
const cenv = mkEnv({ RL_API: counter(1000) });
const state = (r) => r.headers.get("x-edge-cache");

let c1 = await get("/api/standings/all", { Origin: "https://app.test" });
check("first visit goes to the API and is kept", state(c1) === "MISS" && hits["/api/standings/all"] === 1);
let c2 = await get("/api/standings/all", { Origin: "https://app.test" });
check("second visit is served from the cache, the API is not asked", state(c2) === "HIT" && hits["/api/standings/all"] === 1 && (await c2.json()).v === 1);
let c3 = await get("/api/standings/all", { Origin: "https://evil.test" });
check("another website still gets no CORS permission from a cached copy", state(c3) === "HIT" && c3.headers.get("access-control-allow-origin") === null);
c2 = await get("/api/standings/all", { Origin: "https://app.test" });
check("our app gets its CORS permission on a cached copy", c2.headers.get("access-control-allow-origin") === "https://app.test" && c2.headers.get("vary") === "Origin");
await get("/api/team?name=a&x=1"); const k2 = await get("/api/team?x=1&name=a");
check("same page with the options in another order shares one copy", state(k2) === "HIT" && hits["/api/team"] === 1);
await get("/api/team?name=b");
check("a different question is a different copy", hits["/api/team"] === 2);

for (const [path, headers, why] of [
  ["/api/admin/results/list", {}, "admin pages"], ["/api/agent/me", {}, "agent pages"], ["/api/shop/orders/123", {}, "orders"],
  ["/api/shop/stores", {}, "the shop"], ["/api/push/favorites", {}, "push"], ["/api/health", {}, "the health check"],
  ["/api/standings/all", { "x-admin-token": "t" }, "a request carrying a login token"],
  ["/api/standings/all", { Authorization: "Bearer x" }, "a request carrying an Authorization header"],
]) {
  const b = hits[path] || 0; const r = await get(path, headers); const r2 = await get(path, headers);
  check(`never cached: ${why}`, state(r) === null && state(r2) === null && hits[path] === b + 2);
}
const bp = hits["/api/leagues"] || 0;
await worker.fetch(new Request("https://edge.test/api/leagues", { method: "POST", headers: { "CF-Connecting-IP": "1.1.1.1" }, body: "{}" }), cenv, ctx);
check("POST requests are never answered from the cache", hits["/api/leagues"] === bp + 1 && state(await get("/api/leagues")) === "MISS");

clock += 70_000; version = 2;
let s1 = await get("/api/standings/all");
check("an old copy is shown at once while a fresh one is fetched behind the scenes", state(s1) === "STALE" && (await s1.json()).v === 1);
await Promise.all(pending.splice(0));
let s2 = await get("/api/standings/all");
check("the next visitor gets the refreshed copy", state(s2) === "HIT" && (await s2.json()).v === 2);

clock += 3 * 60_000;
version = 3; await get("/api/live"); clock += 20_000; // live: 15s
let live = await get("/api/live");
check("live scores go stale after 15 seconds (not 60)", state(live) === "STALE");
await Promise.all(pending.splice(0));
clock += 3000_000 / 10; // 5 minutes later: too old to show before refreshing
apiDown = true;
let e1 = await get("/api/standings/all");
check("API down: a recent copy is shown instead of an error", e1.status === 200 && state(e1) === "STALE-ERROR");
apiDown = false; nextStatus = 500;
let e2 = await get("/api/standings/all");
check("API answers 500: the copy is shown instead", e2.status === 200 && state(e2) === "STALE-ERROR");
nextStatus = 200;
clock += 2 * 3600_000; apiDown = true;
let threw = false; try { await get("/api/standings/all"); } catch (e) { threw = true; }
check("API down for hours: a very old copy is NOT shown", threw);
apiDown = false;

nextStatus = 404; const nf = await get("/api/team?name=nobody");
const nfCount = hits["/api/team"]; await get("/api/team?name=nobody");
check("errors from the API (404) are passed on and never cached", nf.status === 404 && state(nf) === "BYPASS" && hits["/api/team"] === nfCount + 1);
nextStatus = 200; nextHeaders = { "Cache-Control": "no-store" };
await get("/api/results"); const rc = hits["/api/results"]; await get("/api/results");
check("anything the API marks no-store is respected", hits["/api/results"] === rc + 1);
nextHeaders = {};

await get("/api/fixtures"); await get("/api/fixtures");
const fb = hits["/api/fixtures"]; clock += 1000; version = 9;
await worker.fetch(new Request("https://edge.test/api/admin/match-corrections/set", { method: "POST", headers: { "CF-Connecting-IP": "2.2.2.2", "x-admin-token": "t" }, body: "{}" }), cenv, ctx);
let af = await get("/api/fixtures");
check("after an admin saves something the next visit sees it (no waiting for the copy to expire)", state(af) === "MISS" && hits["/api/fixtures"] === fb + 1 && (await af.json()).v === 9);
nextStatus = 403;
await worker.fetch(new Request("https://edge.test/api/admin/results/set", { method: "POST", headers: { "CF-Connecting-IP": "2.2.2.2" }, body: "{}" }), cenv, ctx);
nextStatus = 200; clock += 1000;
check("a refused admin attempt does not throw the cache away", state(await get("/api/fixtures")) === "HIT");

delete globalThis.caches; Date.now = realNow;
const { freshSeconds } = await import("./worker.js");
check("live match detail is kept only 15 seconds", freshSeconds(new Request("https://x/api/match?url=a"), new URL("https://x/api/match?url=a")) === 15);
check("rules: only public read pages have a lifetime", freshSeconds(new Request("https://x/api/shop/orders/1"), new URL("https://x/api/shop/orders/1")) === 0
  && freshSeconds(new Request("https://x/api/live"), new URL("https://x/api/live")) === 15);

console.log("\nRESULT:", fails ? `${fails} FAILURE(S)` : "all checks passed");
process.exit(fails ? 1 : 0);
