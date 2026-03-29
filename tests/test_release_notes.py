from __future__ import annotations

from pathlib import Path

from scripts.release_notes import extract_release_notes


ROOT = Path(__file__).resolve().parents[1]


def test_extract_release_notes_for_version() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    notes = extract_release_notes(changelog, "v0.1.0")

    assert "Initial Codex skill scaffold" in notes
    assert "GitHub Pages publishing" in notes


def test_extract_release_notes_rejects_missing_version() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    try:
        extract_release_notes(changelog, "v9.9.9")
    except ValueError as error:
        assert "Unable to find changelog section" in str(error)
    else:
        raise AssertionError("missing version should fail")
