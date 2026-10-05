# Safety and security policy

Asxels Cleaner is deliberately a **bounded cleaner**, not a generic file deletion utility.

## Non-negotiable engine guarantees

1. The GUI has no input for an arbitrary filesystem path.
2. Cleanup locations are fixed in `src/engine.cpp` and limited to documented caches and temporary-file stores.
3. Directory junctions and symbolic links are never traversed. A link is handled only as a link.
4. Items locked by an application, protected by Windows, or requiring unavailable permission are skipped and reported; the engine does not take ownership, stop services, kill processes, or use shell-wide recursive-delete commands.
5. The final cleanup action always performs a new scan and requires an explicit confirmation dialog.
6. Memory optimization invokes `EmptyWorkingSet` only for accessible, non-critical named processes. It never terminates processes and cannot create physical RAM.

## Reporting an issue

Do not publish credentials or personal paths in an issue. Describe the category, Windows version, expected result, actual result, and a redacted log excerpt when possible.
