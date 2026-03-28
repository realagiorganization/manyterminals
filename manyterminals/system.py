from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .models import TerminalSnapshot


KNOWN_TERMINALS = {
    "alacritty",
    "foot",
    "ghostty",
    "gnome-console",
    "gnome-terminal",
    "kgx",
    "kitty",
    "konsole",
    "mate-terminal",
    "ptyxis",
    "qmlkonsole",
    "qterminal",
    "rio",
    "terminator",
    "tilix",
    "wezterm",
    "xfce4-terminal",
    "xterm",
    "yakuake",
}

SHELL_COMMANDS = {"bash", "fish", "zsh"}
TERMINAL_HELPERS = {"ghostty", "kitten", "ptyxis-agent", "sh"}

EMPTY_OUTPUT_RE = re.compile(r"^[\s$#>%~]*(?:\[[^\]]+\])?[\s$#>%~]*$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def run(command: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=check)


def which(name: str) -> str | None:
    return shutil.which(name)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "")


def is_effectively_empty(text: str) -> bool:
    cleaned = strip_ansi(text).strip()
    if not cleaned:
        return True
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return True
    return all(EMPTY_OUTPUT_RE.match(line) for line in lines)


def process_parents() -> dict[int, int]:
    ps = run(["ps", "-eo", "pid=,ppid="], check=True)
    mapping: dict[int, int] = {}
    for line in ps.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_str, ppid_str = line.split(maxsplit=1)
        mapping[int(pid_str)] = int(ppid_str)
    return mapping


def process_commands() -> dict[int, str]:
    ps = run(["ps", "-eo", "pid=,comm="], check=True)
    mapping: dict[int, str] = {}
    for line in ps.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_str, comm = line.split(maxsplit=1)
        mapping[int(pid_str)] = Path(comm).name
    return mapping


def is_descendant(pid: int, ancestor: int, parents: dict[int, int]) -> bool:
    current = pid
    seen: set[int] = set()
    while current > 1 and current not in seen:
        if current == ancestor:
            return True
        seen.add(current)
        current = parents.get(current, 1)
    return current == ancestor


def descendants_by_pid(parents: dict[int, int]) -> dict[int, list[int]]:
    children: dict[int, list[int]] = {}
    for pid, ppid in parents.items():
        children.setdefault(ppid, []).append(pid)
    return children


def descendant_processes(pid: int, children: dict[int, list[int]]) -> list[int]:
    found: list[int] = []
    stack = list(children.get(pid, []))
    while stack:
        current = stack.pop()
        found.append(current)
        stack.extend(children.get(current, []))
    return found


def has_active_descendants(snapshot: TerminalSnapshot, children: dict[int, list[int]], commands: dict[int, str]) -> bool:
    descendants = descendant_processes(snapshot.pid, children)
    shell_count = 0
    for pid in descendants:
        command = commands.get(pid, "")
        if not command:
            continue
        if command in SHELL_COMMANDS:
            shell_count += 1
            continue
        if command in TERMINAL_HELPERS:
            continue
        return True
    return shell_count > 1


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_process_tree(root_pid: int, grace_seconds: float = 0.4) -> bool:
    parents = process_parents()
    children = descendants_by_pid(parents)
    ordered = [pid for pid in descendant_processes(root_pid, children) if pid_exists(pid)]
    ordered.reverse()
    ordered.append(root_pid)
    for pid in ordered:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        if not any(pid_exists(pid) for pid in ordered):
            return True
        time.sleep(0.05)
    for pid in ordered:
        if not pid_exists(pid):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    time.sleep(0.05)
    return not any(pid_exists(pid) for pid in ordered)


def iter_terminal_processes() -> list[tuple[int, str]]:
    ps = run(["ps", "-eo", "pid=,comm="], check=True)
    terminals: list[tuple[int, str]] = []
    for line in ps.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_str, comm = line.split(maxsplit=1)
        name = Path(comm).name
        if name in KNOWN_TERMINALS:
            terminals.append((int(pid_str), name))
    parents = process_parents()
    terminal_ids = {pid for pid, _name in terminals}
    deduped: list[tuple[int, str]] = []
    for pid, name in terminals:
        current = parents.get(pid, 1)
        nested = False
        while current > 1:
            if current in terminal_ids:
                nested = True
                break
            current = parents.get(current, 1)
        if not nested:
            deduped.append((pid, name))
    return deduped


def x11_windows() -> dict[int, dict[str, str]]:
    windows: dict[int, dict[str, str]] = {}
    if which("wmctrl"):
        try:
            result = run(["wmctrl", "-lpG"], check=True)
        except subprocess.CalledProcessError:
            result = None
        if result:
            for line in result.stdout.splitlines():
                parts = line.split(None, 8)
                if len(parts) < 9:
                    continue
                window_id, workspace, pid_str = parts[0], parts[1], parts[2]
                title = parts[8]
                try:
                    pid = int(pid_str)
                except ValueError:
                    continue
                windows[pid] = {"window_id": window_id, "workspace": workspace, "title": title}
    if windows or not which("xdotool"):
        return windows
    parents = process_parents()
    children = descendants_by_pid(parents)
    commands = process_commands()
    for pid, _emulator in iter_terminal_processes():
        search_pids = [pid] + descendant_processes(pid, children)
        for candidate_pid in search_pids:
            command = commands.get(candidate_pid, "")
            if candidate_pid != pid and command in SHELL_COMMANDS:
                continue
            result = run(["xdotool", "search", "--pid", str(candidate_pid), "--onlyvisible", ".*"])
            if result.returncode != 0:
                continue
            window_id = next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)
            if not window_id:
                continue
            title_result = run(["xdotool", "getwindowname", window_id])
            title = title_result.stdout.strip() if title_result.returncode == 0 else ""
            windows[pid] = {"window_id": window_id, "workspace": "", "title": title}
            break
    return windows


def close_snapshot(snapshot: TerminalSnapshot) -> bool:
    if snapshot.capture_status == "unavailable":
        return terminate_process_tree(snapshot.pid)
    if snapshot.window_id and which("wmctrl"):
        if run(["wmctrl", "-ic", snapshot.window_id]).returncode == 0:
            return True
    if snapshot.window_id and which("xdotool"):
        if run(["xdotool", "windowclose", snapshot.window_id]).returncode == 0:
            return True
    try:
        return terminate_process_tree(snapshot.pid)
    except OSError:
        return False


def tmux_shell_command(session: str, tmux_base_command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in tmux_base_command + ["new-session", "-A", "-s", session])
