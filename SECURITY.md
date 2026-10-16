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

## Checked and found safe
SQL injection (every query is parameterised) · HTML injection in the React app
(no `dangerouslySetInnerHTML`, no raw `innerHTML`) · secrets in git history
(none found; `.env` and the database are ignored) · constant-time secret
comparison · agent deactivation takes effect immediately · uploaded PDFs are
admin-only and size-capped.

## Still open — your decision
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
