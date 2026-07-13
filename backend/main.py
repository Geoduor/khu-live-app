"""
KHU Backend — main.py
FastAPI server serving real Kenya Hockey Union data.

Strategy (matches how ESPN/SofaScore/FotMob handle unreliable upstream sources):
  1. On startup: load whatever is cached in SQLite INSTANTLY (no blank screen)
  2. Kick off a live scrape in the background
  3. If the scrape succeeds: update cache, serve fresh data
  4. If the scrape fails: keep serving the last-known-good cache,
     and tell the frontend exactly how stale it is
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging
import os

from scraper import (
    scrape_standings,
    scrape_all_fixtures_and_results,
    scrape_team_profile,
    scrape_match_detail,
    _parse_match_date,
    LEAGUES,
    LEAGUE_DISPLAY_ORDER,
)
import database as db
import push


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscription(BaseModel):
    endpoint: str
    keys: PushKeys
    expirationTime: Optional[float] = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Kenya Hockey Union API",
    description="Real-time data from kenyahockeyunion.org, with persistent local caching",
    version="1.1.0",
)

# CORS origins: locally we allow everything for convenience. In production
# (Render), set ALLOWED_ORIGINS to your real Vercel URL(s), comma-separated,
# e.g. "https://khu-live-app.vercel.app,https://your-custom-domain.com"
_allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", "")
allowed_origins = (
    [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
    if _allowed_origins_env
    else ["*"]  # local dev fallback — fine for testing, tighten in production
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory mirror of the DB cache, for fast reads ──
cache = {
    "standings": {},           # league_key -> data dict
    "fixtures_results": None,
    "last_refresh_attempt": None,
    "last_refresh_success": None,
    "status": "starting",
}

STALE_THRESHOLD_SECONDS = 60 * 30  # 30 minutes


def refresh_standings_for(league_key: str):
    """Scrape one league; save to DB regardless of success; update in-memory cache."""
    try:
        data = scrape_standings(league_key)
        success = not bool(data.get("error"))
        db.save_standings(league_key, data, success=success)
        data["_cache_scraped_at"] = datetime.now().isoformat()
        data["_cache_success"] = success
        cache["standings"][league_key] = data
        if success:
            logger.info(f"✅ {league_key}: {data.get('total_teams', 0)} teams")
        else:
            logger.warning(f"⚠️ {league_key}: scrape failed — {data.get('error')}")
        return success
    except Exception as e:
        logger.error(f"❌ {league_key}: exception during scrape — {e}")
        return False


def refresh_fixtures_results():
    """
    Scrape fixtures/results/live using the per-league calendar scraper.
    Also detects newly-LIVE matches (weren't live last refresh) and
    triggers a push notification — same pattern FotMob uses for
    "match started" alerts.
    """
    try:
        data = scrape_all_fixtures_and_results()
        total = data.get("total_fixtures", 0) + data.get("total_results", 0) + data.get("total_live", 0)
        success = total > 0

        # ── Detect newly-live matches vs the previous snapshot ──
        prev_live_keys = set()
        prev_data = cache.get("fixtures_results")
        if prev_data and prev_data.get("live"):
            prev_live_keys = {
                f"{m['home_team']}_vs_{m['away_team']}_{m.get('date','')}"
                for m in prev_data["live"]
            }

        new_live = []
        for m in data.get("live", []):
            key = f"{m['home_team']}_vs_{m['away_team']}_{m.get('date','')}"
            if key not in prev_live_keys:
                new_live.append(m)

        db.save_fixtures_results(data, success=success)
        data["_cache_scraped_at"] = datetime.now().isoformat()
        data["_cache_success"] = success
        cache["fixtures_results"] = data

        # ── Fire push notifications for newly-live matches ──
        # Scoped: subscribers with favorite teams only get alerted when
        # one of THEIR followed teams is playing. Subscribers who haven't
        # set any favorites yet still get everything (see push.py docstring).
        for m in new_live:
            try:
                team_urls = [u for u in [m.get("home_team_url"), m.get("away_team_url")] if u]
                push.send_notification_to_favoriters(
                    team_urls=team_urls,
                    title=f"🔴 LIVE: {m['home_team']} vs {m['away_team']}",
                    body=f"{m.get('league','KHU')} — kicking off now!",
                    url="/",
                )
            except Exception as e:
                logger.error(f"Push notification failed for {m}: {e}")

        if success:
            logger.info(
                f"✅ fixtures/results: {data.get('total_live',0)} live, "
                f"{data.get('total_fixtures',0)} fixtures, {data.get('total_results',0)} results"
                + (f" | {len(new_live)} newly live -> notified" if new_live else "")
            )
        else:
            logger.warning("⚠️ fixtures/results scrape returned nothing useful")
        return success
    except Exception as e:
        logger.error(f"❌ fixtures/results: exception — {e}")
        return False


def refresh_all_data(force: bool = False):
    """
    Refresh every league + homepage. Called on startup, every 15 minutes
    (scheduled/automatic), and on manual refresh (force=True).

    Circuit breaker behavior:
      - Scheduled calls (force=False) respect the breaker — if it's OPEN
        and still in cooldown, we skip the real scrape entirely and just
        keep serving cache. This stops us hammering a struggling KHU server.
      - Manual calls (force=True) always attempt a real scrape, since a
        user action is a stronger signal than a scheduled guess — this
        matches how Gmail/Twitter/FotMob treat pull-to-refresh.
    """
    logger.info("═" * 50)

    if not force and not db.should_attempt_scrape(cooldown_seconds=300):
        logger.info("⚪ Skipping scheduled refresh — circuit breaker OPEN, serving cache only")
        cache["status"] = "cached" if cache["standings"] else cache["status"]
        return

    logger.info(f"Starting full data refresh... (force={force})")
    cache["last_refresh_attempt"] = datetime.now().isoformat()

    results = []
    for league_key in LEAGUES:
        results.append(refresh_standings_for(league_key))
    results.append(refresh_fixtures_results())

    any_success = any(results)
    all_success = all(results)

    # Update circuit breaker based on this cycle's overall outcome
    db.record_scrape_result(success=any_success, failure_threshold=3)

    if all_success:
        cache["status"] = "live"
    elif any_success:
        cache["status"] = "partial"
    else:
        cache["status"] = "error"

    if any_success:
        cache["last_refresh_success"] = datetime.now().isoformat()

    breaker_state = db.get_circuit_state()
    logger.info(f"Refresh complete — status: {cache['status']} | circuit: {breaker_state['state']}")
    logger.info("═" * 50)


def load_from_cache_on_boot():
    """
    Load whatever we have in SQLite immediately on startup,
    so the API can respond instantly even before the first live scrape finishes.
    """
    logger.info("Loading cached data from SQLite (instant boot)...")
    cached_standings = db.load_all_standings()
    for key, data in cached_standings.items():
        cache["standings"][key] = data
    cached_fr = db.load_fixtures_results()
    if cached_fr:
        cache["fixtures_results"] = cached_fr

    if cached_standings or cached_fr:
        cache["status"] = "cached"
        logger.info(f"Loaded {len(cached_standings)} cached leagues from previous run")
    else:
        cache["status"] = "starting"
        logger.info("No previous cache found — this is a fresh start")


# ── Scheduler: refresh every 15 minutes ──
scheduler = BackgroundScheduler()
scheduler.add_job(refresh_all_data, "interval", minutes=15)
scheduler.start()


@app.on_event("startup")
async def startup_event():
    db.init_db()
    push.init_push_table()
    load_from_cache_on_boot()
    logger.info("KHU API starting up — kicking off first live scrape...")
    refresh_all_data()


# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════

def annotate_staleness(data: dict) -> dict:
    """Add a human-readable staleness flag to any cached payload."""
    if not data:
        return data
    scraped_at = data.get("_cache_scraped_at") or data.get("scraped_at")
    if scraped_at:
        age = db.cache_age_seconds(scraped_at)
        data["_cache_age_seconds"] = age
        data["_is_stale"] = age > STALE_THRESHOLD_SECONDS
    return data


# ══════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════

@app.get("/")
def root():
    return {
        "app": "Kenya Hockey Union API",
        "version": "1.1.0",
        "status": cache["status"],
        "last_refresh_attempt": cache["last_refresh_attempt"],
        "last_refresh_success": cache["last_refresh_success"],
        "endpoints": [
            "/api/fixtures", "/api/results",
            "/api/standings/{league_key}", "/api/standings/all",
            "/api/leagues", "/api/refresh", "/api/health",
        ],
    }


@app.get("/api/health")
def health():
    breaker_state = db.get_circuit_state()
    return {
        "status": cache["status"],
        "last_refresh_attempt": cache["last_refresh_attempt"],
        "last_refresh_success": cache["last_refresh_success"],
        "leagues_cached": len(cache["standings"]),
        "fixtures_results_cached": cache["fixtures_results"] is not None,
        "circuit_breaker": {
            "state": breaker_state["state"],
            "consecutive_failures": breaker_state["consecutive_failures"],
            "opened_at": breaker_state["opened_at"],
        },
    }


@app.get("/api/leagues")
def get_leagues():
    """
    Returns leagues in LEAGUE_DISPLAY_ORDER (PLM, PLW, SLM, SLW, then
    National League zones) rather than LEAGUES dict insertion order,
    which is separately optimized for scraping/scheduling sequence.
    """
    ordered_keys = [k for k in LEAGUE_DISPLAY_ORDER if k in LEAGUES]
    # Safety net: include any league not explicitly listed, so a future
    # addition to LEAGUES never silently disappears from this endpoint.
    ordered_keys += [k for k in LEAGUES if k not in ordered_keys]

    return {
        "leagues": [
            {"key": key, "name": LEAGUES[key]["name"], "short": LEAGUES[key]["short"], "url": LEAGUES[key]["url"]}
            for key in ordered_keys
        ]
    }


@app.get("/api/live")
def get_live_matches():
    """Matches currently in progress (state == LIVE)."""
    data = cache.get("fixtures_results")
    if not data:
        raise HTTPException(status_code=503, detail="No match data available yet.")
    data = annotate_staleness(dict(data))
    return {
        "live": data.get("live", []),
        "total": data.get("total_live", 0),
        "source": "kenyahockeyunion.org",
        "scraped_at": data.get("_cache_scraped_at"),
        "is_stale": data.get("_is_stale", False),
    }


@app.get("/api/fixtures")
def get_fixtures():
    data = cache.get("fixtures_results")
    if not data:
        raise HTTPException(status_code=503, detail="No fixtures data available yet — try again shortly.")
    data = annotate_staleness(dict(data))
    return {
        "fixtures": data.get("fixtures", []),
        "total": data.get("total_fixtures", 0),
        "source": "kenyahockeyunion.org",
        "scraped_at": data.get("_cache_scraped_at"),
        "is_stale": data.get("_is_stale", False),
        "cache_age_seconds": data.get("_cache_age_seconds"),
    }


@app.get("/api/results")
def get_results():
    data = cache.get("fixtures_results")
    if not data:
        raise HTTPException(status_code=503, detail="No results data available yet — try again shortly.")
    data = annotate_staleness(dict(data))

    results = data.get("results", [])
    # "most_recent" ignores league grouping entirely and sorts purely
    # by date across ALL leagues — used for the Home page preview,
    # where "3 most recent results anywhere" is the intent, not
    # "3 results from whichever league happens to be first."
    most_recent = sorted(
        results,
        key=lambda m: _parse_match_date(m.get("date", "")),
        reverse=True,
    )

    return {
        "results": results,
        "most_recent": most_recent,
        "total": data.get("total_results", 0),
        "source": "kenyahockeyunion.org",
        "scraped_at": data.get("_cache_scraped_at"),
        "is_stale": data.get("_is_stale", False),
        "cache_age_seconds": data.get("_cache_age_seconds"),
    }


@app.get("/api/standings/all")
def get_all_standings():
    if not cache["standings"]:
        raise HTTPException(status_code=503, detail="Standings not yet loaded.")
    annotated = {k: annotate_staleness(dict(v)) for k, v in cache["standings"].items()}
    return {"standings": annotated, "source": "kenyahockeyunion.org"}


@app.get("/api/teams/all")
def get_all_teams():
    """
    Flat list of every team across all 8 leagues, for the favorites
    onboarding picker — lets the frontend show one unified
    "which teams do you follow?" list without querying 8 endpoints.

    Includes team_url for every team, since that's the identity key
    used everywhere else (standings rows, match cards, push scoping).
    Teams without a captured profile link (rare scrape gaps) are still
    included using their name as a fallback key so they remain
    selectable, but won't scope push notifications until a real
    team_url is available for them.
    """
    if not cache["standings"]:
        raise HTTPException(status_code=503, detail="Standings not yet loaded.")

    teams = []
    seen = set()
    for league_key, league_data in cache["standings"].items():
        league_name = league_data.get("league", league_key)
        for team in league_data.get("standings", []):
            name = team.get("team")
            team_url = team.get("team_url") or ""
            dedupe_key = team_url or name
            if name and dedupe_key not in seen:
                seen.add(dedupe_key)
                teams.append({"name": name, "team_url": team_url, "league": league_name})

    teams.sort(key=lambda t: t["name"])
    return {"teams": teams, "total": len(teams)}


@app.get("/api/standings/{league_key}")
def get_standings(league_key: str):
    if league_key not in LEAGUES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown league '{league_key}'. Available: {list(LEAGUES.keys())}",
        )

    data = cache["standings"].get(league_key)

    if not data:
        # Nothing cached at all yet — try one synchronous scrape right now
        logger.info(f"No cache for {league_key} — scraping live on demand...")
        success = refresh_standings_for(league_key)
        data = cache["standings"].get(league_key)
        if not data:
            raise HTTPException(status_code=503, detail="Could not fetch standings — KHU site may be down.")

    return annotate_staleness(dict(data))


@app.post("/api/refresh")
def manual_refresh():
    """
    User-triggered refresh — always attempts a real scrape (bypasses the
    circuit breaker), because a user action is a stronger, more valuable
    signal than a scheduled guess. Same pattern as Gmail/Twitter/FotMob
    pull-to-refresh.

    Still rate-limited to 1 per 10s so button-mashing can't hammer KHU.
    """
    if not db.can_manual_refresh(min_interval_seconds=10):
        raise HTTPException(
            status_code=429,
            detail="Please wait a few seconds before refreshing again."
        )

    logger.info("Manual refresh triggered by user — bypassing circuit breaker.")
    db.record_manual_refresh()
    refresh_all_data(force=True)

    breaker_state = db.get_circuit_state()
    return {
        "message": "Refresh complete",
        "status": cache["status"],
        "last_refresh_success": cache["last_refresh_success"],
        "circuit_breaker_state": breaker_state["state"],
    }


# ══════════════════════════════════════════════════════
# PUSH NOTIFICATIONS
# ══════════════════════════════════════════════════════

from pydantic import BaseModel
from typing import Optional


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionPayload(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
    expirationTime: Optional[float] = None
    favoriteTeams: Optional[list] = None  # Tier 2 scoping — empty/None = Tier 1 (all matches)


class UpdateFavoritesPayload(BaseModel):
    endpoint: str
    favoriteTeams: list


@app.get("/api/push/vapid-public-key")
def get_vapid_public_key():
    """Frontend calls this to get the public key needed for subscribing."""
    return {"publicKey": push.VAPID_PUBLIC_KEY_B64URL}


@app.post("/api/push/subscribe")
def subscribe_to_push(subscription: PushSubscriptionPayload):
    """
    Store a browser's push subscription so we can notify it on live matches.
    If favoriteTeams is provided and non-empty, this subscriber only gets
    alerts for matches involving those teams (Tier 2 — scoped).
    If omitted/empty, they get alerts for every KHU match (Tier 1 — broad).
    """
    data = subscription.dict()
    favorite_teams = data.pop("favoriteTeams", None)
    push.save_subscription(data, favorite_teams=favorite_teams)
    scope_msg = f"for {len(favorite_teams)} favorite team(s)" if favorite_teams else "for all KHU matches"
    return {"message": f"Subscribed to live match notifications {scope_msg}"}


@app.post("/api/push/update-favorites")
def update_push_favorites(payload: UpdateFavoritesPayload):
    """
    Update which teams an existing subscriber wants alerts for —
    called whenever the user changes their favorites in the app,
    without needing to fully re-subscribe.
    """
    push.update_favorite_teams(payload.endpoint, payload.favoriteTeams)
    return {"message": "Favorite teams updated for notifications"}


@app.get("/api/push/favorites")
def get_push_favorites(endpoint: str):
    """Fetch the current favorite team URLs for a given subscription endpoint."""
    return {"favoriteTeams": push.get_favorite_teams(endpoint)}


@app.post("/api/push/unsubscribe")
def unsubscribe_from_push(payload: dict):
    endpoint = payload.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint is required")
    push.remove_subscription(endpoint)
    return {"message": "Unsubscribed"}


@app.post("/api/push/test")
def send_test_push():
    """Manual trigger to test push notifications are working end-to-end."""
    result = push.send_notification_to_all(
        title="🏑 KHU Test Notification",
        body="If you see this, push notifications are working!",
        url="/",
    )
    return result


# ══════════════════════════════════════════════════════
# TEAM PROFILES & MATCH DETAIL
# ══════════════════════════════════════════════════════
# These are fetched on-demand (not part of the 15-min scheduled refresh)
# since there could be dozens of teams/matches — we cache each result
# in-memory for 10 minutes to avoid hammering KHU if a page is popular.

import time

TEAM_CACHE_TTL = 600  # 10 minutes
_team_cache = {}   # team_url -> (data, fetched_at)
_match_cache = {}  # match_url -> (data, fetched_at)


@app.get("/api/team")
def get_team_profile(url: str, name: str = ""):
    """
    Fetch a team's profile page (position, form, results, fixtures).
    'url' must be a real kenyahockeyunion.org team page URL, which the
    frontend gets from the 'team_url' field already present in standings
    and match data — never guessed or constructed.

    'name' is optional — if the frontend already knows the team's name
    (e.g. from the standings row or match card the user tapped), pass
    it here. This avoids re-scraping the name from the page itself,
    which proved unreliable (the page's first <h1> is the site's own
    masthead, not the team name).
    """
    if "kenyahockeyunion.org" not in url:
        raise HTTPException(status_code=400, detail="Invalid team URL — must be a kenyahockeyunion.org link")

    cache_key = f"{url}::{name}"
    cached = _team_cache.get(cache_key)
    if cached and (time.time() - cached[1]) < TEAM_CACHE_TTL:
        return cached[0]

    data = scrape_team_profile(url, known_team_name=name)
    if not data.get("error"):
        _team_cache[cache_key] = (data, time.time())
    return data


@app.get("/api/match")
def get_match_detail(url: str):
    """
    Fetch a single match's detail page (date, venue, teams, score).
    'url' comes from the 'match_url' field already present in fixtures/results
    data — never guessed or constructed.
    """
    if "kenyahockeyunion.org" not in url:
        raise HTTPException(status_code=400, detail="Invalid match URL — must be a kenyahockeyunion.org link")

    cached = _match_cache.get(url)
    # Live matches should never be served from cache — always fetch fresh
    if cached and (time.time() - cached[1]) < TEAM_CACHE_TTL and not cached[0].get("is_live"):
        return cached[0]

    data = scrape_match_detail(url)
    if not data.get("error"):
        _match_cache[url] = (data, time.time())
    return data
