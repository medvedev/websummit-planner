# Update instructions for agents

Follow this guide when the user asks to update an already installed Web Summit Planner skill. Never touch personal databases (`~/.local/share/websummit-planner/*.db`, or under `XDG_DATA_HOME`, or any `WEBSUMMIT_DB` / `--db` path): they hold the user's decisions. The new planner upgrades an older personal database in place on first use (for example it adds side events) and keeps all history, notes and settings.

1. **Find the installed skill folder(s):** `~/.agents/skills/websummit-planner` (Codex), `~/.claude/skills/websummit-planner` (Claude Code), `~/.gemini/skills/websummit-planner` (Gemini CLI), or the project-scope equivalents. Update only the host you are running in unless the user asks for more. If none exists, follow [INSTALL.md](INSTALL.md) instead.
2. **Get the latest files** into a new temporary directory: `git clone --depth 1 https://github.com/medvedev/websummit-planner` or download and extract the `main` ZIP. Read `install.py` before running it.
3. **Pick the interpreter** exactly as in [the runtime guide](skills/websummit-planner/references/setup.md) (planner-managed runtime first, then existing Python). Do not reinstall a runtime that already works.
4. **Move the old skill folder outside every skills directory** (for example into `~/.websummit-planner-backup/<timestamp>/`), not next to it, so the agent does not load two copies. Do not delete it until step 6 passes.
5. **Install:** run `"<python>" "<repo>/install.py" --agent <codex|claude|gemini>` from the fresh checkout (add `--scope project --project PATH` for project scope).
6. **Verify:** run `planner.py info` and `planner.py search --kind side --limit 1` with the installed copy. Require nonzero `sessions` and `side_events` and a real result. These commands do not need a schedule refresh. If verification fails, restore the folder from the backup and report the error.
7. **Report** the old and new snapshot dates (`info` → `metadata.built_at`) and the new features (side events: `search --kind side`). Do not run `refresh` unless the user asks. Tell the user to start a new session if their agent does not pick up the new SKILL.md.
