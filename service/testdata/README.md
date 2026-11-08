# Migration fixtures

schedule.json is a curated public schedule slice; golden.json captures the former
TypeScript service outputs at repository baseline da04b60. They cover overlaps,
unknown ends, null fields, long IDs, Unicode, plan-code edge cases and filters.
The Go tests read these committed files and require no Node runtime. The TypeScript
source and one-time generator are available in repository history/the migration work.
For independent ongoing parity, tools/check_service.py compares HTTP results against
the Python/SQLite implementation using the full generated snapshot.
