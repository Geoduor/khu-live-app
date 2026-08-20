"""
pdf_fixtures.py — Parses KHU's official "Season Calendar" PDF into the
SAME match dict schema produced by scraper.scrape_all_fixtures_and_results(),
so the rest of the app (API routes, frontend Fixtures tab) doesn't need to
know or care whether a fixture came from the live site or a PDF.

WHY THIS EXISTS:
KHU periodically publishes/updates the season fixture list as a PDF
(e.g. "20260814_KHU_2026_Season_Calendar_Ver_02.pdf") — sometimes ahead
of the live JoomSport site being updated, sometimes with matches the
site calendar view doesn't have yet. Confirmed as a RECURRING pattern,
not a one-off.

GROUND RULE (same as scraper.py): no hallucinated data. Every field
comes directly from the PDF's own table structure. If a row is
malformed or a team name is unrecognized, it is either skipped
(logged) or passed through as-is — never guessed.
"""

import re
import logging
from datetime import datetime

import pdfplumber

logger = logging.getLogger(__name__)

# League short codes as they appear in the PDF's LEAGUE column —
# confirmed to match scraper.LEAGUES[*]["short"] exactly.
KNOWN_LEAGUE_SHORTS = {"PLM", "PLW", "SLM", "SLW", "NLM-EZ", "NLM-CZ", "NLM-WZ", "NLM-SZ"}

# ── PDF-specific team name corrections ──
# The PDF's fixture table uses shorthand names that don't always match
# the canonical names scraped from the live site's team roster/standings
# (e.g. "KU Ladies" in the fixture table vs "Kenyatta University" on the
# site). This map is SEPARATE from scraper.TEAM_NAME_CORRECTIONS (which
# fixes actual site typos) — this one bridges PDF-shorthand -> site-canonical.
#
# Built by manually cross-referencing this PDF's own "LEAGUES AND TEAMS"
# page against its fixture table. New abbreviations in future PDFs will
# need to be added here the same way — this is expected to grow, same
# as TEAM_NAME_CORRECTIONS does.
PDF_NAME_CORRECTIONS = {
    "KU Ladies": "Kenyatta University",
    "UoN Ladies": "University Of Nairobi",
    "MSC Ladies": "Mombasa Sports Club",
    "MSC Men": "Mombasa Sports Club",
    "Sliders": "Sliders Hockey Club",
    "Amira Sailors": "Amira Sailors Hockey Club",
    "Blazers": "Blazers Hockey Club",
    "Strathmore Uni Ladies": "Strathmore University",
    "Daystar Uni Ladies": "Daystar University",
    "Daystar Uni Men": "Daystar University",
    "Swans": "Swans Hockey Club",
    "USIU-A Men": "USIU-A",
    # NOTE: "Lakers" (unqualified) only ever appears in PLW rows in the
    # source PDF used to build this map, so it's resolved to the women's
    # club. If a future PDF uses bare "Lakers" for a MEN's fixture too,
    # this mapping will silently mis-tag it — flagged here rather than
    # guessed around, since disambiguating would require inventing a rule
    # not actually present in the document.
    "Lakers": "Lakers Hockey Club Ladies",
}


def _correct_pdf_team_name(name: str) -> str:
    if not name:
        return name
    name = name.strip()
    return PDF_NAME_CORRECTIONS.get(name, name)


def _parse_pdf_date(date_str: str, time_str: str) -> str:
    """
    Parse the PDF's 'Saturday, August 29, 2026' + '12:00' into the same
    ISO-ish 'YYYY-MM-DD HH:MM' format scraper._parse_match_date() already
    knows how to fall back and parse. Returns '' if unparseable (never
    fabricates a date).
    """
    if not date_str:
        return ""
    date_str = date_str.replace("\n", " ").strip()
    time_str = (time_str or "").strip() or "00:00"

    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%A, %B %d, %Y %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        logger.warning(f"Could not parse PDF date/time: {date_str!r} {time_str!r}")
        return ""


def parse_pdf_fixtures(pdf_path: str) -> dict:
    """
    Extract every real fixture row from a KHU season-calendar PDF.

    Returns matches in the SAME per-match dict shape as
    scraper.scrape_league_calendar()'s "matches" list, plus two extra
    fields: "source" (always "pdf") and "match_no" (the PDF's own
    match numbering, useful for de-duping and cross-referencing).

    Rows that are section headers, tournament announcements, league
    breaks, transfer windows, etc. (i.e. anything without a real
    HOME/AWAY pair in a known league) are skipped — they aren't matches.
    """
    matches = []
    skipped_rows = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row is None or len(row) < 9:
                        continue

                    # The DATE column occasionally gets split by pdfplumber
                    # across 2 or 3 cells depending on subtle layout shifts
                    # per row (e.g. ['S','aturday',', Sept 26, 2026', ...]
                    # vs the normal ['Saturday, Sept 26, 2026', None, None, ...]).
                    # Joining cols 0-2 covers both cases without over-grabbing
                    # into the TIME column (col 3), which is always numeric.
                    date_cell = "".join((row[0] or "", row[1] or "", row[2] or ""))
                    time_cell = row[3] or ""
                    league_cell = (row[4] or "").strip()
                    match_no_cell = (row[5] or "").strip()
                    home_cell = (row[6] or "").strip()
                    away_cell = (row[7] or "").strip()
                    venue_cell = (row[8] or "").strip()

                    # A real match row: known league code + both teams present.
                    if league_cell not in KNOWN_LEAGUE_SHORTS:
                        continue
                    if not home_cell or not away_cell:
                        continue

                    date_str = _parse_pdf_date(date_cell, time_cell)
                    if not date_str:
                        skipped_rows += 1
                        continue

                    is_first_leg = match_no_cell.endswith("*")
                    match_no = match_no_cell.rstrip("*")

                    matches.append({
                        "matchday": "",
                        "date": date_str,
                        "home_team": _correct_pdf_team_name(home_cell),
                        "home_team_url": "",
                        "home_logo_url": "",
                        "away_team": _correct_pdf_team_name(away_cell),
                        "away_team_url": "",
                        "away_logo_url": "",
                        "home_score": None,
                        "away_score": None,
                        "state": "NS",  # PDF only ever lists upcoming/scheduled fixtures
                        "match_url": "",
                        "league": league_cell,
                        "league_short": league_cell,
                        "venue": venue_cell,
                        "match_no": match_no,
                        "is_first_leg": is_first_leg,
                        "source": "pdf",
                    })

    return {
        "matches": matches,
        "total": len(matches),
        "skipped_rows": skipped_rows,
        "source_file": pdf_path,
        "parsed_at": datetime.now().isoformat(),
    }


def merge_pdf_fixtures_into_scraped(scraped_fixtures: list, pdf_matches: list) -> list:
    """
    Merge PDF-sourced fixtures into an already-scraped fixtures list,
    skipping any PDF match that's a clear duplicate of one already
    scraped live from the site (same league + same two teams + same
    calendar date, ignoring kickoff time in case of small discrepancies).

    Site-scraped data always wins on conflict — PDF fixtures only FILL
    GAPS the live site doesn't have yet, never overwrite live data.
    """
    def sig(m):
        date_part = (m.get("date") or "")[:10]  # just the date, not time
        return (
            m.get("league_short", "").strip().upper(),
            m.get("home_team", "").strip().lower(),
            m.get("away_team", "").strip().lower(),
            date_part,
        )

    existing_sigs = {sig(m) for m in scraped_fixtures}

    merged = list(scraped_fixtures)
    added = 0
    for pm in pdf_matches:
        if sig(pm) in existing_sigs:
            continue
        merged.append(pm)
        added += 1

    logger.info(f"Merged {added} new PDF fixtures ({len(pdf_matches) - added} were already present from live scrape)")
    return merged
