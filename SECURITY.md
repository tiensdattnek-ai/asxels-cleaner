# Safety policy

Asxels Cleaner is intentionally a bounded cleanup tool, not a generic file-deletion application.

## Engine guarantees

1. There is no arbitrary path field in the UI or CLI.
2. Every target is created from fixed, documented Windows cache paths in `asxels_cleaner/engine.py`.
3. The recursive scanner/deleter detects symbolic links and Windows reparse points (junctions) and never descends through them.
4. A `CONTENTS` target preserves its container directory and deletes only children.
5. Files blocked by Windows, another application, or unavailable permissions are skipped and included in the result; no ownership takeover, service stop, process kill, or blind shell-delete command is used.
6. Cleaning always uses scan → explicit confirmation → cleanup. CLI cleaning additionally requires `--yes`.
7. Recycle Bin is opt-in, unselected by default, and clearly marked irreversible.
8. Memory optimization only calls Windows `EmptyWorkingSet` on accessible named, non-critical processes; it never terminates an app.

## Reporting a safety issue

Do not include credentials, unredacted user paths, or personal files in a report. State the selected category, Windows version, expected result, actual result, and a redacted local-log excerpt if available.
