# KHU Live App — Product Requirements Document

**Status:** Live (unofficial), pending Kenya Hockey Union review/partnership
**Owner:** Geofry
**Last updated:** September 2026

---

## 1. Problem

Kenya Hockey Union (KHU) publishes standings, fixtures, and results on
`kenyahockeyunion.org` — a desktop-oriented WordPress site running the
JoomSport plugin. Fans following the league on mobile find it hard to
navigate: multi-step menus, no unified live-score view, and inconsistent
data presentation across leagues.

There was no dedicated app for KHU fans. KHU Live fills that gap.

## 2. Goals

- Give fans a fast, mobile-first way to check live scores, standings,
  fixtures, and results across every KHU league.
- Be installable like a real app (home-screen icon, offline shell) without
  requiring an app store — critical given the app launched before KHU
  approval was granted.
- Never show fabricated data. Every number traces back to something KHU
  itself published — scraped from their site, extracted from their own
  PDF calendar, or manually entered by a real person who verified it.
- Stay resilient to KHU's site being inconsistently structured or
  occasionally broken, without silently showing wrong information.

## 3. Non-goals (for now)

- Not seeking app-store distribution (PWA install covers this need at
  much lower risk while KHU approval is pending).
- Not claiming official status. The app is explicitly labeled "Unofficial
  Fan App" everywhere a user would see it (header, browser tab, PWA
  manifest) until/unless KHU grants recognition.
- Not building fan engagement features unrelated to live sports data
  (no forums, no chat, no merchandise) — scope is deliberately narrow.

## 4. Target users

1. **Fans** — the primary audience. Want scores, fixtures, results,
   standings, and team info, fast, on a phone.
2. **Team followers** — fans of a specific club who want that team's
   form, upcoming games, and results without wading through full league
   tables.
3. **Data agents** — people (not necessarily technical) who help keep
   results accurate when the live scrape can't confirm a match yet.
4. **KHU itself** — a potential future stakeholder, if the app is
   recognized or adopted officially.

## 5. Current feature set

### Live data
- Standings for all 8 leagues: Premier League (Men/Women), Super League
  (Men/Women), National League — 4 zones (Men only).
- Upcoming fixtures, grouped by date, filterable by league.
- Results, grouped by league (most recent first within each), filterable
  by league.
- Live-match detection with push notifications when a favorited team's
  match goes live.
- Team profiles: league position, recent form (W/D/L), upcoming fixtures,
  recent results — built entirely from data already scraped and trusted
  elsewhere in the app (see Architecture.md for why).
- National League playoff bracket view.

### Data reliability
- Three data sources feed the same fixtures/results pool, each filling
  gaps the others can't: **live scrape** (primary), **PDF ingestion**
  (KHU's own published season-calendar PDFs, which sometimes lead the
  live site), and **manual entry** (a human confirms a result the
  scraper hasn't caught yet). Whichever source has a given match first
  is what's shown — no source overwrites another's already-recorded data.
- Team crest logos are fetched through a backend proxy (works around
  suspected hotlink protection on KHU's image host) with a graceful
  initials-avatar fallback when a logo genuinely isn't available.
- Past fixtures are automatically filtered out of "Upcoming" — no stale
  matches lingering after their kickoff time passes.

### Data entry tools
- **Admin portal** (`/admin.html`): upload a KHU PDF calendar, manually
  add/edit/delete results, create and manage agent accounts.
- **Agent portal** (`/agent.html`): a lightweight login for people helping
  enter results, without needing the master admin credential. Every
  result records who entered it.

### App experience
- Installable as a PWA on Android, iOS, and desktop — a real home-screen
  app with no app-store dependency.
- Light theme by default (dark available via toggle).
- Favoriting teams for push notifications and quick access.

## 6. Success signals

- Fans actually install the app (tracked informally via WhatsApp-group
  sharing and word of mouth; no formal analytics yet).
- Data stays accurate through a full matchday without manual
  intervention being required for every result.
- KHU responds to the outreach email with either informal blessing,
  formal partnership interest, or specific requested changes.

## 7. Constraints

- **Render free tier**: backend disk is ephemeral — anything that must
  survive a cold start needs a git-committed seed file, not just a
  database row. This shaped how PDF fixtures and manual results are
  persisted (see Architecture.md).
- **KHU's own site is inconsistent**: the same team can have different
  display names on different pages (e.g. "Warriors" on standings vs
  "Butali Warriors" on fixtures), and the live "calendar" view doesn't
  actually return match data server-side at all. Both are handled
  explicitly rather than assumed away.
- **No official API**: everything is scraped or manually entered. This
  is inherently more fragile than a real data feed, which is part of
  the case for eventually seeking KHU's direct cooperation.

## 8. Open items / roadmap

- KHU permission/partnership outcome — pending as of this writing.
- Extend the same multi-source merge pattern to fixtures/standings if
  gaps show up there too (currently results and fixtures are covered;
  standings rely solely on the live scrape).
- Consider surfacing "source" (live / PDF / manual) in the UI itself for
  full transparency, not just in the API response.
- Off Pitch Africa — a related, separate client project reusing this
  app's scraping patterns — is tracked independently.
