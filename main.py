"""Application entry point. The packaged EXE is fully Python/PyInstaller."""
from __future__ import annotations

import argparse
import platform
import sys

from asxels_cleaner.engine import CATEGORY_BY_KEY, clean_targets, human_bytes, resolve_targets, scan_targets
from asxels_cleaner.storage import append_activity


def run_cli(args: argparse.Namespace) -> int:
    if platform.system() != "Windows":
        print("Asxels Cleaner only supports Windows.", file=sys.stderr)
        return 2
    keys = [key.strip() for key in args.categories.split(",") if key.strip()]
    invalid = [key for key in keys if key not in CATEGORY_BY_KEY]
    if invalid:
        print("Invalid category: " + ", ".join(invalid), file=sys.stderr)
        return 2
    report = scan_targets(resolve_targets(keys))
    print(f"Found {human_bytes(report.bytes_found)} in {report.items_found} items.")
    if args.clean:
        if not args.yes:
            print("Refusing cleanup: pass --yes explicitly with --clean.", file=sys.stderr)
            return 3
        result = clean_targets(resolve_targets(keys))
        print(f"Removed {human_bytes(result.bytes_removed)} from {result.files_removed} items; skipped {result.skipped}.")
        append_activity("CLI_CLEAN", f"Removed {human_bytes(result.bytes_removed)} from {result.files_removed} items")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Asxels Cleaner — safe Windows cache cleaner")
    parser.add_argument("--scan", action="store_true", help="scan selected cache categories")
    parser.add_argument("--clean", action="store_true", help="clean selected categories; requires --yes")
    parser.add_argument("--yes", action="store_true", help="explicit confirmation for CLI cleanup")
    parser.add_argument("--categories", default="user_temp", help="comma-separated category keys")
    args = parser.parse_args()
    if args.scan or args.clean:
        return run_cli(args)
    if platform.system() != "Windows":
        print("The desktop app is supported on Windows only.", file=sys.stderr)
        return 2
    from asxels_cleaner.ui import CleanerApp
    app = CleanerApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
