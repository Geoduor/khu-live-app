# Kenya Hockey Union — Live App

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688)
![React](https://img.shields.io/badge/frontend-React-61DAFB)

An unofficial live scores, standings, and fixtures app for the Kenya Hockey Union (KHU), built to solve a real gap: KHU had no dedicated fan-facing app for live results, league tables, or fixtures.

Data is scraped directly and respectfully from [kenyahockeyunion.org](https://www.kenyahockeyunion.org) (a JoomSport-powered WordPress site) and served through a caching API layer, with a React PWA frontend.

> ⚠️ **This is an unofficial, fan-built project — not affiliated with or endorsed by the Kenya Hockey Union.** It reads publicly available data from KHU's own website. Requests are rate-limited and cached to minimize load on their server (see the circuit breaker section below), and this project will be taken down immediately if KHU raises any concern about it.

## Features

- **Live standings** for all 8 KHU leagues (Premier League Men/Women, Super League Men/Women, National League Men — EZ/CZ/WZ/SZ zones)
- **Real match state machine** — Not Started / Live / Full Time, matching JoomSport's own internal logic
- **Fixtures & results**, scraped per-league via JoomSport's calendar view
- **Team profile pages** — position, form, recent results, upcoming fixtures
- **Match detail pages** — date, venue, matchday, live score
- **Row-diff animations** — standings visibly highlight what changed on each live poll
- **Offline-first PWA** — installable, works with cached data when offline
- **Push notifications** — real Web Push (VAPID), alerts when a match goes live
- **Circuit breaker resilience** — if KHU's site goes down, the app stops hammering it and serves cached data gracefully, auto-recovering once the source is back

## Architecture

```
khu-app/
├── backend/          FastAPI + BeautifulSoup scraper + SQLite cache
│   ├── main.py        API endpoints, refresh scheduling, circuit breaker
│   ├── scraper.py      All KHU scraping logic (standings, fixtures, team/match pages)
│   ├── database.py     SQLite persistence + circuit breaker state
│   ├── push.py         Web Push notification system
│   └── requirements.txt
└── frontend/
    └── khu-frontend/  React PWA
        └── src/
            ├── App.js
            ├── api.js
            ├── components/    LeagueTable, MatchCard, TeamProfile, MatchDetail...
            └── hooks/         useDiffedStandings, usePushNotifications
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

### Frontend

```bash
cd frontend/khu-frontend
npm install
npm start
```

Open `http://localhost:3000`.

## Important notes

- This is **not an official KHU product** — it's a fan-built tool that reads publicly available data from the KHU website.
- Data accuracy depends entirely on kenyahockeyunion.org staying online and unchanged in structure. If they redesign their site, the scraper's selectors may need updating.
- Before deploying publicly, generate your own VAPID keypair (instructions in `backend/push.py`) rather than reusing any example keys.
- Requests to KHU respect a 15-minute scheduled refresh interval and a circuit breaker that stops all automatic requests if the site becomes unreachable, resuming automatically once it recovers.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

MIT — see [LICENSE](./LICENSE).
