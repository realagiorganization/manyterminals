from __future__ import annotations

from pathlib import Path


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


def match_target(target: str, emulator: str, title: str | None, window_id: str | None) -> bool:
    if target == "any-empty":
        return True
    haystacks = [emulator, title or "", window_id or ""]
    return any(target in value for value in haystacks)


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
