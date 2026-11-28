"""Checks the U18 World Cup seed: shape, 36 pool games, Kenya's pools, group tables, import is idempotent."""
import json, os, sys, tempfile
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, os.path.dirname(__file__))
import tournaments as tn
d = json.load(open(os.path.join(os.path.dirname(__file__), "tournaments_seed.json")))
TID = "fih-youth-hockey5s-world-cup-2026"
t = next(x for x in d["tournaments"] if x["id"] == TID)
ms = [m for m in d["matches"] if m["tournament_id"] == TID]
bad = 0
def ok(l, c):
    global bad; print(("PASS " if c else "FAIL ") + l); bad += (not c)
ok("dates 5-12 Dec 2026, Cairo", t["start_date"] == "2026-12-05" and t["end_date"] == "2026-12-12" and "Zamalek" in t["venue"])
ok("36 pool games (6 pools x 6)", len(ms) == 36)
kn = {(m["group_name"], m["away_team"] if m["home_team"] == "Kenya" else m["home_team"]): m["date"] for m in ms if "Kenya" in (m["home_team"], m["away_team"])}
ok("Kenya's 6 games have the poster times (EAT)", kn == {("Women Pool B","Poland"):"2026-12-09 12:10",("Women Pool B","Iran"):"2026-12-09 17:30",("Women Pool B","Ukraine"):"2026-12-10 16:50",("Men Pool C","Austria"):"2026-12-09 18:50",("Men Pool C","Egypt"):"2026-12-10 12:50",("Men Pool C","Iran"):"2026-12-10 20:10"})
ok("Kenya is listed first in its games", all(m["home_team"] == "Kenya" for m in ms if "Kenya" in (m["home_team"], m["away_team"])))
ok("old draft event is retired", "fih-hockey5s-u18-world-cup-2026" in d["retired_tournament_ids"] and not any(x["id"] == "fih-hockey5s-u18-world-cup-2026" for x in d["tournaments"]))
ok("unique match ids", len({m["match_id"] for m in ms}) == 36)
ok("all valid", all(tn.validate_match(m) == "" for m in ms))
det = tn.build_tournament_detail(t, ms)
ok("6 group tables of 4", len(det["group_tables"]) == 6 and all(len(g["rows"]) == 4 for g in det["group_tables"]))
g = {x["group"]: [r["team"] for r in x["rows"]] for x in det["group_tables"]}
ok("Kenya men in Pool C with Austria/Egypt/Iran", sorted(g["Men Pool C"]) == ["Austria", "Egypt", "Iran", "Kenya"])
ok("Kenya women in Pool B with Iran/Poland/Ukraine", sorted(g["Women Pool B"]) == ["Iran", "Kenya", "Poland", "Ukraine"])
ok("each team plays 3 pool games", all(sum(1 for m in ms if m["group_name"] == k and team in (m["home_team"], m["away_team"])) == 3 for k, v in g.items() for team in v))
ok("rosters split Men / Women", set(det["rosters"]) == {"Men", "Women"})
import database as db
tmp = tempfile.mkdtemp(); db.DB_PATH = os.path.join(tmp, "t.db") if hasattr(db, "DB_PATH") else None
try:
    a = db.import_tournaments_seed(d["tournaments"], d["matches"], d.get("retired_tournament_ids"))
    b = db.import_tournaments_seed(d["tournaments"], d["matches"], d.get("retired_tournament_ids"))
    ok("import adds it once, second import adds nothing", a >= 1 and b == 0)
    ok("served by the tournaments list", any(x["id"] == TID for x in db.load_tournaments()))
except Exception as e:
    ok("import works: " + repr(e)[:100], False)
sys.exit(1 if bad else 0)
