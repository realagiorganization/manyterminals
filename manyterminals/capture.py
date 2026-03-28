from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from .models import TabSnapshot, TerminalSnapshot
from .system import (
    descendant_processes,
    descendants_by_pid,
    is_descendant,
    iter_terminal_processes,
    process_commands,
    process_parents,
    run,
    strip_ansi,
    which,
    x11_windows,
)
from .tmux_ops import detect_tmux_for_pid, discover_tmux_session_from_env, tmux_capture


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
                    text_result = run(["kitty", "@", "get-text", f"--match=id:{window['id']}"], check=True)
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
                snapshot.tabs = tmux_capture(session, strip_ansi)
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
            snapshot.tabs.append(
                TabSnapshot(title=snapshot.title, content=snapshot.ocr_text, source=snapshot.capture_method)
            )
        snapshots.append(snapshot)
    return snapshots


def load_snapshot_fixture(path: Path) -> list[TerminalSnapshot]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [TerminalSnapshot.from_dict(item) for item in payload]
