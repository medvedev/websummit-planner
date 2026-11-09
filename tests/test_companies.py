import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'websummit-planner'
sys.path.insert(0, str(SKILL / 'scripts'))
import import_companies  # noqa: E402

SEED = SKILL / 'assets' / 'websummit.db'

SOURCE_DDL = """
CREATE TABLE company (id INTEGER PRIMARY KEY, name, country, industry, tier, logo_url, url, page, position, fetched_at);
CREATE TABLE company_profile (company_id, uuid, name, tier, description, location, industry, website, logo_url, fetched_at);
CREATE TABLE company_tag (company_id, tag);
CREATE TABLE company_fact (company_id, position, fact);
CREATE TABLE company_link (company_id, kind, url);
CREATE TABLE company_person (person_uuid, company_id, role, tier, industry, country);
CREATE TABLE company_event (company_id, event_uuid, time_text, title, location, type, description);
CREATE TABLE company_event_speaker (company_id, event_uuid, person_uuid, role, org);
CREATE TABLE company_endorsement (company_id, endorsed_company_id, endorsed_name);
"""


def make_source(path, known_event):
    with closing(sqlite3.connect(path)) as c:
        c.executescript(SOURCE_DDL)
        c.executemany("INSERT INTO company(id,name,country,industry,tier) VALUES (?,?,?,?,?)",
                      [(1, 'Alpha', 'PT', 'Defence', 'Alpha'), (2, 'Beta', 'UA', 'AI', 'Growth')])
        c.executemany("INSERT INTO company_profile(company_id,uuid,name,description,location,website) VALUES (?,?,?,?,?,?)",
                      [(1, 'u1', 'Alpha', 'Mail founder a.b@c.io now', 'Lisbon', 'https://a.example'),
                       (2, 'u2', 'Beta', None, None, None)])
        c.executemany("INSERT INTO company_link VALUES (?,?,?)", [
            (1, 'pitch_deck', 'https://x/rails/active_storage/deck.pdf'),
            (1, 'linkedin', 'https://www.linkedin.com/in/x'),
            (1, 'linkedin', 'https://www.linkedin.com/company/y'),
            (2, 'website', 'https://b.example')])
        c.execute("INSERT INTO company_tag VALUES (1,'drone')")
        c.execute("INSERT INTO company_fact VALUES (1,0,'Seed')")
        c.execute("INSERT INTO company_person VALUES ('p1',1,'CEO','Alpha','Defence','PT')")
        c.executemany("INSERT INTO company_event(company_id,event_uuid,title,time_text) VALUES (?,?,?,?)",
                      [(1, known_event, 'Known', None), (1, 'unknown-uuid', 'Undated', 'Tue evening')])
        c.execute("INSERT INTO company_event_speaker VALUES (1,'unknown-uuid','ghost','Speaker','Alpha')")
        c.execute("INSERT INTO company_endorsement VALUES (1,2,'Beta')")
        c.commit()


class ImportCompaniesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.db = d / 'seed.db'
        shutil.copy(SEED, self.db)
        with closing(sqlite3.connect(self.db)) as c:
            self.known = c.execute("SELECT id FROM session LIMIT 1").fetchone()[0]
        self.src = d / 'src.db'
        make_source(self.src, self.known)
        self.counts = import_companies.import_companies(self.src, self.db)

    def q(self, sql, *a):
        with closing(sqlite3.connect(self.db)) as c:
            return c.execute(sql, a).fetchall()

    def test_import_drops_pitch_decks_and_personal_linkedin(self):
        urls = {r[0] for r in self.q("SELECT url FROM company_link")}
        self.assertEqual(urls, {'https://www.linkedin.com/company/y', 'https://b.example'})
        self.assertEqual(self.q("SELECT count(*) FROM company_link WHERE kind='pitch_deck'")[0][0], 0)

    def test_import_masks_emails(self):
        d = self.q("SELECT description FROM company WHERE id=1")[0][0]
        self.assertIn('[email removed]', d)
        self.assertNotIn('@', d)
        self.assertIsNone(import_companies.mask_emails(None))

    def test_import_links_events_by_id_only(self):
        rows = dict(self.q("SELECT event_uuid, session_id FROM company_event"))
        self.assertEqual(rows[self.known], self.known)
        self.assertIsNone(rows['unknown-uuid'])

    def test_import_idempotent(self):
        again = import_companies.import_companies(self.src, self.db)
        self.assertEqual(again, self.counts)
        self.assertEqual(self.q("SELECT count(*) FROM company")[0][0], 2)

    def test_schema_version_3(self):
        self.assertEqual(self.q("SELECT value FROM meta WHERE key='schema_version'")[0][0], '3')
        self.assertEqual(self.q("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.counts['company'], 2)


if __name__ == '__main__':
    unittest.main()
