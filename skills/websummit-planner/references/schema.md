# Database reference

Tables: `session`, `stage`, `track`, `person`, `session_person`, `shortlist_version`, `setting`, `meta`.
The full DDL is in `scripts/build_db.py`; Python's `sqlite3` module is sufficient, with no sqlite3 executable required.

- `v_titles`: id, day, start, end, stage, track, title. Compact discovery view.
- `v_session_full`: same fields plus description, speakers, shortlist_status, score, note.
- `v_shortlist`: latest non-removed history version per session, including skips.
- `v_conflicts`: a_id/a_title/a_start/a_end/a_stage and matching b fields, kind (`overlap`, `tight-gap`). Only maybe/must selections participate.

`shortlist_version`: version, session_id, status, score, note, created_at, created_by.
Insert a complete new version; UPDATE and DELETE are blocked by triggers.
Set `PRAGMA foreign_keys=ON` on any direct writable connection. Parameterize user input.

`starts_utc` / `ends_utc`: ISO UTC `YYYY-MM-DDTHH:MM:SSZ`.
`starts_local` / `ends_local`: ISO timestamps with Europe/Lisbon offset.
`day`: Lisbon calendar date; `duration_min`: integer minutes.
Views render local start/end as HH:MM. `meta.built_at` is the database build time, not proof the schedule was fetched at that exact time.
`setting.conflict_buffer_min`: nonnegative integer minutes between different stages; default 0.

The schedule covers 9–12 November 2026 only. The fetcher is specific to this edition and its public website endpoint; future editions require reviewing the dates and source format.

Example SQL:

```sql
SELECT * FROM v_titles WHERE day='2026-11-10';
SELECT * FROM v_session_full WHERE id IN (?, ?);
SELECT * FROM shortlist_version WHERE session_id=? ORDER BY version;
SELECT * FROM v_conflicts;
```

Use personal database backups for recovery. Upgrading or removing a skill leaves personal state intact because it is outside the installation directory. The supported concurrency model is one writer per personal database.
