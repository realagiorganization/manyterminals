# Agent Instructions

## Scope

You are operating inside `/home/standart/manyterminals`.

## Rules

- Keep `install.md`, `readme.md`, and `AGENTS.md` present at the repo root.
- Run the local verification commands before commit:
  - `pytest -q`
  - `bash scripts/run-tests-in-docker.sh`
  - `python3 scripts/assert_close_empty_fixture.py tests/fixtures/live-wayland-unavailable.json tests/fixtures/live-wayland-process-tree.json`
  - `python3 scripts/manyterminals.py inspect --fixtures tests/fixtures/inspection.json`
  - `python3 scripts/manyterminals.py close-empty --dry-run --fixtures tests/fixtures/inspection.json`
  - `python3 scripts/manyterminals.py ensure-tmux --dry-run --state-file state/tmux-sessions.md`
- When creating or adopting a new local Git repository, initialize its GitHub remote in `realagiorganization` by default with `gh repo create`, set `origin`, and push after local verification passes.
