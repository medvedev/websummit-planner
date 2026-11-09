#!/usr/bin/env python3
"""Import a sanitized company catalog into a planner database.

Usage: import_companies.py SOURCE_DB [--db assets/websummit.db]

SOURCE_DB is the scraper database (company, company_profile, company_* tables).
Sanitizing: pitch_deck links and linkedin.com/in/ links are dropped, e-mail addresses
in descriptions become "[email removed]". Re-running replaces all company rows in one
transaction. Standard library only.
"""
import argparse
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_db import COMPANY_SCHEMA, COMPANY_TABLES  # noqa: E402

DEFAULT_DB = Path(__file__).resolve().parents[1] / 'assets' / 'websummit.db'
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')


def mask_emails(text):
    return None if text is None else EMAIL.sub('[email removed]', text)


def import_companies(source, db):
    con = sqlite3.connect(Path(db).resolve().as_uri() + '?mode=rw', uri=True)
    try:
        con.create_function('mask_emails', 1, mask_emails, deterministic=True)
        con.execute("ATTACH DATABASE ? AS src", (Path(source).resolve().as_uri() + "?mode=ro",))
        con.executescript(COMPANY_SCHEMA)
        con.execute("BEGIN")
        for t in reversed(COMPANY_TABLES):
            con.execute(f"DELETE FROM main.{t}")
        con.execute("""INSERT INTO company(id,uuid,name,tier,industry,country,location,description,website,logo_url)
            SELECT c.id, p.uuid, c.name, coalesce(c.tier,p.tier), coalesce(c.industry,p.industry), c.country,
                   p.location, mask_emails(p.description), p.website, coalesce(p.logo_url,c.logo_url)
            FROM src.company c LEFT JOIN src.company_profile p ON p.company_id = c.id""")
        con.execute("INSERT INTO company_tag SELECT company_id, tag FROM src.company_tag")
        con.execute("INSERT INTO company_fact SELECT company_id, position, fact FROM src.company_fact")
        con.execute("""INSERT INTO company_link SELECT company_id, kind, url FROM src.company_link
            WHERE kind <> 'pitch_deck' AND url NOT LIKE '%linkedin.com/in/%'""")
        con.execute("""INSERT INTO company_person
            SELECT person_uuid, company_id, role, tier, industry, country FROM src.company_person""")
        con.execute("""INSERT INTO company_event(company_id,event_uuid,session_id,title,time_text,location,type,description)
            SELECT e.company_id, e.event_uuid, s.id, e.title, e.time_text, e.location, e.type, e.description
            FROM src.company_event e LEFT JOIN main.session s ON s.id = e.event_uuid""")
        con.execute("""INSERT INTO company_event_speaker
            SELECT company_id, event_uuid, person_uuid, role, org FROM src.company_event_speaker""")
        con.execute("""INSERT INTO company_endorsement
            SELECT company_id, endorsed_company_id, endorsed_name FROM src.company_endorsement""")
        con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version','3')")
        counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in COMPANY_TABLES}
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        con.commit()
        return counts
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('--db', default=str(DEFAULT_DB))
    a = ap.parse_args()
    for table, n in import_companies(a.source, a.db).items():
        print(f'{table:24}{n}')
