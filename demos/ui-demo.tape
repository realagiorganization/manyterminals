Output docs/ui-demo.gif
Set FontSize 16
Set Width 1200
Set Height 720
Set Theme "Builtin Solarized Dark"
Set Shell "bash"

Type "python3 scripts/manyterminals.py inspect --fixtures tests/fixtures/inspection.json"
Enter
Sleep 2s

Type "python3 scripts/manyterminals.py ensure-tmux --dry-run --state-file state/tmux-sessions.md"
Enter
Sleep 2s

Type "python3 scripts/manyterminals.py plan --state-file state/tmux-sessions.md"
Enter
Sleep 2s
