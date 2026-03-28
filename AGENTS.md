# Agent Instructions

## Scope

You are operating inside `/home/standart/manyterminals`.

## Rules

- Keep `install.md`, `readme.md`, and `AGENTS.md` present at the repo root.
- Run the local verification commands before commit:
  - `pytest -q`
  - `python3 scripts/manyterminals.py inspect --fixtures tests/fixtures/inspection.json`
  - `python3 scripts/manyterminals.py close-empty --dry-run --fixtures tests/fixtures/inspection.json`
  - `python3 scripts/manyterminals.py ensure-tmux --dry-run --state-file state/tmux-sessions.md`
- When creating or adopting a new local Git repository, initialize its GitHub remote in `realagiorganization` by default with `gh repo create`, set `origin`, and push after local verification passes.
