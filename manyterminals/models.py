from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
