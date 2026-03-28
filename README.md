# manyterminals

`manyterminals` is a Codex skill repository for coordinating lots of terminal emulator windows on Linux. It inventories running terminals, tries emulator-specific or OCR-based content capture, keeps tmux assignment intent in Markdown, and can publish the repo with `gh`.

## Status

![CI](https://github.com/realagiorganization/manyterminals/actions/workflows/ci.yml/badge.svg)

## Terminal Demo

The repository includes a recorded terminal-UI run generated from a stable fixture and re-rendered in GitHub Actions.

![Terminal UI demo](docs/ui-demo.gif)

## Local Development

```bash
pytest -q
python3 scripts/manyterminals.py inspect --fixtures tests/fixtures/inspection.json
python3 scripts/manyterminals.py ensure-tmux --dry-run --state-file state/tmux-sessions.md
```

## GitHub Actions

The CI workflow does two things on every push and pull request:

- runs the pytest suite
- renders the terminal UI demo from `demos/ui-demo.tape` and uploads the SVG as a workflow artifact

## Repo Layout

- `SKILL.md`: skill instructions for Codex
- `scripts/manyterminals.py`: main CLI
- `state/tmux-sessions.md`: Markdown plan for tmux sessions
- `tests/`: unit and CLI coverage
- `demos/ui-demo.tape`: recorded terminal UI scenario
- `docs/ui-demo.gif`: checked-in render used by the README
