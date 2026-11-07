# Installation instructions for agents

Follow this guide when the user asks to install Web Summit Planner. It applies to Codex, Claude Code, and other local shell-capable agents. Do not run installation merely because you are reviewing or editing this repository.

## 1. Obtain the files and choose the host

Clone the user-supplied GitHub repository URL or download and extract its ZIP if Git is unavailable. Use the resulting repository as `<repo>`. Read its `install.py` before execution. No Python is needed to download or extract the repository.

Install for the agent the user is currently using:

| Host | Installer option | Default user skill directory |
| --- | --- | --- |
| Codex | `--agent codex` | `~/.agents/skills/websummit-planner` |
| Claude Code | `--agent claude` | `~/.claude/skills/websummit-planner` |
| Another compatible agent | `--dest ABSOLUTE_SKILL_FOLDER` | Use that host's documented skill folder |

Do not infer the host from which configuration folders happen to exist. If host identity is unavailable, ask which agent should receive the skill. Install for both only when requested. Default to user scope; honor a request for project scope with `--scope project --project ABSOLUTE_PROJECT_PATH`.

## 2. Find or prepare Python

Follow [the runtime setup guide](skills/websummit-planner/references/setup.md). Prefer an existing usable Python or existing planner runtime. If Python is absent or lacks SQLite/Lisbon timezone support, prepare the user-owned managed runtime described there. Do not tell the user to manually install Python as the default solution.

Use the selected interpreter's **absolute path** as `<python>`. Follow the host's normal approval and network rules for downloads and writes. This workflow needs no administrator privileges or changes to system Python, shell profiles, or execution policy.

## 3. Install

POSIX shell example (substitute the selected paths):

```sh
"<python>" "<repo>/install.py" --agent codex
# In Claude Code, use --agent claude instead.
```

PowerShell example:

```powershell
& '<python>' '<repo>\install.py' --agent claude
# In Codex, use --agent codex instead.
```

An existing destination is not silently overwritten. If it already contains this skill, read its SKILL.md and test `info`; use it when valid. If the user requested an upgrade, move the old installed skill folder aside and run the installer again. Preserve all personal databases and unrelated installed skills.

If using Codex's built-in GitHub skill installer, the skill path is `skills/websummit-planner`. That installs the files but may not prepare Python; continue with runtime setup and verification here. The same is true of any generic skill-copy tool.

## 4. Verify and start

Read the installed `SKILL.md`. Use the selected absolute interpreter path to run:

```sh
"<python>" "<installed-skill>/scripts/planner.py" info
"<python>" "<installed-skill>/scripts/planner.py" search --limit 1
```

Require successful JSON output with nonzero session count and a real session before declaring installation usable. These checks need no schedule refresh and do not create personal state. Do not save interests, create a shortlist, or refresh merely to test installation.

Codex can invoke `$websummit-planner`; Claude Code can invoke `/websummit-planner`. If native discovery needs a new session, read and use the installed SKILL.md explicitly in the current session, then tell the user how to invoke it later. Ask about their interests and available days and begin planning.

If network access is unavailable and there is no usable Python runtime, report that initial setup needs a runtime download. Once prepared, the offline planner does not require uv or network access to execute.
