from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "manyterminals.py"
SPEC = importlib.util.spec_from_file_location("manyterminals_tmux", MODULE_PATH)
assert SPEC and SPEC.loader
manyterminals = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = manyterminals
SPEC.loader.exec_module(manyterminals)


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
        manyterminals.create_tmux_session(manyterminals.load_plan(state_file)[0])
        tabs = manyterminals.tmux_capture("integ")
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
        manyterminals.TerminalSnapshot(
            emulator="ghostty",
            pid=10,
            title="Scratch",
            window_id="0x44",
            tabs=[manyterminals.TabSnapshot(content="$ ", title="one", source="fixture")],
            capture_method="fixture",
            capture_status="ok",
        )
    ]
    monkeypatch.setattr(manyterminals, "build_snapshots", lambda: snapshots)

    try:
        result = manyterminals.ensure_tmux_command(
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
