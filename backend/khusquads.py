"""
khusquads.py — read a team's public squad list from the Kenya Hockey Union website
and turn it into player profiles (name, shirt number and, where KHU has one, a photo).

Only KHU's own pages and images are fetched (scraper.safe_get refuses any other
host). Profiles an admin or agent already filled in are never overwritten: only
blank shirt numbers and missing photos are completed. Photos KHU shows as a grey
placeholder are ignored.
"""
import logging
import re
from urllib.parse import urljoin

logger = logging.getLogger("khusquads")
MAX_PHOTO_BYTES = 300_000


def _is_placeholder(src: str) -> bool:
    name = (src or "").split("?")[0].rsplit("/", 1)[-1].lower()
    return (not name) or "_st." in name or name.startswith(("player_st", "teams_st", "default"))


def _name_of(node) -> str:
    n = node.select_one(".js_div_particName")
    return " ".join(n.get_text(" ", strip=True).split()) if n else ""


def parse_squad(soup, base_url: str = "https://www.kenyahockeyunion.org/") -> list:
    """[{name, jersey, player_url, photo_url}] from a KHU team page (already parsed)."""
    players, order = {}, []

    def entry(name):
        k = name.lower()
        if k not in players:
            players[k] = {"name": name, "jersey": None, "player_url": "", "photo_url": ""}
            order.append(k)
        return players[k]

    # 1) the squad table: Name ... Shirt Number
    for table in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if "name" not in heads or not any("shirt" in h for h in heads):
            continue
        shirt_col = next(i for i, h in enumerate(heads) if "shirt" in h)
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            name = _name_of(tds[0]) or tds[0].get_text(" ", strip=True)
            if not name:
                continue
            e = entry(name)
            if shirt_col < len(tds):
                digits = re.sub(r"\D", "", tds[shirt_col].get_text())
                if digits and e["jersey"] is None and 0 <= int(digits) <= 99:
                    e["jersey"] = int(digits)
            a = tds[0].find("a", href=True)
            if a and not e["player_url"]:
                e["player_url"] = urljoin(base_url, a["href"])
            img = tds[0].find("img")
            if img and img.get("src") and not _is_placeholder(img["src"]) and not e["photo_url"]:
                e["photo_url"] = urljoin(base_url, img["src"])

    # 2) the picture cards (bigger photos) - they win over the table's thumbnails
    for card in soup.select(".jsplayerCart"):
        name = _name_of(card)
        if not name:
            continue
        e = entry(name)
        a = card.find("a", href=True)
        if a and not e["player_url"]:
            e["player_url"] = urljoin(base_url, a["href"])
        img = card.find("img")
        if img and img.get("src") and not _is_placeholder(img["src"]):
            e["photo_url"] = urljoin(base_url, img["src"])

    return [players[k] for k in order]


def import_team(soup, league_short, team_name, base_url, fetch_photo, save, tally):
    """Save every player found on a parsed team page. fetch_photo(url) -> bytes|None."""
    for p in parse_squad(soup, base_url):
        photo = None
        if p["photo_url"]:
            try:
                photo = fetch_photo(p["photo_url"])
            except Exception as e:  # noqa: BLE001 - one bad photo must not stop the team
                logger.warning("photo skipped for %s: %s", p["name"], type(e).__name__)
            if photo is None:
                tally["photos_skipped"] += 1
        result = save(league_short, team_name, p["name"], p["jersey"], photo)
        tally[result] = tally.get(result, 0) + 1
        if photo and result in ("created", "updated"):
            tally["photos"] += 1
