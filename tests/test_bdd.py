from __future__ import annotations

from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from manyterminals import commands as commands_module
from manyterminals.models import TerminalSnapshot


ROOT = Path(__file__).resolve().parents[1]

scenarios("features/close_empty.feature")


def _pairs(text: str) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for item in text.split(","):
        emulator, pid = item.split(":", 1)
        rows.append((emulator.strip(), int(pid.strip())))
    return rows


def _load_process_tree_fixture() -> dict[str, object]:
    return commands_module.json.loads(
        (ROOT / "tests" / "fixtures" / "live-wayland-process-tree.json").read_text(encoding="utf-8")
    )


@given("the live Wayland fallback fixture", target_fixture="wayland_fixture")
def live_wayland_fixture() -> list[TerminalSnapshot]:
    payload = (ROOT / "tests" / "fixtures" / "live-wayland-unavailable.json").read_text(encoding="utf-8")
    return [TerminalSnapshot.from_dict(item) for item in commands_module.json.loads(payload)]


@when("I select close-empty candidates from that fixture", target_fixture="selected_candidates")
def select_candidates(monkeypatch, wayland_fixture: list[TerminalSnapshot]) -> list[TerminalSnapshot]:
    process_tree = _load_process_tree_fixture()
    parents = {int(pid): int(ppid) for pid, ppid in process_tree["parents"].items()}
    commands = {int(pid): str(command) for pid, command in process_tree["commands"].items()}
    monkeypatch.setattr(commands_module, "process_parents", lambda: parents)
    monkeypatch.setattr(commands_module, "process_commands", lambda: commands)
    return commands_module.select_close_candidates(wayland_fixture)


@then(parsers.parse('the close candidates should equal "{pairs}"'))
def close_candidates_should_match(selected_candidates: list[TerminalSnapshot], pairs: str) -> None:
    assert [(snapshot.emulator, snapshot.pid) for snapshot in selected_candidates] == _pairs(pairs)


@then(parsers.parse('the protected terminals should equal "{pairs}"'))
def protected_terminals_should_be_excluded(
    wayland_fixture: list[TerminalSnapshot],
    selected_candidates: list[TerminalSnapshot],
    pairs: str,
) -> None:
    selected = {(snapshot.emulator, snapshot.pid) for snapshot in selected_candidates}
    all_rows = {(snapshot.emulator, snapshot.pid) for snapshot in wayland_fixture}
    for row in _pairs(pairs):
        assert row in all_rows
        assert row not in selected
