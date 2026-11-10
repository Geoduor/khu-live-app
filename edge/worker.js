/**
 * KHU edge Worker (Cloudflare). Sits in front of the Render API:
 *   - stops floods and password guessing before they reach Render (Cloudflare Rate Limiting bindings),
 *   - checks a Turnstile human-check on logins and shop orders (when TURNSTILE_SECRET is set),
 *   - always accepts Safaricom's M-Pesa payment report, saves it if Render is down, and retries until delivered,
 *   - tells the API the visitor's real address, signed with a secret key only this Worker and the API know.
 *   - keeps a short-lived copy of the PUBLIC read pages (table, fixtures, results...) so busy match days and
 *     slow moments on the API do not reach fans. Admin, agent, shop and push routes are never cached.
 * Setup: docs/EDGE_SETUP.md. Nothing here decides prices, stock or who is logged in: that stays on the API.
 */

const LOGIN_PATHS = new Set(["/api/admin/login", "/api/agent/login"]);
const CALLBACK_PREFIX = "/api/shop/mpesa/callback/";
const MAX_CALLBACK_BYTES = 20000;
const RETRY_PREFIX = "cb:";
const KEEP_RETRYING_MS = 24 * 3600 * 1000;

function allowedOrigins(env) {
  return String(env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
}

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin") || "";
  const ok = origin && allowedOrigins(env).includes(origin);
  return ok ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" } : {};
}

function reply(request, env, status, detail, extra = {}) {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "Content-Type": "application/json", "X-Content-Type-Options": "nosniff", ...corsHeaders(request, env), ...extra },
  });
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// One rate-limit key per connection owner. A single IPv6 connection owns a whole /64 (billions of addresses), so
// counting each address separately let one person rotate addresses to dodge every limit. IPv4 is unchanged.
function ipKey(ip) {
  let s = String(ip || "").toLowerCase();
  if (!s.includes(":")) return s;
  const zone = s.indexOf("%");
  if (zone >= 0) s = s.slice(0, zone);
  if (s.includes(".")) return s.slice(s.lastIndexOf(":") + 1); // ::ffff:1.2.3.4 is really IPv4
  const [head, tail] = s.split("::");
  const h = head ? head.split(":") : [];
  const t = tail ? tail.split(":") : [];
  const fill = tail === undefined ? 0 : Math.max(8 - h.length - t.length, 0);
  const groups = [...h, ...Array(fill).fill("0"), ...t];
  return groups.slice(0, 4).map((g) => g.padStart(4, "0")).join(":") + "::/64";
}

async function limited(binding, key) {
  if (!binding) return false; // not configured: skip rather than block everyone
  try { return !(await binding.limit({ key })).success; } catch (e) { return false; }
}

async function turnstileOk(request, env, ip) {
  if (!env.TURNSTILE_SECRET) return true; // switched off until you add the secret
  const token = request.headers.get("x-turnstile-token") || "";
  if (!token || token.length > 2048) return false;
  const form = new URLSearchParams({ secret: env.TURNSTILE_SECRET, response: token, remoteip: ip });
  try {
    const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body: form });
    const j = await r.json();
    return !!j.success;
  } catch (e) { return false; }
}

function toBackend(request, env, url, ip, body) {
  const headers = new Headers(request.headers);
  for (const h of [...headers.keys()]) if (h.startsWith("x-edge-") || h.startsWith("cf-") || h === "x-forwarded-for" || h === "host") headers.delete(h);
  headers.set("x-edge-key", env.EDGE_KEY);
  headers.set("x-edge-client-ip", ip);
  const target = new URL(url.pathname + url.search, env.BACKEND_URL);
  return new Request(target, { method: request.method, headers, body, redirect: "manual" });
}

async function forwardCallback(env, secret, bodyText) {
  const target = new URL(CALLBACK_PREFIX + secret, env.BACKEND_URL);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 8000);
  try {
    const r = await fetch(target, { method: "POST", headers: { "Content-Type": "application/json", "x-edge-key": env.EDGE_KEY }, body: bodyText, signal: ctrl.signal });
    return r.status >= 200 && r.status < 300;
  } catch (e) { return false; } finally { clearTimeout(timer); }
}

async function handleCallback(request, env, url) {
  const secret = url.pathname.slice(CALLBACK_PREFIX.length);
  if (request.method !== "POST" || !env.CALLBACK_SECRET || !timingSafeEqual(secret, env.CALLBACK_SECRET)) {
    return new Response("Not found", { status: 404 });
  }
  const text = await request.text();
  if (text.length > MAX_CALLBACK_BYTES) return new Response(JSON.stringify({ ResultCode: 0, ResultDesc: "Accepted" }), { headers: { "Content-Type": "application/json" } });
  const delivered = await forwardCallback(env, secret, text);
  if (!delivered && env.RETRY) {
    // Render is restarting or busy: keep the report safely and let the minute-by-minute job deliver it.
    const key = `${RETRY_PREFIX}${Date.now()}:${crypto.randomUUID()}`;
    await env.RETRY.put(key, text, { expirationTtl: 2 * 24 * 3600 });
  }
  return new Response(JSON.stringify({ ResultCode: 0, ResultDesc: "Accepted" }), { headers: { "Content-Type": "application/json" } });
}

async function retryPending(env) {
  if (!env.RETRY || !env.CALLBACK_SECRET) return { tried: 0, delivered: 0 };
  const list = await env.RETRY.list({ prefix: RETRY_PREFIX, limit: 50 });
  let delivered = 0;
  for (const k of list.keys) {
    const ts = Number(k.name.split(":")[1] || 0);
    const text = await env.RETRY.get(k.name);
    if (text === null) continue;
    if (await forwardCallback(env, env.CALLBACK_SECRET, text) || Date.now() - ts > KEEP_RETRYING_MS) {
      await env.RETRY.delete(k.name);
      delivered += 1;
    }
  }
  return { tried: list.keys.length, delivered };
}


// ── Short-lived cache for public read pages ───────────────────────────────
// [fresh seconds] a copy younger than this is served without asking the API.
// A copy older than that (but under STALE_OK_S) is still served at once while a new one is fetched behind the scenes.
// If the API errors or is unreachable, a copy up to ERROR_OK_S old is served instead of an error.
const CACHE_RULES = [
  [/^\/api\/live$/, 15],
  [/^\/api\/match$/, 15],
  [/^\/api\/(fixtures|results|match-notices|team|matches\/history|teams\/all|standings\/all|leagues|playoffs\/nlm)$/, 60],
  [/^\/api\/standings\/[A-Za-z0-9_-]+$/, 60],
  [/^\/api\/(tournaments|tournaments\/[A-Za-z0-9_-]+|seasons|seasons\/[^/]+|history\/honours|sponsors\/active|players\/top-scorers)$/, 120],
];
const STALE_OK_S = 300;       // serve-and-refresh window beyond "fresh"
const ERROR_OK_S = 3600;      // serve an old copy if the API is failing
const MAX_CACHED_BYTES = 2 * 1024 * 1024;
const EPOCH_KEY = "https://edge.internal/epoch";
const SECRET_HEADERS = ["x-admin-token", "x-agent-token", "authorization", "cookie", "x-turnstile-token", "x-push-key"];

function freshSeconds(request, url) {
  if (request.method !== "GET") return 0;
  if (url.search.length > 200) return 0;
  for (const h of SECRET_HEADERS) if (request.headers.has(h)) return 0;
  for (const [re, ttl] of CACHE_RULES) if (re.test(url.pathname)) return ttl;
  return 0;
}

function cacheKey(url) {
  const params = [...url.searchParams.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const u = new URL(url.origin + url.pathname);
  for (const [k, v] of params) u.searchParams.append(k, v);
  return new Request(u.toString(), { method: "GET" });
}

async function lastWriteTime(store) {
  try {
    const r = await store.match(EPOCH_KEY);
    return r ? Number(await r.text()) || 0 : 0;
  } catch (e) { return 0; }
}

// An admin or agent saved something through this Worker: copies made before now are out of date here.
async function noteWrite(store) {
  try { await store.put(EPOCH_KEY, new Response(String(Date.now()), { headers: { "Cache-Control": "max-age=86400" } })); } catch (e) { /* best effort */ }
}

function withCors(request, env, copy, state) {
  const h = new Headers(copy.headers);
  for (const k of [...h.keys()]) if (k.startsWith("access-control-") || k === "vary" || k === "x-edge-cached-at" || k === "set-cookie") h.delete(k);
  for (const [k, v] of Object.entries(corsHeaders(request, env))) h.set(k, v);
  h.set("Cache-Control", "no-cache");
  h.set("X-Edge-Cache", state);
  h.set("X-Content-Type-Options", "nosniff");
  return new Response(copy.body, { status: copy.status, headers: h });
}

async function fetchAndStore(request, env, url, ip, store, key) {
  const upstream = await fetch(toBackend(request, env, url, ip, undefined));
  const type = upstream.headers.get("content-type") || "";
  const cc = (upstream.headers.get("cache-control") || "").toLowerCase();
  const cacheable = upstream.status === 200 && type.includes("application/json") && !upstream.headers.has("set-cookie")
    && !cc.includes("no-store") && !cc.includes("private");
  if (!cacheable) return { upstream, stored: null };
  const bytes = await upstream.arrayBuffer();
  if (bytes.byteLength > MAX_CACHED_BYTES) return { upstream: new Response(bytes, upstream), stored: null };
  const headers = new Headers({ "Content-Type": type, "x-edge-cached-at": String(Date.now()), "Cache-Control": `max-age=${ERROR_OK_S}` });
  const copy = new Response(bytes, { status: 200, headers });
  try { await store.put(key, copy.clone()); } catch (e) { /* a failed save must never break the page */ }
  return { upstream: null, stored: copy };
}

async function cachedGet(request, env, ctx, url, ip, ttl, store) {
  const key = cacheKey(url);
  const hit = await store.match(key).catch(() => null);
  if (hit) {
    const at = Number(hit.headers.get("x-edge-cached-at") || 0);
    const age = (Date.now() - at) / 1000;
    const edited = at < (await lastWriteTime(store));
    if (!edited && age < ttl) return withCors(request, env, hit, "HIT");
    if (!edited && age < ttl + STALE_OK_S) {
      if (ctx && ctx.waitUntil) ctx.waitUntil(fetchAndStore(request, env, url, ip, store, key).catch(() => {}));
      return withCors(request, env, hit, "STALE");
    }
  }
  try {
    const { upstream, stored } = await fetchAndStore(request, env, url, ip, store, key);
    if (stored) return withCors(request, env, stored, "MISS");
    if (upstream.status >= 500 && hit && (Date.now() - Number(hit.headers.get("x-edge-cached-at") || 0)) / 1000 < ERROR_OK_S) {
      return withCors(request, env, hit, "STALE-ERROR");
    }
    const out = new Response(upstream.body, upstream);
    out.headers.set("X-Content-Type-Options", "nosniff");
    out.headers.set("X-Edge-Cache", "BYPASS");
    return out;
  } catch (e) {
    if (hit && (Date.now() - Number(hit.headers.get("x-edge-cached-at") || 0)) / 1000 < ERROR_OK_S) return withCors(request, env, hit, "STALE-ERROR");
    throw e;
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const ip = request.headers.get("CF-Connecting-IP") || "";
    if (!url.pathname.startsWith("/api/")) return new Response("Not found", { status: 404 });
    if (!env.BACKEND_URL || !env.EDGE_KEY) return reply(request, env, 503, "The app is being set up. Try again shortly.");

    if (url.pathname.startsWith(CALLBACK_PREFIX)) return handleCallback(request, env, url);

    if (!["GET", "HEAD", "POST", "DELETE", "OPTIONS"].includes(request.method)) return reply(request, env, 405, "Not allowed.");

    // Cheapest checks first: flood limits, then the human check, so bad traffic never costs Render anything.
    if (request.method === "POST" && LOGIN_PATHS.has(url.pathname)) {
      if (await limited(env.RL_LOGIN, ipKey(ip))) return reply(request, env, 429, "Too many login attempts. Wait a minute and try again.", { "Retry-After": "60" });
      if (!(await turnstileOk(request, env, ip))) return reply(request, env, 403, "Please complete the human check and try again.");
    } else if (request.method === "POST" && url.pathname === "/api/shop/orders") {
      if (await limited(env.RL_ORDER, ipKey(ip))) return reply(request, env, 429, "Too many orders from this connection. Wait a minute and try again.", { "Retry-After": "60" });
      if (!(await turnstileOk(request, env, ip))) return reply(request, env, 403, "Please complete the human check and try again.");
    }
    if (request.method !== "OPTIONS" && (await limited(env.RL_API, ipKey(ip)))) {
      return reply(request, env, 429, "Too many requests. Slow down and try again shortly.", { "Retry-After": "60" });
    }

    const store = globalThis.caches && globalThis.caches.default;
    const ttl = store ? freshSeconds(request, url) : 0;
    if (ttl) return cachedGet(request, env, ctx, url, ip, ttl, store);

    const hasBody = request.method === "POST" || request.method === "DELETE";
    const body = hasBody ? await request.arrayBuffer() : undefined;
    if (body && body.byteLength > 25 * 1024 * 1024) return reply(request, env, 413, "That upload is too large.");
    const upstream = await fetch(toBackend(request, env, url, ip, body));
    if (store && request.method !== "GET" && request.method !== "HEAD" && request.method !== "OPTIONS"
        && upstream.status < 400 && (url.pathname.startsWith("/api/admin/") || url.pathname.startsWith("/api/agent/"))) {
      await noteWrite(store); // so an admin's own change is not hidden behind a copy made a moment ago
    }
    const out = new Response(upstream.body, upstream);
    out.headers.set("X-Content-Type-Options", "nosniff");
    return out;
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(retryPending(env));
  },
};

export { retryPending, handleCallback, freshSeconds, ipKey };
