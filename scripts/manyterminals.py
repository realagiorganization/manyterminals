#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


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


@dataclass
class TabSnapshot:
    title: str | None = None
    content: str | None = None
    source: str | None = None
    pane_id: str | None = None


@dataclass
class TerminalSnapshot:
    emulator: str
    pid: int
    title: str | None = None
    window_id: str | None = None
    workspace: str | None = None
    tabs: list[TabSnapshot] = field(default_factory=list)
    capture_method: str | None = None
    capture_status: str = "unavailable"
    screenshot_path: str | None = None
    ocr_text: str | None = None
    tmux_session: str | None = None

    @property
    def aggregated_text(self) -> str:
        parts = []
        for tab in self.tabs:
            if tab.content:
                parts.append(tab.content)
        if self.ocr_text:
            parts.append(self.ocr_text)
        return "\n".join(part for part in parts if part).strip()

    @property
    def tab_count(self) -> int:
        return max(len(self.tabs), 1 if (self.title or self.window_id) else 0)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TerminalSnapshot":
        tabs = [TabSnapshot(**tab) for tab in payload.get("tabs", [])]
        known_fields = {
            "emulator": payload["emulator"],
            "pid": int(payload["pid"]),
            "title": payload.get("title"),
            "window_id": payload.get("window_id"),
            "workspace": payload.get("workspace"),
            "tabs": tabs,
            "capture_method": payload.get("capture_method"),
            "capture_status": payload.get("capture_status", "unavailable"),
            "screenshot_path": payload.get("screenshot_path"),
            "ocr_text": payload.get("ocr_text"),
            "tmux_session": payload.get("tmux_session"),
        }
        return cls(**known_fields)


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
    for pid, _emulator in iter_terminal_processes():
        result = run(["xdotool", "search", "--pid", str(pid), "--onlyvisible", ".*"])
        if result.returncode != 0:
            continue
        window_id = next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)
        if not window_id:
            continue
        title_result = run(["xdotool", "getwindowname", window_id])
        title = title_result.stdout.strip() if title_result.returncode == 0 else ""
        windows[pid] = {"window_id": window_id, "workspace": "", "title": title}
    return windows


def detect_tmux_for_pid(pid: int) -> str | None:
    environ_path = Path(f"/proc/{pid}/environ")
    try:
        raw = environ_path.read_bytes()
    except OSError:
        return None
    for entry in raw.split(b"\0"):
        if entry.startswith(b"TMUX="):
            return entry.decode("utf-8", errors="ignore").split("=", 1)[1]
    return None


def tmux_capture(session: str) -> list[TabSnapshot]:
    fmt = "#{session_name}\t#{window_index}\t#{window_name}\t#{pane_id}\t#{pane_active}"
    try:
        windows = run(["tmux", "list-windows", "-t", session, "-F", fmt], check=True)
    except subprocess.CalledProcessError:
        return []
    tabs: list[TabSnapshot] = []
    for line in windows.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        session_name, window_index, window_name, pane_id, _pane_active = parts
        try:
            capture = run(["tmux", "capture-pane", "-p", "-t", pane_id], check=True)
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


def discover_tmux_session_from_env(tmux_env: str | None) -> str | None:
    if not tmux_env:
        return None
    try:
        display = run(["tmux", "display-message", "-p", "-F", "#{session_name}"], check=True)
    except subprocess.CalledProcessError:
        return None
    session = display.stdout.strip()
    return session or None


def kitty_tabs() -> dict[int, list[TabSnapshot]]:
    if not which("kitty"):
        return {}
    try:
        result = run(["kitty", "@", "ls"], check=True)
    except subprocess.CalledProcessError:
        return {}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    by_pid: dict[int, list[TabSnapshot]] = {}
    for os_window in payload:
        tabs: list[TabSnapshot] = []
        for tab in os_window.get("tabs", []):
            tab_title = tab.get("title")
            for window in tab.get("windows", []):
                child_pid = window.get("child", {}).get("pid")
                if not child_pid:
                    continue
                try:
                    text_result = run(
                        ["kitty", "@", "get-text", f"--match=id:{window['id']}"],
                        check=True,
                    )
                    content = strip_ansi(text_result.stdout)
                except subprocess.CalledProcessError:
                    content = None
                tabs.append(
                    TabSnapshot(
                        title=tab_title,
                        content=content,
                        source="kitty",
                        pane_id=str(window.get("id")),
                    )
                )
                by_pid.setdefault(int(child_pid), []).append(tabs[-1])
    return by_pid


def wezterm_tabs() -> dict[int, list[TabSnapshot]]:
    if not which("wezterm"):
        return {}
    try:
        result = run(["wezterm", "cli", "list", "--format", "json"], check=True)
    except subprocess.CalledProcessError:
        return {}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    by_pid: dict[int, list[TabSnapshot]] = {}
    for pane in payload:
        pane_id = pane.get("pane_id")
        title = pane.get("title")
        pid = pane.get("pid")
        if not pane_id or not pid:
            continue
        try:
            text_result = run(["wezterm", "cli", "get-text", "--pane-id", str(pane_id)], check=True)
            content = strip_ansi(text_result.stdout)
        except subprocess.CalledProcessError:
            content = None
        by_pid.setdefault(int(pid), []).append(
            TabSnapshot(title=title, content=content, source="wezterm", pane_id=str(pane_id))
        )
    return by_pid


def remap_controlled_tabs(
    controlled: dict[int, list[TabSnapshot]],
    terminals: list[tuple[int, str]],
    parents: dict[int, int],
) -> dict[int, list[TabSnapshot]]:
    remapped: dict[int, list[TabSnapshot]] = {}
    for child_pid, tabs in controlled.items():
        for terminal_pid, _emulator in terminals:
            if is_descendant(child_pid, terminal_pid, parents):
                remapped.setdefault(terminal_pid, []).extend(tabs)
                break
    return remapped


def screenshot_window(window_id: str) -> str | None:
    tmpdir = tempfile.mkdtemp(prefix="manyterminals-")
    target = Path(tmpdir) / "window.png"
    if which("import"):
        result = run(["import", "-window", window_id, str(target)])
        if result.returncode == 0 and target.exists():
            return str(target)
    if which("gnome-screenshot"):
        result = run(["gnome-screenshot", "-w", "-f", str(target)])
        if result.returncode == 0 and target.exists():
            return str(target)
    if which("grim") and os.environ.get("WAYLAND_DISPLAY"):
        result = run(["grim", str(target)])
        if result.returncode == 0 and target.exists():
            return str(target)
    return None


def ocr_image(path: str) -> str | None:
    if not which("tesseract"):
        return None
    output_base = Path(path).with_suffix("")
    result = run(["tesseract", path, str(output_base)], check=False)
    txt_path = output_base.with_suffix(".txt")
    if result.returncode != 0 or not txt_path.exists():
        return None
    try:
        return txt_path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return None


def build_snapshots() -> list[TerminalSnapshot]:
    terminals = iter_terminal_processes()
    parents = process_parents()
    windows = x11_windows()
    kitty = remap_controlled_tabs(kitty_tabs(), terminals, parents)
    wezterm = remap_controlled_tabs(wezterm_tabs(), terminals, parents)
    snapshots: list[TerminalSnapshot] = []
    for pid, emulator in terminals:
        meta = windows.get(pid, {})
        snapshot = TerminalSnapshot(
            emulator=emulator,
            pid=pid,
            title=meta.get("title"),
            window_id=meta.get("window_id"),
            workspace=meta.get("workspace"),
        )
        tmux_env = detect_tmux_for_pid(pid)
        if tmux_env:
            session = discover_tmux_session_from_env(tmux_env)
            snapshot.tmux_session = session
            if session:
                snapshot.tabs = tmux_capture(session)
                if snapshot.tabs:
                    snapshot.capture_method = "tmux"
                    snapshot.capture_status = "ok"
                    snapshots.append(snapshot)
                    continue
        if pid in kitty:
            snapshot.tabs = kitty[pid]
            snapshot.capture_method = "kitty"
            snapshot.capture_status = "ok"
            snapshots.append(snapshot)
            continue
        if pid in wezterm:
            snapshot.tabs = wezterm[pid]
            snapshot.capture_method = "wezterm"
            snapshot.capture_status = "ok"
            snapshots.append(snapshot)
            continue
        if snapshot.window_id:
            image_path = screenshot_window(snapshot.window_id)
            if image_path:
                snapshot.screenshot_path = image_path
                snapshot.capture_method = "screenshot"
                snapshot.capture_status = "partial"
                snapshot.ocr_text = ocr_image(image_path)
                if snapshot.ocr_text:
                    snapshot.capture_method = "screenshot+ocr"
                    snapshot.capture_status = "ok"
        if not snapshot.tabs:
            snapshot.tabs.append(TabSnapshot(title=snapshot.title, content=snapshot.ocr_text, source=snapshot.capture_method))
        snapshots.append(snapshot)
    return snapshots


def load_snapshot_fixture(path: Path) -> list[TerminalSnapshot]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [TerminalSnapshot.from_dict(item) for item in payload]


def load_plan(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    in_table = False
    headers: list[str] = []
    for line in lines:
        if line.strip().startswith("|") and not in_table:
            headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
            in_table = True
            continue
        if in_table and line.strip().startswith("| ---"):
            continue
        if in_table and line.strip().startswith("|"):
            values = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(values) == len(headers):
                rows.append(dict(zip(headers, values)))
            continue
        if in_table:
            break
    return rows


def match_target(target: str, snapshot: TerminalSnapshot) -> bool:
    if target == "any-empty":
        return True
    haystacks = [snapshot.emulator, snapshot.title or "", snapshot.window_id or ""]
    return any(target in value for value in haystacks)


def create_tmux_session(row: dict[str, str]) -> None:
    session = row.get("session", "").strip()
    if not session:
        return
    has = run(["tmux", "has-session", "-t", session])
    if has.returncode != 0:
        command = ["tmux", "new-session", "-d", "-s", session]
        cwd = row.get("cwd", "").strip()
        if cwd:
            command.extend(["-c", os.path.expanduser(cwd)])
        run(command, check=True)
    layout = row.get("layout", "").strip()
    if layout:
        run(["tmux", "select-layout", "-t", session, layout], check=False)
    startup = row.get("command", "").strip()
    if startup:
        run(["tmux", "send-keys", "-t", session, startup, "C-m"], check=False)


def attach_tmux(window_id: str, session: str) -> bool:
    if not which("xdotool"):
        return False
    command = f"tmux new-session -A -s {shlex.quote(session)}"
    steps = [
        ["xdotool", "windowactivate", "--sync", window_id],
        ["xdotool", "type", "--delay", "1", command],
        ["xdotool", "key", "Return"],
    ]
    for step in steps:
        if run(step).returncode != 0:
            return False
    return True


def write_live_assignments(path: Path, assignments: list[str]) -> None:
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    marker = "## Live Assignments"
    prefix = content.split(marker, 1)[0].rstrip()
    lines = [prefix, "", marker, ""]
    if assignments:
        lines.extend(f"- {item}" for item in assignments)
    else:
        lines.append("No assignments were made.")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def select_close_candidates(snapshots: list[TerminalSnapshot]) -> list[TerminalSnapshot]:
    parents = process_parents()
    children = descendants_by_pid(parents)
    commands = process_commands()
    return [
        snapshot
        for snapshot in snapshots
        if snapshot.tab_count <= 1
        and not snapshot.tmux_session
        and (
            (
                snapshot.capture_status == "ok"
                and is_effectively_empty(snapshot.aggregated_text)
            )
            or (
                snapshot.capture_status == "unavailable"
                and not has_active_descendants(snapshot, children, commands)
            )
        )
    ]


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


def inspect_command(args: argparse.Namespace) -> int:
    snapshots = load_snapshot_fixture(Path(args.fixtures)) if args.fixtures else build_snapshots()
    payload = []
    for snapshot in snapshots:
        item = asdict(snapshot)
        item["aggregated_text"] = snapshot.aggregated_text
        item["tab_count"] = snapshot.tab_count
        item["effectively_empty"] = is_effectively_empty(snapshot.aggregated_text)
        payload.append(item)
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    if args.json:
        print(rendered)
        return 0
    for item in payload:
        print(
            f"{item['emulator']} pid={item['pid']} tabs={item['tab_count']} "
            f"capture={item['capture_method'] or 'none'} status={item['capture_status']} "
            f"empty={item['effectively_empty']} title={item['title'] or '-'}"
        )
        preview = item["aggregated_text"].strip().splitlines()
        if preview:
            print(f"  {preview[0][:160]}")
    return 0


def plan_command(args: argparse.Namespace) -> int:
    rows = load_plan(Path(args.state_file))
    print(json.dumps(rows, indent=2, sort_keys=True))
    return 0


def ensure_tmux_command(args: argparse.Namespace) -> int:
    state_file = Path(args.state_file)
    rows = load_plan(state_file)
    if not rows:
        print("No tmux plan rows found.", file=sys.stderr)
        return 1
    snapshots = build_snapshots()
    candidates = [item for item in snapshots if item.tab_count <= 1 and is_effectively_empty(item.aggregated_text)]
    assignments: list[str] = []
    used_windows: set[str] = set()
    for row in rows:
        if not args.dry_run:
            create_tmux_session(row)
        session = row.get("session", "").strip()
        target = row.get("target", "").strip()
        chosen = next(
            (
                candidate
                for candidate in candidates
                if candidate.window_id
                and candidate.window_id not in used_windows
                and match_target(target, candidate)
            ),
            None,
        )
        if not session:
            continue
        if chosen and (args.dry_run or attach_tmux(chosen.window_id or "", session)):
            used_windows.add(chosen.window_id or "")
            status = "would attach" if args.dry_run else "attached"
            assignments.append(
                f"{session} -> {status} {chosen.emulator} pid={chosen.pid} window={chosen.window_id} title={chosen.title or '-'}"
            )
        else:
            assignments.append(f"{session} -> unattached")
    write_live_assignments(state_file, assignments)
    for line in assignments:
        print(line)
    return 0


def close_empty_command(args: argparse.Namespace) -> int:
    snapshots = load_snapshot_fixture(Path(args.fixtures)) if args.fixtures else build_snapshots()
    candidates = select_close_candidates(snapshots)
    if not candidates:
        print("No empty single-tab terminals eligible for closing.")
        return 0
    failures = 0
    for snapshot in candidates:
        status = "would close" if args.dry_run else "closed"
        if args.dry_run or close_snapshot(snapshot):
            print(
                f"{status} {snapshot.emulator} pid={snapshot.pid} "
                f"window={snapshot.window_id or '-'} title={snapshot.title or '-'}"
            )
            continue
        failures += 1
        print(
            f"failed to close {snapshot.emulator} pid={snapshot.pid} "
            f"window={snapshot.window_id or '-'} title={snapshot.title or '-'}",
            file=sys.stderr,
        )
    return 1 if failures else 0


def publish_command(args: argparse.Namespace) -> int:
    if not which("gh"):
        print("gh is not installed.", file=sys.stderr)
        return 1
    repo = args.repo or Path.cwd().name
    full_name = f"{args.org}/{repo}" if args.org else repo
    visibility = "--private" if args.private else "--public"
    create = run(["gh", "repo", "create", full_name, visibility, "--source", ".", "--remote", "origin", "--push"])
    if create.returncode != 0:
        sys.stderr.write(create.stderr)
        return create.returncode
    sys.stdout.write(create.stdout)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect many running terminal emulators and manage tmux attachments.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect running terminal windows.")
    inspect_parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    inspect_parser.add_argument("--output", help="Write inspection JSON to a file.")
    inspect_parser.add_argument("--fixtures", help="Load snapshots from a JSON fixture instead of live discovery.")
    inspect_parser.set_defaults(func=inspect_command)

    plan_parser = subparsers.add_parser("plan", help="Show tmux assignment plan from Markdown.")
    plan_parser.add_argument("--state-file", default="state/tmux-sessions.md", help="Markdown plan file.")
    plan_parser.set_defaults(func=plan_command)

    ensure_parser = subparsers.add_parser("ensure-tmux", help="Create tmux sessions and attach them into empty terminals.")
    ensure_parser.add_argument("--state-file", default="state/tmux-sessions.md", help="Markdown plan file.")
    ensure_parser.add_argument("--dry-run", action="store_true", help="Do not create sessions or type into terminal windows.")
    ensure_parser.set_defaults(func=ensure_tmux_command)

    close_parser = subparsers.add_parser(
        "close-empty",
        help="Close single-tab terminals that were captured as empty and are not tmux-backed.",
    )
    close_parser.add_argument("--dry-run", action="store_true", help="Print the terminals that would be closed.")
    close_parser.add_argument("--fixtures", help="Load snapshots from a JSON fixture instead of live discovery.")
    close_parser.set_defaults(func=close_empty_command)

    publish_parser = subparsers.add_parser("publish", help="Create a remote repo with gh and push.")
    publish_parser.add_argument("--org", help="GitHub organization that will own the repository.")
    publish_parser.add_argument("--repo", help="Repository name. Defaults to the current directory name.")
    publish_parser.add_argument("--private", action="store_true", help="Create the repository as private.")
    publish_parser.set_defaults(func=publish_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
