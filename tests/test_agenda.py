from contextlib import closing
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "skills/websummit-planner/scripts/agenda.py"
spec = importlib.util.spec_from_file_location("agenda", SCRIPT)
agenda = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agenda)

class AgendaTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(id="a", title="Україна, AI; test\\x\nnext", day="2026-11-10", start="09:00", end="10:00", starts_utc="2026-11-10T09:00:00Z", ends_utc="2026-11-10T10:00:00Z", stage="Hall", description="<b>Data</b>", kind="official")]

    def test_app_event_link(self):
        rows = agenda.resolve(self.rows, [{"id": "a", "status": "must"}])
        self.assertEqual(rows[0]["url"], "https://link.websummit.com/?url=https%3A%2F%2Fattend.websummit.com%2Fdl%2Flis26%2Fevent%3Fid%3Da%26mobile%3Dtrue")
        self.assertIn(rows[0]["url"], agenda.markdown(rows))
        side = [{**self.rows[0], "kind": "side", "url": "https://example.org/register"}]
        self.assertEqual(agenda.resolve(side, [{"id": "a", "status": "must"}])[0]["url"], side[0]["url"])

    def test_resolution(self):
        self.assertEqual(agenda.resolve(self.rows, [{"id":"a","status":"must"},{"id":"a","status":"skip"}]), [])
        with self.assertRaises(ValueError): agenda.resolve(self.rows, [{"id":"missing","status":"must"}])
        with self.assertRaises(ValueError): agenda.resolve(self.rows, [{"id":"a","status":"invalid"}])

    def test_calendar(self):
        rows = agenda.resolve(self.rows, [{"id":"a","status":"must"}])
        calendar = agenda.calendar(rows)
        self.assertIn("DTSTART:20261110T090000Z\r\n", calendar)
        self.assertIn("DTEND:20261110T100000Z\r\n", calendar)
        self.assertIn(r"Україна\, AI\; test\\x\nnext", calendar)
        self.assertIn("UID:", calendar)
        self.assertEqual(calendar.count("BEGIN:VEVENT"), 1)
        self.assertTrue(all(len(line.encode()) <= 75 for line in calendar.split("\r\n")))
        self.assertIn("Україна", agenda.markdown(rows))

    def test_cli_keeps_seed_unchanged(self):
        import hashlib
        import json
        import sqlite3
        import subprocess
        import sys
        import tempfile
        seed = SCRIPT.parents[1] / "assets/websummit.db"
        before = hashlib.sha256(seed.read_bytes()).hexdigest()
        with closing(sqlite3.connect(seed.as_uri() + "?mode=ro", uri=True)) as con:
            sid = con.execute("select id from session limit 1").fetchone()[0]
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps([{"id": sid, "status": "must"}]))
            for fmt in ("markdown", "ics"):
                out = Path(tmp) / fmt
                subprocess.run([sys.executable, str(SCRIPT), str(plan), "--format", fmt, "--out", str(out)], check=True)
                self.assertTrue(out.stat().st_size)
        self.assertEqual(hashlib.sha256(seed.read_bytes()).hexdigest(), before)

    def test_explicit_database_snapshot(self):
        import json
        import shutil
        import sqlite3
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db, plan, out = [Path(tmp) / name for name in ("snapshot.db", "plan.json", "agenda.md")]
            shutil.copy(SCRIPT.parents[1] / "assets/websummit.db", db)
            with closing(sqlite3.connect(db)) as con:
                sid = con.execute("select id from session limit 1").fetchone()[0]
                con.execute("update session set title=? where id=?", ("Refreshed title", sid))
                con.commit()
            plan.write_text(json.dumps([{"id": sid, "status": "must"}]))
            subprocess.run([sys.executable, str(SCRIPT), str(plan), "--db", str(db), "--format", "markdown", "--out", str(out)], check=True, capture_output=True)
            self.assertIn("Refreshed title", out.read_text())

    def test_unknown_end_and_unicode_folding(self):
        self.rows[0].update(end_known=0, title="ї" * 150)
        result = agenda.calendar(agenda.resolve(self.rows,[{"id":"a","status":"maybe"}]))
        self.assertNotIn("DTEND:", result)
        self.assertIn("End time unknown", result)
        self.assertTrue(all(len(line.encode()) <= 75 for line in result.split("\r\n")))

if __name__ == "__main__": unittest.main()
