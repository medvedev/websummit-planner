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


import json  # noqa: E402
import subprocess  # noqa: E402


class CompanyCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'personal.db'

    def run_cli(self, *args, ok=True):
        p = subprocess.run([sys.executable, str(SKILL / 'scripts/planner.py'), '--db', str(self.state), *args],
                           capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode == 0, ok, p.stderr)
        return json.loads(p.stdout) if ok else p.stderr

    def test_companies_fact_filter(self):
        rows = self.run_cli('companies', '--fact', 'seed', '--fact', 'actively fundraising', '--limit', '100')
        self.assertTrue(rows)
        for r in rows:
            low = [f.lower() for f in r['facts']]
            self.assertTrue(any('seed' in f for f in low), r)
            self.assertIn('actively fundraising', low)
            self.assertTrue(r['id'].startswith('company:'))
            self.assertEqual(r['url'], 'https://attend.websummit.com/lis26/company/' + r['id'].split(':')[1])

    def test_companies_query_matches_tags(self):
        ids = [r['id'] for r in self.run_cli('companies', 'drone', '--limit', '100')]
        self.assertIn('company:62217', ids)

    def test_companies_order_tier_then_name(self):
        rows = self.run_cli('companies', '--limit', '100')
        rank = {'Partner': 0, 'Growth': 1, 'Beta': 2, 'Alpha': 3, 'Media Partner': 4, None: 5}
        keys = [(rank.get(r['tier'], 5), r['name']) for r in rows]
        self.assertEqual(keys, sorted(keys))

    def test_company_details_sections(self):
        c = self.run_cli('company', 'company:101575')[0]
        self.assertTrue(c['sessions'] and c['activities'] and c['endorses'])
        self.assertTrue(all(s['day'] for s in c['sessions']))
        self.assertTrue(all('name' not in t for t in c['team']))
        self.assertEqual(c['id'], 'company:101575')
        self.assertTrue(all(e['id'] is None or e['id'].startswith('company:') for e in c['endorses']))
        self.assertNotIn('pitch_deck', json.dumps(c))

    def test_session_details_lists_companies(self):
        c = self.run_cli('company', '101575')[0]
        d = self.run_cli('details', c['sessions'][0]['id'])[0]
        self.assertIn({'id': 'company:101575', 'name': c['name'], 'relation': 'host'}, d['companies'])
        plain = self.run_cli('search', '--limit', '1')[0]['id']
        self.assertIn('id', self.run_cli('details', plain)[0])

    def test_company_prefix_and_unknown(self):
        self.assertEqual(self.run_cli('company', 'company:62217')[0]['id'], 'company:62217')
        self.run_cli('company', '1', ok=False)
        self.run_cli('mark', 'company:62217', 'must', ok=False)
        self.assertFalse(self.state.exists())

    def test_info_counts_companies(self):
        info = self.run_cli('info')
        self.assertEqual(info['companies'], 2872)
        self.assertIn('Seed', info['company_facts'])
        self.assertIn('Partner', info['company_tiers'])
