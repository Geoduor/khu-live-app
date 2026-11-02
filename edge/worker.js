/**
 * KHU edge Worker (Cloudflare). Sits in front of the Render API:
 *   - stops floods and password guessing before they reach Render (Cloudflare Rate Limiting bindings),
 *   - checks a Turnstile human-check on logins and shop orders (when TURNSTILE_SECRET is set),
 *   - always accepts Safaricom's M-Pesa payment report, saves it if Render is down, and retries until delivered,
 *   - tells the API the visitor's real address, signed with a secret key only this Worker and the API know.
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const ip = request.headers.get("CF-Connecting-IP") || "";
    if (!url.pathname.startsWith("/api/")) return new Response("Not found", { status: 404 });
    if (!env.BACKEND_URL || !env.EDGE_KEY) return reply(request, env, 503, "The app is being set up. Try again shortly.");

    if (url.pathname.startsWith(CALLBACK_PREFIX)) return handleCallback(request, env, url);

    if (!["GET", "HEAD", "POST", "DELETE", "OPTIONS"].includes(request.method)) return reply(request, env, 405, "Not allowed.");

    // Cheapest checks first: flood limits, then the human check, so bad traffic never costs Render anything.
    if (request.method === "POST" && LOGIN_PATHS.has(url.pathname)) {
      if (await limited(env.RL_LOGIN, ip)) return reply(request, env, 429, "Too many login attempts. Wait a minute and try again.", { "Retry-After": "60" });
      if (!(await turnstileOk(request, env, ip))) return reply(request, env, 403, "Please complete the human check and try again.");
    } else if (request.method === "POST" && url.pathname === "/api/shop/orders") {
      if (await limited(env.RL_ORDER, ip)) return reply(request, env, 429, "Too many orders from this connection. Wait a minute and try again.", { "Retry-After": "60" });
      if (!(await turnstileOk(request, env, ip))) return reply(request, env, 403, "Please complete the human check and try again.");
    }
    if (request.method !== "OPTIONS" && (await limited(env.RL_API, ip))) {
      return reply(request, env, 429, "Too many requests. Slow down and try again shortly.", { "Retry-After": "60" });
    }

    const hasBody = request.method === "POST" || request.method === "DELETE";
    const body = hasBody ? await request.arrayBuffer() : undefined;
    if (body && body.byteLength > 25 * 1024 * 1024) return reply(request, env, 413, "That upload is too large.");
    const upstream = await fetch(toBackend(request, env, url, ip, body));
    const out = new Response(upstream.body, upstream);
    out.headers.set("X-Content-Type-Options", "nosniff");
    return out;
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(retryPending(env));
  },
};

export { retryPending, handleCallback };
