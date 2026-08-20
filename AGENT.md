# AGENT.md — KHU Live App

Context file for anyone (human or AI) picking up work on this repo. Read this
before touching `scraper.py` or the fixtures pipeline — most of the "why is
this written so weirdly" questions are answered below.

---

## What this is

A personal fan project providing live scores, standings, fixtures, and team
info for **Kenya Hockey Union** leagues. Not affiliated with KHU.

- **Backend:** FastAPI + BeautifulSoup, deployed on Render
- **Frontend:** React PWA, deployed on Vercel
- **Data source:** `kenyahockeyunion.org` (runs JoomSport on WordPress) +
  official KHU season-calendar PDFs (see "Dual-Source Fixtures" below)
- **Repo:** `github.com/Geoduor/khu-live-app`

## Ground rule — read this first

**No hallucinated data. Ever.** Every score, standing, and fixture shown in
the app must trace back to something KHU actually published — either scraped
from their live site or extracted from their own PDF. If a scraper can't find
something, the correct behavior is to show an empty/error state, never to
guess, interpolate, or carry over stale-looking-plausible data silently.

---

## Architecture

```
backend/
  main.py           FastAPI app, routes, scheduler, in-memory cache layer
  scraper.py         JoomSport HTML scraping (standings, fixtures, results, live)
  pdf_fixtures.py    KHU season-calendar PDF parsing (see below)
  database.py        SQLite persistence — survives backend restarts
  push.py            Web Push / VAPID notifications
  render.yaml         Render deploy config (repo root, not backend/)

frontend/khu-frontend/
  src/App.js          Main app + views (Standings, Fixtures, Results, Team, Match)
  ...React PWA, service worker, push subscription handling
```

### Data flow

1. **Live scrape** (`scraper.py`) runs on startup, every 15 min (scheduled),
   and on manual pull-to-refresh. Hits `kenyahockeyunion.org`'s JoomSport
   tables and per-league `?action=calendar` pages.
2. **PDF ingestion** (`pdf_fixtures.py`) runs only when an admin uploads a
   PDF via `POST /api/admin/fixtures/upload-pdf`. Parsed matches are stored
   **permanently** in a separate SQLite table (`pdf_fixtures_store`).
3. **Every refresh cycle** (step 1) re-merges whatever's in
   `pdf_fixtures_store` into the freshly-scraped fixtures before caching.
   This is the important part — see below.

---

## Dual-Source Fixtures — why this exists

KHU **regularly** (confirmed recurring, not a one-off) publishes the season's
fixture calendar as a PDF — sometimes before the live JoomSport site's
calendar view is updated to match. Relying on the live scrape alone means the
Fixtures tab can go empty for days even though KHU has already told the world
the schedule.

**Critical implementation detail:** `refresh_fixtures_results()` in
`main.py` re-merges `db.load_pdf_fixtures()` into the scrape result on
**every single refresh**, not just at upload time. If you ever refactor this
function, preserve that merge step — without it, the next scheduled scrape
(15 min later) will silently overwrite the cache with the live site's
current state, wiping out any PDF-only fixtures. This was a real bug caught
in production (Aug 2026) — the live site had zero fixtures listed during a
KHU-published league break, and the schedulerkept re-caching that emptiness
until the merge step was added.

**Dedup rule** (`pdf_fixtures.merge_pdf_fixtures_into_scraped` /
`database._pdf_match_key`): a PDF fixture is considered "the same match" as
a scraped one if `league_short + home_team + away_team + date` (date only,
not kickoff time) match. Live-scraped data always wins on conflict — PDF
fixtures only fill gaps, never override live data.

### Team name shorthand in PDFs

KHU's PDF fixture tables use different name shorthand than the live site
(`"KU Ladies"` in the PDF vs `"Kenyatta University"` on the site). This is
bridged by `PDF_NAME_CORRECTIONS` in `pdf_fixtures.py` — separate from
`TEAM_NAME_CORRECTIONS` in `scraper.py`, which fixes actual site typos.

**Known blind spot:** bare `"Lakers"` in a PDF is currently always resolved
to `Lakers Hockey Club Ladies`, because that's the only context it's
appeared in so far. If a future PDF uses unqualified `"Lakers"` for a men's
fixture, it'll mis-tag it. Don't guess a fix without evidence from an actual
PDF — flag it and wait for the ambiguous case to actually occur.

### Uploading a new PDF

```bash
curl -X POST \
  -H "x-admin-token: $ADMIN_TOKEN" \
  -F "file=@/path/to/calendar.pdf" \
  https://<render-backend-url>/api/admin/fixtures/upload-pdf
```

Re-uploading (e.g. a corrected "Ver 03" PDF) upserts by match key — no
duplicates, corrections to time/venue/etc. take effect automatically.

---

## Known gotchas / hard-won fixes

- **JoomSport table selectors:** class `cansorttbl`, id `jstable_1`. Column
  order: `#/Teams/Pl/W/D/L/Diff/GD/Pts/Current Form`. Per-league calendar
  uses `?action=calendar` URLs.
- **Form-parsing double-count bug:** use leaf-only tag matching — nested
  wrapper + inner span tags will double-count form results if you don't.
- **VAPID keys:** must be raw base64url (32-byte private key), **not**
  PEM-armored. Passing PEM causes "ASN.1 parsing error: invalid length" in
  `py_vapid`. (Note: the Render env var is still named
  `VAPID_PRIVATE_KEY_PEM` for historical reasons even though it holds a raw
  value — don't let the name mislead you.)
- **Render + Python version:** must set `PYTHON_VERSION: 3.11.9` (or your
  pinned version) explicitly in `render.yaml`. Render ignores `runtime.txt`
  (that's a Heroku convention). Newer Python defaults can break
  `pydantic-core` wheel availability.
- **Vercel CI:** `CI=true` treats unused variables as build errors. Strip
  unused destructured variables before every commit.
- **Team name corrections** (`scraper.TEAM_NAME_CORRECTIONS`): e.g.
  `"Kisumu Youngsters"` → `"Kisumu Youngstars"` — confirmed site typo.
- **League exclusions** (`scraper.LEAGUE_EXCLUSIONS`): e.g. Kenyatta
  University Ladies excluded from Super League Women — confirmed KHU site
  error, not a scraper bug.
- **Placeholder teams:** Kisii University Ladies added as an honest
  placeholder in SLW via `inject_placeholder_teams()` — auto-removes once
  KHU publishes the real entry.
- **Service worker:** network-first, not cache-first. Cache-first caused
  blank screens on refresh after deployments.
- **Sandbox/CI network allowlists:** `kenyahockeyunion.org` is typically
  NOT on a sandboxed dev environment's network allowlist. Don't assume a
  live-scrape test will work in CI/sandbox without checking egress rules
  first — verify against a real deploy instead.

---

## Environment variables (backend)

See `backend/env.example` for the full template. Notable ones:

| Var | Purpose |
|---|---|
| `ADMIN_TOKEN` | Gates `POST /api/admin/fixtures/upload-pdf`. Fails closed if unset. |
| `VAPID_PRIVATE_KEY_PEM` / `VAPID_PUBLIC_KEY_B64URL` | Web Push — raw base64url, not PEM despite the var name. |
| `VAPID_CONTACT_EMAIL` | Required by the Web Push protocol. |
| `ALLOWED_ORIGINS` | CORS — must include the Vercel frontend URL. |
| `PYTHON_VERSION` | Must be pinned in `render.yaml`, not `runtime.txt`. |

`render.yaml` lives at the **repo root**, not inside `backend/`.

---

## Deployment checklist

1. Backend changes → push → Render auto-deploys from `backend/` (`rootDir`
   set in `render.yaml`).
2. Frontend changes → push → Vercel auto-deploys.
3. New env vars → add to **both** `render.yaml` (as `sync: false` if
   secret) **and** the Render dashboard (`sync: false` means Render won't
   auto-populate it — you must type the value in manually once).
4. After any change to `scraper.py` or `pdf_fixtures.py`'s output schema,
   re-check `main.py`'s `_group_and_sort_matches` and the frontend's
   `MatchCard`/`GroupedMatchList` still agree on field names.

---

*Last updated: August 2026, during the PDF-fixtures dual-source pipeline build.*
