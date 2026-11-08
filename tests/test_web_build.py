import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class WebBuildTest(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'dist'
            subprocess.run([sys.executable, str(ROOT / 'tools/build_web.py'), '--out', str(out)], check=True, capture_output=True)
            data = json.loads((out / 'schedule.json').read_text(encoding='utf-8'))
            self.assertEqual(data['info']['sessions'], 1122)
            lines = (out / 'schedule-compact.md').read_text(encoding='utf-8').splitlines()
            self.assertEqual(sum(1 for l in lines if l.count(' | ') >= 6 and not l.startswith('Columns')), 1122)
            self.assertEqual(len(list(out.glob('schedule-2026-*.md'))), 4)
            names = zipfile.ZipFile(out / 'websummit-planner.zip').namelist()
            self.assertIn('websummit-planner/SKILL.md', names)
            self.assertEqual([n for n in names if n.endswith('.db')], ['websummit-planner/assets/websummit.db'])
            self.assertFalse([n for n in names if 'tests' in n or '__pycache__' in n])
            self.assertIn('llms.txt', [p.name for p in out.iterdir()])
            self.assertIn('unofficial', (out / 'index.html').read_text(encoding='utf-8').lower())

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
