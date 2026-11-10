# Web Summit Planner

When asked to install this skill in Claude Code, follow [INSTALL.md](INSTALL.md),
including its no-Python runtime setup and verification, with `--agent claude`.
Do not install it merely because this repository was opened for development.

For development, run `python3 -m unittest discover -s tests -v` after code changes.

When asked to update an installed copy, follow [UPDATE.md](UPDATE.md).

Cloud Run: never set min instances to 1 or higher; keep scale-to-zero (see docs/deployment.md).
