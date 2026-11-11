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

## Audit 3 (November 2026) — new code since audit 2: match corrections and the page cache

Method: attacker's-eye review of everything added since the last audit, plus a re-run of the full checks (all 6 test suites, `pip-audit` clean, `npm audit` for shipped packages clean, secrets scan of the repository clean, no `innerHTML`/`eval` anywhere in the pages, server-side fetches still limited to kenyahockeyunion.org images and pages the app already knows).

| # | Weakness | Severity | Fix |
|---|---|---|---|
| 1 | A damaged or hand-edited backup file could put a correction with nonsense values (for example a score of "abc") into the database. Every refresh would then fail on it, freezing fixtures and results at their last values until someone found and removed it. Needs the admin token to restore, so it is a safety net more than an attack, but one bad file would stop the live data. | Medium | Restore now checks every correction (league, date, names, lengths, scores 0-99 and both-or-neither, at least one real change), computes the storage key itself, and drops unknown fields. Invalid entries are skipped and counted. |
| 2 | Even with clean input, one failing correction could abort the whole refresh. | Medium | Each correction is applied on its own; a failing one is logged and skipped, the match stays as KHU shows it, and its archive record is kept. |
| 3 | The page cache kept live match details for 60 seconds, longer than the app's own 15-second rule for live matches. | Low | Match details are cached for 15 seconds, the same as live scores. |

Checked and found safe (attacker view):
- **Cache poisoning:** the cache key is the full address with options sorted, so two different questions never share an answer. None of the cached pages changes with who is asking (none reads a login token, cookie or header). Requests carrying a token, cookie or Authorization header are never cached or served from the cache. Only successful JSON answers are stored; 404s, errors and anything marked `no-store` are not.
- **Cross-site reads of cached copies:** the stored copy carries no CORS permission; permission is added per request, only for our own sites.
- **Forging the "someone saved a change" signal:** it is only set after a successful admin or agent write through the Worker, and its storage address is not reachable by any visitor request.
- **Match corrections:** admin-only (401 without the token, tested on set, list, delete and export); agents cannot use them; replacement teams must exist in the league table; text is shown with `textContent` only.

Accepted risks, your decision:
- A visitor can add random options (`?x=1`, `?x=2`, ...) to a cached address to skip the cache. That costs no more than having no cache, and the per-visitor rate limits still apply. I did not restrict which options are allowed, because forgetting one real option would show fans the wrong data.
- Cached pages can be up to 2 minutes old for fans (15 seconds for live data), and up to an hour old if Render is failing.

## Audit 4 (November 2026) — shop attacked as a buyer, a forger and a snooper

Method: a dedicated attacker script (`backend/verify_redteam.py`, 120 checks, passes on SQLite and Postgres) run against a full local copy of the shop, plus a re-read of the ordering and payment code. The live site, the Worker and Render could not be reached from the build environment, so everything below was tested locally; the "Check these on the live site" list at the end covers the part only you can test.

| # | Weakness | Severity | Fix |
|---|---|---|---|
| 1 | A payment report with an amount that is not a number ("abc", NaN, infinity) crashed the handler with a server error instead of being ignored. Only the sender of a report to the secret callback address could trigger it, but a crash on every retry is noise at best and a nuisance at worst. | Low | The amount is now converted safely; anything that is not a clean number counts as a mismatch, the order stays unpaid and is flagged for a human check. |

Attacks tried that were stopped (all passing): negative, zero, fractional, text and huge quantities; the same item split across lines to beat the per-item limit; a bad line late in an order keeping earlier stock; buyer-supplied price, total, status and delivery fee (ignored); another store's product, hidden products, closed stores; SQL injection and script text in every field and in the order lookup; path tricks and over-long ids on every public shop address; Arabic-Indic digits and letters in phone numbers; wrong, near-miss, empty and over-long callback secrets; forged payment reports with wrong, missing, negative, huge, text, NaN, null and list amounts, malformed bodies and oversized bodies; replays of a genuine report and of a failure after payment; twelve buyers grabbing the last item at once (exactly one wins, stock never below zero); visitors and guessed tokens against every admin shop address; customer details leaking in public or customer views; broken JSON, form posts, other HTTP methods, cross-site permission requests.

Accepted risks (your decision):
- Anyone can type any phone number at checkout, so a stranger can make that person's phone show an M-Pesa prompt. This is limited by the human check, one waiting payment per number, three per number per hour, a couple of unpaid orders per visitor and the Worker's flood limits. It cannot be removed completely without making buyers log in.
- A payment that arrives after the 15-minute hold is still honoured (the customer really paid). If the stock was sold meanwhile, the order is flagged "refund or fulfil by hand" in the admin page.

### Check these on the live site (5 minutes, no tools needed)
1. Open `https://khu-backend.onrender.com/api/standings/all` in a browser. Expected: an error page or "forbidden", NOT table data. If you see data, `EDGE_KEY` is not set on Render and the Worker's protection can be walked around.
2. Open `https://khu-backend.onrender.com/docs` and `/openapi.json`. Expected: not found.
3. Open `https://khu-edge.geoduor.workers.dev/api/admin/shop/overview`. Expected: "Missing or invalid admin token".
4. Open `https://khu-live-app.vercel.app/admin.html` without logging in. Expected: only a login box, no data.
5. At checkout the "I am not a robot" box must appear and the order must be refused if you skip it.
6. After Daraja go-live: place one small real order, confirm it turns "paid" in the admin page, then refund it.

## Audit 5 (November 2026) — whole codebase re-read as an attacker: logins, uploads, restore, importers, Worker, admin pages

Method: a fresh read of the sign-in and session code, the request middleware, every restore/import path, the file and image handlers, the server-side fetchers, the Cloudflare Worker and the admin/agent pages, looking for things the first four audits did not cover. New regression tests: `backend/verify_audit5.py` (28 checks; they fail on the old code and pass now) and four more in `edge/worker.test.mjs`. All earlier suites still pass. As before, this was a code review plus local attack simulations; the live Render, Vercel and Worker deployments could not be reached from the build environment.

| # | Weakness (plain English) | Severity | Fix |
|---|---|---|---|
| 1 | **One person could look like billions of visitors.** Every phone or home connection on IPv6 is given a whole block of about 18 quintillion addresses. The login lockout and every rate limit counted each address separately, so an attacker could change address on every try and never be locked out or slowed (on the API and on the Worker). | Medium | Both now count an IPv6 connection by its /64 block (the unit one connection owns); IPv4 is unchanged. `_ip_bucket()` in `main.py`, `ipKey()` in `edge/worker.js`. |
| 2 | **The admin lockout could be wiped out of memory.** When the failed-login table reached 20,000 entries the server threw away the *oldest* one, which is exactly the "admin account" counter. An attacker flooding it with fresh addresses could reset the counter and keep guessing. Merely *checking* an address also added an entry, which made the flood cheap. | Medium | Expired entries are dropped first, then address entries; the admin counter is never dropped, and checking an address no longer creates entries. |
| 3 | **The image proxy would fetch any page on KHU's site**, not only images (home page, search results, feeds, `wp-admin`), up to 240 a minute per visitor, and failed requests were never remembered. Every one is a real request to KHU from our server's address, which KHU already blocks when it sees too much (the "scraper stalled" problem). Audit 1 closed the same hole on `/api/match`; this one was missed. | Medium | Only `https://kenyahockeyunion.org/wp-content/...` is accepted (no `..`, no encoded dots, 300 characters at most), and an address that failed is not requested again for 10 minutes. |
| 4 | **Agent "Log out" only forgot the token on that phone.** The token itself stayed valid for 30 days on the server, so one copied from a shared or lost phone kept working. | Medium | New `POST /api/agent/logout` deletes the session on the server; the agent page calls it. Other sessions of the same agent are unaffected. |
| 5 | A season label ending in a newline slipped past the format check (`$` allows a trailing newline). | Low | Whole-string match. |
| 6 | A broken PDF upload returned the raw Python error text to the browser. | Low | Plain message; the detail goes to the server log only. |
| 7 | If `EDGE_KEY` is missing on Render the API quietly accepts direct traffic and the Worker's flood and password limits can be walked around. | Low | A loud warning is now written to the Render log at start-up when `EDGE_KEY` is unset. |

Checked and found safe (attacker view): admin session signing and expiry (constant-time, forged and expired tokens refused); master-token and password comparisons (constant-time); the "no such user" login path spends the same time as a real one; agent sessions are stored hashed and a deactivated agent loses access at once; every `/api/admin/*` write route checks the admin token (agents reach only the match-day routes); request-size limits run before any body is read; sponsor links must be `https://` with no embedded password and are shown as text and a plain link; sponsor and shop pictures are checked by their first bytes and served with `nosniff` and a sandbox policy; the Worker strips any `x-edge-*`, `cf-*` and `x-forwarded-for` headers a visitor sends, never caches anything carrying a token or cookie, and only echoes our own sites in CORS; no `innerHTML`, `eval` or `document.write` in the admin, agent or React code.

Still open — your decision (not changed, because each is a trade-off or needs a deliberate choice):
- **Locking out the real admin.** Thirty wrong passwords in 15 minutes lock admin sign-in for everyone, so an attacker can keep you out of the login page (not out of a session you already hold, which lasts 8 hours). The Worker's per-visitor limit and Turnstile make it costly; keep Turnstile switched on.
- **Admin sessions cannot be ended one at a time.** They are signed, not stored. To end all of them, change `ADMIN_TOKEN` on Render.
- **Agent tokens live in the phone's `localStorage` for up to 30 days** (now revocable with Log out). If agents share phones, shorten the lifetime (`timedelta(days=30)` in `database.py`).
- **Restore trusts a backup file.** Only an admin can restore, and corrections are re-checked, but shop rows (prices, image types, order status) and season data are loaded as they come. Keep backup files private and only restore files you made. The bucket's own access keys (`BACKUP_S3_*`) are the thing to protect.
- **The admin and agent pages allow inline scripts** (`'unsafe-inline'` in their security policy) because the pages are single files. Nothing injects markup today (no `innerHTML`); moving the script to its own file would let that be tightened.
- **Turnstile is off until `TURNSTILE_SECRET` is set** in the Worker (by design, documented in `docs/EDGE_SETUP.md`).

### Check these on the live site after deploying (2 minutes)
1. Render log at start-up must NOT contain "EDGE_KEY is not set". If it does, set `EDGE_KEY` (same value as in the Worker).
2. In the agent page, log in, press Log out, then press the browser Back button: you should be asked to log in again.
3. Team logos still show on Home, Table and Fixtures (if a logo is missing, send me its address; it means KHU serves it from outside `/wp-content/`).

## Contributor access (November 2026)

A contributor was added with the **Write** role. What that role can and cannot do, and the settings that keep it safe.

**He can:** create and delete his own branches, push to them, open pull requests, comment, open issues.
**He cannot:** change `main` (the "Protect main" ruleset requires a pull request, one approval and a code-owner review), change repository settings or rulesets, see Render, Vercel or Cloudflare, or read any secret. No secrets are stored in the repository or its history (checked: current files and every commit on every branch, November 2026).

Settings that must stay as they are:
1. Ruleset "Protect main" is **Active**, and its bypass list contains only the owner (Repository admin).
2. His role is **Write**, never Maintain or Admin (Admin could switch the ruleset off).
3. `CODEOWNERS` has `* @Geoduor`, so every file needs the owner's approval. Only the owner may be a code owner.
4. There are **no GitHub Actions workflows** in the repository. Any new file under `.github/workflows/` is a red flag. In Settings → Actions → General keep "Require approval for all outside collaborators" and set Workflow permissions to **Read repository contents**.
5. Render: Pull Request Previews **Disabled**; auto-deploy tracks `main` only.
6. Vercel: the `khu-live-app` project holds one variable (`REACT_APP_API_URL`, the public backend address). Do not add secrets to it. Other Vercel projects (`buddy`, `off-pitch`) are separate and not reachable from this repository.
7. The Cloudflare Worker is deployed by hand with `wrangler deploy`; nothing a contributor pushes reaches it.
8. Secret scanning and push protection are on (free for public repositories).

How a takeover could still happen: only by the owner approving a pull request that hides something. Use `docs/REVIEWING_PRS.md` and run `python3 scripts/pr_risk_check.py origin/main origin/<branch>` before approving.
