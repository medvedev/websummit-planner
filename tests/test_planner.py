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

    def test_export_import_round_trip(self):
        ids = [r['id'] for r in self.run_cli('search', '--limit', '2')]
        self.run_cli('mark', ids[0], 'must', '--score', '4', '--note', 'n1')
        self.run_cli('mark', ids[1], 'maybe')
        self.run_cli('mark', ids[1], 'removed')
        self.run_cli('buffer', '15')
        plan = Path(self.tmp.name) / 'plan.json'
        self.run_cli('export', '--out', str(plan))
        data = json.loads(plan.read_text(encoding='utf-8'))
        self.assertEqual(len(data['history']), 3)
        self.assertEqual(data['settings']['conflict_buffer_min'], 15)
        self.state = Path(self.tmp.name) / 'fresh.db'
        res = self.run_cli('import', str(plan))
        self.assertEqual(res['imported'], 3)
        sl = self.run_cli('shortlist')
        self.assertEqual([(r['id'], r['shortlist_status'], r['score'], r['note']) for r in sl],
                         [(ids[0], 'must', 4, 'n1')])
        self.assertEqual(self.run_cli('info')['settings']['conflict_buffer_min'], '15')
        self.assertEqual(len(self.run_cli('history', ids[1])), 2)

    def test_export_empty_plan_and_stdout(self):
        data = self.run_cli('export')
        self.assertEqual(data['history'], [])
        self.assertFalse(self.state.exists())
        plan = Path(self.tmp.name) / 'empty.json'
        plan.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(self.run_cli('import', str(plan))['imported'], 0)

    def test_import_rejects_unknown_ids_and_bad_files(self):
        plan = Path(self.tmp.name) / 'bad.json'
        plan.write_text(json.dumps({'format': 'websummit-plan-v1', 'settings': {},
                                    'history': [{'session_id': 'nope', 'status': 'must'}]}), encoding='utf-8')
        self.assertIn('nope', self.run_cli('import', str(plan), ok=False))
        self.assertFalse(self.state.exists())
        plan.write_text('[1]', encoding='utf-8')
        self.run_cli('import', str(plan), ok=False)
        self.run_cli('import', str(Path(self.tmp.name) / 'missing.json'), ok=False)
        self.assertFalse(self.state.exists())

    def test_import_refuses_non_empty_state(self):
        sid = self.run_cli('search', '--limit', '1')[0]['id']
        self.run_cli('mark', sid, 'must')
        plan = Path(self.tmp.name) / 'p.json'
        self.run_cli('export', '--out', str(plan))
        self.run_cli('import', str(plan), ok=False)

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

    def test_side_events_separate_by_default_and_shortlistable(self):
        official = self.run_cli('search', '--limit', '100')
        self.assertTrue(all(r['kind'] == 'official' for r in official))
        side = self.run_cli('search', '--kind', 'side', '--limit', '100')
        self.assertEqual(len(side), 100)
        self.assertTrue(all(r['id'].startswith('side:') for r in side))
        both = self.run_cli('search', '--kind', 'all', '--day', '2026-11-10', '--limit', '1000')
        self.assertEqual({r['kind'] for r in both}, {'official', 'side'})
        info = self.run_cli('info')
        self.assertEqual((info['sessions'], info['side_events']), (1122, 344))
        d = self.run_cli('details', side[0]['id'])[0]
        self.assertEqual(d['side_event']['session_id'], side[0]['id'])
        self.assertTrue(d['side_event']['url'].startswith('https://'))
        self.run_cli('mark', side[0]['id'], 'maybe')
        self.assertEqual(self.run_cli('shortlist')[0]['kind'], 'side')

    def test_side_event_conflicts_with_official_session(self):
        side = self.run_cli('search', '--kind', 'side', '--day', '2026-11-10', '--limit', '1000')
        official = {r['id']: r for r in self.run_cli('search', '--day', '2026-11-10', '--limit', '1000')}
        pair = next((s, o) for s in side for o in official.values()
                    if s['start'] < o['end'] and o['start'] < s['end'] and s['end'] > s['start'])
        for r in pair:
            self.run_cli('mark', r['id'], 'must')
        kinds = [(c['a_id'], c['b_id'], c['kind']) for c in self.run_cli('conflicts')]
        self.assertIn(tuple(sorted([pair[0]['id'], pair[1]['id']])) + ('overlap',), kinds)

    def test_old_personal_database_is_upgraded_in_place(self):
        old = Path(self.tmp.name) / 'old.db'
        with closing(sqlite3.connect(SKILL / 'assets/websummit.db')) as src, closing(sqlite3.connect(old)) as dst:
            src.backup(dst)
            dst.executescript("DROP VIEW v_titles; DROP VIEW v_session_full; DROP TABLE side_event;"
                              "DELETE FROM session WHERE id LIKE 'side:%'; DELETE FROM stage WHERE id LIKE 'side:%';"
                              "DELETE FROM track WHERE name='Side event';"
                              "CREATE VIEW v_titles AS SELECT s.id,s.day,'' start,'' end,'' stage,s.track,s.title FROM session s;"
                              "CREATE VIEW v_session_full AS SELECT s.id,s.day,'' start,'' end,'' stage,s.track,s.title,'' description,'' speakers,"
                              "NULL shortlist_status,NULL score,NULL note FROM session s;")
            sid = dst.execute('SELECT id FROM session LIMIT 1').fetchone()[0]
            dst.execute("INSERT INTO shortlist_version(session_id,status,note) VALUES (?, 'must', 'old note')", (sid,))
            dst.commit()
        self.state = old
        info = self.run_cli('info')
        self.assertEqual(info['side_events'], 344)
        self.assertEqual(self.run_cli('history', sid)[0]['note'], 'old note')
        self.assertEqual(len(self.run_cli('search', '--kind', 'side', '--limit', '5')), 5)

    def test_refresh_keeps_side_events_and_their_history(self):
        sid = self.run_cli('search', '--limit', '1')[0]['id']
        side = self.run_cli('search', '--kind', 'side', '--limit', '1')[0]['id']
        self.run_cli('mark', side, 'must')
        source = Path(self.tmp.name) / 's.json'
        source.write_text(json.dumps([{'id': sid, 'slug': 'x', 'title': 'X', 'starts_at': '2026-11-09T18:00:00Z',
                                       'ends_at': '2026-11-09T18:30:00Z', 'location': {'id': 'l', 'name': 'L'}}]))
        self.run_cli('refresh', '--json', str(source))
        self.assertEqual(self.run_cli('info')['side_events'], 344)
        self.assertEqual(self.run_cli('shortlist')[0]['id'], side)

    def test_refresh_keeps_companies(self):
        sid = self.run_cli('search', '--limit', '1')[0]['id']
        source = Path(self.tmp.name) / 's.json'
        source.write_text(json.dumps([{'id': sid, 'slug': 'x', 'title': 'X', 'starts_at': '2026-11-09T18:00:00Z',
                                       'ends_at': '2026-11-09T18:30:00Z', 'location': {'id': 'l', 'name': 'L'}}]))
        self.run_cli('refresh', '--json', str(source))
        with closing(sqlite3.connect(self.state)) as c, closing(sqlite3.connect(SKILL / 'assets/websummit.db')) as s:
            for t in ('company', 'company_tag', 'company_fact', 'company_link', 'company_person',
                      'company_event', 'company_event_speaker', 'company_endorsement'):
                self.assertEqual(c.execute(f'SELECT count(*) FROM {t}').fetchone(), s.execute(f'SELECT count(*) FROM {t}').fetchone(), t)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(c.execute("SELECT count(*) FROM company_event WHERE session_id IS NOT NULL").fetchone()[0] <= 248, True)
            self.assertEqual(c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '3')

    def test_old_personal_database_gains_companies(self):
        old = Path(self.tmp.name) / 'old.db'
        with closing(sqlite3.connect(SKILL / 'assets/websummit.db')) as src, closing(sqlite3.connect(old)) as dst:
            src.backup(dst)
            for t in ('company_endorsement', 'company_event_speaker', 'company_event', 'company_person',
                      'company_link', 'company_fact', 'company_tag', 'company'):
                dst.execute(f'DROP TABLE {t}')
            dst.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
            dst.commit()
        self.state = old
        self.assertEqual(self.run_cli('info')['sessions'], 1122)
        with closing(sqlite3.connect(old)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM company').fetchone()[0], 2872)
            self.assertEqual(c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '3')

    def test_import_side_events_filters_and_is_idempotent(self):
        sys.path.insert(0, str(SKILL / 'scripts'))
        import import_side_events as ise
        db = Path(self.tmp.name) / 'e.db'
        db.write_bytes((SKILL / 'assets/websummit.db').read_bytes())
        ev = lambda slug, **kw: {'name': slug, 'description': 'd', 'startDate': '2026-11-10T14:00:00+00:00',
                                 'url': 'https://example.org/events/' + slug, 'location': {'@type': 'Place', 'name': 'V'},
                                 'offers': {'price': '5', 'priceCurrency': 'EUR'}, **kw}
        events = [ev('keep-one', endDate='2026-11-10T15:00:00+00:00'), ev('keep-two', inLanguage='en'), ev('drop-me', inLanguage='ru')]
        self.assertEqual(ise.import_events(db, events), 2)
        self.assertEqual(ise.import_events(db, events), 2)
        with closing(sqlite3.connect(db)) as c:
            self.assertIsNone(c.execute("SELECT 1 FROM session WHERE id='side:drop-me'").fetchone())
            self.assertEqual(c.execute("SELECT end_known FROM side_event WHERE session_id='side:keep-two'").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT duration_min FROM session WHERE id='side:keep-one'").fetchone()[0], 60)

    def test_export_keeps_timestamps_and_creates_parent_directory(self):
        sid = self.run_cli('search', '--limit', '1')[0]['id']
        self.run_cli('mark', sid, 'must')
        plan = Path(self.tmp.name) / 'new/dir/plan.json'
        self.run_cli('export', '--out', str(plan))
        data = json.loads(plan.read_text(encoding='utf-8'))
        data['history'][0]['created_at'] = '2026-01-02T03:04:05Z'
        plan.write_text(json.dumps(data), encoding='utf-8')
        self.state = Path(self.tmp.name) / 'fresh2.db'
        self.run_cli('import', str(plan))
        self.assertEqual(self.run_cli('history', sid)[0]['created_at'], '2026-01-02T03:04:05Z')

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
