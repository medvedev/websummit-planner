import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'websummit-planner'


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='planner test ')
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'personal.db'

    def run_cli(self, *args, ok=True, script=None):
        p = subprocess.run([sys.executable, str(script or SKILL / 'scripts/planner.py'),
                            '--db', str(self.state), *args], cwd=self.tmp.name,
                           capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode == 0, ok, p.stderr)
        return json.loads(p.stdout) if ok else p.stderr

    def test_offline_read_does_not_create_state(self):
        info = self.run_cli('info')
        self.assertEqual(info['sessions'], 1122)
        self.assertFalse(self.state.exists())
        rows = self.run_cli('search', '--day', '2026-11-10', '--limit', '3')
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['day'] == '2026-11-10' for r in rows))
        self.assertEqual(self.run_cli('details', rows[0]['id'])[0]['id'], rows[0]['id'])

    def test_history_removal_and_seed_isolation(self):
        seed = SKILL / 'assets/websummit.db'
        before = hashlib.sha256(seed.read_bytes()).hexdigest()
        sid = self.run_cli('search', '--limit', '1')[0]['id']
        self.run_cli('mark', sid, 'must', '--score', '5', '--note', 'personal note')
        self.assertEqual(self.run_cli('shortlist')[0]['shortlist_status'], 'must')
        self.run_cli('mark', sid, 'removed')
        self.assertEqual(self.run_cli('shortlist'), [])
        self.assertEqual(len(self.run_cli('history', sid)), 2)
        self.assertEqual(hashlib.sha256(seed.read_bytes()).hexdigest(), before)
        with closing(sqlite3.connect(self.state)) as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('delete from shortlist_version')

    def test_invalid_write_does_not_initialize_state(self):
        self.run_cli('mark', 'missing', 'must', ok=False)
        self.assertFalse(self.state.exists())
        self.run_cli('buffer', '-1', ok=False)
        self.assertFalse(self.state.exists())

    def test_conflicts(self):
        seed = sqlite3.connect((SKILL / 'assets/websummit.db').as_uri() + '?mode=ro', uri=True)
        self.addCleanup(seed.close)
        pair = seed.execute('select a.id,b.id from session a join session b on a.id<b.id '
                            'and a.starts_utc<b.ends_utc and b.starts_utc<a.ends_utc limit 1').fetchone()
        for sid in pair:
            self.run_cli('mark', sid, 'must')
        self.assertEqual(self.run_cli('conflicts')[0]['kind'], 'overlap')
        self.run_cli('buffer', '10')
        self.assertEqual(self.run_cli('info')['settings']['conflict_buffer_min'], '10')

    def test_install_is_portable_and_refuses_overwrite(self):
        dest = Path(self.tmp.name) / 'installed skill'
        command = [sys.executable, str(ROOT / 'install.py'), '--dest', str(dest)]
        p = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.run_cli('info', script=dest / 'scripts/planner.py')['sessions'], 1122)
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_refresh_preserves_history_and_failure_preserves_database(self):
        sid = self.run_cli('search', '--limit', '1')[0]['id']
        self.run_cli('mark', sid, 'must', '--note', 'keep me')
        self.run_cli('buffer', '12')
        item = {'id': sid, 'slug': 'updated', 'title': 'Updated session',
                'description': 'Updated description', 'starts_at': '2026-11-09T18:00:00Z',
                'ends_at': '2026-11-09T18:30:00Z',
                'location': {'id': 'stage-test', 'name': 'Test Stage'},
                'schedule_track': {'name': 'Test'}, 'timeslot_participations': []}
        source = Path(self.tmp.name) / 'schedule.json'
        source.write_text(json.dumps([item]))
        self.run_cli('refresh', '--json', str(source))
        self.assertEqual(self.run_cli('shortlist')[0]['title'], 'Updated session')
        self.assertEqual(self.run_cli('history', sid)[0]['note'], 'keep me')
        self.assertEqual(self.run_cli('info')['settings']['conflict_buffer_min'], '12')
        before = self.state.read_bytes()
        for contents in [[], [{**item, 'id': 'replacement'}], [{'id': sid}]]:
            source.write_text(json.dumps(contents))
            self.run_cli('refresh', '--json', str(source), ok=False)
            self.assertEqual(self.state.read_bytes(), before)

    def test_tight_gap_and_same_stage_behavior(self):
        source = Path(self.tmp.name) / 'fixture.json'
        items = []
        for sid, start, end, stage in [('a', '09:00', '09:30', 'one'),
                                        ('b', '09:35', '10:00', 'two'),
                                        ('c', '10:05', '10:30', 'two')]:
            items.append({'id': sid, 'slug': sid, 'title': sid,
                          'starts_at': f'2026-11-10T{start}:00Z',
                          'ends_at': f'2026-11-10T{end}:00Z',
                          'location': {'id': stage, 'name': stage}})
        source.write_text(json.dumps(items))
        self.run_cli('refresh', '--json', str(source))
        for sid in ['a', 'b', 'c']:
            self.run_cli('mark', sid, 'maybe')
        self.assertEqual(self.run_cli('conflicts'), [])
        self.run_cli('buffer', '10')
        conflicts = self.run_cli('conflicts')
        self.assertEqual([(r['a_id'], r['b_id'], r['kind']) for r in conflicts], [('a', 'b', 'tight-gap')])

    def test_both_project_install_locations(self):
        p = subprocess.run([sys.executable, str(ROOT / 'install.py'), '--agent', 'both',
                            '--scope', 'project', '--project', self.tmp.name], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        for directory in ['.agents', '.claude']:
            self.assertEqual(self.run_cli('info', script=Path(self.tmp.name) / directory /
                                         'skills/websummit-planner/scripts/planner.py')['sessions'], 1122)

    def test_gemini_project_install_location(self):
        p = subprocess.run([sys.executable, str(ROOT / 'install.py'), '--agent', 'gemini',
                            '--scope', 'project', '--project', self.tmp.name], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.run_cli('info', script=Path(self.tmp.name) / '.gemini' /
                                     'skills/websummit-planner/scripts/planner.py')['sessions'], 1122)

    def test_snapshot_has_no_author_state(self):
        with closing(sqlite3.connect(SKILL / 'assets/websummit.db')) as c:
            self.assertEqual(c.execute('select count(*) from shortlist_version').fetchone()[0], 0)
            self.assertEqual(dict(c.execute('select * from setting')), {'conflict_buffer_min': '0'})
            self.assertEqual(dict(c.execute('select * from meta'))['source'], 'https://websummit.com/schedule/')
            self.assertEqual(c.execute('pragma integrity_check').fetchone()[0], 'ok')
            self.assertEqual(c.execute('pragma foreign_key_check').fetchall(), [])

    def test_refresh_pipeline_preserves_unicode_under_non_utf8_locale(self):
        output = Path(self.tmp.name) / 'cached export'
        raw = output / 'raw'
        raw.mkdir(parents=True)
        item = {'id': 'unicode', 'slug': 'unicode', 'title': 'Роботика — café',
                'starts_at': '2026-11-10T09:00:00Z', 'ends_at': '2026-11-10T09:30:00Z',
                'location': {'id': 'one', 'name': 'Palco'}, 'description': '智能'}
        (raw / '2026-11-10_p001.json').write_text(json.dumps(
            {'data': {'listItems': [item], 'nbPages': 1}}, ensure_ascii=False), encoding='utf-8')
        env = {**os.environ, 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0', 'LC_ALL': 'C'}
        p = subprocess.run([sys.executable, str(SKILL / 'scripts/fetch_schedule.py'),
                            '--dates', '2026-11-10', '--out', str(output)], env=env, capture_output=True)
        self.assertEqual(p.returncode, 0, repr(p.stderr))
        self.assertEqual(json.loads((output / 'schedule.json').read_text(encoding='utf-8'))[0]['title'], item['title'])
        p = subprocess.run([sys.executable, str(SKILL / 'scripts/build_db.py'),
                            '--json', str(output / 'schedule.json'), '--db', str(self.state)],
                           env=env, capture_output=True)
        self.assertEqual(p.returncode, 0, repr(p.stderr))
        self.assertEqual(self.run_cli('details', 'unicode')[0]['title'], item['title'])


if __name__ == '__main__':
    unittest.main()
