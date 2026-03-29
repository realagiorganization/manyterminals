from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SECTION_RE = re.compile(r"^## \[(?P<version>[^\]]+)\](?: - .+)?$", re.MULTILINE)


def extract_release_notes(changelog: str, version: str) -> str:
    normalized_version = version.removeprefix("v")
    matches = list(SECTION_RE.finditer(changelog))
    for index, match in enumerate(matches):
        if match.group("version") != normalized_version:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(changelog)
        body = changelog[start:end].strip()
        if not body:
            raise ValueError(f"Changelog section for {version} is empty.")
        return body + "\n"
    raise ValueError(f"Unable to find changelog section for {version}.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract release notes for a tag from CHANGELOG.md.")
    parser.add_argument("version", help="Tag or version name, for example v0.1.0.")
    parser.add_argument("--changelog", default="CHANGELOG.md", help="Path to the changelog file.")
    parser.add_argument("--output", help="Optional file path to write the extracted release notes.")
    args = parser.parse_args()

    changelog = Path(args.changelog).read_text(encoding="utf-8")
    try:
        notes = extract_release_notes(changelog, args.version)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(notes, encoding="utf-8")
    else:
        sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
