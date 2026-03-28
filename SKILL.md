---
name: manyterminals
description: Inspect currently running Linux terminal emulators, try emulator-specific dumps or screenshot-plus-OCR fallbacks to recover visible session contents including tabs when possible, then attach empty single-tab terminals to tmux sessions tracked in a Markdown file. Use when Codex needs to coordinate many terminal windows, harvest their visible state, keep tmux layout associations, or publish the skill repository with gh.
---

# Many Terminals

Use the bundled helper instead of hand-rolling terminal inspection. The helper is intentionally best-effort because tab enumeration and screen scraping differ by emulator and by display server.

## Commands

Inventory running terminal windows:

```bash
python3 scripts/manyterminals.py inspect
```

Emit machine-readable inspection output:

```bash
python3 scripts/manyterminals.py inspect --json
```

Persist an inspection snapshot:

```bash
python3 scripts/manyterminals.py inspect --json --output state/last-inspection.json
```

Show the current tmux assignment plan:

```bash
python3 scripts/manyterminals.py plan --state-file state/tmux-sessions.md
```

Create detached tmux sessions from the Markdown plan and attach them into empty single-tab terminals when possible:

```bash
python3 scripts/manyterminals.py ensure-tmux --state-file state/tmux-sessions.md
```

Create an org-owned GitHub repository with `gh`, set `origin`, and push the current branch:

```bash
python3 scripts/manyterminals.py publish --org YOUR_ORG --repo manyterminals --private
```

## Workflow

1. Run `inspect` first. Prefer `--json` when another tool will consume the output.
2. Read the `capture_method` and `capture_status` fields before trusting content. `tmux`, `kitty`, and `wezterm` methods are higher signal than OCR.
3. Treat tab discovery as opportunistic. Some emulators expose panes or tabs; others only provide a single window snapshot.
4. Keep tmux intent in [state/tmux-sessions.md](state/tmux-sessions.md). The helper reads the Markdown table and appends live assignment notes back into the same file.
5. Use `ensure-tmux` only when the target terminals should be empty. The helper only injects commands into windows that look empty after capture.
6. Use `publish` after local verification. It shells out to `gh`, so GitHub auth and org permissions must already exist.

## Notes

- X11 support is materially better than Wayland because window IDs, screenshots, and synthetic typing are easier to access.
- OCR requires `tesseract` and a screenshot tool such as ImageMagick `import`, `gnome-screenshot`, or `grim`.
- `xdotool` and `wmctrl` are optional but improve window discovery and command injection.
- The helper never destroys tmux sessions. It only creates missing ones and attaches to them.
