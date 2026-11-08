# Web Summit Planner — portable agent skill

Plan Web Summit Lisbon **9–12 November 2026** in Codex, Claude Code, Gemini CLI, or another shell-capable agent. Includes **1,122 sessions**, **344 community side events** (7–14 Nov), speaker details, an empty personal shortlist, append-only decisions, and overlap/travel-gap checks.

**You do not need Python preinstalled.** Ask your agent to follow [INSTALL.md](INSTALL.md): it can prepare a user-owned Python runtime automatically with uv, without administrator access or system Python changes. First-time runtime setup needs internet access; planning works offline afterward. Existing Python 3.9+ with SQLite and Lisbon timezone data also works. No API keys, accounts, MCP server, or Node.js are required. Optional schedule refresh needs internet access.

## Easiest: ask your agent to install it

Paste this prompt into Codex, Claude Code, Gemini CLI, or another local agent:

> Install the websummit-planner skill from https://github.com/medvedev/websummit-planner for this agent. Follow INSTALL.md, including managed runtime setup if Python is missing, and verify the installed skill works. Then help me plan Web Summit Lisbon 2026. Ask about my interests and available days.

For Codex's built-in skill installer, specify **`skills/websummit-planner`** as the path inside the GitHub repository. The complete skill, including its database and scripts, is contained there.

For Codex, add “Install for Codex” to the prompt; for Claude Code, add “Install for Claude Code”; for Gemini CLI, add “Install for Gemini CLI.” [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md) and [GEMINI.md](GEMINI.md) route those hosts to the same setup procedure. Other agents can follow [INSTALL.md](INSTALL.md) and choose their own skill folder. No personal-state initialization command is needed.

## Update an installed copy

Paste this into the same agent you used to install it:

> Update my installed websummit-planner skill to the latest version from https://github.com/medvedev/websummit-planner. Follow UPDATE.md: keep my personal shortlist database untouched, move the old skill folder out of the skills directory, install the latest files, and verify with `info` and a side-event search. Then tell me what changed.

Your shortlist, notes and settings are kept; your personal database is upgraded in place the first time the new version runs.

## Local installation

With a usable Python already installed, clone or download the repository, open a terminal in it, then run one command:

```sh
python3 install.py --agent codex
# or
python3 install.py --agent claude
# or
python3 install.py --agent gemini
# or install for both
python3 install.py --agent both
```

Without Python, give the agent the installation prompt above. For manual setup, follow the [macOS/Linux or Windows runtime commands](skills/websummit-planner/references/setup.md), then substitute the managed interpreter's absolute path for `python3` in these commands.

| Target | User installation |
| --- | --- |
| Codex | `~/.agents/skills/websummit-planner/` |
| Claude Code | `~/.claude/skills/websummit-planner/` |
| Gemini CLI | `~/.gemini/skills/websummit-planner/` (also reads `~/.agents/skills/`) |

For project-only installation, add `--scope project --project /path/to/project`.
For any other Agent Skills-compatible agent, use `--dest /path/to/skills/websummit-planner` (the exact skill folder). You can also copy the entire `skills/websummit-planner` folder yourself.

For a shell-capable agent without skill discovery, ask it to read `skills/websummit-planner/SKILL.md` from the checkout and follow it. Installation is optional for this use.

In Codex invoke `$websummit-planner`; in Claude Code invoke `/websummit-planner`. Example requests:

- “Find robotics and computer vision sessions on Tuesday.”
- “Help me choose sessions based on my work and interests.”
- “Add these two sessions as must-attend, then check conflicts.”
- “Allow ten minutes between stages and show my plan.”

## Try without installing

From this repository:

```sh
python3 skills/websummit-planner/scripts/planner.py info
python3 skills/websummit-planner/scripts/planner.py search robotics
python3 skills/websummit-planner/scripts/planner.py search --day 2026-11-10 --limit 20
```

All commands return JSON; help is available with `--help` or `COMMAND --help`. All displayed times are Europe/Lisbon. Search uses literal substring matching, with SQLite's built-in case handling (ASCII case-insensitive).

## Personal data and updates

The shipped snapshot contains **no personal shortlist or notes**. Read commands do not create files. The first write creates `~/.local/share/websummit-planner/2026.db` (or under `XDG_DATA_HOME`). Use `WEBSUMMIT_DB` or `--db PATH` before the command for another location or separate plans. Keep that file to retain your history.

The installer refuses existing destinations. To upgrade, move the old **installed skill folder** aside and install again. This does not remove your personal database. A newer bundled snapshot does not automatically replace an existing personal schedule; ask the agent to refresh it. To uninstall, remove the installed skill folder; separately remove personal state only if you want to erase your decisions.

The snapshot was collected **7 November 2026** from the public Web Summit website. Sessions may change. To refresh your personal schedule explicitly:

```sh
python3 skills/websummit-planner/scripts/planner.py refresh
```

Refresh preserves decisions and settings and refuses a result that would discard history for vanished sessions. Failed builds leave the database intact. Empty results are rejected; a nonempty successful download is not a guarantee the upstream website is complete. Do not run simultaneous refreshes or writes to the same personal database.

## Development and sharing

```sh
python3 -m unittest discover -s tests -v
```

Tests use temporary personal databases and install destinations. GitHub Actions runs them on Linux, macOS, and Windows. Native agent discovery still depends on the installed agent version and session.

When sharing or forking, keep `skills/websummit-planner` intact and do not add your personal database. Code and instructions are MIT licensed; event content is attributed separately in [DATA_NOTICE.md](DATA_NOTICE.md). This is an unofficial independent tool.

Skill format and installation references: [OpenAI skills](https://developers.openai.com/plugins/build/skills), [OpenAI agent installation paths](https://developers.openai.com/api/reference/cli), [Claude Code skills](https://code.claude.com/docs/en/skills).

## Web assistants and agenda downloads

The public source is read-only. Keep your shortlist and notes in your assistant's context.
See [web instructions](docs/web-instructions.md) for Claude, ChatGPT, Codex web and Gemini.
The distribution includes a skill ZIP, schedule JSON, per-day text and an agenda exporter.
No Gemini subscription or model API key is required for the file-upload route.

Ask your agent: “Use the Web Summit snapshot, help me choose sessions, then create my
agenda as Markdown, PDF and an ICS calendar.” The helper `scripts/agenda.py` takes a
context-held selection array and reads the snapshot without creating personal state.
Markdown and ICS require only Python; PDF requires ReportLab and a Unicode font.
ICS files are for manual Google/Apple/Outlook imports; they do not create Teams meetings.
Host-generated PDF/download support varies. No server stores your personal plan.
