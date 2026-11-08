import json
import sqlite3
from contextlib import closing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

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
            self.assertIn('unofficial', (out / 'index.html').read_text(encoding='utf-8').lower())

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
