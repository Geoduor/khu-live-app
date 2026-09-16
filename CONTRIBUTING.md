# Contributing to KHU Live App

## Ground rule — read this first

**No hallucinated data. Ever.** Every score, standing, and fixture shown
in the app must trace back to something KHU actually published — scraped
from their live site, extracted from their own PDF, or entered by a
person who verified it. If a scraper can't find something, the correct
behavior is an empty/error state, never a guess.

## Local setup

### Backend
```bash
cd backend
pip install -r requirements.txt --break-system-packages   # or use a venv
cp env.example .env    # fill in real values — never commit .env
uvicorn main:app --reload
```

### Frontend
```bash
cd frontend/khu-frontend
npm install
npm start
```

Set `REACT_APP_API_URL` in a `.env.local` file if your backend isn't at
`http://localhost:8000`.

## Before opening a PR

1. **Backend**: verify `python3 -c "import main"` succeeds cleanly and
   run any relevant test script for the area you touched (there's no
   persistent test suite yet — see individual functions' docstrings for
   the manual testing patterns used during development).
2. **Frontend**: run `CI=true npm run build` before pushing — this is
   what Vercel uses, and it treats ESLint warnings (like unused
   variables) as hard errors. A build that passes locally without
   `CI=true` can still fail on Vercel.
3. If you touched anything in `scraper.py` that targets a specific KHU
   URL or HTML structure, verify against the *real* site — this
   codebase has more than one bug already caused by assuming a URL or
   selector worked without checking (see ARCHITECTURE.md §3 for the
   most significant example).

## Conventions this codebase already follows

- **Team name corrections** live in dedicated, well-commented dicts
  (`TEAM_NAME_CORRECTIONS`, `PDF_NAME_CORRECTIONS`,
  `LOGO_NAME_ALIAS_GROUPS`) rather than scattered inline fixes. If you
  find a new name mismatch, add it there with a comment explaining the
  evidence (which pages showed which name).
- **Never guess a fuzzy match**. The matching system in `main.py`
  (`fuzzy_match_logo`, `_find_standings_entry_for_team`) requires gender
  and squad-qualifier agreement, and only acts when exactly one
  candidate qualifies. If you're tempted to loosen this to "fix" a
  missing match, first check whether it's actually two different teams
  (development squad, reserve team, different gender) before assuming
  it's a bug.
- **Anything that must survive Render's cold starts** needs a
  git-committed seed file, not just a database row — see
  ARCHITECTURE.md §4. If you add a new persistent data type, follow the
  existing pattern (`pdf_fixtures_seed.json`,
  `manual_results_seed.json`).
- **Multiple data sources merge, never overwrite.** If you're adding a
  new source of fixtures/results, follow `merge_pdf_fixtures_into_scraped`
  / `merge_manual_results_into_scraped`'s pattern: an existing entry for
  a match always wins, a new source only fills genuine gaps.

## Verifying against the real site

Several past bugs in this project came from assuming a URL or HTML
structure worked without checking it directly. Before changing scraping
logic:

1. Fetch the actual page (a browser, or a tool with real network access —
   note that some sandboxed dev environments block `kenyahockeyunion.org`
   entirely, which can produce a false "it's broken" signal that's
   actually just a network restriction).
2. Compare the real HTML/structure against what the parser expects.
3. If you're changing a class name or URL pattern the scraper depends
   on, document the real evidence in a comment, the same way existing
   code does (e.g. `scraper.py`'s "TEAM-PAGE-BASED RESULTS SCRAPING"
   section explains exactly what was tested and found).

## Copyright / attribution

All data originates from `kenyahockeyunion.org`. This app is not
affiliated with or endorsed by Kenya Hockey Union. Keep the "Unofficial
Fan App" labeling intact in the UI, manifest, and page metadata unless
KHU has explicitly granted official recognition — see PRD.md §7.
