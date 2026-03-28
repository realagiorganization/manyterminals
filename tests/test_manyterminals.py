from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "manyterminals.py"
SPEC = importlib.util.spec_from_file_location("manyterminals", MODULE_PATH)
assert SPEC and SPEC.loader
manyterminals = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = manyterminals
SPEC.loader.exec_module(manyterminals)


def test_load_plan_parses_markdown_table() -> None:
    rows = manyterminals.load_plan(ROOT / "state" / "tmux-sessions.md")
    assert rows[0]["session"] == "ops"
    assert rows[1]["layout"] == "even-horizontal"


def test_is_effectively_empty_accepts_prompt_only_output() -> None:
    assert manyterminals.is_effectively_empty("$ ")
    assert manyterminals.is_effectively_empty("#")
    assert not manyterminals.is_effectively_empty("running build")


def test_remap_controlled_tabs_maps_child_pid_to_terminal_pid() -> None:
    tabs = {102: [manyterminals.TabSnapshot(title="demo", content="hello", source="kitty")]}
    terminals = [(100, "kitty")]
    parents = {102: 101, 101: 100, 100: 1}
    remapped = manyterminals.remap_controlled_tabs(tabs, terminals, parents)
    assert 100 in remapped
    assert remapped[100][0].title == "demo"


def test_inspect_command_uses_fixture_and_writes_output(tmp_path, capsys) -> None:
    output_path = tmp_path / "inspection.json"
    args = argparse.Namespace(
        fixtures=str(ROOT / "tests" / "fixtures" / "inspection.json"),
        json=False,
        output=str(output_path),
    )
    result = manyterminals.inspect_command(args)
    captured = capsys.readouterr().out
    assert result == 0
    assert "kitty pid=4242 tabs=2 capture=tmux status=ok empty=False" in captured
    assert "ghostty pid=5252 tabs=1 capture=screenshot+ocr status=ok empty=True" in captured
    assert output_path.exists()


def test_ensure_tmux_dry_run_assigns_empty_terminals(monkeypatch, tmp_path, capsys) -> None:
    state_file = tmp_path / "tmux-sessions.md"
    state_file.write_text(
        "\n".join(
            [
                "# Tmux Sessions",
                "",
                "| target | session | layout | cwd | command | notes |",
                "| --- | --- | --- | --- | --- | --- |",
                "| any-empty | ops | tiled | ~ |  | demo |",
                "| any-empty | logs | even-horizontal | ~ |  | demo |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    snapshots = [
        manyterminals.TerminalSnapshot(
            emulator="ghostty",
            pid=1,
            title="Ghostty 1",
            window_id="0x1",
            tabs=[manyterminals.TabSnapshot(content="$ ", title="one", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        ),
        manyterminals.TerminalSnapshot(
            emulator="kitty",
            pid=2,
            title="Kitty Busy",
            window_id="0x2",
            tabs=[manyterminals.TabSnapshot(content="running build", title="two", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        ),
        manyterminals.TerminalSnapshot(
            emulator="alacritty",
            pid=3,
            title="Alacritty 2",
            window_id="0x3",
            tabs=[manyterminals.TabSnapshot(content="#", title="three", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        ),
    ]
    monkeypatch.setattr(manyterminals, "build_snapshots", lambda: snapshots)

    args = argparse.Namespace(state_file=str(state_file), dry_run=True)
    result = manyterminals.ensure_tmux_command(args)
    captured = capsys.readouterr().out

    assert result == 0
    assert "ops -> would attach ghostty pid=1 window=0x1 title=Ghostty 1" in captured
    assert "logs -> would attach alacritty pid=3 window=0x3 title=Alacritty 2" in captured
    updated = state_file.read_text(encoding="utf-8")
    assert "- ops -> would attach ghostty pid=1 window=0x1 title=Ghostty 1" in updated


def test_select_close_candidates_skips_tmux_and_busy_snapshots() -> None:
    snapshots = [
        manyterminals.TerminalSnapshot(
            emulator="ghostty",
            pid=1,
            title="Ghostty Empty",
            window_id="0x1",
            tabs=[manyterminals.TabSnapshot(content="$ ", title="one", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        ),
        manyterminals.TerminalSnapshot(
            emulator="kitty",
            pid=2,
            title="Kitty Tmux",
            window_id="0x2",
            tabs=[manyterminals.TabSnapshot(content="$ ", title="two", source="fixture")],
            capture_method="tmux",
            capture_status="ok",
            tmux_session="ops",
        ),
        manyterminals.TerminalSnapshot(
            emulator="alacritty",
            pid=3,
            title="Alacritty Busy",
            window_id="0x3",
            tabs=[manyterminals.TabSnapshot(content="running build", title="three", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        ),
        manyterminals.TerminalSnapshot(
            emulator="wezterm",
            pid=4,
            title="WezTerm Unknown",
            window_id="0x4",
            tabs=[manyterminals.TabSnapshot(content="", title="four", source="fixture")],
            capture_method="fixture",
            capture_status="unavailable",
        ),
    ]

    candidates = manyterminals.select_close_candidates(snapshots)

    assert [snapshot.pid for snapshot in candidates] == [1]


def test_close_empty_dry_run_uses_fixture(capsys) -> None:
    args = argparse.Namespace(
        dry_run=True,
        fixtures=str(ROOT / "tests" / "fixtures" / "inspection.json"),
    )

    result = manyterminals.close_empty_command(args)
    captured = capsys.readouterr()

    assert result == 0
    assert "would close ghostty pid=5252 window=0x01000002 title=Ghostty Scratch" in captured.out
    assert captured.err == ""
