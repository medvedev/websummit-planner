# Web Summit Planner

For user requests to install or import this skill, follow [INSTALL.md](INSTALL.md).
It covers Codex, Claude Code, other hosts, and users without Python installed.
Complete the runtime check and installed-skill smoke test before reporting success.

For repository maintenance, follow the user's task; installation is not a prerequisite.
Run `python3 -m unittest discover -s tests -v` for code changes.

In Codex cloud, run the skill in place from `skills/websummit-planner`; no install needed. Offer `export --out plan.json` at the end so the user can keep their shortlist.
