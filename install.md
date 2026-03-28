# manyterminals install

```bash
python3 -m venv .venv-test
. .venv-test/bin/activate
python -m pip install -r requirements-test.txt
pytest -q
bash scripts/run-tests-in-docker.sh
python3 scripts/manyterminals.py inspect --fixtures tests/fixtures/inspection.json
python3 scripts/manyterminals.py close-empty --dry-run --fixtures tests/fixtures/inspection.json
python3 scripts/manyterminals.py ensure-tmux --dry-run --state-file state/tmux-sessions.md
```
