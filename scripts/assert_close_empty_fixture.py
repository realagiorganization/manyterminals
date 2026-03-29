#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if sys.path and sys.path[0] == str(Path(__file__).resolve().parent):
    sys.path.pop(0)

from manyterminals import commands as commands_module
from manyterminals.models import TerminalSnapshot


def _load_pairs(items: list[list[object]]) -> list[tuple[str, int]]:
    return [(str(emulator), int(pid)) for emulator, pid in items]


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: assert_close_empty_fixture.py SNAPSHOT_FIXTURE PROCESS_TREE_FIXTURE", file=sys.stderr)
        return 2

    snapshot_path = Path(sys.argv[1])
    process_tree_path = Path(sys.argv[2])

    snapshots_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    process_tree = json.loads(process_tree_path.read_text(encoding="utf-8"))
    snapshots = [TerminalSnapshot.from_dict(item) for item in snapshots_payload]
    parents = {int(pid): int(ppid) for pid, ppid in process_tree["parents"].items()}
    commands = {int(pid): str(command) for pid, command in process_tree["commands"].items()}
    expected_close = _load_pairs(process_tree["expected_close_candidates"])
    expected_protected = _load_pairs(process_tree["expected_protected"])

    original_parents = commands_module.process_parents
    original_commands = commands_module.process_commands
    try:
        commands_module.process_parents = lambda: parents
        commands_module.process_commands = lambda: commands
        selected = commands_module.select_close_candidates(snapshots)
    finally:
        commands_module.process_parents = original_parents
        commands_module.process_commands = original_commands

    actual_close = [(snapshot.emulator, snapshot.pid) for snapshot in selected]
    all_rows = {(snapshot.emulator, snapshot.pid) for snapshot in snapshots}
    if actual_close != expected_close:
        print(f"close-empty fixture mismatch: expected {expected_close}, got {actual_close}", file=sys.stderr)
        return 1
    for row in expected_protected:
        if row not in all_rows:
            print(f"protected terminal missing from fixture: {row}", file=sys.stderr)
            return 1
        if row in actual_close:
            print(f"protected terminal selected for close: {row}", file=sys.stderr)
            return 1
    print("close-empty fixture matrix assertion passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
