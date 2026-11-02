# Edge setup: Cloudflare Worker in front of the API

The Worker (`edge/worker.js`) stands between the app and Render. It:

1. **Stops floods and password guessing** before they reach Render (limits per visitor address).
2. **Adds a human check (Cloudflare Turnstile)** on admin login, agent login and shop ordering.
3. **Never misses an M-Pesa payment report.** It always answers Safaricom, saves the report if Render is restarting, and re-sends it every minute until Render accepts it.
4. **Locks Render so only the Worker can use the API.** Anyone calling the Render address directly gets "403".

Everything stays off until you do the steps below, so merging the code changes nothing by itself. Do the steps in this order. Everything runs on Cloudflare's free plan.

## 0. What you need

- A free Cloudflare account (you already have one for backups).
- Node installed on your computer (for the `wrangler` tool), or ask me for a click-through version using the dashboard.

## 1. Create the Turnstile human check

Cloudflare dashboard → **Turnstile** → **Add widget**. Name it `KHU`, add the domains `khu-live-app.vercel.app` (and `localhost` if you test locally), type **Managed**. You get two keys:

- **Site key**: public. It goes in `frontend/khu-frontend/public/edge-config.js`.
- **Secret key**: private. It goes only into the Worker (step 3). Never paste it in chat or commit it.

## 2. Create the retry store

In the `edge` folder:

```
npm install -g wrangler
wrangler login
wrangler kv namespace create RETRY
```

Paste the printed `id` into `edge/wrangler.toml` (replace `PASTE_KV_NAMESPACE_ID_HERE`).

## 3. Add the secrets and deploy

Make two long random strings (30+ characters each): one is the **edge key**, the other you already have as `MPESA_CALLBACK_SECRET`. Then:

```
wrangler secret put EDGE_KEY            # the new edge key
wrangler secret put CALLBACK_SECRET     # same value as MPESA_CALLBACK_SECRET on Render
wrangler secret put TURNSTILE_SECRET    # the Turnstile SECRET key (leave this out to keep the human check off)
wrangler deploy
```

Wrangler prints the Worker address, like `https://khu-edge.YOURNAME.workers.dev`. Check `BACKEND_URL` and `ALLOWED_ORIGINS` in `edge/wrangler.toml` match your Render and Vercel addresses.

## 4. Point the app at the Worker

Edit `frontend/khu-frontend/public/edge-config.js`:

```js
window.KHU_EDGE = {
  apiBase: "https://khu-edge.YOURNAME.workers.dev",
  turnstileSiteKey: "YOUR_SITE_KEY"
};
```

Push to the branch Vercel deploys. The same file drives the fan app, the admin page and the agent page. Also tighten the two `https://*.workers.dev` entries in `frontend/khu-frontend/vercel.json` to your exact Worker address.

**Test before locking Render:** open the app, check standings load, log in on the admin page (you will see the human check), and place a sandbox order.

## 5. Make M-Pesa report to the Worker

On Render, set `MPESA_CALLBACK_BASE` to the Worker address (same value as `apiBase`). New payment prompts now tell Safaricom to report to the Worker. Orders already waiting keep their old address, which still works.

## 6. Lock Render (last step)

On Render, add `EDGE_KEY` with the **same** value as the Worker's `EDGE_KEY`. From then on only the Worker can use the API; Safaricom's secret-URL callback and `/api/health` stay open as a backup.

If something goes wrong, **delete `EDGE_KEY` on Render** and Render accepts direct calls again. You can also set `apiBase: ""` in `edge-config.js` to send the app straight to Render.

## Extra protection in the Cloudflare dashboard (no code)

- **Security → WAF → Rate limiting rules**, Cloudflare's own firewall in front of everything: for example 20 requests per 10 seconds per visitor on `/api/*`.
- **Security → Bots → Bot Fight Mode**: on.

## What this does not do

It does not decide prices, stock or who is logged in. That stays on the API. If Render is down, fans still can't load data, but payments are never lost.

## Checking it works

- Hit the Render address directly in a browser: you should see "Use the official app address." (after step 6).
- Try a wrong admin password 6 times quickly: you should be blocked for a minute.
- Place a sandbox order, then restart Render during the payment: the order should still turn paid within a minute or two.

## Testing the code

- Worker: `cd edge && node worker.test.mjs` (23 checks, no setup).
- API side: `cd backend && python verify_edge.py`.
