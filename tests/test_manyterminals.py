from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from manyterminals import commands as commands_module
from manyterminals import capture as capture_module
from manyterminals import system as system_module
from manyterminals.models import TabSnapshot, TerminalSnapshot


def test_load_plan_parses_markdown_table() -> None:
    rows = commands_module.load_plan(ROOT / "state" / "tmux-sessions.md")
    assert rows[0]["session"] == "ops"
    assert rows[1]["layout"] == "even-horizontal"


def test_is_effectively_empty_accepts_prompt_only_output() -> None:
    assert system_module.is_effectively_empty("$ ")
    assert system_module.is_effectively_empty("#")
    assert not system_module.is_effectively_empty("running build")


def test_remap_controlled_tabs_maps_child_pid_to_terminal_pid() -> None:
    tabs = {102: [TabSnapshot(title="demo", content="hello", source="kitty")]}
    terminals = [(100, "kitty")]
    parents = {102: 101, 101: 100, 100: 1}
    remapped = capture_module.remap_controlled_tabs(tabs, terminals, parents)
    assert 100 in remapped
    assert remapped[100][0].title == "demo"


def test_iter_terminal_processes_dedupes_nested_terminal_wrappers(monkeypatch) -> None:
    responses = {
        ("ps", "-eo", "pid=,comm="): subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="\n".join(
                [
                    "100 ghostty",
                    "101 ghostty",
                    "200 alacritty",
                    "",
                ]
            ),
            stderr="",
        )
    }

    monkeypatch.setattr(system_module, "run", lambda command, check=False: responses[tuple(command)])
    monkeypatch.setattr(system_module, "process_parents", lambda: {100: 1, 101: 100, 200: 1})

    assert system_module.iter_terminal_processes() == [(100, "ghostty"), (200, "alacritty")]


def test_x11_windows_uses_descendant_pid_search(monkeypatch) -> None:
    monkeypatch.setattr(system_module, "which", lambda name: None if name == "wmctrl" else "/usr/bin/xdotool")
    monkeypatch.setattr(system_module, "iter_terminal_processes", lambda: [(100, "ghostty")])
    monkeypatch.setattr(system_module, "process_parents", lambda: {100: 1, 101: 100})
    monkeypatch.setattr(system_module, "process_commands", lambda: {100: "ghostty", 101: "ghostty"})

    def fake_run(command, check=False):
        key = tuple(command)
        responses = {
            ("xdotool", "search", "--pid", "100", "--onlyvisible", ".*"): subprocess.CompletedProcess(command, 1, "", ""),
            ("xdotool", "search", "--pid", "101", "--onlyvisible", ".*"): subprocess.CompletedProcess(command, 0, "777\n", ""),
            ("xdotool", "getwindowname", "777"): subprocess.CompletedProcess(command, 0, "Ghostty Child\n", ""),
        }
        return responses[key]

    monkeypatch.setattr(system_module, "run", fake_run)

    windows = system_module.x11_windows()

    assert windows == {100: {"window_id": "777", "workspace": "", "title": "Ghostty Child"}}


def test_terminate_process_tree_escalates_to_sigkill(monkeypatch) -> None:
    sent: list[tuple[int, int]] = []
    existing = {10, 11}
    ticks = {"value": 0.0}

    monkeypatch.setattr(system_module, "process_parents", lambda: {10: 1, 11: 10})

    def fake_time() -> float:
        ticks["value"] += 0.25
        return ticks["value"]

    monkeypatch.setattr(
        system_module,
        "time",
        type("FakeTime", (), {"time": staticmethod(fake_time), "sleep": staticmethod(lambda _x: None)}),
    )

    def fake_pid_exists(pid: int) -> bool:
        return pid in existing

    def fake_kill(pid: int, sig: int) -> None:
        sent.append((pid, sig))
        if sig == system_module.signal.SIGKILL:
            existing.discard(pid)

    monkeypatch.setattr(system_module, "pid_exists", fake_pid_exists)
    monkeypatch.setattr(system_module.os, "kill", fake_kill)

    assert system_module.terminate_process_tree(10) is True
    assert sent == [
        (11, system_module.signal.SIGTERM),
        (10, system_module.signal.SIGTERM),
        (11, system_module.signal.SIGKILL),
        (10, system_module.signal.SIGKILL),
    ]


def test_close_snapshot_prefers_wmctrl_on_x11(monkeypatch) -> None:
    snapshot = TerminalSnapshot(
        emulator="ghostty",
        pid=101,
        title="Ghostty",
        window_id="0x1",
        tabs=[TabSnapshot(content="$ ", title="shell", source="fixture")],
        capture_method="fixture",
        capture_status="ok",
    )
    commands: list[tuple[str, ...]] = []

    def fake_run(command, check=False):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(system_module, "which", lambda name: f"/usr/bin/{name}" if name == "wmctrl" else None)
    monkeypatch.setattr(system_module, "run", fake_run)
    monkeypatch.setattr(system_module, "terminate_process_tree", lambda pid: False)

    assert system_module.close_snapshot(snapshot) is True
    assert commands == [("wmctrl", "-ic", "0x1")]


def test_close_snapshot_falls_back_to_xdotool_after_wmctrl_failure(monkeypatch) -> None:
    snapshot = TerminalSnapshot(
        emulator="kitty",
        pid=202,
        title="Kitty",
        window_id="0x2",
        tabs=[TabSnapshot(content="$ ", title="shell", source="fixture")],
        capture_method="fixture",
        capture_status="ok",
    )
    commands: list[tuple[str, ...]] = []

    def fake_run(command, check=False):
        commands.append(tuple(command))
        if tuple(command) == ("wmctrl", "-ic", "0x2"):
            return subprocess.CompletedProcess(command, 1, "", "failed")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(system_module, "which", lambda name: f"/usr/bin/{name}" if name in {"wmctrl", "xdotool"} else None)
    monkeypatch.setattr(system_module, "run", fake_run)
    monkeypatch.setattr(system_module, "terminate_process_tree", lambda pid: False)

    assert system_module.close_snapshot(snapshot) is True
    assert commands == [
        ("wmctrl", "-ic", "0x2"),
        ("xdotool", "windowclose", "0x2"),
    ]


def test_close_snapshot_falls_back_to_process_termination_when_window_close_unavailable(monkeypatch) -> None:
    snapshot = TerminalSnapshot(
        emulator="qmlkonsole",
        pid=303,
        title="Scratch",
        window_id="850",
        tabs=[TabSnapshot(content="", title="shell", source="fixture")],
        capture_method="fixture",
        capture_status="ok",
    )
    commands: list[tuple[str, ...]] = []

    def fake_run(command, check=False):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 1, "", "failed")

    monkeypatch.setattr(system_module, "which", lambda name: f"/usr/bin/{name}" if name in {"wmctrl", "xdotool"} else None)
    monkeypatch.setattr(system_module, "run", fake_run)
    monkeypatch.setattr(system_module, "terminate_process_tree", lambda pid: pid == 303)

    assert system_module.close_snapshot(snapshot) is True
    assert commands == [
        ("wmctrl", "-ic", "850"),
        ("xdotool", "windowclose", "850"),
    ]


def test_inspect_command_uses_fixture_and_writes_output(tmp_path, capsys) -> None:
    output_path = tmp_path / "inspection.json"
    args = argparse.Namespace(
        fixtures=str(ROOT / "tests" / "fixtures" / "inspection.json"),
        json=False,
        output=str(output_path),
    )
    result = commands_module.inspect_command(args)
    captured = capsys.readouterr().out
    assert result == 0
    assert "kitty pid=4242 tabs=2 capture=tmux status=ok empty=False" in captured
    assert "ghostty pid=5252 tabs=1 capture=screenshot+ocr status=ok empty=True" in captured
    assert output_path.exists()


def test_record_fixture_command_writes_live_snapshots(monkeypatch, tmp_path, capsys) -> None:
    output_path = tmp_path / "generated.json"
    snapshots = [
        TerminalSnapshot(
            emulator="ghostty",
            pid=101,
            title="Scratch",
            window_id="0x1",
            tabs=[TabSnapshot(content="$ ", title="shell", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        )
    ]
    monkeypatch.setattr(commands_module, "build_snapshots", lambda: snapshots)

    args = argparse.Namespace(output=str(output_path), force=False)
    result = commands_module.record_fixture_command(args)
    captured = capsys.readouterr()

    assert result == 0
    assert "Recorded 1 terminal snapshots" in captured.out
    payload = commands_module.json.loads(output_path.read_text(encoding="utf-8"))
    assert payload == commands_module.snapshots_payload(snapshots)


def test_record_fixture_command_requires_force_to_overwrite(tmp_path, capsys) -> None:
    output_path = tmp_path / "generated.json"
    output_path.write_text("[]\n", encoding="utf-8")

    args = argparse.Namespace(output=str(output_path), force=False)
    result = commands_module.record_fixture_command(args)
    captured = capsys.readouterr()

    assert result == 1
    assert "Use --force to overwrite it." in captured.err


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
        TerminalSnapshot(
            emulator="ghostty",
            pid=1,
            title="Ghostty 1",
            window_id="0x1",
            tabs=[TabSnapshot(content="$ ", title="one", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        ),
        TerminalSnapshot(
            emulator="kitty",
            pid=2,
            title="Kitty Busy",
            window_id="0x2",
            tabs=[TabSnapshot(content="running build", title="two", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        ),
        TerminalSnapshot(
            emulator="alacritty",
            pid=3,
            title="Alacritty 2",
            window_id="0x3",
            tabs=[TabSnapshot(content="#", title="three", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        ),
    ]
    monkeypatch.setattr(commands_module, "build_snapshots", lambda: snapshots)

    args = argparse.Namespace(state_file=str(state_file), dry_run=True)
    result = commands_module.ensure_tmux_command(args)
    captured = capsys.readouterr().out

    assert result == 0
    assert "ops -> would attach ghostty pid=1 window=0x1 title=Ghostty 1" in captured
    assert "logs -> would attach alacritty pid=3 window=0x3 title=Alacritty 2" in captured
    updated = state_file.read_text(encoding="utf-8")
    assert "- ops -> would attach ghostty pid=1 window=0x1 title=Ghostty 1" in updated


def test_select_close_candidates_skips_tmux_and_busy_snapshots() -> None:
    snapshots = [
        TerminalSnapshot(
            emulator="ghostty",
            pid=1,
            title="Ghostty Empty",
            window_id="0x1",
            tabs=[TabSnapshot(content="$ ", title="one", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        ),
        TerminalSnapshot(
            emulator="kitty",
            pid=2,
            title="Kitty Tmux",
            window_id="0x2",
            tabs=[TabSnapshot(content="$ ", title="two", source="fixture")],
            capture_method="tmux",
            capture_status="ok",
            tmux_session="ops",
        ),
        TerminalSnapshot(
            emulator="alacritty",
            pid=3,
            title="Alacritty Busy",
            window_id="0x3",
            tabs=[TabSnapshot(content="running build", title="three", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        ),
        TerminalSnapshot(
            emulator="wezterm",
            pid=4,
            title="WezTerm Unknown",
            window_id="0x4",
            tabs=[TabSnapshot(content="", title="four", source="fixture")],
            capture_method="fixture",
            capture_status="partial",
        ),
    ]

    candidates = commands_module.select_close_candidates(snapshots)

    assert [snapshot.pid for snapshot in candidates] == [1]


def test_close_empty_dry_run_uses_fixture(capsys) -> None:
    args = argparse.Namespace(
        dry_run=True,
        fixtures=str(ROOT / "tests" / "fixtures" / "inspection.json"),
    )

    result = commands_module.close_empty_command(args)
    captured = capsys.readouterr()

    assert result == 0
    assert "would close ghostty pid=5252 window=0x01000002 title=Ghostty Scratch" in captured.out
    assert captured.err == ""


def test_select_close_candidates_live_wayland_fixture_uses_process_fallback(monkeypatch) -> None:
    payload = (ROOT / "tests" / "fixtures" / "live-wayland-unavailable.json").read_text(encoding="utf-8")
    snapshots = [TerminalSnapshot.from_dict(item) for item in commands_module.json.loads(payload)]

    parents = {
        2073: 1,
        58097: 2073,
        59155: 58097,
        348869: 1,
        348889: 348869,
        350889: 348869,
        944645: 1,
        945427: 944645,
        955961: 1,
        958316: 955961,
        1067483: 1,
        1067497: 1067483,
        1220861: 1067497,
    }
    commands = {
        58097: "zsh",
        59155: "node-MainThread",
        348889: "zsh",
        350889: "zsh",
        945427: "zsh",
        958316: "zsh",
        1067497: "zsh",
        1220861: "node-MainThread",
    }

    monkeypatch.setattr(commands_module, "process_parents", lambda: parents)
    monkeypatch.setattr(commands_module, "process_commands", lambda: commands)

    candidates = commands_module.select_close_candidates(snapshots)

    assert [snapshot.pid for snapshot in candidates] == [
        944645,
        955961,
    ]
