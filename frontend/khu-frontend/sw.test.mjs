// Offline checks for the service worker's request handling. Run: node sw.test.mjs
import fs from "node:fs";
import vm from "node:vm";
let fails = 0;
const check = (label, ok) => { console.log(`  [${ok ? "PASS" : "FAIL"}] ${label}`); if (!ok) fails++; };
const listeners = {};
const self_ = { location: { origin: "https://app.test" }, addEventListener: (t, f) => { listeners[t] = f; }, skipWaiting() {}, clients: { claim() {} }, registration: {} };
const ctx = vm.createContext({ self: self_, caches: { open: async () => ({ addAll: async () => {}, put: async () => {} }), keys: async () => [], match: async () => undefined, delete: async () => true }, fetch: async () => new Response("x"), URL, Response, console });
vm.runInContext(fs.readFileSync(new URL("./public/service-worker.js", import.meta.url), "utf8"), ctx);
const handled = (url, method = "GET") => {
  let took = false;
  listeners.fetch({ request: { url, method }, respondWith: () => { took = true; } });
  return took;
};
console.log("Service worker request handling");
check("Cloudflare Turnstile script is left alone", !handled("https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"));
check("any other website's script is left alone", !handled("https://example.com/lib.js"));
check("our own pages and files are still handled", handled("https://app.test/") && handled("https://app.test/static/js/main.js"));
check("the API on the Worker address still gets the offline fallback", handled("https://khu-edge.x.workers.dev/api/standings/all"));
check("the API on the Render address still gets the offline fallback", handled("https://khu-backend.onrender.com/api/fixtures"));
check("orders are never touched", !handled("https://khu-edge.x.workers.dev/api/shop/orders/1"));
check("POST requests are never touched", !handled("https://app.test/api/analytics/hit", "POST"));
console.log(fails ? `\n${fails} FAILED` : "\nall checks passed");
process.exit(fails ? 1 : 0);
