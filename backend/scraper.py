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
    JoomSport renders form as colored spans with text W, D or L.
    Example: <span class="label label-success">W</span>
             <span class="label label-danger">L</span>
    Returns list of last 5 results e.g. ['W', 'D', 'L', 'W', 'W']
    """
    form = []
    for tag in cell.find_all(True):
        text = tag.get_text(strip=True).upper()
        if text in ("W", "D", "L") and len(text) == 1:
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


def parse_standings_table(table) -> list:
    """
    Parse a JoomSport standings table into a list of team dicts.
    Column order (confirmed from KHU screenshot):
    0=Rank | 1=Team | 2=Pl | 3=W | 4=D | 5=L | 6=Diff | 7=GD | 8=Pts | 9=Form
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
        team_link_tag = team_cell.find("a")
        team_url = team_link_tag.get("href", "") if team_link_tag else ""
        for img in team_cell.find_all("img"):
            img.decompose()
        team_name = team_cell.get_text(strip=True)
        if not team_name:
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

    standings = parse_standings_table(table)

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
            home_name = (inner or home_cell).get_text(strip=True)
            link_tag = home_cell.find("a")
            if link_tag:
                home_team_url = link_tag.get("href", "")

        # Away team name + profile link
        away_cell = row.find(class_="jsMatchDivAway")
        away_name = ""
        away_team_url = ""
        if away_cell:
            inner = away_cell.find(class_="jsDivLineEmbl")
            away_name = (inner or away_cell).get_text(strip=True)
            link_tag = away_cell.find("a")
            if link_tag:
                away_team_url = link_tag.get("href", "")

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
            "away_team":  away_name,
            "away_team_url": away_team_url,
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


def scrape_all_fixtures_and_results() -> dict:
    """
    Scrape the calendar for EVERY league and split matches into
    upcoming fixtures (NS) vs results (FT) vs live (LIVE).
    This replaces the old unreliable homepage-guessing scraper.
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


def scrape_team_profile(team_url: str) -> dict:
    """
    Scrape a team's profile page — confirmed structure from JoomSport source
    (sportleague/views/default/elements/team-overview.php):

      <div class="overviewBlocks"><h3>Position</h3><table class="tblPosition">...</table></div>
      <div class="overviewBlocks"><h3>Current form</h3><table class="tblPosition">...</table></div>
      <div class="overviewBlocks"><h3>Results</h3>
        <table class="tblPosition">
          <thead><tr><th>Date</th><th>Team</th><th>Location</th><th>Results</th></tr></thead>
          <tbody>...</tbody>
        </table>
      </div>
      <div class="overviewBlocks"><h3>Fixtures</h3><table class="tblPosition">...same columns...</table></div>
    """
    if not team_url:
        return {"error": "No team URL provided"}

    soup = fetch_page(team_url)
    if not soup:
        return {"error": f"Could not reach {team_url}", "source_url": team_url}

    result = {
        "team_name": "",
        "position": None,
        "form": [],
        "recent_results": [],
        "upcoming_fixtures": [],
        "source_url": team_url,
        "scraped_at": datetime.now().isoformat(),
    }

    h1 = soup.find("h1")
    if h1:
        result["team_name"] = h1.get_text(strip=True)

    blocks = soup.find_all("div", class_="overviewBlocks")
    for block in blocks:
        heading = block.find("h3")
        heading_text = heading.get_text(strip=True).lower() if heading else ""
        table = block.find("table", class_="tblPosition")
        if not table:
            continue

        if "position" in heading_text:
            tbody = table.find("tbody")
            row = tbody.find("tr") if tbody else None
            if row:
                cells = [c.get_text(strip=True) for c in row.find_all("td")]
                if cells:
                    result["position"] = cells[0]

        elif "current form" in heading_text:
            tbody = table.find("tbody")
            row = tbody.find("tr") if tbody else None
            if row:
                form = []
                for cell in row.find_all("td"):
                    letter_tag = cell.find(class_=re.compile(r"jsform"))
                    text = (letter_tag or cell).get_text(strip=True).upper()
                    if text in ("W", "D", "L"):
                        form.append(text)
                result["form"] = form

        elif "results" in heading_text:
            tbody = table.find("tbody")
            if tbody:
                for row in tbody.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) >= 4:
                        result["recent_results"].append({
                            "date":     cells[0].get_text(strip=True),
                            "opponent": cells[1].get_text(strip=True),
                            "venue":    cells[2].get_text(strip=True),
                            "result":   cells[3].get_text(strip=True),
                        })

        elif "fixtures" in heading_text:
            tbody = table.find("tbody")
            if tbody:
                for row in tbody.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) >= 4:
                        result["upcoming_fixtures"].append({
                            "date":     cells[0].get_text(strip=True),
                            "opponent": cells[1].get_text(strip=True),
                            "venue":    cells[2].get_text(strip=True),
                            "info":     cells[3].get_text(strip=True),
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
        result["home_team"] = (name_tag or home_tag).get_text(strip=True)

    away_tag = soup.find(class_="jsMatchAwayTeam")
    if away_tag:
        name_tag = away_tag.find(class_="jsMatchPartName")
        result["away_team"] = (name_tag or away_tag).get_text(strip=True)

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
    print("[9] FIXTURES & RESULTS (Homepage)")
    print("-" * 65)
    fr = scrape_fixtures_and_results()
    print(f"  Fixtures : {fr.get('total_fixtures', 0)}")
    print(f"  Results  : {fr.get('total_results', 0)}")
    if fr.get("error"):
        print(f"  ⚠ ERROR  : {fr['error']}")
    if fr.get("results"):
        print("\n  Recent Results:")
        for r in fr["results"][:8]:
            print(f"    {r['date']:12} {r['home_team']} vs {r['away_team']} | {r['score']}")
    if fr.get("fixtures"):
        print("\n  Upcoming Fixtures:")
        for f in fr["fixtures"][:8]:
            print(f"    {f['date']:12} {f['time']:8} {f['home_team']} vs {f['away_team']}")

    print(f"\n{'─'*65}")
    print("[9] FIXTURES & RESULTS — NEW: per-league calendar scraper")
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
