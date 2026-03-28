from __future__ import annotations

import os
import shlex
import subprocess

from .models import TabSnapshot
from .system import run, which


def tmux_base_command() -> list[str]:
    command = ["tmux"]
    socket_name = os.environ.get("MANYTERMINALS_TMUX_SOCKET")
    if socket_name:
        command.extend(["-L", socket_name])
    socket_path = os.environ.get("MANYTERMINALS_TMUX_SOCKET_PATH")
    if socket_path:
        command.extend(["-S", socket_path])
    return command


def run_tmux(args: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return run(tmux_base_command() + args, check=check)


def detect_tmux_for_pid(pid: int) -> str | None:
    environ_path = f"/proc/{pid}/environ"
    try:
        with open(environ_path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    for entry in raw.split(b"\0"):
        if entry.startswith(b"TMUX="):
            return entry.decode("utf-8", errors="ignore").split("=", 1)[1]
    return None


def discover_tmux_session_from_env(tmux_env: str | None) -> str | None:
    if not tmux_env:
        return None
    try:
        display = run_tmux(["display-message", "-p", "-F", "#{session_name}"], check=True)
    except subprocess.CalledProcessError:
        return None
    session = display.stdout.strip()
    return session or None


def tmux_capture(session: str, strip_ansi) -> list[TabSnapshot]:
    fmt = "#{session_name}\t#{window_index}\t#{window_name}\t#{pane_id}\t#{pane_active}"
    try:
        windows = run_tmux(["list-windows", "-t", session, "-F", fmt], check=True)
    except subprocess.CalledProcessError:
        return []
    tabs: list[TabSnapshot] = []
    for line in windows.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        session_name, window_index, window_name, pane_id, _pane_active = parts
        try:
            capture = run_tmux(["capture-pane", "-p", "-t", pane_id], check=True)
            content = strip_ansi(capture.stdout)
        except subprocess.CalledProcessError:
            content = None
        tabs.append(
            TabSnapshot(
                title=f"{session_name}:{window_index}:{window_name}",
                content=content,
                source="tmux",
                pane_id=pane_id,
            )
        )
    return tabs


def create_tmux_session(row: dict[str, str]) -> None:
    session = row.get("session", "").strip()
    if not session:
        return
    has = run_tmux(["has-session", "-t", session])
    if has.returncode != 0:
        command = ["new-session", "-d", "-s", session]
        cwd = row.get("cwd", "").strip()
        if cwd:
            command.extend(["-c", os.path.expanduser(cwd)])
        run_tmux(command, check=True)
    layout = row.get("layout", "").strip()
    if layout:
        run_tmux(["select-layout", "-t", session, layout], check=False)
    startup = row.get("command", "").strip()
    if startup:
        run_tmux(["send-keys", "-t", session, startup, "C-m"], check=False)


def attach_tmux(window_id: str, session: str) -> bool:
    if not which("xdotool"):
        return False
    command = " ".join(shlex.quote(part) for part in tmux_base_command() + ["new-session", "-A", "-s", session])
    steps = [
        ["xdotool", "windowactivate", "--sync", window_id],
        ["xdotool", "type", "--delay", "1", command],
        ["xdotool", "key", "Return"],
    ]
    for step in steps:
        if run(step).returncode != 0:
            return False
    return True
