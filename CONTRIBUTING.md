# Contributing to the KHU Live App

Thanks for your interest in improving this project! This started as a fix for a real gap — Kenya Hockey Union fans had no dedicated live-scores app — and contributions are welcome.

## Ways to help

- **Report scraper breakage**: if `kenyahockeyunion.org` changes its site structure and the scraper stops working, open an issue with the error output from `python scraper.py`.
- **Add a new league or fix a wrong URL**: KHU league season URLs change yearly. Updates to `LEAGUES` in `backend/scraper.py` are always welcome.
- **UI/UX improvements**: the frontend is a standard React app (`frontend/khu-frontend`) — PRs for accessibility, mobile polish, or new views are welcome.
- **New features**: see open issues for ideas like favorites/my-teams, search, or statistics pages.

## Development setup

See the main [README](./README.md) for backend/frontend setup instructions.

## Before submitting a PR

1. Test the scraper against the live site: `python scraper.py` should show real data for all 8 leagues.
2. Make sure the frontend builds without errors: `npm run build`.
3. Keep scraping respectful — no reducing the refresh interval below what's already set, and no removing the circuit breaker logic that protects `kenyahockeyunion.org` from being hammered during outages.

## Code of conduct

Be kind. This is a small community project built to help real hockey fans — treat it and each other accordingly.
