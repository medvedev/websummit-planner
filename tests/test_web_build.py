import json
import sqlite3
from contextlib import closing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / 'skills/websummit-planner/assets/websummit.db'


class WebBuildTest(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'dist'
            subprocess.run([sys.executable, str(ROOT / 'tools/build_web.py'), '--out', str(out)], check=True, capture_output=True)
            data = json.loads((out / 'schedule.json').read_text(encoding='utf-8'))
            with closing(sqlite3.connect(SEED.as_uri() + '?mode=ro', uri=True)) as c:
                official = c.execute('SELECT count(*) FROM session WHERE id NOT IN (SELECT session_id FROM side_event)').fetchone()[0]
                side = c.execute('SELECT count(*) FROM side_event').fetchone()[0]
                days = c.execute('SELECT count(DISTINCT day) FROM session WHERE id NOT IN (SELECT session_id FROM side_event)').fetchone()[0]
            self.assertEqual(data['info']['sessions'], official)
            self.assertEqual(data['info']['side_events'], side)
            self.assertGreater(side, 0)
            for row in data['sessions']:
                if row['kind'] == 'official':
                    self.assertEqual(row['url'], 'https://link.websummit.com/?url=' + quote('https://attend.websummit.com/dl/lis26/event?id=' + row['id'] + '&mobile=true', safe=''))
                    for person in row['people']:
                        self.assertEqual(person['url'], 'https://attend.websummit.com/lis26/profiles/' + person['id'])
                else:
                    self.assertFalse(row['url'].startswith('https://link.websummit.com/'))
            self.assertEqual(sum(1 for r in data['sessions'] if r['kind'] == 'side'), side)
            lines = (out / 'schedule-compact.md').read_text(encoding='utf-8').splitlines()
            self.assertEqual(sum(1 for l in lines if l.count(' | ') >= 6 and not l.startswith('Columns')), official)
            self.assertEqual(len(list(out.glob('schedule-2026-*.md'))), days)
            self.assertEqual((out / 'side-events.md').read_text(encoding='utf-8').count('\n- id: side:'), side)
            llms = (out / 'llms.txt').read_text(encoding='utf-8')
            self.assertIn('https://medvedev.github.io/websummit-planner/schedule-compact.md', llms)
            self.assertIn('https://medvedev.github.io/websummit-planner/llms.txt', (out / 'index.html').read_text(encoding='utf-8'))
            names = zipfile.ZipFile(out / 'websummit-planner.zip').namelist()
            self.assertIn('websummit-planner/SKILL.md', names)
            self.assertEqual([n for n in names if n.endswith('.db')], ['websummit-planner/assets/websummit.db'])
            self.assertFalse([n for n in names if 'tests' in n or '__pycache__' in n])
            self.assertIn('llms.txt', [p.name for p in out.iterdir()])
            self.assertTrue((out / 'agenda.py').is_file())
            self.assertIn('read-only', (out / 'web-instructions.md').read_text())
            plan = Path(tmp) / 'plan.json'
            plan.write_text(json.dumps([{'id': data['sessions'][0]['id'], 'status': 'must'}]))
            subprocess.run([sys.executable, str(out / 'agenda.py'), str(plan), '--schedule', str(out / 'schedule.json'),
                            '--format', 'ics', '--out', str(Path(tmp) / 'agenda.ics')], check=True, capture_output=True)
            self.assertIn('BEGIN:VEVENT', (Path(tmp) / 'agenda.ics').read_text())
            self.assertIn('websummit-planner/scripts/agenda.py', names)
            comps = json.loads((out / 'companies.json').read_text(encoding='utf-8'))
            self.assertEqual(len(comps['companies']), 2872)
            self.assertEqual(comps['info']['companies'], 2872)
            self.assertTrue(comps['info']['notice'])
            self.assertEqual(sum(1 for l in (out / 'companies-compact.md').read_text(encoding='utf-8').splitlines() if l.startswith('company:')), 2872)
            self.assertIn('## MakeLocal', (out / 'companies.md').read_text(encoding='utf-8'))
            self.assertTrue(any(r.get('companies') for r in data['sessions']))
            self.assertTrue(all(set(c) == {'id', 'name', 'relation'} for r in data['sessions'] for c in r.get('companies', [])))
            self.assertTrue(all('companies' not in r for r in data['sessions'] if r['kind'] == 'side'))
            self.assertIn('companies-compact.md', llms)
            self.assertIn('unofficial', (out / 'index.html').read_text(encoding='utf-8').lower())

    def test_exports_have_no_restricted_links(self):
        import re
        email = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
        banned = ('rails/active_storage', 'linkedin.com/in/', 'pitch_deck')

        def check(label, text):
            for b in banned:
                self.assertNotIn(b, text, label)
            self.assertIsNone(email.search(text), label)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'dist'
            subprocess.run([sys.executable, str(ROOT / 'tools/build_web.py'), '--out', str(out)], check=True, capture_output=True)
            for f in out.glob('companies*'):
                check(f.name, f.read_text(encoding='utf-8'))
            sched = json.loads((out / 'schedule.json').read_text(encoding='utf-8'))
            check('session companies', json.dumps([r.get('companies', []) for r in sched['sessions']]))
            with zipfile.ZipFile(out / 'websummit-planner.zip') as z:
                dbfile = Path(tmp) / 'zip.db'
                dbfile.write_bytes(z.read('websummit-planner/assets/websummit.db'))
            with closing(sqlite3.connect(dbfile)) as c:
                tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'company%'")]
                self.assertEqual(len(tables), 8)
                for t in tables:
                    check(t, json.dumps(c.execute(f'SELECT * FROM {t}').fetchall(), ensure_ascii=False))

    def test_build_refuses_to_wipe_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'precious.txt').write_text('x')
            p = subprocess.run([sys.executable, str(ROOT / 'tools/build_web.py'), '--out', tmp], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertTrue((Path(tmp) / 'precious.txt').exists())

    def test_export_text_is_read_only_on_seed(self):
        import hashlib
        seed = ROOT / 'skills/websummit-planner/assets/websummit.db'
        before = hashlib.sha256(seed.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, str(ROOT / 'skills/websummit-planner/scripts/export_text.py'), '--out', tmp],
                           check=True, capture_output=True)
        self.assertEqual(hashlib.sha256(seed.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
