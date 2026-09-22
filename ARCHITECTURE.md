# KHU Live App — Architecture

This document explains how the system is built and, more importantly,
**why** — several design decisions exist specifically because an earlier,
more obvious approach was tried first and found to be broken. Where that's
true, it's called out explicitly so nobody re-introduces the same bug.

---

## 1. High-level overview

```
┌─────────────────┐         ┌──────────────────────┐         ┌─────────────────────┐
│  React PWA       │  HTTPS  │  FastAPI backend      │  HTTPS  │  kenyahockeyunion.org │
│  (Vercel)        │◄───────►│  (Render, free tier)  │◄───────►│  (JoomSport/WordPress)│
└─────────────────┘         └──────────┬───────────┘         └─────────────────────┘
                                        │
                                        ▼
                              ┌──────────────────┐
                              │  SQLite           │
                              │  (ephemeral disk — │
                              │   see §4)          │
                              └──────────────────┘
```

- **Frontend**: React PWA, deployed on Vercel. `frontend/khu-frontend/`.
- **Backend**: FastAPI + BeautifulSoup, deployed on Render's free tier.
  `backend/`.
- **Data sources**: KHU's live site (scraped), KHU's own published PDF
  season calendars (parsed), and manually-entered results (human-verified).

## 2. Backend structure

| File | Responsibility |
|---|---|
| `main.py` | FastAPI app, all routes, in-memory cache, scheduler, merge/backfill logic |
| `scraper.py` | Everything that talks to kenyahockeyunion.org — standings, fixtures/results, team pages |
| `pdf_fixtures.py` | Parses KHU's season-calendar PDF into the same match schema as the live scraper |
| `database.py` | SQLite persistence layer — cache, PDF fixtures, manual results, agent accounts/sessions |
| `push.py` | Web Push (VAPID) notifications for favorited teams going live |

### Data flow per refresh cycle (every 15 minutes, plus on-demand)

1. **Standings** are scraped first, per league, from each league's
   season-specific URL (e.g. `.../premier-league-men-plm-2026/`). This
   also captures each team's real page URL and logo — both needed by
   later steps.
2. **Fixtures/results/live** are built by visiting **every team's own
   page**, filtered to the current season (see §3 for why this replaced
   a much simpler-looking approach).
3. **PDF-sourced fixtures** (if any have been uploaded) are merged in —
   filling gaps the live scrape hasn't caught, never overwriting a live
   match that's already present.
4. **Manually-entered results** (if any) are merged in the same way.
5. **Standings overlays are recomputed** from the raw scrape: the table
   users see is `scraped row + effects of manual results the site hasn't
   published yet + explicit admin corrections`, rebuilt from a pristine
   baseline every time (see `recompute_league_standings` in `main.py`).
   This is idempotent, so the two sources genuinely back each other up:
   while KHU's table lags, manual results carry it; the moment the site
   publishes a match, that match's manual effect drops out of the table
   and the site's own numbers take over — automatically, no cleanup.
6. **Team logos** are backfilled from standings data wherever a fixture
   or result is missing one, using exact match → known-alias match →
   conservative fuzzy match (see §5).
7. Past-dated fixtures are filtered out of "upcoming" at request time
   (not just at refresh time), so staleness never depends on when the
   last scheduled refresh happened to run.

## 3. Why fixtures/results come from team pages, not the season calendar

The obvious approach — fetch `{season_url}/?action=calendar`, since that's
the URL JoomSport's own "Calendar" tab links to — **does not work**. This
was verified by directly fetching that exact URL: it returns the
identical standings-only HTML as the base season URL. The calendar tab's
content isn't something a plain HTTP GET ever receives; whatever populates
it client-side isn't present in the server-rendered page at all.

What **does** reliably contain full match history, confirmed by direct
inspection, is each team's own page
(`kenyahockeyunion.org/joomsport_team/<slug>/`). The catch: by default it
mixes together every season a team has ever played. The fix is a
`?sid=<season_id>` query parameter that scopes the page to one season.
The real season ID for each of KHU's 8 current leagues was obtained
directly from their own site (visible in standings-widget links) and is
hardcoded in `scraper.py`'s `LEAGUES` dict.

**Tradeoff**: this means one HTTP request per team instead of one per
league — roughly 70-90 requests per refresh cycle instead of 8. A small
courtesy delay is added between requests to avoid hammering KHU's server.
Matches that appear on both participating teams' pages are deduplicated
by their match URL.

## 4. Render's ephemeral filesystem

Render's free tier wipes the backend's local disk — including the SQLite
database — every time the service spins down from inactivity and cold-
starts again. This is documented Render behavior, not a bug, but it means
anything written only to SQLite disappears unpredictably.

**Pattern used everywhere this matters**: pair the database table with a
git-committed JSON seed file (`pdf_fixtures_seed.json`,
`manual_results_seed.json`). On every startup, the seed file is loaded
back into the database automatically. After adding new PDF fixtures or
manual results, hit the matching `/api/admin/.../export-seed` endpoint,
save its output over the seed file, and commit it — that's what makes
the addition survive future cold starts permanently, not just until the
next restart.

## 5. Team name matching

KHU is not internally consistent about team names across different pages
of its own site — e.g. standings shows "Warriors," fixtures shows "Butali
Warriors." This is handled in layers, from most to least precise:

1. **Exact match** on the normalized name.
2. **Known alias groups** (`LOGO_NAME_ALIAS_GROUPS` in `main.py`) — a
   curated list of confirmed same-team name pairs.
3. **Conservative fuzzy match** — one name's significant words are a
   subset of the other's, **but only if**:
   - Gender matches (`_gender_bucket`) — "Daystar University" (men,
     unsuffixed) must never match "Daystar University Ladies."
   - Squad qualifier matches (`_squad_qualifier`) — "Western Jaguars"
     must never match "Western Jaguars Dev"; a trailing hyphenated
     letter like "Lakers Hockey Club - B" is also caught, with "-A"
     specifically excluded since it's core to some teams' actual names
     (USIU-A), not a reserve-team marker.
   - Exactly one candidate satisfies the match — if two different teams
     could both plausibly match, no logo is assigned rather than
     guessing.

This same matching system is reused for logo backfill, team profile
lookup, and manual/PDF/live result deduplication.

## 6. Team profiles — built from cache, not scraped fresh

An earlier version scraped each team's own page directly for its
profile. That page mixes every season together with no filter — a real
bug, not a hypothetical, confirmed by direct inspection (2022 and 2026
matches on the same page). Team profiles are now built entirely from
data already scraped and trusted elsewhere: position/form/logo from
standings, fixtures/results from the same merged pool the Fixtures and
Results tabs use. This guarantees a team's profile can never disagree
with what's shown elsewhere in the app, and avoids the season-mixing
problem entirely.

## 7. Image handling

Team crest URLs load through a backend proxy (`GET /api/logo`) rather
than directly from KHU's site. Direct browser loading was unreliable —
suspected referrer/hotlink protection on their WordPress host, though
this couldn't be conclusively proven from the development sandbox (whose
own network restrictions produced a similar-looking failure). The proxy
fetches server-side (where requests demonstrably work, since that's how
the scraper functions at all) and streams the image back under the app's
own domain, with a small in-memory cache. When no logo is available at
all, `TeamLogo.js` falls back to a generated initials avatar rather than
a broken-image icon.

## 8. Manual data entry & agents

Two admin surfaces, both static HTML files served alongside the React
build (no build-step dependency, zero risk to the main app bundle):

- `public/admin.html` — master control: add/edit/delete manual results,
  upload PDF calendars, create/deactivate agent accounts. Gated by
  `ADMIN_TOKEN`.
- `public/agent.html` — a lightweight login for people helping enter
  results day-to-day, without the master token. Agent passwords are
  salted PBKDF2-SHA256 hashes (Python stdlib `hashlib`/`secrets` — no
  extra dependency). Deactivating an agent takes effect immediately,
  even for an already-issued session token, since every write re-checks
  the account's active status.

Every manually-entered result records `entered_by` (the agent's display
name, or "Admin"), giving a real accountability trail.

## 9. Frontend structure

| Path | Responsibility |
|---|---|
| `src/App.js` | Main app shell, all views (Home, Table, Fixtures, Results), navigation |
| `src/api.js` | Backend API client, including the logo-proxy URL rewriter |
| `src/components/` | `MatchCard`, `LeagueTable`, `TeamProfile`, `TeamLogo`, `PlayoffBracket`, `InstallBanner`, etc. |
| `src/hooks/` | `useTheme`, `useFavorites`, `usePushNotifications`, `useInstallPrompt`, `useDiffedStandings` |
| `public/` | Static assets, manifest, service worker, `admin.html`, `agent.html` |

Fixtures and Results share the same date-grouping and league-filter
dropdown components (`DateGroupedMatchList`, `LeagueFilterSelect`) —
Results additionally groups by league (mirroring the backend's own
league-then-date sort order) since agents/fans tend to want a specific
league's recent results together, most-recent-first.

## 10. Known limitations

- Refresh cycles are heavier now (team-page-based) than the original
  calendar-based design was intended to be — acceptable for a 15-minute
  background job, but worth remembering if request volume ever becomes
  a concern with KHU's hosting.
- The gender/squad-qualifier matching guards are deliberately
  conservative — they will sometimes fail to match two names that really
  are the same team, rather than risk merging two that aren't. A missing
  logo is preferred over a wrong one.
- No automated tests run in CI yet — verification has been done via
  targeted manual test scripts during development, not a persistent test
  suite.
