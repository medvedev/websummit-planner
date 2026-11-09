#!/usr/bin/env python3
"""Add community side events (schema.org Event JSON array) to a planner database.

Usage: import_side_events.py EVENTS.json [--db assets/websummit.db]

Side events become ordinary `session` rows (id `side:<slug>`, track `Side event`, stage = venue)
so shortlist and conflict checks work unchanged, plus a `side_event` row with extra fields.
Re-running updates existing side events. Standard library only.
"""
import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_db import side_upgrade_sql  # noqa: E402

TZ = ZoneInfo('Europe/Lisbon')
DEFAULT_DB = Path(__file__).resolve().parents[1] / 'assets' / 'websummit.db'


def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-') or 'venue'


def utc(iso):
    return datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone(timezone.utc)


def ensure_schema(con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='side_event'").fetchone():
        con.executescript(side_upgrade_sql())
    has_company = con.execute("SELECT 1 FROM sqlite_master WHERE name='company'").fetchone()
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", ('3' if has_company else '2',))


def wanted(e):
    return e.get('inLanguage') != 'ru'


def import_events(db, events):
    con = sqlite3.connect(db)
    con.execute('PRAGMA foreign_keys=ON')
    count = 0
    try:
        ensure_schema(con)
        con.execute("INSERT OR IGNORE INTO track VALUES ('Side event')")
        for e in events:
            if not wanted(e):
                continue
            slug = e['url'].rstrip('/').rsplit('/', 1)[-1]
            sid = 'side:' + slug
            s = utc(e['startDate'])
            end_known = bool(e.get('endDate'))
            en = utc(e['endDate']) if end_known else s
            loc = e.get('location') or {}
            online = loc.get('@type') == 'VirtualLocation' or 'Online' in str(e.get('eventAttendanceMode'))
            venue = 'Online' if online else (loc.get('name') or 'Venue to be confirmed').strip()
            stage_id = 'side:' + slugify(venue)
            addr = (loc.get('address') or {}).get('streetAddress') if isinstance(loc.get('address'), dict) else None
            con.execute('INSERT OR IGNORE INTO stage VALUES (?,?,?)', (stage_id, venue, None))
            sl, el = s.astimezone(TZ), en.astimezone(TZ)
            fmt = '%Y-%m-%dT%H:%M:%SZ'
            con.execute('INSERT OR REPLACE INTO session VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (sid, slug, e['name'].strip(), (e.get('description') or '').strip() or None,
                         s.strftime(fmt), en.strftime(fmt), sl.isoformat(timespec='seconds'),
                         el.isoformat(timespec='seconds'), sl.date().isoformat(),
                         int((en - s).total_seconds() // 60), stage_id, 'Side event'))
            offer = e.get('offers') or {}
            org = (e.get('organizer') or {}).get('name')
            free = e.get('isAccessibleForFree')
            con.execute('INSERT OR REPLACE INTO side_event VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (sid, e.get('url'), org, addr, offer.get('url'), str(offer['price']) if offer.get('price') is not None else None,
                         offer.get('priceCurrency'), None if free is None else int(bool(free)), int(online),
                         int(end_known), e.get('inLanguage')))
            count += 1
        assert con.execute('PRAGMA foreign_key_check').fetchall() == []
        con.commit()
    finally:
        con.close()
    return count


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('events', type=Path)
    p.add_argument('--db', type=Path, default=DEFAULT_DB)
    a = p.parse_args()
    events = json.loads(a.events.read_text(encoding='utf-8'))
    print(json.dumps({'side_events': import_events(a.db, events)}))


if __name__ == '__main__':
    main()
