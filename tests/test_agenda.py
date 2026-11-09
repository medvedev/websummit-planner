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
        rows, _ = agenda.resolve(self.rows, [{"id": "a", "status": "must"}])
        self.assertEqual(rows[0]["url"], "https://link.websummit.com/?url=https%3A%2F%2Fattend.websummit.com%2Fdl%2Flis26%2Fevent%3Fid%3Da%26mobile%3Dtrue")
        self.assertIn(rows[0]["url"], agenda.markdown(rows))
        side = [{**self.rows[0], "kind": "side", "url": "https://example.org/register"}]
        self.assertEqual(agenda.resolve(side, [{"id": "a", "status": "must"}])[0][0]["url"], side[0]["url"])

    def test_resolution(self):
        self.assertEqual(agenda.resolve(self.rows, [{"id":"a","status":"must"},{"id":"a","status":"skip"}]), ([], []))
        with self.assertRaises(ValueError): agenda.resolve(self.rows, [{"id":"missing","status":"must"}])
        with self.assertRaises(ValueError): agenda.resolve(self.rows, [{"id":"a","status":"invalid"}])

    def test_calendar(self):
        rows, _ = agenda.resolve(self.rows, [{"id":"a","status":"must"}])
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
        result = agenda.calendar(agenda.resolve(self.rows,[{"id":"a","status":"maybe"}])[0])
        self.assertNotIn("DTEND:", result)
        self.assertIn("End time unknown", result)
        self.assertTrue(all(len(line.encode()) <= 75 for line in result.split("\r\n")))


class CompanyAgendaTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(id="a", title="T", day="2026-11-10", start="09:00", end="10:00", starts_utc="2026-11-10T09:00:00Z", ends_utc="2026-11-10T10:00:00Z", stage="Hall", description="d", kind="official")]
        self.comps = [
            {"id": "company:62217", "name": "MakeLocal", "tier": "Beta", "industry": "Defence", "location": "Kyiv", "url": "https://attend.websummit.com/lis26/company/62217"},
            {"id": "company:5", "name": "Acme", "tier": "Alpha", "industry": "AI", "location": None, "url": "https://attend.websummit.com/lis26/company/5"}]
        self.plan = [{"id": "a", "status": "must"}, {"id": "company:62217", "status": "maybe", "note": "ask about pilots"},
                     {"id": "5", "status": "must"}]

    def test_company_entries_markdown(self):
        sessions, comps = agenda.resolve(self.rows, self.plan, self.comps)
        text = agenda.markdown(sessions, comps)
        self.assertIn("## Companies to meet", text)
        self.assertIn("https://attend.websummit.com/lis26/company/62217", text)
        self.assertIn("ask about pilots", text)
        self.assertLess(text.index("Acme"), text.index("MakeLocal"))  # must before maybe
        self.assertEqual([c["id"] for c in comps], ["company:5", "company:62217"])
        self.assertNotIn("Companies to meet", agenda.markdown(sessions))

    def test_company_entries_not_in_ics(self):
        sessions, comps = agenda.resolve(self.rows, self.plan, self.comps)
        self.assertEqual(agenda.calendar(sessions).count("BEGIN:VEVENT"), 1)
        self.assertEqual(agenda.calendar(agenda.resolve(self.rows, [self.plan[0]])[0]).replace("DTSTAMP", ""),
                         agenda.calendar(sessions).replace("DTSTAMP", ""))

    def test_unknown_company_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown company ID: company:999"):
            agenda.resolve(self.rows, [{"id": "company:999", "status": "must"}], self.comps)

    def test_schedule_json_without_companies_file_errors(self):
        import json, subprocess, sys, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            sched, plan = Path(tmp) / "s.json", Path(tmp) / "p.json"
            sched.write_text(json.dumps({"sessions": self.rows}))
            plan.write_text(json.dumps([{"id": "company:5", "status": "must"}]))
            r = subprocess.run([sys.executable, str(SCRIPT), str(plan), "--schedule", str(sched), "--format", "markdown",
                                "--out", str(Path(tmp) / "o.md")], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("--companies", r.stderr)
            comp = Path(tmp) / "companies.json"
            comp.write_text(json.dumps({"companies": [{**self.comps[1], "id": "company:5"}]}))
            r = subprocess.run([sys.executable, str(SCRIPT), str(plan), "--schedule", str(sched), "--companies", str(comp),
                                "--format", "markdown", "--out", str(Path(tmp) / "o.md")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Acme", (Path(tmp) / "o.md").read_text())

    def test_cli_company_from_seed_db(self):
        import json, subprocess, sys, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan, out = Path(tmp) / "p.json", Path(tmp) / "o.md"
            plan.write_text(json.dumps([{"id": "company:62217", "status": "must"}]))
            subprocess.run([sys.executable, str(SCRIPT), str(plan), "--format", "markdown", "--out", str(out)], check=True)
            self.assertIn("MakeLocal", out.read_text())

if __name__ == "__main__": unittest.main()
