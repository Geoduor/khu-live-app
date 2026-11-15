"""Audit 6: an admin edit must not make stale scrape data look fresh."""
import os, tempfile, json
import database as db
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db"); db.init_db()
ok = True
def check(n, c):
    global ok; print(("PASS " if c else "FAIL ") + n); ok = ok and c
db.save_fixtures_results({"results": [1]}, success=False)  # first row
db.save_fixtures_results({"results": [1, 2]}, success=True)
conn = db.get_connection()
conn.execute("UPDATE fixtures_results_cache SET scraped_at='2020-01-01T00:00:00', success=0"); conn.commit(); conn.close()
db.save_fixtures_results({"results": [1]}, keep_timestamp=True)
conn = db.get_connection(); r = conn.execute("SELECT * FROM fixtures_results_cache WHERE id=1").fetchone(); conn.close()
check("timestamp kept", r["scraped_at"].startswith("2020-01-01"))
check("success flag kept", r["success"] == 0)
check("data updated", json.loads(r["data_json"]) == {"results": [1]})
robots = open("../frontend/khu-frontend/public/robots.txt").read()
check("robots does not advertise admin paths", "/admin" not in robots and "/agent" not in robots)
raise SystemExit(0 if ok else 1)
