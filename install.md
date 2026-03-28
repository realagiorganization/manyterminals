# manyterminals install

```bash
python3 -m pip install pytest
pytest -q
python3 scripts/manyterminals.py inspect --fixtures tests/fixtures/inspection.json
python3 scripts/manyterminals.py close-empty --dry-run --fixtures tests/fixtures/inspection.json
python3 scripts/manyterminals.py ensure-tmux --dry-run --state-file state/tmux-sessions.md
```
