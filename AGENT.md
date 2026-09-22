# AGENT.md — KHU Live App

Context file for anyone (human or AI) picking up work on this repo. Read
this before touching `scraper.py`, the fixtures/results pipeline, or the
matching system — most "why is this written so weirdly" questions are
answered below. See also `PRD.md`, `ARCHITECTURE.md`, and `API.md` for
deeper detail on each area.

---

## What this is

A personal fan project providing live scores, standings, fixtures, team
info, and now manual-entry tooling for **Kenya Hockey Union** leagues.
Not affiliated with KHU — clearly labeled "Unofficial Fan App"
everywhere a user would see it.

- **Backend:** FastAPI + BeautifulSoup, deployed on Render (free tier)
- **Frontend:** React PWA, deployed on Vercel
- **Data sources:** live scrape of `kenyahockeyunion.org` (team-page
  based, not the season calendar view — see below), KHU's own published
  season-calendar PDFs, and manually-entered results from admin/agents
- **Repo:** `github.com/Geoduor/khu-live-app`

## Ground rule — read this first

**No hallucinated data. Ever.** Every score, standing, and fixture shown
in the app must trace back to something KHU actually published. If a
scraper can't find something, show an empty/error state — never guess,
interpolate, or carry over stale-looking-plausible data silently.

---

## Architecture (see ARCHITECTURE.md for full detail)

```
backend/
  main.py            FastAPI app, routes, scheduler, cache, merge/backfill logic, agent auth
  scraper.py         All kenyahockeyunion.org scraping — standings, team-page-based results, name corrections
  pdf_fixtures.py    KHU season-calendar PDF parsing
  database.py        SQLite — cache, PDF fixtures, manual results, agent accounts/sessions
  push.py            Web Push (VAPID) notifications
  render.yaml        Render deploy config (repo root)

frontend/khu-frontend/
  src/App.js                        Main app, all views, navigation
  src/api.js                        API client incl. logo-proxy rewriting
  src/components/                   MatchCard, LeagueTable, TeamProfile, TeamLogo, InstallBanner, etc.
  src/hooks/                        useTheme, useFavorites, usePushNotifications, useInstallPrompt
  public/admin.html                 Master admin portal (PDF upload, manual results, agent management)
  public/agent.html                 Agent login + result entry (no master token needed)
```

## The single most important thing to know: how results are actually scraped

**The obvious approach doesn't work.** `{season_url}/?action=calendar` —
the URL JoomSport's own "Calendar" tab links to — was directly fetched
and confirmed to return the *identical* standings-only HTML as the plain
season URL. No match data exists in that server-rendered page at all.
Whatever populates that tab client-side, a plain HTTP GET never receives.

**What actually works**: each team's own page
(`kenyahockeyunion.org/joomsport_team/<slug>/`) has real, complete match
history — but mixes every season together by default. The fix is
`?sid=<season_id>&jslimit=100&jscurtab=stab_matches`. The real sid for
each of the 8 current leagues was pulled directly from KHU's own site
(visible in standings-widget links) and is hardcoded in `LEAGUES` in
`scraper.py`. `scrape_league_results_via_teams()` visits every team in a
league, parses their match history, and deduplicates by match URL (a
round-robin match appears on both participating teams' pages).

**Cost of this**: ~70-90 HTTP requests per refresh cycle instead of 8. A
small courtesy delay is added between team fetches. Acceptable for a
15-minute background job; would need reconsidering if request volume
ever became a real concern for KHU's hosting.

If you're ever tempted to "simplify" this back to the calendar URL —
don't. It was tried, verified broken, and is why this exists.

## Multi-source fixtures/results — the merge rule

Three sources feed the same fixtures/results pool: **live scrape**
(primary), **PDF fixtures** (KHU's own calendar PDF, sometimes ahead of
the live site), and **manual entries** (admin/agent-confirmed). The rule
is consistent across all three: **whichever source has a given match
first is what's shown — no source overwrites another's existing entry.**
See `merge_pdf_fixtures_into_scraped()` and
`merge_manual_results_into_scraped()` in `main.py` — both implement the
identical philosophy, just for fixtures vs. results respectively.

This is why `refresh_fixtures_results()` re-applies both merges on
**every** refresh, not just once — without that, a scheduled scrape
would silently overwrite the cache with the live site's current state
(including nothing, during a genuine gap), wiping out PDF/manual data
that was only ever recorded elsewhere.

The same philosophy now applies to the **standings table itself**. It is
rebuilt on every refresh from the raw scrape as
`scraped row + effects of manual results KHU hasn't published yet +
explicit admin corrections` (see `recompute_league_standings` in
`main.py`). Recomputing from the pristine baseline is what keeps it
idempotent and stops either source from freezing or double-counting the
other: a manual result contributes only until the live scrape publishes
that same match (matched by league + teams + calendar date), at which
point the site's own numbers take back over automatically. Note the
matching deliberately EXCLUDES entries whose `source` is `"manual"` —
otherwise a manual result would look "already published" to itself and
never reach the table. When an overlay changes the numbers the table
re-sorts by points → goal difference → goals for, so positions can never
contradict the stats sitting beside them.

## Render's ephemeral filesystem

Free-tier Render wipes local disk (including SQLite) on every cold
start after inactivity. Confirmed Render behavior, not a bug. The fix:
pair every persistent table with a git-committed JSON seed file
(`pdf_fixtures_seed.json`, `manual_results_seed.json`), reloaded
automatically on every startup. After adding data you want to survive
permanently, hit the matching `/api/admin/.../export-seed` endpoint,
save the output over the seed file, and commit it.

## Team name matching — layered, and deliberately conservative

KHU is not internally consistent about team names across its own pages
(e.g. "Warriors" on standings, "Butali Warriors" on fixtures). Handled
in `main.py` in this order: exact match → curated alias groups
(`LOGO_NAME_ALIAS_GROUPS`) → conservative fuzzy match requiring:

- **Gender agreement** (`_gender_bucket`) — "Daystar University" (men)
  must never match "Daystar University Ladies."
- **Squad-qualifier agreement** (`_squad_qualifier`) — "Western Jaguars"
  must never match "Western Jaguars Dev"; hyphen-glued suffixes like
  "Lakers Hockey Club - B" are also caught (with "-A" specifically
  excluded, since it's core to USIU-A's actual name, not a reserve
  marker).
- **Uniqueness** — only acts when exactly one candidate qualifies.

A missing logo/match is always preferred over a wrong one. Don't loosen
these guards to "fix" a missing match without first checking whether
it's genuinely two different teams.

## Team profiles — built from cache, not scraped fresh

An earlier version scraped a team's own page directly for its profile.
That page mixes every season together with zero filter — confirmed by
direct inspection (2022 and 2026 matches on the same page). Team
profiles are now built entirely from already-scraped, already-trusted
data: position/form/logo from standings, fixtures/results from the same
merged pool everything else uses. See `build_team_profile_from_cache()`.

## Logo proxy

Team crests load through `GET /api/logo`, not directly from KHU's site —
direct browser loading was unreliable (suspected hotlink protection,
though this couldn't be conclusively proven from the dev sandbox, whose
own network restrictions produced a similar-looking failure). The
backend fetches server-side (proven to work — that's how the scraper
functions at all) and streams the image back under the app's own domain.
`TeamLogo.js` falls back to a generated initials avatar when no logo is
available — never a broken-image icon.

## Manual entry & agents

Two static HTML admin surfaces, served alongside the React build with
zero build-step coupling:

- `public/admin.html` — master control (PDF upload, manual results,
  agent account management). Gated by `ADMIN_TOKEN`.
- `public/agent.html` — lightweight login for people helping enter
  results. Passwords are salted PBKDF2-SHA256 (stdlib only, no new
  dependency). Deactivating an agent takes effect immediately, even for
  an already-issued session — every write re-checks `agents.active`.

Every manual result records `entered_by`.

## Known gotchas / hard-won fixes

- **JoomSport table selectors:** class `cansorttbl`, id `jstable_1` on
  standings; team-page match rows use `jstable-row` /
  `jsMatchDivTime` / `jsMatchDivHome(Embl)` / `jsMatchDivScore` /
  `jsMatchDivAway(Embl)`.
- **Form-parsing double-count bug:** use leaf-only tag matching — nested
  wrapper + inner span tags will double-count form results otherwise.
- **VAPID keys:** must be raw base64url, not PEM-armored. The Render env
  var is still named `VAPID_PRIVATE_KEY_PEM` for historical reasons even
  though it holds a raw value — don't let the name mislead you.
- **Render + Python version:** pin `PYTHON_VERSION` explicitly in
  `render.yaml` — Render ignores `runtime.txt` (a Heroku convention).
- **Vercel CI:** `CI=true` treats ESLint warnings (including unused
  variables/functions) as build-breaking errors. Always test with
  `CI=true npm run build` before pushing, not plain `npm run build`.
- **Team name corrections were originally guessed from the PDF's own
  roster page** and several were wrong — always prefer the *live site's*
  exact display text over the PDF's wording when the two disagree (see
  `pdf_fixtures.py`'s `PDF_NAME_CORRECTIONS` comments for the specific
  corrections this caused: Kenyatta University Ladies, UON Ladies,
  Strathmore University Ladies, Daystar University Ladies, Lakers
  Hockey Club).
- **Sandbox/CI network allowlists:** a sandboxed dev environment
  blocking `kenyahockeyunion.org` produces a 403 that looks identical to
  a real site-side block. Don't conclude the live site is broken without
  testing from an environment that can actually reach it (e.g. the
  deployed Render backend, or a tool with real external network access).
- **Browser-verification interstitials — NOT Cloudflare:** KHU's host
  sometimes serves a "One moment, please..." page that runs JS checks
  (webdriver / headless user-agent / plugin & mime spoofing / zero outer
  dimensions) and expects the browser to auto-submit a computed
  `wsidchk` token back to a per-site path before the real page is
  served. A Python scraper never runs that JS, so it only ever sees the
  interstitial. `scraper.py` detects it (`_looks_like_bot_challenge`),
  retries up to 3 times spaced past the page's own ~5s self-reload, and
  logs loudly if it persists; `/api/health`'s `scraper.last_challenge_at`
  reports when it last happened. While it persists, the app serves cached
  data + manual entries (which is exactly why the standings-overlay /
  backup design exists). Politeness knobs, no code change needed:
  `KHU_REQUEST_DELAY_SECONDS`, `KHU_CHALLENGE_BACKOFF_MULTIPLIER`,
  `KHU_REFRESH_INTERVAL_MINUTES`. The durable fix is KHU's cooperation
  (see PRD §6/§8) — not escalating an arms race with the filter.

## Deployment checklist

1. Backend changes → push → Render auto-deploys from `backend/`
   (`rootDir` in `render.yaml`).
2. Frontend changes → push → Vercel auto-deploys.
3. New env vars → add to both `render.yaml` (`sync: false` if secret)
   and the Render dashboard directly (Render won't auto-populate a
   `sync: false` value — you type it in once).
4. After changing `scraper.py` or `pdf_fixtures.py`'s output schema,
   re-check `main.py`'s merge functions and the frontend's `MatchCard`
   still agree on field names.
5. After adding PDF fixtures or manual results you want to persist
   permanently, export and commit the matching seed file (see above).

---

*Last updated: September 2026, after the team-page-based scraping
rewrite, multi-source results merging, and the agent/manual-entry system.*
