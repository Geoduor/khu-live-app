# Kenya Hockey Union — Live App

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688)
![React](https://img.shields.io/badge/frontend-React-61DAFB)
![PWA](https://img.shields.io/badge/installable-PWA-5A0FC8)

An unofficial live scores, standings, and fixtures app for the Kenya Hockey Union (KHU), built to solve a real gap: KHU had no dedicated fan-facing app for live results, league tables, or fixtures.

Data is scraped directly and respectfully from [kenyahockeyunion.org](https://www.kenyahockeyunion.org) (a JoomSport-powered WordPress site) and served through a caching API layer, with a React PWA frontend.

> ⚠️ **This is an unofficial, fan-built project — not affiliated with or endorsed by the Kenya Hockey Union.** It reads publicly available data from KHU's own website. Requests are rate-limited and cached to minimize load on their server (see the circuit breaker section below), and this project will be taken down immediately if KHU raises any concern about it.

## Features

### Live data
- **Live standings** for all 8 KHU leagues — Premier League Men/Women, Super League Men/Women, and National League Men across all four zones (EZ, CZ, WZ, SZ)
- **Real match state machine** — Not Started / Live / Full Time, derived directly from JoomSport's own internal match-status logic (not guessed from score text)
- **Fixtures & results**, scraped per-league via JoomSport's calendar view (`?action=calendar`), not homepage guessing
- **Team profile pages** — league position, last-5 form, recent results, upcoming fixtures
- **Match detail pages** — date, venue, matchday name, live/final score
- **Row-diff animations** — standings visibly flash and show rank-change arrows on each live poll, so the table feels alive instead of just reloading

### Personalization
- **Favorites / "Your Teams"** — star any team from the table, a match card, or its profile page. No login required; favorites live on-device (localStorage), the same zero-friction pattern FotMob and SofaScore used before they added accounts.
- **First-launch onboarding** — a "which teams do you follow?" picker appears once, lets you search and select right away
- **Scoped push notifications** — Web Push (VAPID) alerts fire when a match goes live, but only to devices that have favorited one of the two teams playing (or to everyone, if that device hasn't set favorites yet)

### Reliability & resilience
- **SQLite persistent cache** — the app loads instantly from the last successful scrape on startup, never a blank screen
- **Circuit breaker** — if kenyahockeyunion.org goes down, the app stops hammering it (CLOSED → OPEN → HALF_OPEN states, same pattern as Netflix's Hystrix), automatically resuming once the source recovers. Manual refresh always bypasses the breaker and tries for real, rate-limited to prevent abuse.
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
│   ├── database.py              SQLite persistence + circuit breaker state
│   ├── push.py                  Web Push system with favorites-based scoping
│   ├── requirements.txt
│   ├── .env.example              Template for required environment variables
│   └── .gitignore
└── frontend/
    └── khu-frontend/           React PWA
        ├── public/
        │   ├── khu-logo.png       Official KHU crest
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
            │   └── OnboardingPicker.js
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

1. Save the official KHU crest as `khu-logo.png` in `frontend/khu-frontend/public/`
2. Regenerate the installable app icons from it:
   ```bash
   cd frontend/khu-frontend/public
   pip install pillow
   python generate_icons.py
   ```

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
