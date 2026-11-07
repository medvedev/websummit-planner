# Web Summit planner implementation plan

Goal: share an immediately usable offline Lisbon 2026 planner as a portable Agent Skill.
Approved scope: search, session details, personal shortlist, conflicts, optional refresh.
Python 3.9+ standard library only; no service, credentials, or package installation.

- [x] Bundle a fresh database built from the existing schedule JSON, with no personal history or absolute source path.
- [x] Test and implement a JSON CLI: info, search, details, shortlist, mark, history, buffer, conflicts, refresh.
  Reads use the bundled snapshot until a personal database exists; writes initialize an external per-user copy.
  Refresh preserves history and replaces the database only after validation.
  Ruling: reject refresh when referenced sessions disappear rather than maintaining an archived schedule schema; the old database and all history remain intact.
- [x] Test and implement copy installation for Codex, Claude Code, and custom destinations, refusing overwrite.
- [x] Write SKILL.md, schema reference, README with agent-assisted installation and manual fallback, MIT code license and separate data attribution.
- [x] Run the complete unittest suite, skill validation, copied-install smoke tests, and inspect the distributable for private state.

Review focus: arbitrary working directories and spaces in paths; invalid IDs/scores;
empty or failed refresh; installation collisions; user state surviving skill replacement.
Keep original project files unchanged. Initialize a local Git repository; do not commit or push.

Validation: 10 unittest integration tests passed on the local Linux host, including
Unicode refresh under a non-UTF-8 locale, install portability, history preservation,
overlap and travel-gap detection. Skill quick validation passed. Independent review
identified locale-dependent text IO; corrected and covered by a failing-then-passing test.
No personal rows or author filesystem paths found in the bundled database.
GitHub Actions is configured for Python 3.9/3.13 on Linux/macOS/Windows but has not run.
Live website refresh and native agent discovery have not been exercised in this session.

Follow-up: added universal INSTALL.md, Codex AGENTS.md and Claude Code CLAUDE.md
installation routing, plus a runtime guide bundled inside the skill. Users without
Python can obtain a dedicated user-owned runtime through uv; later sessions locate
that persistent interpreter before trying system Python. Verified on Linux using
a newly downloaded managed Python, paths containing spaces, PATH without system
Python, and disabled system timezone lookup. Installed-skill info/search succeeded;
all 10 tests also passed under the managed interpreter. Windows PowerShell runtime
setup is documented but has not been executed locally. No commits or pushes made.
