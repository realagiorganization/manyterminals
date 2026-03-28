from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "scripts/manyterminals.py", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_help_exits_successfully() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    assert "ensure-tmux" in result.stdout
    assert "close-empty" in result.stdout


def test_plan_outputs_json() -> None:
    result = run_cli("plan", "--state-file", "state/tmux-sessions.md")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload[0]["session"] == "ops"


def test_inspect_fixture_json_output() -> None:
    result = run_cli("inspect", "--json", "--fixtures", "tests/fixtures/inspection.json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload[0]["tab_count"] == 2
    assert payload[1]["effectively_empty"] is True


def test_close_empty_dry_run_fixture_output() -> None:
    result = run_cli("close-empty", "--dry-run", "--fixtures", "tests/fixtures/inspection.json")
    assert result.returncode == 0
    assert "would close ghostty pid=5252 window=0x01000002 title=Ghostty Scratch" in result.stdout


def test_close_empty_dry_run_live_wayland_fixture_finds_qmlkonsole_and_yakuake() -> None:
    result = run_cli("close-empty", "--dry-run", "--fixtures", "tests/fixtures/live-wayland-unavailable.json")
    assert result.returncode == 0
    assert "would close qmlkonsole pid=944645 window=850 title=-" in result.stdout
    assert "would close yakuake pid=955961 window=850 title=-" in result.stdout
