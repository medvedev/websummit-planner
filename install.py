#!/usr/bin/env python3
"""Copy the self-contained skill into an agent's skills directory."""
import argparse
from pathlib import Path
import shutil
import sys


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument('--agent', choices=['codex', 'claude', 'gemini', 'both'])
    choice.add_argument('--dest', type=Path, help='exact destination skill folder for any compatible agent')
    p.add_argument('--scope', choices=['user', 'project'], default='user')
    p.add_argument('--project', type=Path, default=Path.cwd())
    a = p.parse_args()
    source = Path(__file__).resolve().parent / 'skills/websummit-planner'
    base = Path.home() if a.scope == 'user' else a.project.expanduser().resolve()
    if a.dest:
        destinations = [a.dest.expanduser().resolve()]
    else:
        agents = ['codex', 'claude'] if a.agent == 'both' else [a.agent]
        folders = {'codex': '.agents', 'claude': '.claude', 'gemini': '.gemini'}
        destinations = [base / folders[agent] / 'skills/websummit-planner' for agent in agents]
    for dest in destinations:
        if dest.exists() or dest.is_symlink():
            p.exit(1, f'Refusing to overwrite {dest}. Move the old skill aside, then retry. Personal state is stored separately.\n')
        if dest == source or source in dest.parents:
            p.exit(1, 'Destination must be outside the source skill.\n')
    for dest in destinations:
        shutil.copytree(source, dest, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        print(f'Installed {dest}')
    print('Use in your next turn; if your agent does not discover it, start a new session.')
    print('Ask: Use websummit-planner to find sessions relevant to my interests.')


if __name__ == '__main__':
    main()
