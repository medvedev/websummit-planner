#!/usr/bin/env python3
"""Offline Web Summit planner. Python 3.9+, standard library only."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parent))
import companies  # noqa: E402
from companies import event_url  # noqa: E402,F401

SEED = Path(__file__).resolve().parents[1] / 'assets' / 'websummit.db'


def default_db():
    if os.environ.get('WEBSUMMIT_DB'):
        return Path(os.environ['WEBSUMMIT_DB']).expanduser()
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    return base / 'websummit-planner' / '2026.db'


@contextmanager
def connect(path, readonly=False):
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) if readonly else sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        with con:
            yield con
    finally:
        con.close()


def rows(con, sql, params=()):
    result = [dict(r) for r in con.execute(sql, params)]
    for r in result:
        if r.get('kind') == 'official':
            r['url'] = event_url(r['id'])
    return result


def initialize(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Publish a complete copy exclusively, even if two sessions initialize at once.
    fd, temporary = tempfile.mkstemp(prefix='.initialize-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(SEED.read_bytes())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary)


def upgrade(path):
    """Add side-event and company support to a personal database from an older snapshot (in place, one transaction)."""
    from build_db import side_upgrade_sql, company_upgrade_sql, carry_companies
    with connect(path) as con:
        need_side = not con.execute("SELECT 1 FROM sqlite_master WHERE name='side_event'").fetchone()
        need_company = not con.execute("SELECT 1 FROM sqlite_master WHERE name='company'").fetchone()
        if not (need_side or need_company):
            return
        con.executescript('BEGIN;' + (side_upgrade_sql() if need_side else '') + (company_upgrade_sql() if need_company else ''))
        con.execute('ATTACH ? AS seed', (str(SEED),))
        if need_side:
            con.execute("INSERT OR IGNORE INTO stage SELECT * FROM seed.stage WHERE id LIKE 'side:%'")
            con.execute("INSERT OR IGNORE INTO track SELECT * FROM seed.track WHERE name='Side event'")
            con.execute('INSERT OR IGNORE INTO session SELECT * FROM seed.session WHERE id IN (SELECT session_id FROM seed.side_event)')
            con.execute('INSERT OR IGNORE INTO side_event SELECT * FROM seed.side_event')
        if need_company:
            carry_companies(con, 'seed')
        con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', '3')")
        con.commit()
        con.execute('DETACH seed')


def refresh(path, json_path=None):
    """Build and validate in a temporary directory before replacing personal state."""
    from build_db import build
    from fetch_schedule import main as fetch
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.refresh-', dir=path.parent) as tmp:
        tmp = Path(tmp)
        source = Path(json_path).resolve() if json_path else tmp / 'out/schedule.json'
        if not json_path:
            previous = sys.argv
            try:
                sys.argv = ['fetch_schedule.py', '--force', '--out', str(tmp / 'out')]
                # Progress remains on stderr; keep stdout machine readable.
                from contextlib import redirect_stdout
                with redirect_stdout(sys.stderr):
                    fetch()
            finally:
                sys.argv = previous
        items = json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(items, list) or not items:
            raise ValueError('Refresh returned no sessions; personal database was not replaced')
        old = path if path.exists() else SEED
        ids = {item['id'] for item in items}
        with connect(old, True) as con:
            ids |= {r[0] for r in con.execute('SELECT session_id FROM side_event')}
            missing = [r[0] for r in con.execute('SELECT DISTINCT session_id FROM shortlist_version') if r[0] not in ids]
        if missing:
            raise ValueError('Refresh would discard shortlist history for missing sessions; database unchanged: ' + ', '.join(missing))
        target = tmp / 'next.db'
        with connect(old, True) as src, connect(target) as dst:
            src.backup(dst)
        build(str(source), str(target))
        with connect(target) as con:
            con.execute("UPDATE meta SET value=? WHERE key='source'", ('https://websummit.com/schedule/',))
        os.replace(target, path)
    return {'refreshed': True, 'database': str(path), 'sessions': len(items)}


PLAN_FORMAT = 'websummit-plan-v1'


def import_plan(path, plan_path):
    """Replay an exported plan through the append-only path; validate everything first."""
    try:
        plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise ValueError('Plan file is not valid JSON: ' + str(error))
    if not isinstance(plan, dict) or plan.get('format') != PLAN_FORMAT or not isinstance(plan.get('history'), list):
        raise ValueError('Not a ' + PLAN_FORMAT + ' plan file')
    settings = plan.get('settings') or {}
    buffer = settings.get('conflict_buffer_min', 0)
    if not isinstance(buffer, int) or isinstance(buffer, bool) or buffer < 0:
        raise ValueError('Plan has an invalid travel buffer')
    source = path if path.exists() else SEED
    with connect(source, True) as con:
        if con.execute('SELECT 1 FROM shortlist_version LIMIT 1').fetchone():
            raise ValueError('Personal state already has history; import into a fresh --db')
        known = {r[0] for r in con.execute('SELECT id FROM session')}
    entries = []
    for e in plan['history']:
        if not isinstance(e, dict) or e.get('status') not in ('maybe', 'must', 'skip', 'removed'):
            raise ValueError('Plan has an invalid history entry: ' + json.dumps(e, ensure_ascii=False)[:200])
        if e.get('session_id') not in known:
            raise ValueError('Unknown session: ' + str(e.get('session_id')))
        score = e.get('score')
        if score is not None and (not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5):
            raise ValueError('Plan has an invalid score for ' + e['session_id'])
        created = e.get('created_at')
        if created is not None and not isinstance(created, str):
            raise ValueError('Plan has an invalid timestamp for ' + e['session_id'])
        entries.append((e['session_id'], e['status'], score, e.get('note') or '', e.get('created_by'), created))
    initialize(path)
    with connect(path) as con:
        con.executemany("INSERT INTO shortlist_version(session_id,status,score,note,created_by,created_at) VALUES (?,?,?,?,?,coalesce(?,strftime('%Y-%m-%dT%H:%M:%SZ','now')))", entries)
        con.execute("UPDATE setting SET value=? WHERE key='conflict_buffer_min'", (str(buffer),))
    return {'imported': len(entries), 'conflict_buffer_min': buffer}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, default=default_db(), help='personal database (or WEBSUMMIT_DB)')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('info')
    s = sub.add_parser('search')
    s.add_argument('query', nargs='?', default='', help='literal substring across title, description, speakers, companies')
    s.add_argument('--day')
    s.add_argument('--track')
    s.add_argument('--stage')
    s.add_argument('--limit', type=int, default=30)
    s.add_argument('--kind', choices=['official', 'side', 'all'], default='official',
                   help='official Web Summit sessions (default), community side events, or both')
    c = sub.add_parser('companies', help='search the company catalog')
    c.add_argument('query', nargs='?', default='', help='literal substring across name, description, location, tags')
    c.add_argument('--industry')
    c.add_argument('--country')
    c.add_argument('--tier')
    c.add_argument('--tag', action='append', default=[], help='exact tag (case-insensitive); repeat to AND')
    c.add_argument('--fact', action='append', default=[], help='case-insensitive substring of a fact; repeat to AND')
    c.add_argument('--limit', type=int, default=30)
    cd = sub.add_parser('company', help='company details by id (company:<n> or <n>)')
    cd.add_argument('ids', nargs='+')
    d = sub.add_parser('details')
    d.add_argument('ids', nargs='+')
    sub.add_parser('shortlist')
    m = sub.add_parser('mark')
    m.add_argument('id')
    m.add_argument('status', choices=['maybe', 'must', 'skip', 'removed'])
    m.add_argument('--score', type=int, choices=range(1, 6))
    m.add_argument('--note', default='')
    m.add_argument('--by', default='agent')
    h = sub.add_parser('history')
    h.add_argument('id')
    b = sub.add_parser('buffer')
    b.add_argument('minutes', type=int)
    sub.add_parser('conflicts')
    x = sub.add_parser('export', help='write shortlist history and settings as portable JSON')
    x.add_argument('--out', type=Path, help='write to this file instead of stdout')
    i = sub.add_parser('import', help='replay an exported plan into empty personal state')
    i.add_argument('plan', type=Path)
    r = sub.add_parser('refresh')
    r.add_argument('--json', type=Path, help='build from a local schedule JSON instead of downloading')
    return p


def run(a):
    path = a.db.expanduser().resolve()
    if path == SEED.resolve():
        raise ValueError('--db must point to personal state, not the bundled snapshot')
    if path.exists():
        upgrade(path)
    if a.command == 'refresh':
        return refresh(path, a.json)
    if a.command == 'import':
        return import_plan(path, a.plan)
    source = path if path.exists() else SEED
    with connect(source, True) as con:
        if a.command in ('mark', 'details', 'history'):
            ids = a.ids if a.command == 'details' else [a.id]
            for sid in ids:
                if not con.execute('SELECT 1 FROM session WHERE id=?', (sid,)).fetchone():
                    raise ValueError('Unknown session: ' + sid)
        if a.command in ('search', 'companies') and a.limit < 1:
            raise ValueError('--limit must be positive')
        if a.command == 'buffer' and a.minutes < 0:
            raise ValueError('Travel buffer must be nonnegative')
        if a.command == 'info':
            return {'database': str(source), 'personal_database': str(path),
                    'sessions': con.execute('SELECT count(*) FROM session WHERE id NOT IN (SELECT session_id FROM side_event)').fetchone()[0],
                    'side_events': con.execute('SELECT count(*) FROM side_event').fetchone()[0],
                    'days': [r[0] for r in con.execute('SELECT DISTINCT day FROM session ORDER BY day')],
                    'metadata': dict(con.execute('SELECT * FROM meta')),
                    'settings': dict(con.execute('SELECT * FROM setting')),
                    **companies.info_counts(con)}
        if a.command == 'companies':
            return companies.search_companies(con, a.query, a.industry, a.country, a.tier, a.tag, a.fact, a.limit)
        if a.command == 'company':
            nums = []
            for raw in a.ids:
                n = companies.parse_company_id(raw)
                if n is None or not con.execute('SELECT 1 FROM company WHERE id=?', (n,)).fetchone():
                    raise ValueError('Unknown company: ' + raw)
                nums.append(n)
            return companies.company_objects(con, nums)
        if a.command == 'search':
            where, params = [], []
            if a.query:
                where.append("(instr(lower(s.title),lower(?))>0 OR instr(lower(coalesce(s.description,'')),lower(?))>0 OR EXISTS (SELECT 1 FROM session_person sp JOIN person p ON p.id=sp.person_id WHERE sp.session_id=s.id AND instr(lower(p.name||' '||coalesce(p.company,'')),lower(?))>0))")
                params.extend([a.query] * 3)
            for col, value in [('s.day', a.day), ('s.track', a.track), ('st.name', a.stage)]:
                if value:
                    where.append(col + '=?')
                    params.append(value)
            if a.kind != 'all':
                where.append('v.kind=?')
                params.append(a.kind)
            sql = 'SELECT v.* FROM v_titles v JOIN session s ON s.id=v.id LEFT JOIN stage st ON st.id=s.stage_id'
            if where:
                sql += ' WHERE ' + ' AND '.join(where)
            return rows(con, sql + ' ORDER BY s.starts_utc,v.stage,v.id LIMIT ?', params + [a.limit])
        if a.command == 'details':
            found = rows(con, 'SELECT * FROM v_session_full WHERE id IN (' + ','.join('?' for _ in a.ids) + ') ORDER BY day,start,id', a.ids)
            for r in found:
                if r['kind'] == 'official':
                    host = companies.session_companies(con, r['id'])
                    if host:
                        r['companies'] = host
                    r['people'] = rows(con, 'SELECT p.* FROM session_person sp JOIN person p ON p.id=sp.person_id WHERE sp.session_id=? ORDER BY sp.position', (r['id'],))
                    for person in r['people']:
                        person['url'] = 'https://attend.websummit.com/lis26/profiles/' + person['id']
                if r['kind'] == 'side':
                    r['side_event'] = rows(con, 'SELECT * FROM side_event WHERE session_id=?', (r['id'],))[0]
            return found
        if a.command == 'shortlist':
            return rows(con, 'SELECT * FROM v_session_full WHERE shortlist_status IS NOT NULL ORDER BY day,start,id')
        if a.command == 'history':
            return rows(con, 'SELECT * FROM shortlist_version WHERE session_id=? ORDER BY version', (a.id,))
        if a.command == 'conflicts':
            return rows(con, 'SELECT * FROM v_conflicts')
        if a.command == 'export':
            plan = {'format': PLAN_FORMAT,
                    'settings': {'conflict_buffer_min': int(dict(con.execute('SELECT * FROM setting'))['conflict_buffer_min'])},
                    'history': rows(con, 'SELECT session_id,status,score,note,created_at,created_by FROM shortlist_version ORDER BY version')}
            if a.out:
                a.out.parent.mkdir(parents=True, exist_ok=True)
                a.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
                return {'exported': len(plan['history']), 'file': str(a.out)}
            return plan
    initialize(path)
    with connect(path) as con:
        if a.command == 'mark':
            cursor = con.execute('INSERT INTO shortlist_version(session_id,status,score,note,created_by) VALUES (?,?,?,?,?)',
                                 (a.id, a.status, a.score, a.note, a.by))
            return rows(con, 'SELECT * FROM shortlist_version WHERE version=?', (cursor.lastrowid,))[0]
        con.execute("UPDATE setting SET value=? WHERE key='conflict_buffer_min'", (str(a.minutes),))
        return {'conflict_buffer_min': a.minutes}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    p = parser()
    a = p.parse_args()
    try:
        print(json.dumps(run(a), ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError, RuntimeError, sqlite3.Error) as error:
        p.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
