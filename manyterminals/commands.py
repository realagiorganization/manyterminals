from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .capture import build_snapshots, load_snapshot_fixture, remap_controlled_tabs
from .models import TabSnapshot, TerminalSnapshot
from .planning import load_plan, match_target, write_live_assignments
from .system import (
    close_snapshot,
    descendant_processes,
    descendants_by_pid,
    has_active_descendants,
    is_descendant,
    is_effectively_empty,
    iter_terminal_processes,
    pid_exists,
    process_commands,
    process_parents,
    run,
    strip_ansi,
    terminate_process_tree,
    which,
    x11_windows,
)
from .tmux_ops import (
    attach_tmux,
    create_tmux_session,
    detect_tmux_for_pid,
    discover_tmux_session_from_env,
    run_tmux,
    tmux_base_command,
    tmux_capture,
)


def snapshots_payload(snapshots: list[TerminalSnapshot]) -> list[dict[str, object]]:
    payload = []
    for snapshot in snapshots:
        item = asdict(snapshot)
        item["aggregated_text"] = snapshot.aggregated_text
        item["tab_count"] = snapshot.tab_count
        item["effectively_empty"] = is_effectively_empty(snapshot.aggregated_text)
        payload.append(item)
    return payload


def inspect_command(args: argparse.Namespace) -> int:
    snapshots = load_snapshot_fixture(Path(args.fixtures)) if args.fixtures else build_snapshots()
    payload = snapshots_payload(snapshots)
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


def record_fixture_command(args: argparse.Namespace) -> int:
    output_path = Path(args.output)
    if output_path.exists() and not args.force:
        print(f"{output_path} already exists. Use --force to overwrite it.", file=sys.stderr)
        return 1
    snapshots = build_snapshots()
    payload = snapshots_payload(snapshots)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Recorded {len(payload)} terminal snapshots to {output_path}")
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
                and match_target(target, candidate.emulator, candidate.title, candidate.window_id)
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
            (snapshot.capture_status == "ok" and is_effectively_empty(snapshot.aggregated_text))
            or (snapshot.capture_status == "unavailable" and not has_active_descendants(snapshot, children, commands))
        )
    ]


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

    record_parser = subparsers.add_parser(
        "record-fixture",
        help="Record a live inspection snapshot into a JSON fixture file.",
    )
    record_parser.add_argument("output", help="Fixture file to write.")
    record_parser.add_argument("--force", action="store_true", help="Overwrite an existing fixture file.")
    record_parser.set_defaults(func=record_fixture_command)

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


__all__ = [
    "TabSnapshot",
    "TerminalSnapshot",
    "attach_tmux",
    "build_parser",
    "build_snapshots",
    "close_empty_command",
    "close_snapshot",
    "create_tmux_session",
    "descendant_processes",
    "descendants_by_pid",
    "detect_tmux_for_pid",
    "discover_tmux_session_from_env",
    "ensure_tmux_command",
    "has_active_descendants",
    "inspect_command",
    "is_descendant",
    "is_effectively_empty",
    "iter_terminal_processes",
    "load_plan",
    "load_snapshot_fixture",
    "main",
    "match_target",
    "pid_exists",
    "plan_command",
    "process_commands",
    "process_parents",
    "publish_command",
    "record_fixture_command",
    "remap_controlled_tabs",
    "run",
    "snapshots_payload",
    "run_tmux",
    "select_close_candidates",
    "strip_ansi",
    "terminate_process_tree",
    "tmux_base_command",
    "tmux_capture",
    "which",
    "write_live_assignments",
    "x11_windows",
]
