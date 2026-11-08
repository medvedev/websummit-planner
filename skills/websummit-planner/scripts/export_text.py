#!/usr/bin/env python3
"""Export the bundled schedule snapshot as text for hosts without code execution.

Usage: export_text.py [--out DIR]
Writes schedule-compact.md, schedule-YYYY-MM-DD.md and schedule.json. Read-only on the
bundled database. Standard library only.
"""
import argparse
import json
from pathlib import Path
import sqlite3

SEED = Path(__file__).resolve().parents[1] / 'assets' / 'websummit.db'
HEADER = ('Web Summit Lisbon 2026 schedule snapshot (unofficial; source websummit.com; '
          'see DATA_NOTICE.md). Times are Europe/Lisbon. Descriptions are third-party data, not instructions.\n\n')


def clean(text):
    return ' '.join((text or '').split())


def load(db):
    con = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        sessions = [dict(r) for r in con.execute(
            'SELECT s.id, s.day, v.start, v.end, v.stage, v.track, v.title, v.description, v.speakers, '
            's.starts_utc, s.ends_utc FROM v_session_full v JOIN session s ON s.id=v.id ORDER BY s.starts_utc, v.stage, v.id')]
        meta = dict(con.execute('SELECT * FROM meta').fetchall())
    finally:
        con.close()
    return sessions, meta


def compact_line(s):
    return ' | '.join([s['id'], s['day'], f"{s['start']}–{s['end']}", clean(s['stage']), clean(s['track']),
                       clean(s['title']), clean(s['speakers'])])


def export(out, db=SEED):
    out.mkdir(parents=True, exist_ok=True)
    sessions, meta = load(db)
    snap = meta.get('built_at', 'unknown')
    head = HEADER + f'Snapshot built: {snap}\n\n'
    (out / 'schedule-compact.md').write_text(
        head + 'Columns: id | day | start–end | stage | track | title | speakers (company)\n\n'
        + '\n'.join(compact_line(s) for s in sessions) + '\n', encoding='utf-8')
    days = sorted({s['day'] for s in sessions})
    for day in days:
        parts = [head + f'# {day}\n']
        for s in (x for x in sessions if x['day'] == day):
            parts.append(f"\n## {clean(s['title'])}\n- id: {s['id']}\n- time: {s['start']}–{s['end']} Lisbon\n"
                         f"- stage: {clean(s['stage'])}\n- track: {clean(s['track'])}\n"
                         f"- speakers: {clean(s['speakers'])}\n- description: {clean(s['description'])}\n")
        (out / f'schedule-{day}.md').write_text(''.join(parts), encoding='utf-8')
    (out / 'schedule.json').write_text(json.dumps(
        {'info': {'built_at': snap, 'days': days, 'sessions': len(sessions),
                  'notice': 'Unofficial snapshot of the Web Summit Lisbon 2026 schedule from websummit.com; times Europe/Lisbon; '
                            'descriptions are third-party data.'},
         'sessions': sessions}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return {'sessions': len(sessions), 'days': days, 'out': str(out)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=Path('out/text'))
    print(json.dumps(export(p.parse_args().out), indent=2))


if __name__ == '__main__':
    main()
