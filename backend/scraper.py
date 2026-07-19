"""
KHU Scraper — scraper.py
Fetches REAL data from kenyahockeyunion.org
Confirmed working leagues from test run:
  - Premier League Men PLM 2026    ✅
  - Premier League Women PLW 2026  ✅
  - Super League Men/Women URLs    ✅
  - National League EZ/CZ/WZ/SZ   → scraping all

Column order confirmed from KHU screenshot:
# | Teams | Pl | W | D | L | Diff | GD | Pts | Current Form
"""

import requests
from bs4 import BeautifulSoup
import logging
import re
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

BASE_URL = "https://www.kenyahockeyunion.org"

# JoomSport match states (confirmed from source code — m_played field):
#   0 or ''  -> NOT_STARTED (shows "vs")
#   -1       -> LIVE (shows score + a "jscalendarLive" div)
#   1        -> FINISHED (shows final score)
MATCH_STATE_NOT_STARTED = "NS"
MATCH_STATE_LIVE = "LIVE"
MATCH_STATE_FINISHED = "FT"

# ── Team name corrections ──
# KHU's own site occasionally has typos/inconsistent naming for a club.
# Rather than patch this in five different places (standings, calendar,
# team profiles, match details), every raw team name extracted from the
# site passes through this single correction map first.
TEAM_NAME_CORRECTIONS = {
    "Kisumu Youngsters": "Kisumu Youngstars",
}

# ── League membership corrections ──
# KHU's own live site occasionally lists a team in a league it doesn't
# actually belong in (confirmed manually against KHU's official season
# document + direct verification that this is a genuine site error,
# not a legitimate reserve/second-team situation). Rather than silently
# trust every row scraped, teams listed here are EXCLUDED from the
# specific league_key they're wrongly appearing in — they still appear
# normally in whichever league they actually belong to.
#
# Format: { league_key: {set of team names to exclude from that league} }
LEAGUE_EXCLUSIONS = {
    "super_league_women": {"Kenyatta University Ladies", "Kenyatta University"},
}


def is_excluded_from_league(team_name: str, league_key: str) -> bool:
    """Check whether a team should be excluded from a given league's standings/results."""
    excluded_names = LEAGUE_EXCLUSIONS.get(league_key, set())
    return team_name.strip() in excluded_names


# ── Placeholder teams ──
# A team confirmed (via KHU's official season document + direct manual
# verification) to genuinely belong in a league, but not yet published
# on KHU's LIVE site — e.g. they haven't played their first fixture
# yet, so there's no real row to scrape. We show them with zero stats
# rather than omit them entirely, but this is CLEARLY NOT hallucinated
# data: every field is honestly zero/empty, never guessed.
#
# CRITICAL: once KHU actually publishes this team's real row (they
# start playing and get added to the live standings table), the
# placeholder must automatically stop appearing — see
# inject_placeholder_teams() below, which checks for a real match by
# name before ever adding a placeholder, so we never show both at once.
PLACEHOLDER_TEAMS = {
    "super_league_women": ["Kisii University Ladies"],
}


def inject_placeholder_teams(standings: list, league_key: str) -> list:
    """
    Append placeholder rows for teams confirmed to belong in this
    league but not yet published live by KHU — ONLY if a real scraped
    entry with that name doesn't already exist (which would mean KHU
    has since published them for real, and the placeholder should
    naturally stop being used).
    """
    placeholders = PLACEHOLDER_TEAMS.get(league_key, [])
    existing_names = {t["team"].strip().lower() for t in standings}

    for name in placeholders:
        if name.strip().lower() in existing_names:
            # KHU has published real data for this team now — don't
            # add a duplicate placeholder alongside the real entry.
            continue

        standings.append({
            "position":      str(len(standings) + 1),
            "team":          name,
            "team_url":      "",
            "team_logo_url": "",
            "played":        "0",
            "won":           "0",
            "drawn":         "0",
            "lost":          "0",
            "goals_for":     "0",
            "goals_against": "0",
            "goal_diff":     "0",
            "points":        "0",
            "form":          [],
            "is_placeholder": True,
        })

    return standings


def correct_team_name(name: str) -> str:
    """Apply known name corrections to a raw scraped team name."""
    if not name:
        return name
    return TEAM_NAME_CORRECTIONS.get(name.strip(), name.strip())

# ── All leagues — update Super League URLs once Geofry confirms them ──
LEAGUES = {
    # ── MEN'S SECTION (Tier 1 → 2 → 3) ──
    "premier_league_men": {
        "name": "Premier League Men",
        "short": "PLM",
        "gender": "men",
        "tier": 1,
        "url": f"{BASE_URL}/joomsport_season/premier-league-men-plm-2026/",
    },
    "super_league_men": {
        "name": "Super League Men",
        "short": "SLM",
        "gender": "men",
        "tier": 2,
        "url": f"{BASE_URL}/joomsport_season/super-league-men-slm-2026/",
    },
    "national_league_men_ez": {
        "name": "National League Men — Eastern Zone",
        "short": "NLM-EZ",
        "gender": "men",
        "tier": 3,
        "zone": "EZ",
        "url": f"{BASE_URL}/joomsport_season/national-league-men-_-ez-nlm-ez-2026/",
    },
    "national_league_men_cz": {
        "name": "National League Men — Central Zone",
        "short": "NLM-CZ",
        "gender": "men",
        "tier": 3,
        "zone": "CZ",
        "url": f"{BASE_URL}/joomsport_season/national-league-men-_-cz-nlm-cz-2026/",
    },
    "national_league_men_wz": {
        "name": "National League Men — Western Zone",
        "short": "NLM-WZ",
        "gender": "men",
        "tier": 3,
        "zone": "WZ",
        "url": f"{BASE_URL}/joomsport_season/national-league-men-wz-nlm-wz-2026/",
    },
    "national_league_men_sz": {
        "name": "National League Men — Southern Zone",
        "short": "NLM-SZ",
        "gender": "men",
        "tier": 3,
        "zone": "SZ",
        "url": f"{BASE_URL}/joomsport_season/national-league-men-sz-nlm-sz-2026/",
    },
    # ── WOMEN'S SECTION (Tier 1 → 2) ──
    "premier_league_women": {
        "name": "Premier League Women",
        "short": "PLW",
        "gender": "women",
        "tier": 1,
        "url": f"{BASE_URL}/joomsport_season/premier-league-women-plw-2026/",
    },
    "super_league_women": {
        "name": "Super League Women",
        "short": "SLW",
        "gender": "women",
        "tier": 2,
        "url": f"{BASE_URL}/joomsport_season/super-league-women-slw-2026/",
    },
}


def fetch_page(url: str, timeout: int = 20):
    """
    Fetch a page and return BeautifulSoup.
    Retries once if connection drops.
    Returns None on failure.
    """
    for attempt in range(2):
        try:
            logger.info(f"Fetching (attempt {attempt+1}): {url}")
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            logger.info(f"OK — {len(resp.text)} bytes")
            return soup
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error {e.response.status_code}: {url}")
            return None  # Don't retry HTTP errors (404 etc)
        except requests.RequestException as e:
            logger.warning(f"Attempt {attempt+1} failed: {e}")
            if attempt == 1:
                logger.error(f"FAILED after 2 attempts: {url}")
                return None
    return None


def try_alt_urls(league: dict):
    """
    For leagues with alt_urls, try each URL until one works.
    Returns (soup, working_url) or (None, None).
    """
    urls_to_try = league.get("alt_urls", [league["url"]])
    for url in urls_to_try:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                logger.info(f"Found working URL: {url}")
                soup = BeautifulSoup(resp.text, "lxml")
                return soup, url
            else:
                logger.warning(f"  {url} → {resp.status_code}")
        except Exception as e:
            logger.warning(f"  {url} → Error: {e}")
    return None, None


def parse_form_from_cell(cell):
    """
    JoomSport renders form as up to 5 slots, each a colored span:
      <span class="jsform_none match_win">W</span>
      <span class="jsform_none match_draw">D</span>
      <span class="jsform_none match_loose">L</span>
      <span class="jsform_none match_quest">?</span>   <- unplayed/unknown slot

    CONFIRMED from JoomSport's own source (class-jsport-tourn-matches.php):
    the 5 slots are built oldest-match-first, left-to-right, with the
    most recent result rightmost. Critically, a slot with NO recorded
    result renders as "?" rather than being omitted — so we MUST keep
    that placeholder in our output, or every subsequent real letter
    shifts left and silently misrepresents which match it belongs to.

    BUG FIX (previously caused e.g. "W W W W W" for a team with only
    3 real wins): each form slot can be a wrapper tag (e.g. a <a> or
    <div>) around an INNER tag that actually holds the letter. If both
    the wrapper AND the inner tag have text that's exactly "W"/"D"/"L"/
    "?", find_all(True) matched BOTH — silently DOUBLE-COUNTING every
    real slot. Taking the last 5 of a doubled, mostly-repeating list
    tended to collapse onto whichever letter repeated most at the end
    of the season, exactly the symptom reported. We now only count
    LEAF-level tags — ones with no element children of their own —
    so a slot contributes exactly one entry no matter how many levels
    of wrapping markup surround its letter.

    Returns a list of up to 5 entries, each "W", "D", "L", or "?".
    """
    form = []
    for tag in cell.find_all(True):
        # Skip any tag that itself contains a child element — we only
        # want the innermost tag actually holding the letter, so a
        # wrapper and its child never both get counted for one slot.
        if tag.find(True) is not None:
            continue
        text = tag.get_text(strip=True).upper()
        if text in ("W", "D", "L", "?"):
            form.append(text)
    return form[-5:] if len(form) > 5 else form


def find_standings_table(soup):
    """
    Find the JoomSport standings table using multiple strategies.
    JoomSport confirmed class: 'table table-striped cansorttbl'
    JoomSport confirmed id: 'jstable_1'
    """
    # Strategy 1: exact JoomSport class (most reliable)
    table = soup.find("table", class_="cansorttbl")
    if table:
        return table

    # Strategy 2: inside joomsport-container div
    container = soup.find(id="joomsport-container")
    if container:
        table = container.find("table")
        if table:
            return table

    # Strategy 3: table id starts with jstable
    table = soup.find("table", id=re.compile(r"^jstable", re.I))
    if table:
        return table

    # Strategy 4: table-striped class
    table = soup.find("table", class_="table-striped")
    if table:
        return table

    # Strategy 5: any table with more than 5 rows that looks like standings
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if len(rows) >= 5:
            # Check if first data row starts with a number (position)
            for row in rows:
                cells = row.find_all("td")
                if cells and cells[0].get_text(strip=True).isdigit():
                    return t

    return None


def parse_standings_table(table, league_key: str = "") -> list:
    """
    Parse a JoomSport standings table into a list of team dicts.
    Column order (confirmed from KHU screenshot):
    0=Rank | 1=Team | 2=Pl | 3=W | 4=D | 5=L | 6=Diff | 7=GD | 8=Pts | 9=Form

    league_key (optional) enables LEAGUE_EXCLUSIONS filtering — a team
    confirmed to be wrongly listed in a given league on KHU's own live
    site gets skipped here rather than silently trusted.
    """
    standings = []
    tbody = table.find("tbody") or table

    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        # Cell 0 = Position — must be a digit
        position = cells[0].get_text(strip=True)
        if not position.isdigit():
            continue

        # Cell 1 = Team name — capture the profile link before stripping images
        team_cell = cells[1]

        # A team cell can contain TWO separate <a> tags: one wrapping just
        # the team's logo/emblem image, and one wrapping the team name text.
        # Blindly taking the FIRST <a> in the cell risks grabbing a
        # logo-only link that may point somewhere generic (e.g. the site
        # homepage) rather than the real team profile page. We specifically
        # want the anchor whose own text content is non-empty — that's the
        # one that actually wraps the team's name — falling back to the
        # first anchor only if none has text (better than nothing).
        team_url = ""
        candidate_links = team_cell.find_all("a")
        text_link = next((a for a in candidate_links if a.get_text(strip=True)), None)
        if text_link:
            team_url = text_link.get("href", "")
        elif candidate_links:
            team_url = candidate_links[0].get("href", "")

        team_logo_url = ""
        logo_img = team_cell.find("img")
        if logo_img and logo_img.get("src"):
            team_logo_url = logo_img.get("src")
            # Resolve relative URLs (e.g. "/wp-content/...") to absolute
            if team_logo_url.startswith("/"):
                team_logo_url = BASE_URL + team_logo_url

        for img in team_cell.find_all("img"):
            img.decompose()
        team_name = correct_team_name(team_cell.get_text(strip=True))
        if not team_name:
            continue

        # Skip teams confirmed to be wrongly listed in this league on
        # KHU's own live site (see LEAGUE_EXCLUSIONS docstring above).
        if league_key and is_excluded_from_league(team_name, league_key):
            logger.info(f"Excluding '{team_name}' from {league_key} (confirmed site error)")
            continue

        def get(idx):
            return cells[idx].get_text(strip=True) if idx < len(cells) else "0"

        played    = get(2)
        won       = get(3)
        drawn     = get(4)
        lost      = get(5)
        diff_raw  = get(6)   # "20 - 12" format
        goal_diff = get(7)
        points    = get(8)
        form      = parse_form_from_cell(cells[9]) if len(cells) > 9 else []

        # Parse goals for / against from "20 - 12"
        goals_for, goals_against = "", ""
        if " - " in diff_raw:
            parts = diff_raw.split(" - ")
            if len(parts) == 2:
                goals_for     = parts[0].strip()
                goals_against = parts[1].strip()

        standings.append({
            "position":      position,
            "team":          team_name,
            "team_url":      team_url,
            "team_logo_url": team_logo_url,
            "played":        played,
            "won":           won,
            "drawn":         drawn,
            "lost":          lost,
            "goals_for":     goals_for,
            "goals_against": goals_against,
            "goal_diff":     goal_diff,
            "points":        points,
            "form":          form,
        })

    # Re-number positions sequentially in case any rows were excluded
    # above — otherwise an excluded team leaves a gap (e.g. 1,2,4,5
    # instead of a clean 1,2,3,4).
    for i, team in enumerate(standings, start=1):
        team["position"] = str(i)

    return standings


def scrape_standings(league_key: str) -> dict:
    """
    Scrape standings for one league from kenyahockeyunion.org.
    Handles leagues with alt_urls (Super League) by trying each URL.
    """
    league = LEAGUES.get(league_key)
    if not league:
        return {"error": f"Unknown league key: {league_key}"}

    # Use alt_url fallback for leagues that had 404 issues
    if league.get("alt_urls"):
        soup, working_url = try_alt_urls(league)
        used_url = working_url or league["url"]
    else:
        soup = fetch_page(league["url"])
        used_url = league["url"]

    if not soup:
        return {
            "league":      league["name"],
            "short":       league["short"],
            "gender":      league["gender"],
            "tier":        league["tier"],
            "standings":   [],
            "total_teams": 0,
            "error":       f"Could not reach {used_url} — please update URL",
            "scraped_at":  datetime.now().isoformat(),
            "source_url":  used_url,
        }

    table = find_standings_table(soup)
    if not table:
        return {
            "league":      league["name"],
            "short":       league["short"],
            "gender":      league["gender"],
            "tier":        league["tier"],
            "standings":   [],
            "total_teams": 0,
            "error":       "Standings table not found on page",
            "scraped_at":  datetime.now().isoformat(),
            "source_url":  used_url,
        }

    standings = parse_standings_table(table, league_key=league_key)
    standings = inject_placeholder_teams(standings, league_key)

    return {
        "league":      league["name"],
        "short":       league["short"],
        "gender":      league["gender"],
        "tier":        league.get("tier", 1),
        "zone":        league.get("zone", None),
        "standings":   standings,
        "total_teams": len(standings),
        "scraped_at":  datetime.now().isoformat(),
        "source_url":  used_url,
    }


def parse_match_state(cell_text: str, has_live_marker: bool, has_digit_score: bool) -> str:
    """
    Determine match state using JoomSport's own logic (confirmed from source):
      - jscalendarLive div present -> LIVE
      - score contains digits (and no live marker) -> FINISHED
      - otherwise (shows 'vs' or dash) -> NOT_STARTED
    """
    if has_live_marker:
        return MATCH_STATE_LIVE
    if has_digit_score:
        return MATCH_STATE_FINISHED
    return MATCH_STATE_NOT_STARTED


def scrape_league_calendar(league_key: str) -> dict:
    """
    Scrape the fixtures/results calendar for ONE league using JoomSport's
    confirmed calendar view: {season_url}?action=calendar

    Real JoomSport HTML structure (from source code, sportleague/helpers/js-helper.php):
      <div class="jstable jsMatchDivMain">
        <div class="jstable-row js-mdname">
          <div class="jsrow-matchday-name">Matchday 5</div>
        </div>
        <div class="jstable-row">
          <div class="jstable-cell jsMatchDivTime">
            <div class="jsDivLineEmbl">Sat, 28 Jun 2026 10:00</div>
          </div>
          <div class="jstable-cell jsMatchDivHome">
            <div class="jsDivLineEmbl">Strathmore Gladiators</div>
          </div>
          <div class="jstable-cell jsMatchDivHomeEmbl">...emblem...</div>
          <div class="jstable-cell jsMatchDivScore">
            2 - 1   <!-- or "vs" if not started -->
            <div class="jscalendarLive">Live</div>  <!-- only present if m_played == -1 -->
          </div>
          <div class="jstable-cell jsMatchDivAwayEmbl">...emblem...</div>
          <div class="jstable-cell jsMatchDivAway">
            <div class="jsDivLineEmbl">Kenya Police</div>
          </div>
        </div>
      </div>
    """
    league = LEAGUES.get(league_key)
    if not league:
        return {"error": f"Unknown league key: {league_key}"}

    calendar_url = league["url"].rstrip("/") + "/?action=calendar"
    soup = fetch_page(calendar_url)

    if not soup:
        return {
            "league": league["name"],
            "short": league["short"],
            "matches": [],
            "error": f"Could not reach {calendar_url}",
            "scraped_at": datetime.now().isoformat(),
            "source_url": calendar_url,
        }

    # Find the match list container — confirmed class from source
    container = soup.find("div", class_=re.compile(r"jsMatchDivMain"))
    if not container:
        # Fallback: any element containing jstable-row children
        container = soup.find(lambda tag: tag.find("div", class_="jstable-row") is not None)

    if not container:
        return {
            "league": league["name"],
            "short": league["short"],
            "matches": [],
            "error": "No match container found on calendar page",
            "scraped_at": datetime.now().isoformat(),
            "source_url": calendar_url,
        }

    matches = []
    current_matchday = ""

    row_divs = container.find_all("div", class_="jstable-row", recursive=False)
    # Some JoomSport themes nest deeper — fallback to any depth if none found directly
    if not row_divs:
        row_divs = container.find_all("div", class_="jstable-row")

    for row in row_divs:
        row_classes = row.get("class", [])

        # Matchday header row (not an actual match)
        if "js-mdname" in row_classes:
            name_div = row.find(class_="jsrow-matchday-name")
            if name_div:
                current_matchday = name_div.get_text(strip=True)
            continue

        # Time / date
        time_cell = row.find(class_="jsMatchDivTime")
        date_str = ""
        if time_cell:
            inner = time_cell.find(class_="jsDivLineEmbl")
            date_str = (inner or time_cell).get_text(strip=True)

        # Home team name + profile link
        home_cell = row.find(class_="jsMatchDivHome")
        home_name = ""
        home_team_url = ""
        if home_cell:
            inner = home_cell.find(class_="jsDivLineEmbl")
            home_name = correct_team_name((inner or home_cell).get_text(strip=True))
            link_tag = home_cell.find("a")
            if link_tag:
                home_team_url = link_tag.get("href", "")

        # Home team logo — confirmed JoomSport structure uses a SEPARATE
        # emblem cell (jsMatchDivHomeEmbl), not embedded in the name cell.
        home_logo_url = ""
        home_embl_cell = row.find(class_="jsMatchDivHomeEmbl")
        if home_embl_cell:
            img_tag = home_embl_cell.find("img")
            if img_tag and img_tag.get("src"):
                home_logo_url = img_tag.get("src")
                if home_logo_url.startswith("/"):
                    home_logo_url = BASE_URL + home_logo_url

        # Away team name + profile link
        away_cell = row.find(class_="jsMatchDivAway")
        away_name = ""
        away_team_url = ""
        if away_cell:
            inner = away_cell.find(class_="jsDivLineEmbl")
            away_name = correct_team_name((inner or away_cell).get_text(strip=True))
            link_tag = away_cell.find("a")
            if link_tag:
                away_team_url = link_tag.get("href", "")

        # Away team logo — same dedicated-cell approach
        away_logo_url = ""
        away_embl_cell = row.find(class_="jsMatchDivAwayEmbl")
        if away_embl_cell:
            img_tag = away_embl_cell.find("img")
            if img_tag and img_tag.get("src"):
                away_logo_url = img_tag.get("src")
                if away_logo_url.startswith("/"):
                    away_logo_url = BASE_URL + away_logo_url

        if not home_name and not away_name:
            continue  # skip malformed rows

        # Score cell + live marker + match detail link
        score_cell = row.find(class_="jsMatchDivScore")
        live_marker = None
        score_text = ""
        match_url = ""
        if score_cell:
            live_marker = score_cell.find(class_=re.compile(r"jscalendarLive"))
            score_link_tag = score_cell.find("a")
            if score_link_tag:
                match_url = score_link_tag.get("href", "")
            score_copy_text = score_cell.get_text(separator=" ", strip=True)
            score_text = score_copy_text

        has_live = live_marker is not None
        has_digit_score = bool(re.search(r"\d+\s*[-:]\s*\d+", score_text))

        state = parse_match_state(score_text, has_live, has_digit_score)

        # Skip this match entirely if either team is confirmed excluded
        # from this specific league (same LEAGUE_EXCLUSIONS check used
        # for standings) — a mis-listed team shouldn't show up in
        # fixtures/results for a league it doesn't actually belong to.
        if is_excluded_from_league(home_name, league_key) or is_excluded_from_league(away_name, league_key):
            continue

        # Extract clean numeric score if finished/live
        home_score, away_score = None, None
        score_match = re.search(r"(\d+)\s*[-:]\s*(\d+)", score_text)
        if score_match:
            home_score = int(score_match.group(1))
            away_score = int(score_match.group(2))

        matches.append({
            "matchday":   current_matchday,
            "date":       date_str,
            "home_team":  home_name,
            "home_team_url": home_team_url,
            "home_logo_url": home_logo_url,
            "away_team":  away_name,
            "away_team_url": away_team_url,
            "away_logo_url": away_logo_url,
            "home_score": home_score,
            "away_score": away_score,
            "state":      state,   # NS | LIVE | FT
            "match_url":  match_url,
            "league":     league["name"],
            "league_short": league["short"],
        })

    return {
        "league":     league["name"],
        "short":      league["short"],
        "matches":    matches,
        "total":      len(matches),
        "scraped_at": datetime.now().isoformat(),
        "source_url": calendar_url,
    }


# League display order for grouping results/fixtures — Premier tier
# (men + women together) first, then Super tier, then National Zones.
# This is presentation order only; it's separate from LEAGUES dict
# insertion order, which stays as-is for scraping/scheduling purposes.
LEAGUE_DISPLAY_ORDER = [
    "premier_league_men",
    "premier_league_women",
    "super_league_men",
    "super_league_women",
    "national_league_men_cz",
    "national_league_men_ez",
    "national_league_men_sz",
    "national_league_men_wz",
]


def _parse_match_date(date_str: str):
    """
    Parse JoomSport's date format (confirmed as DD-MM-YYYY HH:MM from
    real scraped output, e.g. '13-06-2026 15:00') into a sortable
    datetime. Falls back to datetime.min for unparseable/blank dates
    so they sort last rather than crashing the whole sort.
    """
    if not date_str:
        return datetime.min
    for fmt in ("%d-%m-%Y %H:%M", "%d-%m-%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return datetime.min


def _group_and_sort_matches(matches: list) -> list:
    """
    Group matches by league in LEAGUE_DISPLAY_ORDER, and within each
    league group, sort by date descending (most recent first) — e.g.
    for Results, the latest final score appears at the top of its
    league's section; for Fixtures, the soonest upcoming match leads.
    Leagues not present in LEAGUE_DISPLAY_ORDER (shouldn't normally
    happen) are appended at the end, so nothing silently disappears.
    Matches with an unparseable date sink to the bottom of their
    league group rather than crashing the sort or floating to the top.
    """
    league_key_by_short = {info["short"]: key for key, info in LEAGUES.items()}

    def sort_key(match):
        league_short = match.get("league_short", "")
        league_key = league_key_by_short.get(league_short)
        league_index = (
            LEAGUE_DISPLAY_ORDER.index(league_key)
            if league_key in LEAGUE_DISPLAY_ORDER
            else len(LEAGUE_DISPLAY_ORDER)
        )

        parsed_date = _parse_match_date(match.get("date", ""))
        # Negate the timestamp so ascending sort = most-recent-first.
        # Unparseable dates (datetime.min) get a neutral 0, which sorts
        # after any real modern date's large negative key.
        date_key = -parsed_date.timestamp() if parsed_date != datetime.min else 0

        return (league_index, date_key)

    return sorted(matches, key=sort_key)


def scrape_all_fixtures_and_results() -> dict:
    """
    Scrape the calendar for EVERY league and split matches into
    upcoming fixtures (NS) vs results (FT) vs live (LIVE).

    Results/fixtures are grouped by league (Premier Men+Women first,
    then Super, then National Zones — see LEAGUE_DISPLAY_ORDER), and
    sorted by date within each group — most recent first for results,
    soonest-upcoming first for fixtures.
    """
    all_matches = []
    errors = []

    for league_key in LEAGUES:
        data = scrape_league_calendar(league_key)
        if data.get("error"):
            errors.append({"league": league_key, "error": data["error"]})
        all_matches.extend(data.get("matches", []))

    fixtures = [m for m in all_matches if m["state"] == MATCH_STATE_NOT_STARTED]
    results  = [m for m in all_matches if m["state"] == MATCH_STATE_FINISHED]
    live     = [m for m in all_matches if m["state"] == MATCH_STATE_LIVE]

    fixtures = _group_and_sort_matches(fixtures)
    results  = _group_and_sort_matches(results)
    live     = _group_and_sort_matches(live)

    return {
        "fixtures": fixtures,
        "results":  results,
        "live":     live,
        "total_fixtures": len(fixtures),
        "total_results":  len(results),
        "total_live":     len(live),
        "leagues_with_errors": errors,
        "scraped_at": datetime.now().isoformat(),
    }


def scrape_team_profile(team_url: str, known_team_name: str = "") -> dict:
    """
    Scrape a team's profile page.

    CORRECTED structure (confirmed by directly inspecting a real KHU
    team page, since generic JoomSport plugin source didn't match this
    site's actual theme/customization):

      - The page's FIRST <h1> is the site-wide masthead ("KENYA HOCKEY
        UNION"), NOT the team name — using soup.find("h1") blindly
        was pulling the wrong text entirely. We now prefer a name
        already known from standings/match data (passed in as
        known_team_name) since that's proven reliable, and only fall
        back to page scraping if it's not supplied.

      - Match history lives under an "Matches" tab
        ({team_url}#stab_matches), but is server-rendered directly
        into the initial page HTML (the #anchor just toggles CSS
        visibility client-side — confirmed by viewing the real page).
        It uses the EXACT SAME jstable-row / jsMatchDivHome /
        jsMatchDivAway / jsMatchDivScore structure as the per-league
        calendar view we already parse successfully in
        scrape_league_calendar() — so we reuse that same row-parsing
        logic here rather than the old (incorrect) overviewBlocks/
        tblPosition assumption.
    """
    if not team_url:
        return {"error": "No team URL provided"}

    if "/joomsport_team/" not in team_url:
        return {
            "error": "This link doesn't point to a real team profile page — it may have been mis-captured during scraping.",
            "source_url": team_url,
        }

    soup = fetch_page(team_url)
    if not soup:
        return {"error": f"Could not reach {team_url}", "source_url": team_url}

    result = {
        "team_name": correct_team_name(known_team_name) if known_team_name else "",
        "logo_url": "",
        "position": None,
        "form": [],
        "recent_results": [],
        "upcoming_fixtures": [],
        "source_url": team_url,
        "scraped_at": datetime.now().isoformat(),
    }

    # Only scrape the name from the page if we weren't given one —
    # and even then, skip the site's masthead h1 by looking for a
    # heading that sits near the team badge image instead of just
    # taking the first h1 on the page.
    if not result["team_name"]:
        badge_img = soup.find("img", src=re.compile(r"team|emblem|logo|badge", re.I))
        name_candidate = None
        if badge_img:
            # The team name typically appears as a heading shortly after
            # the badge image in the page's reading order.
            name_candidate = badge_img.find_next(["h1", "h2", "h3"])
        if name_candidate:
            result["team_name"] = correct_team_name(name_candidate.get_text(strip=True))
        else:
            # Last resort: page <title> often reads "TeamName - Site Name"
            title_tag = soup.find("title")
            if title_tag:
                title_text = title_tag.get_text(strip=True)
                result["team_name"] = correct_team_name(title_text.split("-")[0].strip())

    # Team badge/logo — same heuristic used elsewhere in this file.
    logo_img = soup.find("img", class_=re.compile(r"team|emblem|logo|badge", re.I))
    if not logo_img:
        logo_img = soup.find("img", src=re.compile(r"team|emblem|logo|badge", re.I))
    if logo_img and logo_img.get("src"):
        logo_src = logo_img.get("src")
        if logo_src.startswith("/"):
            logo_src = BASE_URL + logo_src
        result["logo_url"] = logo_src

    # ── Match history: reuse the proven jstable-row parsing approach ──
    # Find every match row anywhere on the page (the tab system is
    # client-side visibility toggling, not separate content) and split
    # into recent_results / upcoming_fixtures the same way the calendar
    # scraper does, using this team's own name to label the opponent.
    row_divs = soup.find_all("div", class_="jstable-row")
    for row in row_divs:
        if "js-mdname" in row.get("class", []):
            continue  # matchday header row, not an actual match

        time_cell = row.find(class_="jsMatchDivTime")
        date_str = ""
        if time_cell:
            inner = time_cell.find(class_="jsDivLineEmbl")
            date_str = (inner or time_cell).get_text(strip=True)

        home_cell = row.find(class_="jsMatchDivHome")
        home_name = ""
        if home_cell:
            inner = home_cell.find(class_="jsDivLineEmbl")
            home_name = correct_team_name((inner or home_cell).get_text(strip=True))

        away_cell = row.find(class_="jsMatchDivAway")
        away_name = ""
        if away_cell:
            inner = away_cell.find(class_="jsDivLineEmbl")
            away_name = correct_team_name((inner or away_cell).get_text(strip=True))

        if not home_name and not away_name:
            continue

        score_cell = row.find(class_="jsMatchDivScore")
        score_text = ""
        has_live = False
        if score_cell:
            has_live = score_cell.find(class_=re.compile(r"jscalendarLive")) is not None
            score_text = score_cell.get_text(separator=" ", strip=True)

        has_digit_score = bool(re.search(r"\d+\s*[-:]\s*\d+", score_text))

        # Determine which side is "us" vs the opponent, using whichever
        # name is a closer match to our known team name — falls back to
        # simple substring comparison since exact scrape formatting can
        # vary slightly between the calendar view and this team-page view.
        team_name_lower = (result["team_name"] or "").lower()
        is_home_us = team_name_lower and team_name_lower in home_name.lower()
        opponent = away_name if is_home_us else home_name
        venue = "H" if is_home_us else "A"

        if has_digit_score and not has_live:
            result["recent_results"].append({
                "date": date_str,
                "opponent": opponent,
                "venue": venue,
                "result": score_text,
            })
        elif not has_digit_score:
            result["upcoming_fixtures"].append({
                "date": date_str,
                "opponent": opponent,
                "venue": venue,
                "info": "",
            })

    return result


def scrape_match_detail(match_url: str) -> dict:
    """
    Scrape a single match's detail page — confirmed structure from JoomSport
    source (sportleague/views/default/match.php):

      <div class="jsMatchHeader">
        <div class="matchdtime">...date/time...</div>
        <div class="jsmatchday">...matchday name...</div>
        <div class="matchvenue">...venue...</div>
      </div>
      <div class="jsMatchResults">
        <div class="jsMatchTeam jsMatchHomeTeam">
          <div class="jsMatchPartName"><span>Team Name</span></div>
        </div>
        <div class="jsMatchTeam jsMatchAwayTeam">...</div>
        <div class="jsMatchScore">...score...</div>
      </div>
    """
    if not match_url:
        return {"error": "No match URL provided"}

    soup = fetch_page(match_url)
    if not soup:
        return {"error": f"Could not reach {match_url}", "source_url": match_url}

    result = {
        "date": "", "matchday": "", "venue": "",
        "home_team": "", "away_team": "",
        "home_score": None, "away_score": None,
        "is_live": False,
        "source_url": match_url,
        "scraped_at": datetime.now().isoformat(),
    }

    header = soup.find(class_="jsMatchHeader")
    if header:
        date_tag = header.find(class_="matchdtime")
        if date_tag:
            result["date"] = date_tag.get_text(strip=True)
        matchday_tag = header.find(class_="jsmatchday")
        if matchday_tag:
            result["matchday"] = matchday_tag.get_text(strip=True)
        venue_tag = header.find(class_="matchvenue")
        if venue_tag:
            result["venue"] = venue_tag.get_text(strip=True)

    home_tag = soup.find(class_="jsMatchHomeTeam")
    if home_tag:
        name_tag = home_tag.find(class_="jsMatchPartName")
        result["home_team"] = correct_team_name((name_tag or home_tag).get_text(strip=True))

    away_tag = soup.find(class_="jsMatchAwayTeam")
    if away_tag:
        name_tag = away_tag.find(class_="jsMatchPartName")
        result["away_team"] = correct_team_name((name_tag or away_tag).get_text(strip=True))

    score_tag = soup.find(class_="jsMatchScore")
    if score_tag:
        score_text = score_tag.get_text(separator=" ", strip=True)
        score_match = re.search(r"(\d+)\s*[-:]\s*(\d+)", score_text)
        if score_match:
            result["home_score"] = int(score_match.group(1))
            result["away_score"] = int(score_match.group(2))
        result["is_live"] = bool(score_tag.find(class_=re.compile(r"jscalendarLive")))

    return result





    """
    Scrape upcoming fixtures and recent results from the KHU homepage.
    Uses a retry + longer timeout since homepage sometimes drops connections.
    """
    # Try homepage with longer timeout and retry
    soup = None
    for attempt in range(3):
        try:
            logger.info(f"Fetching homepage (attempt {attempt+1})")
            resp = requests.get(
                BASE_URL + "/",
                headers=HEADERS,
                timeout=25
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                logger.info(f"Homepage OK — {len(resp.text)} bytes")
                break
        except Exception as e:
            logger.warning(f"Homepage attempt {attempt+1} failed: {e}")

    if not soup:
        return {
            "fixtures": [], "results": [],
            "total_fixtures": 0, "total_results": 0,
            "error": "Homepage unreachable after 3 attempts",
            "scraped_at": datetime.now().isoformat(),
        }

    fixtures = []
    results  = []

    # Try known JoomSport event class names
    event_blocks = []
    for cls in [
        "jsEvent", "jssEvent", "jsMatch",
        "joomSport-event", "event-row", "match-row",
        "jss-event", "js-event"
    ]:
        found = soup.find_all(["div", "tr", "li"], class_=cls)
        if found:
            logger.info(f"Found {len(found)} events with class='{cls}'")
            event_blocks = found
            break

    # Fallback: look inside joomsport containers
    if not event_blocks:
        for container_id in ["joomsport-container", "jssContainer", "jsContainer"]:
            container = soup.find(id=container_id)
            if container:
                event_blocks = container.find_all("tr")
                if event_blocks:
                    logger.info(f"Found {len(event_blocks)} rows in #{container_id}")
                    break

    # Last fallback: all table rows
    if not event_blocks:
        logger.info("Using all table rows as fallback...")
        event_blocks = [
            row for row in soup.find_all("tr")
            if len(row.find_all("td")) >= 4
        ]

    for block in event_blocks[:200]:
        # Extract fields using regex-based class matching
        date_tag   = block.find(class_=re.compile(r"date",    re.I))
        time_tag   = block.find(class_=re.compile(r"time",    re.I))
        score_tag  = block.find(class_=re.compile(r"score|result",  re.I))
        venue_tag  = block.find(class_=re.compile(r"venue|location|ground|stadium", re.I))
        league_tag = block.find(class_=re.compile(r"league|season|competition", re.I))

        date_str    = date_tag.get_text(strip=True)   if date_tag   else ""
        time_str    = time_tag.get_text(strip=True)   if time_tag   else ""
        score       = score_tag.get_text(strip=True)  if score_tag  else ""
        venue       = venue_tag.get_text(strip=True)  if venue_tag  else ""
        league_name = league_tag.get_text(strip=True) if league_tag else ""

        # Extract team names
        team_tags = block.find_all(class_=re.compile(r"team", re.I))
        home_team = team_tags[0].get_text(strip=True) if len(team_tags) > 0 else ""
        away_team = team_tags[1].get_text(strip=True) if len(team_tags) > 1 else ""

        if not home_team and not away_team:
            continue

        entry = {
            "date":      date_str,
            "time":      time_str,
            "home_team": home_team,
            "away_team": away_team,
            "score":     score,
            "venue":     venue,
            "league":    league_name,
        }

        if score and re.search(r"\d", score):
            results.append(entry)
        else:
            fixtures.append(entry)

    return {
        "fixtures":       fixtures,
        "results":        results,
        "total_fixtures": len(fixtures),
        "total_results":  len(results),
        "scraped_at":     datetime.now().isoformat(),
        "source_url":     BASE_URL,
    }


def scrape_all_standings() -> dict:
    """Scrape all 8 leagues in order: Men Tier1→2→3, Women Tier1→2."""
    all_data = {}
    order = [
        "premier_league_men",
        "super_league_men",
        "national_league_men_ez",
        "national_league_men_cz",
        "national_league_men_wz",
        "national_league_men_sz",
        "premier_league_women",
        "super_league_women",
    ]
    for key in order:
        logger.info(f"── Scraping: {LEAGUES[key]['name']} ──")
        all_data[key] = scrape_standings(key)
    return all_data


# ══════════════════════════════════════════════════════════
# TEST — run: python scraper.py
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    SEP = "=" * 65

    print(f"\n{SEP}")
    print("  KHU SCRAPER — LIVE DATA TEST")
    print(f"  Source: kenyahockeyunion.org")
    print(f"  Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEP)

    league_order = [
        ("premier_league_men",      "[1] PREMIER LEAGUE MEN (Tier 1)"),
        ("super_league_men",        "[2] SUPER LEAGUE MEN (Tier 2)"),
        ("national_league_men_ez",  "[3] NATIONAL LEAGUE MEN — EZ (Tier 3)"),
        ("national_league_men_cz",  "[4] NATIONAL LEAGUE MEN — CZ (Tier 3)"),
        ("national_league_men_wz",  "[5] NATIONAL LEAGUE MEN — WZ (Tier 3)"),
        ("national_league_men_sz",  "[6] NATIONAL LEAGUE MEN — SZ (Tier 3)"),
        ("premier_league_women",    "[7] PREMIER LEAGUE WOMEN (Tier 1)"),
        ("super_league_women",      "[8] SUPER LEAGUE WOMEN (Tier 2)"),
    ]

    for league_key, label in league_order:
        print(f"\n{label}")
        print("-" * 65)
        data = scrape_standings(league_key)
        print(f"  League : {data.get('league')}")
        print(f"  Teams  : {data.get('total_teams', 0)}")
        if data.get("error"):
            print(f"  ⚠ ERROR: {data['error']}")
            print(f"  URL    : {data.get('source_url', '')}")
        else:
            for t in data.get("standings", []):
                form = " ".join(t.get("form", [])) or "—"
                print(
                    f"  {t['position']:>2}. {t['team']:<30} "
                    f"Pl:{t['played']:>2} W:{t['won']} D:{t['drawn']} L:{t['lost']} "
                    f"GF:{t['goals_for']:>2} GA:{t['goals_against']:>2} "
                    f"GD:{t['goal_diff']:>3} Pts:{t['points']:>2}  [{form}]"
                )

    print(f"\n{'─'*65}")
    print("[9] FIXTURES & RESULTS — per-league calendar scraper")
    print("-" * 65)
    fr2 = scrape_all_fixtures_and_results()
    print(f"  Live     : {fr2.get('total_live', 0)}")
    print(f"  Fixtures : {fr2.get('total_fixtures', 0)}")
    print(f"  Results  : {fr2.get('total_results', 0)}")
    if fr2.get("leagues_with_errors"):
        print(f"  ⚠ Errors in {len(fr2['leagues_with_errors'])} leagues:")
        for e in fr2["leagues_with_errors"]:
            print(f"    {e['league']}: {e['error']}")
    if fr2.get("live"):
        print("\n  -- LIVE NOW --")
        for m in fr2["live"][:5]:
            print(f"    [{m['league_short']}] {m['home_team']} {m['home_score']}-{m['away_score']} {m['away_team']}")
    if fr2.get("results"):
        print("\n  -- Recent Results (calendar-based) --")
        for m in fr2["results"][:8]:
            print(f"    [{m['league_short']}] {m['date']:20} {m['home_team']} {m['home_score']}-{m['away_score']} {m['away_team']}")
    if fr2.get("fixtures"):
        print("\n  -- Upcoming Fixtures (calendar-based) --")
        for m in fr2["fixtures"][:8]:
            print(f"    [{m['league_short']}] {m['date']:20} {m['home_team']} vs {m['away_team']}")

    print(f"\n{SEP}")
    print("  Test complete.")
    print(SEP)
