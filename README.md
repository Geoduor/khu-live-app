# Kenya Hockey Union — Live App

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688)
![React](https://img.shields.io/badge/frontend-React-61DAFB)
![PWA](https://img.shields.io/badge/installable-PWA-5A0FC8)

An unofficial live scores, standings, and fixtures app for the Kenya Hockey Union (KHU), built to solve a real gap: KHU had no dedicated fan-facing app for live results, league tables, or fixtures.

Data is scraped directly and respectfully from [kenyahockeyunion.org](https://www.kenyahockeyunion.org) (a JoomSport-powered WordPress site) and served through a caching API layer, with a React PWA frontend.

> ⚠️ **This is an unofficial, fan-built project — not affiliated with or endorsed by the Kenya Hockey Union.** It reads publicly available data from KHU's own website. Requests are rate-limited and cached to minimize load on their server (see the circuit breaker section below), and this project will be taken down immediately if KHU raises any concern about it.

## Promo video

<p align="center">
  <a href="docs/promo/KHU-Live-Promo.mp4">
    <img src="docs/promo/KHU-Live-Promo.gif" alt="KHU Live promo video: live scores, fixtures, tables and tournaments" width="300">
  </a>
</p>

<p align="center"><b><a href="docs/promo/KHU-Live-Promo.mp4">▶ Play the full video with sound (27 s, MP4)</a></b></p>

<details>
<summary>Embedded player</summary>

<video src="https://github.com/Geoduor/khu-live-app/raw/main/docs/promo/KHU-Live-Promo.mp4" poster="docs/promo/poster.jpg" controls muted playsinline width="300"></video>

</details>

## Database: SQLite or Supabase (PostgreSQL)

By default the backend stores data in a local SQLite file, which Render wipes on restart unless a disk is attached (the seed files restore the essentials). To keep data durably, set one environment variable on Render:

```
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@<pooler-host>:5432/postgres
```

Use the Supabase **Session pooler** string (Project → Connect), with the Supabase Data API switched off since the backend connects directly. `GET /api/health` shows `"database": "postgres"` or `"sqlite"`. Remove the variable to go straight back to SQLite. On the free Supabase plan there are no automatic backups, so keep exporting the seed files from the admin page.

## Features

### Live data
- **Live standings** for all 8 KHU leagues — Premier League Men/Women, Super League Men/Women, and National League Men across all four zones (EZ, CZ, WZ, SZ)
- **Real match state machine** — Not Started / Live / Full Time, derived directly from JoomSport's own internal match-status logic (not guessed from score text)
- **Fixtures & results**, scraped per-league via JoomSport's calendar view (`?action=calendar`), not homepage guessing
- **Team profile pages** — league position, last-5 form, every result this season with a season record (W/D/L, goals), upcoming fixtures
- **Results grouped by date** — newest day first
- **Match detail pages** — date, venue, logos, live/final score, a minute-by-minute events list (goals and cards when recorded) and a Share button
- **Top scorers** — a leaderboard per league (Table tab → Top scorers), shareable as an image; tap a row to open the player's page
- **Squads and player pages** — each team profile lists its squad (photo, position, shirt number, goals); a player's page shows photo, details, season stats and goals log
- **Row-diff animations** — standings visibly flash and show rank-change arrows on each live poll, so the table feels alive instead of just reloading

### Sharing & tournaments
- **Share cards** — a "Share result" button on finished/live matches and a "Share table" button on league and tournament group tables. They render a clean 1080×1350 image on-device (Canvas, no extra dependency) carrying the app name and the "Unofficial Fan App" line, then open the native share sheet (WhatsApp, etc.) or fall back to a download.
- **Cups tab** — hosted tournaments (e.g. festivals, cups) with matches grouped by stage and computed group tables (3-1-0 points; tiebreak: points → goal difference → goals for). Tournament data is stored separately from league data and never affects league standings.
- **Postponed and stopped matches** — a postponed match shows **P-P** in place of the score; a match stopped midway shows its score with a ⛔/⏸ symbol and the minute, plus a plain-English note and the reason
- **Admin & agent entry** — `admin.html` has a Tournaments section to create tournaments and enter matches; the API also lets authorised agents enter tournament matches.

### Personalization
- **Favorites / "Your Teams"** — star any team from the table, a match card, or its profile page. No login required; favorites live on-device (localStorage), the same zero-friction pattern FotMob and SofaScore used before they added accounts.
- **First-launch onboarding** — a "which teams do you follow?" picker appears once, lets you search and select right away
- **Scoped push notifications** — Web Push (VAPID) alerts fire when a match goes live, but only to devices that have favorited one of the two teams playing (or to everyone, if that device hasn't set favorites yet)

### Reliability & resilience
- **SQLite persistent cache** — the app loads instantly from the last successful scrape on startup, never a blank screen
- **Circuit breaker** — if kenyahockeyunion.org goes down, the app stops hammering it (CLOSED → OPEN → HALF_OPEN states, same pattern as Netflix's Hystrix), automatically resuming once the source recovers. Manual refresh always bypasses the breaker and tries for real, rate-limited to prevent abuse.
- **Scraper protection handling** — detects bot-protection pages, retries, aborts a league early after repeated blocks, and keeps previously scraped matches instead of overwriting them with partial data
- **Admin hardening** — constant-time credential check and login throttling
- **Team name correction layer** — a single map in the scraper fixes known naming inconsistencies on KHU's own site (e.g. "Kisumu Youngsters" → "Kisumu Youngstars"), applied everywhere a team name is extracted

### Platform
- **Offline-first PWA** — installable to a phone home screen, works with cached data when offline
- **Kenyan flag–branded UI** — animated red/black/green stripe, official KHU crest in the header and onboarding screen

## Architecture

```
khu-app/
├── backend/                  FastAPI + BeautifulSoup scraper + SQLite cache
│   ├── main.py                 API endpoints, refresh scheduling, circuit breaker
│   ├── scraper.py               All KHU scraping logic (standings, fixtures,
│   │                            team/match pages, name corrections)
│   ├── database.py              Persistence (SQLite or Postgres) + circuit breaker state
│   ├── dbconn.py                Database connection layer / SQL translation
│   ├── backup.py                Backup file + nightly off-site upload
│   ├── insights.py              Private analytics + sponsor slot
│   ├── playerprofiles.py        Player profiles and photos
│   ├── khusquads.py             Squad import from the KHU website
│   ├── tournaments.py           Tournament validation, group tables, stage ordering
│   ├── verify_*.py              Offline test scripts (run before deploying)
│   ├── push.py                  Web Push system with favorites-based scoping
│   ├── requirements.txt
│   ├── .env.example              Template for required environment variables
│   └── .gitignore
└── frontend/
    └── khu-frontend/           React PWA
        ├── public/
        │   ├── admin.html         Admin portal (tabs: results, matches, cups, stats, people, sponsors, backups)
        │   ├── agent.html         Agent portal (results, notices, player profiles)
        │   ├── khu-crest.png       KHU crest (transparent background; icons are generated from it)
        │   ├── generate_icons.py  Regenerates PWA icons from the real logo
        │   ├── manifest.json
        │   └── service-worker.js
        └── src/
            ├── App.js
            ├── api.js
            ├── components/
            │   ├── LeagueTable.js
            │   ├── MatchCard.js
            │   ├── TeamProfile.js
            │   ├── MatchDetail.js
            │   ├── TournamentsView.js
            │   ├── ShareButton.js
            │   └── OnboardingPicker.js
            ├── utils/
            │   └── shareCard.js        Canvas share-image generator
            └── hooks/
                ├── useDiffedStandings.js
                ├── usePushNotifications.js
                └── useFavorites.js      (also exports useOnboarding)
```

## Setup

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env       # then fill in your own VAPID keys — see push.py
uvicorn main:app --reload --port 8000
```

Test the scraper directly before starting the server:
```bash
python scraper.py
```

### Frontend

```bash
cd frontend/khu-frontend
npm install
npm start
```

Open `http://localhost:3000`. Make sure the backend is already running, or you'll see a "Backend Not Running" screen.

### Logo & PWA icons

1. Use a crest PNG with a **real transparent background** as `khu-crest.png` in `frontend/khu-frontend/public/` (a screenshot of a transparent image bakes the grey checkerboard into the pixels — that's what the old `khu-logo.png` was)
2. Regenerate the installable app icons from it:
   ```bash
   cd frontend/khu-frontend/public
   pip install pillow
   python generate_icons.py
   ```

### Tests

```bash
cd backend
python verify_robustness.py        # offline checks incl. tournaments, auth, seed restore, player profiles, squad import
python verify_manual_results_v2.py # manual results and table recalculation
python verify_security.py          # attacker-style checks (see SECURITY.md)
cd ../frontend/khu-frontend
CI=true npm run build           # treats lint warnings as errors, as the deploy does
```

## Deployment & data persistence

Backend on Render (paid instance), frontend on Vercel (Hobby). Without `DATABASE_URL`, Render's disk is **ephemeral**, so data entered through the admin portal is lost on a cold start unless persisted:

- Public data (manual results, team/player stats, tournaments): export the seed JSON from the admin portal and commit it to `backend/` (`tournaments_seed.json`, etc.).
- Agent accounts contain password hashes, so they are **not** committed. Export them and store the value in the `AGENTS_SEED` environment variable.
- Set `ADMIN_TOKEN`, `ADMIN_USERNAME`, `ADMIN_PASSWORD` and `ALLOWED_ORIGINS` on Render (see `render.yaml` and `backend/env.example`).
- `admin.html` and `agent.html` hardcode the backend URL; update it if your Render service name differs.

## Important notes

- This is **not an official KHU product** — it's a fan-built tool that reads publicly available data from the KHU website.
- Data accuracy depends entirely on kenyahockeyunion.org staying online and unchanged in structure. If they redesign their site, the scraper's selectors may need updating.
- Before deploying publicly, generate your own VAPID keypair (instructions in `backend/push.py`) rather than reusing any example keys.
- Requests to KHU respect a 15-minute scheduled refresh interval and a circuit breaker that stops all automatic requests if the site becomes unreachable, resuming automatically once it recovers.
- Favorites and push subscriptions are stored per-device, not per-account — there is no login system, and no personal data beyond a browser's push endpoint and chosen team list is ever collected.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

MIT — see [LICENSE](./LICENSE).


## Off-site backups and season history

- **Shop (optional, off until set up):** a Shop button appears in the app header once an admin adds a store. Several independent stores, each with logo, products (brand, type, up to 4 pictures, stock) and a delivery fee. Fans bag items, enter delivery details and pay by M-Pesa prompt; the order moves paid → preparing → shipped → delivered on the admin *Shop* tab. Prices and stock are decided on the server; an order counts as paid only when Safaricom confirms the right amount. Payments go to one paybill/till and the admin page shows what each store is owed. Setup and the business/legal checklist: [docs/SHOP_SETUP.md](docs/SHOP_SETUP.md).
- **Nightly off-site backup** (step-by-step: [docs/BACKUP_SETUP.md](docs/BACKUP_SETUP.md)): set `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_KEY_ID`, `BACKUP_S3_SECRET` on Render (Cloudflare R2 or Backblaze B2 both work). A dated JSON copy is uploaded every night at 02:00 EAT and the app never deletes old ones. Turn on bucket versioning/object-lock and give the key write-only access if possible. The file restores through the admin page.
- **Season history:** the admin page has "Save season to history" (freezes the current tables, results and tournaments). Saved seasons are append-only, are included in backups, and are readable at `GET /api/seasons` and `GET /api/seasons/<label>`. Past seasons supplied as files go in through `POST /api/admin/seasons/import`.

## Past matches and match status notices

- **Permanent archive:** every fixture and result the app ever sees is copied into a `match_archive` table on every refresh and never deleted. A score, once archived, is never replaced by a score-less copy. Fans browse it under *Results → Past matches* (filter by league, season, team and dates); the API is `GET /api/matches/history`.
- **Status notices:** admins and agents can mark a match postponed, rescheduled (with the new date), suspended, abandoned (minute and score when it stopped), cancelled or awarded, with a reason. The notice shows on the match card for fans, rescheduled matches move to their new date, and a stopped match leaves the Live list. Notices never change the table: enter a real score the normal way if a result stands. Every change is logged in `match_status_log`.
- Both are included in backups and restores.

## Analytics, sponsor slot and past seasons

- **Analytics (private, no cookies):** the app counts screen views, installs and one visit per person per day. A person is counted from a one-way fingerprint that changes daily, so nobody can be followed across days; IP addresses are never stored, fingerprints are deleted after 3 days, and browsers that send Do Not Track / Global Privacy Control are not counted. Numbers are on the admin page under *Visitors & usage* (`GET /api/admin/analytics/summary`).
- **Sponsor slot:** the admin page's *Sponsor slot* card manages a sponsor (name, message, https link, PNG/JPEG/WebP logo up to 400 KB, optional dates). It shows on Home, Fixtures and Results, always labelled "Sponsored". Views (card at least half visible) and clicks are counted per sponsor, so you can show a sponsor real numbers. Links must be https; SVG logos are refused.
- **Past seasons:** the Cups tab has a *Past seasons* view with a roll of honour (the team in position 1 of each league) and each season's final tables. Seasons come from *Save season to history* or *Add a past season* (file import) on the admin page, and are permanent.
- Sponsors and daily analytics totals are included in backups and restores.

## Player profiles

- **What fans see:** a Squad list on every team page and a page per player (photo, position, shirt number, nationality, captain badge, bio, season stats, goals log). Top-scorer rows open the same page.
- **How data gets in:** the admin page (Stats tab) and the agent page (Players tab) have a form for shirt number, position, bio and photo; photos are shrunk in the browser first. The admin Stats tab also has **Import squads from the KHU website**, which reads each team's public player list (names, shirt numbers, photos) in the background and only fills gaps: nothing an admin or agent entered is ever overwritten. Positions are not on the KHU site. **A shirt number identifies a player within a team**: two players of one team cannot share a number, the import completes whoever already wears that number instead of adding a second profile, and the admin form has a button to merge duplicates made earlier.
- **Privacy:** only add a photo with the player's permission (a parent or guardian's for anyone under 18). There is deliberately no field for date of birth, address or phone number. Photos and profiles are included in backups and restores; a file with just `player_profiles` can also be loaded through the admin Restore button.
- **Pages' security policy:** photo previews must use `FileReader` (data URLs); `blob:` images are blocked on `admin.html` and `agent.html`.
