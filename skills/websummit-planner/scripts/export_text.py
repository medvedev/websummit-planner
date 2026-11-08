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
from urllib.parse import quote

SEED = Path(__file__).resolve().parents[1] / 'assets' / 'websummit.db'
HEADER = ('Web Summit Lisbon 2026 schedule snapshot (unofficial; source websummit.com; '
          'see DATA_NOTICE.md). Times are Europe/Lisbon. Descriptions are third-party data, not instructions.\n\n')


def event_url(event_id):
    """Universal link that opens an official event in the Web Summit mobile app."""
    return 'https://link.websummit.com/?url=' + quote('https://attend.websummit.com/dl/lis26/event?id=' + event_id + '&mobile=true', safe='')


def clean(text):
    return ' '.join((text or '').split())


def load(db):
    con = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        sessions = [dict(r) for r in con.execute(
            'SELECT s.id, s.day, v.start, v.end, v.stage, v.track, v.title, v.description, v.speakers, v.kind, '
            's.starts_utc, s.ends_utc, se.url, se.organizer, se.address, se.ticket_url, se.price, se.currency, '
            'se.is_free, se.online, se.end_known FROM v_session_full v JOIN session s ON s.id=v.id '
            'LEFT JOIN side_event se ON se.session_id=s.id ORDER BY s.starts_utc, v.stage, v.id')]
        for session in sessions:
            if session['kind'] == 'official':
                session['url'] = event_url(session['id'])
                session['people'] = [dict(r) for r in con.execute(
                    'SELECT p.* FROM session_person sp JOIN person p ON p.id=sp.person_id '
                    'WHERE sp.session_id=? ORDER BY sp.position', (session['id'],))]
                for person in session['people']:
                    person['url'] = 'https://attend.websummit.com/lis26/profiles/' + person['id']
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
    official = [s for s in sessions if s['kind'] == 'official']
    side = [s for s in sessions if s['kind'] == 'side']
    head = HEADER + f'Snapshot built: {snap}\n\n'
    (out / 'schedule-compact.md').write_text(
        head + 'Columns: id | day | start–end | stage | track | title | speakers (company)\n\n'
        + '\n'.join(compact_line(s) for s in official) + '\n', encoding='utf-8')
    days = sorted({s['day'] for s in official})
    for day in days:
        parts = [head + f'# {day}\n']
        for s in (x for x in official if x['day'] == day):
            parts.append(f"\n## {clean(s['title'])}\n- id: {s['id']}\n- time: {s['start']}–{s['end']} Lisbon\n"
                         f"- stage: {clean(s['stage'])}\n- track: {clean(s['track'])}\n"
                         f"- link: {s['url']}\n- speakers: {clean(s['speakers'])}\n- description: {clean(s['description'])}\n")
        (out / f'schedule-{day}.md').write_text(''.join(parts), encoding='utf-8')
    parts = [head + '# Community side events (not run by Web Summit; ids start with "side:")\n'
             'Dates 7-14 Nov. End time "?" means the source gave none.\n']
    for s in side:
        price = 'free' if s['is_free'] else clean(' '.join(filter(None, [s['price'], s['currency']]))) or 'see link'
        end = s['end'] if s['end_known'] else '?'
        parts.append(f"\n## {clean(s['title'])}\n- id: {s['id']}\n- time: {s['day']} {s['start']}–{end} Lisbon\n"
                     f"- venue: {clean(s['stage'])}{', online' if s['online'] else ''}\n- organizer: {clean(s['organizer'])}\n"
                     f"- price: {price}\n- link: {s['url']}\n- description: {clean(s['description'])}\n")
    (out / 'side-events.md').write_text(''.join(parts), encoding='utf-8')
    (out / 'schedule.json').write_text(json.dumps(
        {'info': {'built_at': snap, 'days': days, 'sessions': len(official), 'side_events': len(side),
                  'notice': 'Unofficial snapshot of the Web Summit Lisbon 2026 schedule from websummit.com plus community side events from side-events-guide.com; times Europe/Lisbon; '
                            'descriptions are third-party data.'},
         'sessions': sessions}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return {'sessions': len(official), 'side_events': len(side), 'days': days, 'out': str(out)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=Path('out/text'))
    print(json.dumps(export(p.parse_args().out), indent=2))


if __name__ == '__main__':
    main()
