#!/usr/bin/env python3
"""Build websummit.db (SQLite) from out/schedule.json.

Usage: build_db.py [--json out/schedule.json] [--db websummit.db]

Safe to re-run after a refresh: schedule tables are rebuilt from the JSON, while
user data (shortlist_version, setting) is carried over from the existing db.
Standard library only.
"""
import argparse, json, os, sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Lisbon")

COMPANY_SCHEMA = r"""
-- Company catalog from the Web Summit attendee portal (sanitized: no pitch decks,
-- no personal LinkedIn links, emails masked in descriptions). Not refreshable offline.
CREATE TABLE IF NOT EXISTS company (
  id INTEGER PRIMARY KEY, uuid TEXT, name TEXT NOT NULL, tier TEXT, industry TEXT,
  country TEXT, location TEXT, description TEXT, website TEXT, logo_url TEXT
);
CREATE TABLE IF NOT EXISTS company_tag (
  company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE, tag TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_fact (
  company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
  position INTEGER, fact TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_link (
  company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, url TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_person (
  person_uuid TEXT NOT NULL, company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
  role TEXT, tier TEXT, industry TEXT, country TEXT
);
CREATE TABLE IF NOT EXISTS company_event (
  company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
  event_uuid TEXT NOT NULL, session_id TEXT REFERENCES session(id) ON DELETE SET NULL,
  title TEXT, time_text TEXT, location TEXT, type TEXT, description TEXT
);
CREATE TABLE IF NOT EXISTS company_event_speaker (
  company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
  event_uuid TEXT NOT NULL, person_uuid TEXT NOT NULL, role TEXT, org TEXT
);
CREATE TABLE IF NOT EXISTS company_endorsement (
  company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
  endorsed_company_id INTEGER, endorsed_name TEXT
);
CREATE INDEX IF NOT EXISTS company_tag_tag ON company_tag(tag);
CREATE INDEX IF NOT EXISTS company_fact_fact ON company_fact(fact);
CREATE INDEX IF NOT EXISTS company_person_company ON company_person(company_id);
CREATE INDEX IF NOT EXISTS company_person_person ON company_person(person_uuid);
CREATE INDEX IF NOT EXISTS company_event_session ON company_event(session_id);
"""

COMPANY_TABLES = ("company", "company_tag", "company_fact", "company_link", "company_person",
                  "company_event", "company_event_speaker", "company_endorsement")

SCHEMA = r"""
PRAGMA foreign_keys = ON;

-- Time conventions: *_utc = ISO 8601 UTC 'YYYY-MM-DDTHH:MM:SSZ' (sortable, SQLite-parsable);
-- *_local = ISO 8601 Europe/Lisbon with offset 'YYYY-MM-DDTHH:MM:SS+00:00'; day = Lisbon date 'YYYY-MM-DD'.
CREATE TABLE stage (
  id   TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  venue TEXT
);
CREATE TABLE track (
  name TEXT PRIMARY KEY            -- natural key; source track ids are empty
);
CREATE TABLE person (
  id        TEXT PRIMARY KEY,      -- source attendance_id
  name      TEXT NOT NULL,
  company   TEXT,
  job_title TEXT
);
CREATE TABLE session (
  id          TEXT PRIMARY KEY,
  slug        TEXT NOT NULL,
  title       TEXT NOT NULL,
  description TEXT,
  starts_utc  TEXT NOT NULL CHECK (starts_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
  ends_utc    TEXT NOT NULL CHECK (ends_utc   GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
  starts_local TEXT NOT NULL,
  ends_local   TEXT NOT NULL,
  day         TEXT NOT NULL CHECK (day GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  duration_min INTEGER NOT NULL CHECK (duration_min >= 0),
  stage_id    TEXT REFERENCES stage(id),
  track       TEXT REFERENCES track(name),
  CHECK (ends_utc >= starts_utc)
);
CREATE INDEX session_time  ON session(starts_utc, ends_utc);
CREATE INDEX session_day   ON session(day);
CREATE INDEX session_stage ON session(stage_id);
CREATE INDEX session_track ON session(track);
CREATE TABLE session_person (
  session_id TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
  person_id  TEXT NOT NULL REFERENCES person(id),
  position   INTEGER NOT NULL,     -- order as listed by the source
  role       TEXT,
  PRIMARY KEY (session_id, person_id)
);
CREATE INDEX session_person_person ON session_person(person_id);

-- Shortlist: append-only version log. Never UPDATE/DELETE rows; insert a new one.
-- status 'removed' takes a session off the shortlist. Current state = v_shortlist.
CREATE TABLE shortlist_version (
  version     INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL REFERENCES session(id),
  status      TEXT NOT NULL CHECK (status IN ('maybe','must','skip','removed')),
  score       INTEGER CHECK (score BETWEEN 1 AND 5),
  note        TEXT,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  created_by  TEXT
);
CREATE INDEX shortlist_version_session ON shortlist_version(session_id, version);
CREATE TRIGGER shortlist_version_no_update BEFORE UPDATE ON shortlist_version
  BEGIN SELECT RAISE(ABORT, 'shortlist_version is append-only: INSERT a new version'); END;
CREATE TRIGGER shortlist_version_no_delete BEFORE DELETE ON shortlist_version
  BEGIN SELECT RAISE(ABORT, 'shortlist_version is append-only: INSERT a new version'); END;

CREATE TABLE setting (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
INSERT INTO setting VALUES ('conflict_buffer_min', '0');   -- travel gap between different stages

CREATE TABLE side_event (
  session_id TEXT PRIMARY KEY REFERENCES session(id) ON DELETE CASCADE,
  url TEXT, organizer TEXT, address TEXT, ticket_url TEXT,
  price TEXT, currency TEXT, is_free INTEGER, online INTEGER NOT NULL DEFAULT 0,
  end_known INTEGER NOT NULL DEFAULT 1,   -- 0: source gave no end time; end = start
  language TEXT
);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- Latest version per session, excluding removed ones.
CREATE VIEW v_shortlist AS
SELECT sv.version, sv.session_id, sv.status, sv.score, sv.note, sv.created_at
FROM shortlist_version sv
WHERE sv.version = (SELECT MAX(version) FROM shortlist_version WHERE session_id = sv.session_id)
  AND sv.status <> 'removed';

-- Compact list for title triage (this is the first thing to read).
-- kind: 'official' Web Summit session, 'side' community side event (see side_event).
CREATE VIEW v_titles AS
SELECT s.id, s.day, substr(s.starts_local,12,5) AS start, substr(s.ends_local,12,5) AS end,
       st.name AS stage, s.track, s.title,
       CASE WHEN se.session_id IS NULL THEN 'official' ELSE 'side' END AS kind
FROM session s LEFT JOIN stage st ON st.id = s.stage_id
LEFT JOIN side_event se ON se.session_id = s.id
ORDER BY s.starts_utc, st.name;

-- Full detail with speakers and shortlist state.
CREATE VIEW v_session_full AS
SELECT s.id, s.day, substr(s.starts_local,12,5) AS start, substr(s.ends_local,12,5) AS end,
       st.name AS stage, s.track, s.title, s.description,
       (SELECT group_concat(p.name || ' (' || trim(coalesce(p.job_title,'') ||
               CASE WHEN p.job_title<>'' AND p.company<>'' THEN ', ' ELSE '' END ||
               coalesce(p.company,'')) || ')', '; ')
        FROM (SELECT * FROM session_person WHERE session_id = s.id ORDER BY position) sp
        JOIN person p ON p.id = sp.person_id) AS speakers,
       sl.status AS shortlist_status, sl.score, sl.note,
       CASE WHEN se.session_id IS NULL THEN 'official' ELSE 'side' END AS kind
FROM session s LEFT JOIN stage st ON st.id = s.stage_id
LEFT JOIN side_event se ON se.session_id = s.id
LEFT JOIN v_shortlist sl ON sl.session_id = s.id;

-- Conflicts between shortlisted sessions with status maybe/must.
-- Overlap in time, or (different stage) a gap smaller than setting.conflict_buffer_min.
CREATE VIEW v_conflicts AS
SELECT a.id AS a_id, a.title AS a_title, a.start_t AS a_start, a.end_t AS a_end, a.stage AS a_stage,
       b.id AS b_id, b.title AS b_title, b.start_t AS b_start, b.end_t AS b_end, b.stage AS b_stage,
       CASE WHEN a.starts_utc < b.ends_utc AND b.starts_utc < a.ends_utc THEN 'overlap' ELSE 'tight-gap' END AS kind
FROM (SELECT s.*, substr(s.starts_local,12,5) start_t, substr(s.ends_local,12,5) end_t, st.name stage
      FROM session s LEFT JOIN stage st ON st.id=s.stage_id
      JOIN v_shortlist v ON v.session_id=s.id AND v.status IN ('maybe','must')) a
JOIN (SELECT s.*, substr(s.starts_local,12,5) start_t, substr(s.ends_local,12,5) end_t, st.name stage
      FROM session s LEFT JOIN stage st ON st.id=s.stage_id
      JOIN v_shortlist v ON v.session_id=s.id AND v.status IN ('maybe','must')) b
  ON a.id < b.id
 AND ( (a.starts_utc < b.ends_utc AND b.starts_utc < a.ends_utc)
    OR (coalesce(a.stage_id,'') <> coalesce(b.stage_id,'')
        AND a.starts_utc < strftime('%Y-%m-%dT%H:%M:%SZ', b.ends_utc, '+' || (SELECT value FROM setting WHERE key='conflict_buffer_min') || ' minutes')
        AND b.starts_utc < strftime('%Y-%m-%dT%H:%M:%SZ', a.ends_utc, '+' || (SELECT value FROM setting WHERE key='conflict_buffer_min') || ' minutes')
        AND (SELECT CAST(value AS INTEGER) FROM setting WHERE key='conflict_buffer_min') > 0) )
ORDER BY a.starts_utc, b.starts_utc;
""" + COMPANY_SCHEMA


def side_upgrade_sql():
    """DDL that adds side_event support to a database built before schema_version 2."""
    table = SCHEMA[SCHEMA.index("CREATE TABLE side_event"):SCHEMA.index("CREATE TABLE meta")]
    views = SCHEMA[SCHEMA.index("CREATE VIEW v_titles"):SCHEMA.index("-- Conflicts between")]
    return table + "DROP VIEW IF EXISTS v_titles;\nDROP VIEW IF EXISTS v_session_full;\n" + views


def company_upgrade_sql():
    """DDL that adds company support to a database built before schema_version 3."""
    return COMPANY_SCHEMA


def carry_companies(con, alias):
    """Copy company tables from an attached database; session_id is re-derived from event_uuid (set only if that session exists)."""
    if not con.execute(f"SELECT 1 FROM {alias}.sqlite_master WHERE name='company'").fetchone():
        return False
    for t in COMPANY_TABLES:
        if t == "company_event":
            con.execute(f"INSERT OR IGNORE INTO company_event(company_id,event_uuid,session_id,title,time_text,location,type,description) "
                        f"SELECT company_id,event_uuid,(SELECT id FROM main.session WHERE id=e.event_uuid),title,time_text,location,type,description "
                        f"FROM {alias}.company_event e")
        else:
            con.execute(f"INSERT OR IGNORE INTO {t} SELECT * FROM {alias}.{t}")
    return True


def utc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def build(json_path, db_path):
    with open(json_path, encoding='utf-8') as source:
        items = json.load(source)
    tmp = db_path + ".new"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)

    for it in items:
        s, e = utc(it["starts_at"]), utc(it["ends_at"])
        loc, tr = it["location"], (it.get("schedule_track") or {}).get("name") or None
        con.execute("INSERT OR IGNORE INTO stage VALUES (?,?,?)", (loc["id"], loc["name"], loc.get("venue") or None))
        if tr:
            con.execute("INSERT OR IGNORE INTO track VALUES (?)", (tr,))
        sl, el = s.astimezone(TZ), e.astimezone(TZ)
        con.execute(
            "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (it["id"], it["slug"], it["title"].strip(), (it.get("description") or "").strip() or None,
             s.strftime("%Y-%m-%dT%H:%M:%SZ"), e.strftime("%Y-%m-%dT%H:%M:%SZ"),
             sl.isoformat(timespec="seconds"), el.isoformat(timespec="seconds"),
             sl.date().isoformat(), int((e - s).total_seconds() // 60), loc["id"], tr))
        for pos, p in enumerate(it.get("timeslot_participations") or []):
            pid = p["attendance_id"]
            con.execute("INSERT OR IGNORE INTO person VALUES (?,?,?,?)",
                        (pid, p["name"], p.get("company_name") or None, p.get("job_title") or None))
            con.execute("INSERT OR IGNORE INTO session_person VALUES (?,?,?,?)",
                        (it["id"], pid, pos, p.get("role") or None))

    con.execute("INSERT INTO meta VALUES ('built_at', ?)", (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    con.execute("INSERT INTO meta VALUES ('source', ?)", (os.path.abspath(json_path),))
    con.execute("INSERT INTO meta VALUES ('schema_version', '3')")

    # Carry over user data from the previous db.
    carried = 0
    if os.path.exists(db_path):
        con.execute("ATTACH ? AS old", (db_path,))
        con.execute("UPDATE setting SET value = (SELECT value FROM old.setting o WHERE o.key=setting.key) "
                    "WHERE key IN (SELECT key FROM old.setting)")
        if con.execute("SELECT 1 FROM old.sqlite_master WHERE name='side_event'").fetchone():
            con.execute("INSERT OR IGNORE INTO stage SELECT * FROM old.stage WHERE id LIKE 'side:%'")
            con.execute("INSERT OR IGNORE INTO track SELECT * FROM old.track WHERE name='Side event'")
            con.execute("INSERT OR IGNORE INTO session SELECT * FROM old.session WHERE id IN (SELECT session_id FROM old.side_event)")
            con.execute("INSERT OR IGNORE INTO side_event SELECT * FROM old.side_event")
        carry_companies(con, "old")
        # keep only versions whose session still exists
        con.execute("INSERT INTO shortlist_version(version,session_id,status,score,note,created_at,created_by) "
                    "SELECT version,session_id,status,score,note,created_at,created_by FROM old.shortlist_version "
                    "WHERE session_id IN (SELECT id FROM session) ORDER BY version")
        carried = con.execute("SELECT COUNT(*) FROM shortlist_version").fetchone()[0]
        con.commit()
        con.execute("DETACH old")
    con.commit()

    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()
    os.replace(tmp, db_path)
    return carried


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="out/schedule.json")
    ap.add_argument("--db", default="websummit.db")
    a = ap.parse_args()
    carried = build(a.json, a.db)
    con = sqlite3.connect(a.db)
    for t in ("session", "stage", "track", "person", "session_person", "side_event", "shortlist_version", "company"):
        print(f"{t:18}{con.execute(f'select count(*) from {t}').fetchone()[0]}")
    print(f"carried over shortlist versions: {carried}")
