# Security review — KHU Live App

Reviewed as an attacker would: every route, every input, every place the app
fetches or stores something. Re-run the checks any time with
`python backend/verify_security.py` (no network needed).

Severity: **High** = someone could take over admin or break the service ·
**Medium** = abuse or data tampering is realistic · **Low** = hardening.

## Fixed

| # | Severity | What was wrong (plain English) | Fix |
|---|---|---|---|
| 1 | High | **Login lockout could be skipped.** The server believed whatever "X-Forwarded-For" header the visitor sent, so an attacker could pretend to be a new person on every guess and try unlimited passwords. | Only the address added by Render's own proxy is trusted (`TRUSTED_PROXY_HOPS`). Added a per-agent-account lockout (10 fails) and a global admin cap (30 fails) so a botnet can't spread guesses across many IPs. |
| 2 | High | **The admin page stored the permanent master key in the browser.** Any script bug on the site, or anyone with the device, could copy a key that never expires. | Admin login now returns a signed 8-hour session token kept in `sessionStorage` (gone when the tab closes). The master `ADMIN_TOKEN` never reaches a browser. Changing `ADMIN_TOKEN` instantly kills every session. |
| 3 | High | **Text injection in admin/agent pages.** Team and player names were pasted into the page as HTML, so a crafted name could run a script inside an admin's browser. | Pages now build content with text nodes only (no `innerHTML`). Tested with hostile names. |
| 4 | High | **Anyone could send a notification to every subscriber** (`/api/push/test`) and **start a full scrape** (`/api/refresh`, which also held the request open for minutes). | Test push is admin-only. Refresh runs in the background, one at a time, once per 5 minutes. |
| 5 | Medium | **The server could be tricked into fetching other addresses.** Image/page fetches followed redirects anywhere; a redirect on the KHU site could point at internal addresses. | `safe_get()` follows redirects only while every hop is on kenyahockeyunion.org. Push subscriptions only accept real push services (Google, Mozilla, Microsoft, Apple). |
| 6 | Medium | **Logo proxy had no size limit and accepted SVG** (SVG can carry scripts). Many different URLs could fill server memory. | 2 MB cap, PNG/JPEG/GIF/WebP/ICO only, `nosniff` + sandbox CSP, rate-limited. |
| 7 | Medium | **`/api/match` would fetch any page on KHU's site** on request, so someone could make our server hammer KHU (and get our IP blocked). | Only matches already in our own fixtures/results are fetched; rate-limited. |
| 8 | Medium | **No rate limits on public endpoints.** | Per-IP limits on team, match, logo, push and login routes. |
| 9 | Medium | **An agent account could overwrite the standings table and player stats.** Agents only need to enter results. | Team-stats and player-stats routes are admin-only. |
| 10 | Medium | **No browser security headers** (no CSP, framing allowed → clickjacking, no HSTS). | `frontend/khu-frontend/vercel.json` adds CSP, frame-ancestors none, HSTS, nosniff, referrer and permissions policies; admin/agent pages are also `noindex` and uncacheable. The API sends nosniff/DENY/HSTS and `no-store` on admin routes. |
| 11 | Medium | **Outdated libraries with known CVEs**: FastAPI/Starlette (multipart DoS), python-multipart, pdfminer (unsafe pickle in crafted PDFs), requests, axios. | Upgraded and pinned in `requirements.txt` / `package.json`; all tests re-run on a clean install. |
| 12 | Medium | **Unlimited input sizes** (names, lists, scores) and **unlimited push subscriptions.** | Length/range limits on every input model; 5,000-subscription cap; max 60 favourites. |
| 13 | Low | Weak password handling: 100k PBKDF2 rounds, 6-character minimum. | 600k rounds for new passwords, old hashes upgrade automatically at next login; minimum 10 characters. |
| 14 | Low | `/docs` and `/openapi.json` listed every admin route publicly. | Off unless `KHU_ENABLE_DOCS=1`. |
| 15 | Low | CORS allowed credentials and every method/header. | No credentials (auth uses headers), only the methods/headers the app uses; a warning is logged if `ALLOWED_ORIGINS` is unset. |
| 16 | Low | A push payload could in theory open another website. | Notification clicks stay on the app's own origin. |
| 17 | Low | Raw scraped pages were written to disk on failures. | Only when `KHU_DEBUG_DUMP=1`. |
| 18 | Medium | **Session tokens were stored as-is** in the database. | Agent sessions are stored as SHA-256 hashes; a database leak no longer gives usable sessions. |
| 19 | Medium | **Player photos could carry scripts or be fake images.** | Photos are accepted only as PNG/JPEG/WebP judged by the file's own first bytes (SVG refused), capped at 300 KB, served with `nosniff` and a sandbox CSP. The admin/agent forms shrink photos in the browser first. Only admins can delete a profile. |
| 20 | Medium | **The squad importer could be pointed at other sites.** | It only fetches pages and images through `safe_get()` (KHU's own host, redirects checked), is admin-only, rate-limited, and runs one at a time. It never overwrites data an admin or agent entered. |

## Checked and found safe
SQL injection (every query is parameterised) · HTML injection in the React app
(no `dangerouslySetInnerHTML`, no raw `innerHTML`) · secrets in git history
(none found; `.env` and the database are ignored) · constant-time secret
comparison · agent deactivation takes effect immediately · uploaded PDFs are
admin-only and size-capped.

## Still open — your decision
- **Player photos are personal data.** Only add a photo with the player's permission (a parent or guardian's for anyone under 18). Do not store dates of birth, addresses or phone numbers; the app has no field for them. Any profile or photo can be removed from the admin or agent Players form.
- **Page security policy:** `admin.html` and `agent.html` allow images only from the site itself and `data:` (no `blob:`). Code that previews uploads must read files with `FileReader`, not `URL.createObjectURL`.
- **Rotate `ADMIN_TOKEN` after deploying this.** Before the fix it lived in
  browsers; a new value also invalidates any old session. Use a 40+ character
  random string.
- Agents can delete *any* manual result (a deliberate choice documented in the
  code). Say if you want agents limited to their own entries.
- One shared admin password, no 2-factor sign-in.
- Push subscribe/unsubscribe are public by design; the long subscription URL is
  the only secret, and they are now rate-limited and capped.
- Rate limits live in memory (reset on restart; fine for one Render instance).
- `npm audit` still lists many issues, all inside `react-scripts` build tooling
  (not shipped to users). Moving off Create React App is the long-term fix.
- This was a code review plus local attack simulations. It was not a test of the
  live Render/Vercel deployment.

## New settings (all optional)
`TRUSTED_PROXY_HOPS` (default 1) · `KHU_ENABLE_DOCS` · `KHU_DEBUG_DUMP`.
Keep `ALLOWED_ORIGINS` set to your Vercel address(es) only.


## Shop and payments

- Prices, totals and delivery fees are always computed on the server from the product list; quantities are capped, so a tampered request cannot change what is charged.
- Stock is reserved in one atomic step when an order is created and released if payment fails, times out (15 minutes) or the order is cancelled, so the last item cannot be sold twice.
- An order is marked paid only by Safaricom's callback (sent to a URL containing a secret, compared in constant time) or by the server's own query to Safaricom, and only when the amount matches. The browser can never mark an order paid. Repeated callbacks are harmless.
- Rate limits: 6 orders per 10 minutes per IP and 4 per hour per phone number; order status needs the order code and the phone number.
- Customer name, phone and address are personal data: shown only on the admin page, included in the nightly backup, and covered by the privacy notice. M-Pesa keys live only in Render environment variables.
- Admin store/product text is shown with `textContent`, never HTML; product pictures are checked by their bytes (no SVG).

### Shop review findings (attacker view) and fixes

| # | Weakness | Severity | Fix |
|---|---|---|---|
| 1 | Anyone could place unpaid orders (typing any phone number) to lock stock for 15 minutes each, or to flood a stranger's phone with M-Pesa prompts | Medium | A phone with a payment waiting cannot get another; 3 orders per phone per hour; one visitor can hold at most 2 unpaid orders at once |
| 2 | A "payment succeeded" callback with no amount would have been accepted as paid | Medium (needs the callback secret) | Callbacks without an amount are never marked paid; the admin is told to check M-Pesa |
| 3 | The secret callback URL appeared in the server's request log | Low | The secret is masked in logs |
| 4 | Existing: fresh Postgres could lose the match-notice tables | Low | Committed on creation |

Still your decision: a determined attacker with many phone numbers and IP addresses could still tie up a small catalogue for short periods. Keep stock counts honest, watch the *Waiting for payment* count on the Shop tab, and rotate `MPESA_CALLBACK_SECRET` if the logs were ever shared.

## Edge layer (optional Cloudflare Worker)

- Flood and password-guess limits run on Cloudflare before traffic reaches Render; logins and shop orders can require a Turnstile human check.
- With `EDGE_KEY` set on Render, requests lacking the Worker's secret key get 403 (except `/api/health`, browser preflight and Safaricom's secret-URL callback). The visitor address is taken from the Worker only when that key matches, so nobody can fake it.
- The M-Pesa callback goes through the Worker, which saves a report if Render is down and re-sends it every minute (up to 24 hours). The API also checks waiting orders with Safaricom every minute, so a missed report cannot leave a paid order stuck.
- The secret keys (`EDGE_KEY`, Turnstile secret, callback secret) live only in Cloudflare and Render settings. The Turnstile *site key* in `edge-config.js` is public by design.
- Orders status lookups are no longer stored in the phone's offline cache.

## Full audit (November 2026) — findings and fixes

Method: every one of the 101 API routes checked for an authorisation call in its handler (the only admin path without one is the login itself; agents can reach only the match-day routes); every database query checked for safe parameters; the pages checked for HTML injection (none: no `innerHTML`); Python libraries checked with `pip-audit` (no known flaws) and the packages shipped to browsers with `npm audit` (none flagged; the remaining warnings are build tooling that never reaches fans).

| # | Weakness | Severity | Fix |
|---|---|---|---|
| 1 | Anyone could send a huge request (60 MB tested) to a public address; the server read and parsed all of it before any check, a cheap way to exhaust memory and CPU | Medium | Body limits before anything is read: 1 MB for fans, 30 MB for admin/agent, also for chunked uploads with no declared size (413) |
| 2 | Anyone could stuff the push-notification list with junk subscriptions (fake keys), crowding out real fans | Low | Subscription keys must have the real browser format (65-byte public key, 16-byte secret) |
| 3 | Anyone could inflate a sponsor's views and clicks (60 a minute from one connection) | Low | Per visitor and sponsor: at most 3 clicks and 40 views counted per hour |

Accepted risks, your decision:
- `POST /api/refresh` is public by design (pull-to-refresh). It is limited to one real scrape every 5 minutes for everyone, but a determined visitor can use up that slot. Impact: at worst slightly staler data. Make it admin-only if this ever matters.
- Agent logins lock an account for 15 minutes after 10 failed tries, so someone who knows an agent's username could keep that agent locked out. The Worker's per-visitor limit softens this.
- Push unsubscribe and favourites are keyed by the subscription address, which works like a password held only by that phone.
