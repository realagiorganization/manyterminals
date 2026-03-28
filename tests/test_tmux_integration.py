from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from manyterminals import commands as commands_module
from manyterminals import tmux_ops as tmux_module
from manyterminals.models import TabSnapshot, TerminalSnapshot


def tmux_available() -> bool:
    return subprocess.run(["tmux", "-V"], capture_output=True, text=True, check=False).returncode == 0


def test_create_tmux_session_and_capture(monkeypatch, tmp_path) -> None:
    if not tmux_available():
        raise SystemExit("tmux is required for this integration test")

    socket_name = f"manyterminals-test-{os.getpid()}"
    monkeypatch.setenv("MANYTERMINALS_TMUX_SOCKET", socket_name)

    state_file = tmp_path / "tmux-sessions.md"
    state_file.write_text(
        "\n".join(
            [
                "# Tmux Sessions",
                "",
                "| target | session | layout | cwd | command | notes |",
                "| --- | --- | --- | --- | --- | --- |",
                f"| any-empty | integ | tiled | {tmp_path} | printf 'hello from tmux' | integration |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        tmux_module.create_tmux_session(commands_module.load_plan(state_file)[0])
        tabs = tmux_module.tmux_capture("integ", commands_module.strip_ansi)
        joined = "\n".join(tab.content or "" for tab in tabs)
        assert tabs
        assert "hello from tmux" in joined
    finally:
        subprocess.run(["tmux", "-L", socket_name, "kill-server"], capture_output=True, text=True, check=False)


def test_ensure_tmux_dry_run_uses_private_socket(monkeypatch, tmp_path, capsys) -> None:
    if not tmux_available():
        raise SystemExit("tmux is required for this integration test")

    socket_name = f"manyterminals-test-{os.getpid()}-dry"
    monkeypatch.setenv("MANYTERMINALS_TMUX_SOCKET", socket_name)

    state_file = tmp_path / "tmux-sessions.md"
    state_file.write_text(
        "\n".join(
            [
                "# Tmux Sessions",
                "",
                "| target | session | layout | cwd | command | notes |",
                "| --- | --- | --- | --- | --- | --- |",
                f"| any-empty | dryrun | even-horizontal | {tmp_path} |  | integration |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    snapshots = [
        TerminalSnapshot(
            emulator="ghostty",
            pid=10,
            title="Scratch",
            window_id="0x44",
            tabs=[TabSnapshot(content="$ ", title="one", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        )
    ]
    monkeypatch.setattr(commands_module, "build_snapshots", lambda: snapshots)

    try:
        result = commands_module.ensure_tmux_command(
            argparse.Namespace(state_file=str(state_file), dry_run=True)
        )
        captured = capsys.readouterr()
        assert result == 0
        assert "dryrun -> would attach ghostty pid=10 window=0x44 title=Scratch" in captured.out
        has_session = subprocess.run(
            ["tmux", "-L", socket_name, "has-session", "-t", "dryrun"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert has_session.returncode != 0
    finally:
        subprocess.run(["tmux", "-L", socket_name, "kill-server"], capture_output=True, text=True, check=False)
