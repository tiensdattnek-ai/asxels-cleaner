"""Local-only settings and activity history; no network or telemetry."""
from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Any


def app_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    folder = base / "AsxelsCleaner"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def log_path() -> Path:
    logs = app_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "activity.log"


def append_activity(event: str, details: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with log_path().open("a", encoding="utf-8") as output:
            output.write(f"[{stamp}] {event}: {details}\n")
    except OSError:
        pass


def history_path() -> Path:
    return app_dir() / "history.json"


def save_summary(summary: dict[str, Any]) -> None:
    """Keep only a small local last-run summary; never stores file paths."""
    payload = {"updated_at": datetime.now().isoformat(timespec="seconds"), **summary}
    try:
        history_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_summary() -> dict[str, Any]:
    try:
        raw = json.loads(history_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
