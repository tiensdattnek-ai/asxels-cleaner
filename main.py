#!/usr/bin/env python3
"""Asxels Cleaner — a conservative, transparent Windows maintenance tool.

This program intentionally targets known disposable caches only.  It never
searches the whole disk, removes personal folders, edits the registry, or uses
blind shell deletion commands.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import datetime as dt
import os
from pathlib import Path
import platform
import queue
import shutil
import stat
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

APP_NAME = "Asxels Cleaner"
VERSION = "1.0.0"
IS_WINDOWS = platform.system() == "Windows"

# Visual language
BG = "#0A1020"
PANEL = "#111A2E"
PANEL_2 = "#17233B"
BORDER = "#263653"
TEXT = "#F3F7FF"
MUTED = "#9CADCB"
ACCENT = "#4E8CFF"
ACCENT_HOVER = "#72A4FF"
TEAL = "#3DDBC0"
DANGER = "#F0A36B"
SUCCESS = "#6DE3A8"


@dataclass(frozen=True)
class Target:
    """A predetermined safe path. clear_contents keeps the container itself."""

    path: Path
    clear_contents: bool = True


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    subtitle: str
    default: bool
    warning: str
    resolver: Callable[[], list[Target]]


@dataclass
class ScanReport:
    bytes_found: int = 0
    files_found: int = 0
    inaccessible: int = 0
    targets_found: int = 0


@dataclass
class CleanReport:
    bytes_removed: int = 0
    files_removed: int = 0
    folders_removed: int = 0
    skipped: int = 0
    errors: int = 0


# -------- Safe, bounded target definitions --------

def _env_path(name: str) -> Optional[Path]:
    value = os.environ.get(name)
    return Path(value) if value else None


def _profile_path_or_default(variable: str, leaf: str) -> Path:
    """Accept a redirected AppData location only inside the current user profile.

    This conservative validation prevents an altered environment variable from
    ever turning a cache cleaner into a broad-folder cleaner.
    """
    fallback = Path.home() / "AppData" / leaf
    candidate = _env_path(variable)
    if candidate and candidate.name.lower() == leaf.lower() and _is_descendant(candidate, Path.home()):
        return candidate
    return fallback


def _local_app_data() -> Path:
    return _profile_path_or_default("LOCALAPPDATA", "Local")


def _app_data() -> Path:
    return _profile_path_or_default("APPDATA", "Roaming")


def _windows_dir() -> Path:
    """Use Windows' own API rather than a mutable WINDIR environment variable."""
    if IS_WINDOWS:
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer))
            if length:
                return Path(buffer.value)
        except (AttributeError, OSError):
            pass
    return Path(r"C:\Windows")


def _existing_contents(path: Path) -> list[Target]:
    return [Target(path, True)] if path.is_dir() else []


def _existing_files(folder: Path, pattern: str) -> list[Target]:
    if not folder.is_dir():
        return []
    try:
        return [Target(item, False) for item in folder.glob(pattern) if item.is_file() or item.is_symlink()]
    except OSError:
        return []


def _browser_cache_targets() -> list[Target]:
    """Known cache locations only; profiles' cookies/history are untouched."""
    local = _local_app_data()
    roots = [
        local / "Google" / "Chrome" / "User Data",
        local / "Microsoft" / "Edge" / "User Data",
        local / "BraveSoftware" / "Brave-Browser" / "User Data",
        _app_data() / "Mozilla" / "Firefox" / "Profiles",
    ]
    found: list[Target] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            # Cache directories are at most two profile levels below a browser root.
            for pattern in ("*/Cache", "*/Code Cache", "*/GPUCache", "*/Service Worker/CacheStorage",
                            "*/cache2", "Cache", "cache2"):
                for candidate in root.glob(pattern):
                    if candidate.is_dir():
                        found.append(Target(candidate, True))
        except OSError:
            continue
    return _dedupe_targets(found)


def _temp_targets() -> list[Target]:
    local = _local_app_data()
    # Windows normally stores user TEMP under LocalAppData.  Do not trust a
    # TEMP/TMP value outside that bounded area, even if an environment is altered.
    candidates = [_env_path("TEMP"), _env_path("TMP"), local / "Temp"]
    for temp in candidates:
        if temp and temp.name.lower() in {"temp", "tmp"} and _is_descendant(temp, local):
            return _existing_contents(temp)
    return []


def _windows_temp_targets() -> list[Target]:
    return _existing_contents(_windows_dir() / "Temp")


def _thumb_targets() -> list[Target]:
    explorer = _local_app_data() / "Microsoft" / "Windows" / "Explorer"
    return _existing_files(explorer, "thumbcache*.db") + _existing_files(explorer, "iconcache*.db")


def _shader_targets() -> list[Target]:
    local = _local_app_data()
    paths = [
        local / "D3DSCache",
        local / "NVIDIA" / "DXCache",
        local / "NVIDIA" / "GLCache",
        local / "AMD" / "DxCache",
        local / "AMD" / "GLCache",
    ]
    targets: list[Target] = []
    for p in paths:
        targets.extend(_existing_contents(p))
    return targets


def _error_report_targets() -> list[Target]:
    base = _local_app_data() / "Microsoft" / "Windows" / "WER"
    paths = [base / "ReportArchive", base / "ReportQueue", base / "Temp"]
    targets: list[Target] = []
    for p in paths:
        targets.extend(_existing_contents(p))
    return targets


def _internet_cache_targets() -> list[Target]:
    paths = [
        _local_app_data() / "Microsoft" / "Windows" / "INetCache",
        _local_app_data() / "Temp" / "INetCache",
    ]
    targets: list[Target] = []
    for p in paths:
        targets.extend(_existing_contents(p))
    return _dedupe_targets(targets)


def _delivery_optimization_targets() -> list[Target]:
    # May require elevated rights; skipped files are recorded instead of forced.
    return _existing_contents(_windows_dir() / "SoftwareDistribution" / "DeliveryOptimization" / "Cache")


CATEGORIES: tuple[Category, ...] = (
    Category("user_temp", "Tệp tạm người dùng", "TEMP/TMP của tài khoản hiện tại", True, "", _temp_targets),
    Category("thumbs", "Thumbnail & icon cache", "Ảnh thu nhỏ Windows sẽ tự tạo lại", True, "", _thumb_targets),
    Category("shader", "DirectX / GPU shader cache", "Cache đồ họa có thể được tạo lại", True, "", _shader_targets),
    Category("reports", "Báo cáo lỗi Windows", "WER report archive và hàng đợi lỗi", True, "", _error_report_targets),
    Category("internet", "Internet cache hệ thống", "INetCache của tài khoản hiện tại", True, "", _internet_cache_targets),
    Category("browser", "Cache trình duyệt", "Chrome, Edge, Brave, Firefox — hãy đóng trình duyệt trước", False,
             "Không xóa lịch sử, cookie hoặc mật khẩu; tệp đang dùng sẽ được bỏ qua.", _browser_cache_targets),
    Category("windows_temp", "Windows Temp", "Có thể cần quyền Administrator", False,
             "Chỉ xóa nội dung C:\\Windows\\Temp; các tệp bị Windows khóa sẽ được bỏ qua.", _windows_temp_targets),
    Category("delivery", "Delivery Optimization cache", "Bộ nhớ đệm tải Windows Update", False,
             "Có thể cần quyền Administrator; Windows có thể tải lại dữ liệu khi cần.", _delivery_optimization_targets),
)
CATEGORY_BY_KEY = {c.key: c for c in CATEGORIES}


# -------- Filesystem safety and accounting --------

def _norm(path: Path) -> str:
    try:
        return os.path.normcase(os.path.abspath(os.fspath(path)))
    except (OSError, TypeError):
        return ""


def _is_descendant(path: Path, parent: Path) -> bool:
    child = _norm(path)
    root = _norm(parent)
    return bool(child and root and (child == root or child.startswith(root + os.sep)))


def _dedupe_targets(targets: Iterable[Target]) -> list[Target]:
    seen: set[tuple[str, bool]] = set()
    output: list[Target] = []
    for target in targets:
        key = (_norm(target.path), target.clear_contents)
        if key[0] and key not in seen:
            seen.add(key)
            output.append(target)
    return output


def selected_targets(keys: Iterable[str]) -> list[Target]:
    """Resolve only internal category functions — no free-form delete path exists."""
    result: list[Target] = []
    for key in keys:
        category = CATEGORY_BY_KEY.get(key)
        if category:
            try:
                result.extend(category.resolver())
            except OSError:
                # An unreadable cache target is treated as absent and reported during scans where possible.
                continue
    return _dedupe_targets(result)


def _iter_contents(target: Target) -> Iterable[Path]:
    if target.clear_contents:
        try:
            with os.scandir(target.path) as entries:
                yield from (Path(entry.path) for entry in entries)
        except (FileNotFoundError, PermissionError, OSError):
            return
    else:
        yield target.path


def _entry_size(path: Path, report: ScanReport) -> tuple[int, int]:
    """Return (bytes, entries); never follows symlinks/junctions."""
    try:
        info = path.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        report.inaccessible += 1
        return 0, 0

    if stat.S_ISLNK(info.st_mode):
        return 0, 1
    if not stat.S_ISDIR(info.st_mode):
        return max(0, info.st_size), 1

    total, entries = 0, 1
    try:
        with os.scandir(path) as children:
            for child in children:
                child_bytes, child_entries = _entry_size(Path(child.path), report)
                total += child_bytes
                entries += child_entries
    except (PermissionError, OSError):
        report.inaccessible += 1
    return total, entries


def scan_targets(targets: list[Target], progress: Optional[Callable[[str], None]] = None) -> ScanReport:
    report = ScanReport(targets_found=len(targets))
    for target in targets:
        if progress:
            progress(f"Đang kiểm tra: {target.path.name or target.path}")
        for entry in _iter_contents(target):
            size, count = _entry_size(entry, report)
            report.bytes_found += size
            report.files_found += count
    return report


def _make_writable(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass


def _remove_entry(path: Path, report: CleanReport) -> None:
    """Delete one pre-scanned cache entry. Symlinks are unlinked, never followed."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except PermissionError:
        report.skipped += 1
        return
    except OSError:
        report.errors += 1
        return

    try:
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            size = max(0, info.st_size)
            try:
                path.unlink()
            except PermissionError:
                _make_writable(os.fspath(path))
                path.unlink()
            report.bytes_removed += size
            report.files_removed += 1
            return

        # rmtree does not follow a symlink; lstat check above makes that explicit.
        # Account a directory only after it is gone: locked descendants must never
        # be reported as successfully removed.
        estimated = ScanReport()
        bytes_before, entries_before = _entry_size(path, estimated)

        def retry_readonly(operation: Callable[..., object], item: str, _exc: object) -> None:
            _make_writable(item)
            try:
                operation(item)
            except OSError:
                pass

        shutil.rmtree(path, onerror=retry_readonly)
        if not os.path.lexists(os.fspath(path)):
            report.bytes_removed += bytes_before
            report.files_removed += entries_before
            report.folders_removed += 1
        else:
            report.skipped += 1
    except PermissionError:
        report.skipped += 1
    except OSError:
        # Locked files and protected system files are expected; do not retry forcefully.
        report.skipped += 1


def clean_targets(targets: list[Target], progress: Optional[Callable[[str], None]] = None) -> CleanReport:
    report = CleanReport()
    for target in targets:
        if progress:
            progress(f"Đang dọn: {target.path.name or target.path}")
        for entry in _iter_contents(target):
            _remove_entry(entry, report)
    return report


# -------- Windows memory helper --------

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def memory_status() -> tuple[int, int, int]:
    """Return total physical, available physical and Windows load percentage."""
    if not IS_WINDOWS:
        return 0, 0, 0
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        if ok:
            return int(status.ullTotalPhys), int(status.ullAvailPhys), int(status.dwMemoryLoad)
    except (AttributeError, OSError):
        pass
    return 0, 0, 0


def _process_name(handle: int) -> str:
    buff = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buff))
    try:
        ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buff, ctypes.byref(size))
        return Path(buff.value).name.lower() if ok else ""
    except (AttributeError, OSError):
        return ""


def trim_process_working_sets(progress: Optional[Callable[[str], None]] = None) -> tuple[int, int]:
    """Ask Windows to trim safe user-process working sets; never terminates a process."""
    if not IS_WINDOWS:
        return 0, 0
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    # Explicit signatures prevent a 64-bit Windows process handle from being
    # truncated by ctypes' default integer conversion.
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    psapi.EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD)]
    psapi.EnumProcesses.restype = wintypes.BOOL
    psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    psapi.EmptyWorkingSet.restype = wintypes.BOOL
    # Query process image plus quota change required by EmptyWorkingSet.
    access = 0x1000 | 0x0100  # PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_QUOTA
    excluded = {"system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
                "services.exe", "lsass.exe", "fontdrvhost.exe", "dwm.exe", "memory compression"}
    pids = (wintypes.DWORD * 8192)()
    needed = wintypes.DWORD()
    tried = trimmed = 0
    try:
        if not psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(needed)):
            return 0, 0
        count = min(len(pids), needed.value // ctypes.sizeof(wintypes.DWORD))
        own_pid = os.getpid()
        for pid in pids[:count]:
            pid_value = int(pid)
            if pid_value <= 4 or pid_value == own_pid:
                continue
            handle = kernel32.OpenProcess(access, False, pid_value)
            if not handle:
                continue
            try:
                name = _process_name(handle)
                if name in excluded:
                    continue
                tried += 1
                if psapi.EmptyWorkingSet(handle):
                    trimmed += 1
            finally:
                kernel32.CloseHandle(handle)
        if progress:
            progress(f"Đã gửi yêu cầu trim đến {trimmed}/{tried} tiến trình người dùng")
    except (AttributeError, OSError):
        return tried, trimmed
    return tried, trimmed


# -------- Shared formatting / logging --------

def human_bytes(value: int) -> str:
    value = max(0, int(value))
    units = ["B", "KB", "MB", "GB", "TB"]
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return f"{number:.1f} TB"


def log_file() -> Path:
    folder = _local_app_data() / "AsxelsCleaner" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "activity.log"


def write_log(line: str) -> None:
    try:
        with log_file().open("a", encoding="utf-8") as output:
            output.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {line}\n")
    except OSError:
        pass


# -------- GUI --------

class CleanerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME}  •  {VERSION}")
        self.geometry("1040x760")
        self.minsize(920, 650)
        self.configure(bg=BG)
        self.option_add("*Font", ("Segoe UI", 10))
        self._setup_dpi()
        self.style = ttk.Style(self)
        self._setup_style()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.category_vars: dict[str, tk.BooleanVar] = {
            category.key: tk.BooleanVar(value=category.default) for category in CATEGORIES
        }
        self.busy = False
        self.pending_clean = False
        self.last_report: Optional[ScanReport] = None
        self._build()
        self._refresh_memory()
        self.after(100, self._drain_events)
        self.after(5000, self._auto_refresh_memory)

    def _setup_dpi(self) -> None:
        if IS_WINDOWS:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except (AttributeError, OSError):
                    pass

    def _setup_style(self) -> None:
        self.style.theme_use("clam")
        self.style.configure("TFrame", background=BG)
        self.style.configure("Panel.TFrame", background=PANEL)
        self.style.configure("TLabel", background=BG, foreground=TEXT)
        self.style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        self.style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        self.style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 24))
        self.style.configure("SubTitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        self.style.configure("CardTitle.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 11))
        self.style.configure("CardSub.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 8))
        self.style.configure("Value.TLabel", background=PANEL, foreground=TEAL, font=("Segoe UI Semibold", 19))
        self.style.configure("SmallValue.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 13))
        self.style.configure("TCheckbutton", background=PANEL, foreground=TEXT, font=("Segoe UI", 10), focuscolor=PANEL)
        self.style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("disabled", MUTED)])
        self.style.configure("Accent.TButton", background=ACCENT, foreground="#FFFFFF", borderwidth=0,
                             padding=(18, 12), font=("Segoe UI Semibold", 10))
        self.style.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("disabled", "#33425E")])
        self.style.configure("Ghost.TButton", background=PANEL_2, foreground=TEXT, borderwidth=0,
                             padding=(14, 10), font=("Segoe UI Semibold", 9))
        self.style.map("Ghost.TButton", background=[("active", BORDER), ("disabled", "#243149")])
        self.style.configure("TProgressbar", troughcolor="#0F1930", background=TEAL, borderwidth=0, thickness=6)

    def _build(self) -> None:
        root = ttk.Frame(self, padding=(32, 24, 32, 20))
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x")
        left = ttk.Frame(header)
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="ASXELS", style="SubTitle.TLabel", foreground=ACCENT).pack(anchor="w")
        ttk.Label(left, text="Dọn sạch thông minh. Có kiểm soát.", style="Title.TLabel").pack(anchor="w", pady=(2, 3))
        ttk.Label(left, text="Chỉ xử lý cache và tệp tạm đã biết — không quét hoặc xóa dữ liệu cá nhân.",
                  style="SubTitle.TLabel").pack(anchor="w")
        self.system_badge = tk.Label(header, text="  WINDOWS  ", bg="#18375C" if IS_WINDOWS else "#5C3131",
                                     fg="#DCEBFF", font=("Segoe UI Semibold", 8), padx=6, pady=5)
        self.system_badge.pack(side="right", anchor="n", pady=5)

        # status / metrics
        metrics = ttk.Frame(root)
        metrics.pack(fill="x", pady=(22, 18))
        metrics.columnconfigure((0, 1, 2), weight=1, uniform="metrics")
        self.found_value = self._metric(metrics, 0, "SẴN SÀNG DỌN", "Chưa kiểm tra")
        self.memory_value = self._metric(metrics, 1, "RAM KHẢ DỤNG", "Đang tải…")
        self.last_value = self._metric(metrics, 2, "LẦN GẦN NHẤT", "Chưa có dữ liệu")

        content = ttk.Frame(root)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=7)
        content.columnconfigure(1, weight=4)
        content.rowconfigure(0, weight=1)

        clean_panel = ttk.Frame(content, style="Panel.TFrame", padding=18)
        clean_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self._build_cleanup_panel(clean_panel)

        side = ttk.Frame(content, style="Panel.TFrame", padding=18)
        side.grid(row=0, column=1, sticky="nsew")
        self._build_side_panel(side)

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(15, 0))
        self.status_var = tk.StringVar(value="Sẵn sàng. Nên bấm “Xem trước” trước khi dọn.")
        ttk.Label(footer, textvariable=self.status_var, style="SubTitle.TLabel").pack(side="left")
        ttk.Label(footer, text=f"v{VERSION}  •  hoạt động cục bộ", style="SubTitle.TLabel").pack(side="right")

    def _metric(self, parent: ttk.Frame, col: int, title: str, value: str) -> ttk.Label:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=(17, 13))
        card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 6 if col != 2 else 0))
        ttk.Label(card, text=title, style="Muted.TLabel").pack(anchor="w")
        label = ttk.Label(card, text=value, style="Value.TLabel")
        label.pack(anchor="w", pady=(5, 0))
        return label

    def _build_cleanup_panel(self, panel: ttk.Frame) -> None:
        top = ttk.Frame(panel, style="Panel.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Khu vực dọn dẹp", style="CardTitle.TLabel").pack(side="left")
        ttk.Label(top, text="CHỌN HẠNG MỤC", style="Muted.TLabel", foreground=ACCENT).pack(side="right")
        ttk.Separator(panel, orient="horizontal").pack(fill="x", pady=(12, 10))

        self.category_box = ttk.Frame(panel, style="Panel.TFrame")
        self.category_box.pack(fill="both", expand=True)
        for i, category in enumerate(CATEGORIES):
            row = ttk.Frame(self.category_box, style="Panel.TFrame", padding=(4, 7))
            row.pack(fill="x")
            check = ttk.Checkbutton(row, text=category.title, variable=self.category_vars[category.key],
                                    command=self._selection_changed)
            check.pack(anchor="w")
            detail = category.subtitle
            if category.warning:
                detail += "  •  " + category.warning
            ttk.Label(row, text=detail, style="CardSub.TLabel", wraplength=540, justify="left").pack(anchor="w", padx=(27, 0), pady=(1, 0))
            if i != len(CATEGORIES) - 1:
                tk.Frame(self.category_box, bg=BORDER, height=1).pack(fill="x", padx=4)

        action_row = ttk.Frame(panel, style="Panel.TFrame")
        action_row.pack(fill="x", pady=(12, 0))
        self.preview_button = ttk.Button(action_row, text="↻  XEM TRƯỚC", style="Ghost.TButton", command=self.preview)
        self.preview_button.pack(side="left")
        self.clean_button = ttk.Button(action_row, text="✦  DỌN DẸP AN TOÀN", style="Accent.TButton", command=self.request_clean)
        self.clean_button.pack(side="right")

    def _build_side_panel(self, panel: ttk.Frame) -> None:
        ttk.Label(panel, text="Bộ nhớ tức thì", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Yêu cầu Windows trim working set của ứng dụng thường. Không đóng tiến trình, không tăng RAM vật lý.",
                  style="CardSub.TLabel", wraplength=270, justify="left").pack(anchor="w", pady=(5, 12))
        self.mem_detail = ttk.Label(panel, text="Đang tải thông tin RAM…", style="CardSub.TLabel", wraplength=270, justify="left")
        self.mem_detail.pack(anchor="w")
        self.memory_bar = ttk.Progressbar(panel, mode="determinate", maximum=100)
        self.memory_bar.pack(fill="x", pady=(10, 11))
        self.memory_button = ttk.Button(panel, text="⚡  TỐI ƯU BỘ NHỚ", style="Ghost.TButton", command=self.optimize_memory)
        self.memory_button.pack(fill="x")

        ttk.Separator(panel, orient="horizontal").pack(fill="x", pady=18)
        ttk.Label(panel, text="Minh bạch & an toàn", style="CardTitle.TLabel").pack(anchor="w")
        safeguards = [
            ("✓", "Không đụng Documents, Downloads, Desktop hoặc Registry."),
            ("✓", "Không theo liên kết symbolic/junction khi xóa."),
            ("✓", "Tệp đang khóa hoặc cần quyền cao sẽ được bỏ qua."),
            ("✓", "Luôn xem dung lượng trước, rồi mới xác nhận."),
        ]
        for icon, text in safeguards:
            line = ttk.Frame(panel, style="Panel.TFrame")
            line.pack(fill="x", pady=4)
            ttk.Label(line, text=icon, style="Panel.TLabel", foreground=SUCCESS, font=("Segoe UI Semibold", 10)).pack(side="left")
            ttk.Label(line, text=text, style="CardSub.TLabel", wraplength=245, justify="left").pack(side="left", padx=(7, 0))

        ttk.Separator(panel, orient="horizontal").pack(fill="x", pady=18)
        logrow = ttk.Frame(panel, style="Panel.TFrame")
        logrow.pack(fill="x")
        ttk.Label(logrow, text="Nhật ký hoạt động lưu cục bộ", style="Muted.TLabel").pack(side="left")
        ttk.Button(logrow, text="MỞ", style="Ghost.TButton", command=self.open_log_folder).pack(side="right")

    def _selected_keys(self) -> list[str]:
        return [key for key, var in self.category_vars.items() if var.get()]

    def _selection_changed(self) -> None:
        if not self.busy:
            self.found_value.configure(text="Cần kiểm tra")
            self.status_var.set("Lựa chọn đã đổi. Bấm “Xem trước” để tính lại chính xác.")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.preview_button.configure(state=state)
        self.clean_button.configure(state=state)
        self.memory_button.configure(state=state)

    def _run_background(self, kind: str, worker: Callable[[], object]) -> None:
        self._set_busy(True)
        def run() -> None:
            try:
                result = worker()
                self.events.put((kind, result))
            except Exception as exc:  # UI reports unexpected failures; it must not delete beyond safe targets.
                self.events.put(("error", (kind, str(exc))))
        threading.Thread(target=run, daemon=True).start()

    def preview(self) -> None:
        keys = self._selected_keys()
        if not keys:
            messagebox.showinfo(APP_NAME, "Hãy chọn ít nhất một khu vực để kiểm tra.")
            return
        self.pending_clean = False
        self.status_var.set("Đang kiểm tra các khu vực đã chọn…")
        def work() -> tuple[ScanReport, list[Target]]:
            targets = selected_targets(keys)
            report = scan_targets(targets, lambda msg: self.events.put(("status", msg)))
            return report, targets
        self._run_background("scan", work)

    def request_clean(self) -> None:
        keys = self._selected_keys()
        if not keys:
            messagebox.showinfo(APP_NAME, "Hãy chọn ít nhất một khu vực để dọn.")
            return
        # Re-scan right before consent so the shown amount is current.
        self.pending_clean = True
        self.status_var.set("Đang kiểm tra lần cuối trước khi dọn…")
        def work() -> tuple[ScanReport, list[Target]]:
            targets = selected_targets(keys)
            report = scan_targets(targets, lambda msg: self.events.put(("status", msg)))
            return report, targets
        self._run_background("scan", work)

    def _after_scan(self, payload: tuple[ScanReport, list[Target]]) -> None:
        report, targets = payload
        self.last_report = report
        self.found_value.configure(text=human_bytes(report.bytes_found))
        self.last_value.configure(text=f"{report.files_found:,} mục".replace(",", "."))
        notice = f"Tìm thấy {human_bytes(report.bytes_found)} trong {report.files_found:,} mục".replace(",", ".")
        if report.inaccessible:
            notice += f" • {report.inaccessible} mục không đọc được"
        self.status_var.set(notice)
        self._set_busy(False)

        if not self.pending_clean:
            return
        self.pending_clean = False
        if not targets or report.files_found == 0:
            messagebox.showinfo(APP_NAME, "Không tìm thấy tệp cache/tạm phù hợp để dọn trong các mục đã chọn.")
            return
        answer = messagebox.askyesno(
            "Xác nhận dọn dẹp",
            f"Xóa an toàn tối đa {human_bytes(report.bytes_found)} từ {report.files_found:,} mục cache/tạm?\n\n"
            "• Chỉ các vị trí được liệt kê trong ứng dụng.\n"
            "• Tệp đang được dùng hoặc cần quyền cao sẽ được bỏ qua.\n"
            "• Không thể hoàn tác thao tác này."
        )
        if not answer:
            self.status_var.set("Đã hủy. Không có tệp nào bị thay đổi.")
            return
        self.status_var.set("Đang dọn dẹp an toàn…")
        self._run_background("clean", lambda: clean_targets(targets, lambda msg: self.events.put(("status", msg))))

    def _after_clean(self, report: CleanReport) -> None:
        self._set_busy(False)
        self.found_value.configure(text="Đã dọn " + human_bytes(report.bytes_removed))
        self.last_value.configure(text=f"{report.files_removed:,} mục".replace(",", "."))
        details = f"Đã dọn {human_bytes(report.bytes_removed)} từ {report.files_removed:,} mục".replace(",", ".")
        if report.skipped:
            details += f" • bỏ qua {report.skipped} mục đang khóa/bảo vệ"
        if report.errors:
            details += f" • lỗi {report.errors}"
        self.status_var.set(details)
        write_log(details)
        messagebox.showinfo(APP_NAME, details + "\n\nCác tệp bị khóa hoặc bảo vệ không bị ép xóa.")

    def _refresh_memory(self) -> None:
        total, available, load = memory_status()
        if total:
            self.memory_value.configure(text=f"{human_bytes(available)}")
            self.mem_detail.configure(text=f"{human_bytes(available)} khả dụng / {human_bytes(total)} tổng • đang dùng {load}%")
            self.memory_bar.configure(value=load)
        elif not IS_WINDOWS:
            self.memory_value.configure(text="Windows only")
            self.mem_detail.configure(text="Tối ưu bộ nhớ sử dụng Windows API, chỉ hoạt động trên Windows.")
        else:
            self.memory_value.configure(text="Không đọc được")

    def _auto_refresh_memory(self) -> None:
        if not self.busy:
            self._refresh_memory()
        self.after(5000, self._auto_refresh_memory)

    def optimize_memory(self) -> None:
        if not IS_WINDOWS:
            messagebox.showwarning(APP_NAME, "Tính năng này chỉ hỗ trợ Windows.")
            return
        before_total, before_available, _ = memory_status()
        self.status_var.set("Đang gửi yêu cầu tối ưu working set đến Windows…")
        self._run_background("memory", lambda: (before_total, before_available, *trim_process_working_sets(
            lambda msg: self.events.put(("status", msg)))))

    def _after_memory(self, result: tuple[int, int, int, int]) -> None:
        _total, before_available, tried, trimmed = result
        self._set_busy(False)
        # Let Windows settle on its own scheduler before reading its accounting.
        self.after(400, self._refresh_memory)
        details = f"Đã yêu cầu Windows trim working set: {trimmed}/{tried} tiến trình phù hợp."
        if before_available:
            details += " Dung lượng RAM khả dụng sẽ được Windows cập nhật tự động."
        self.status_var.set(details)
        write_log(details)
        messagebox.showinfo(APP_NAME, details + "\n\nThao tác này không đóng ứng dụng; một số ứng dụng có thể nạp lại dữ liệu vào RAM khi cần.")

    def open_log_folder(self) -> None:
        folder = log_file().parent
        try:
            if IS_WINDOWS:
                os.startfile(os.fspath(folder))  # type: ignore[attr-defined]
            else:
                messagebox.showinfo(APP_NAME, f"Nhật ký: {folder}")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Không thể mở thư mục nhật ký.\n{exc}")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "scan":
                    self._after_scan(payload)  # type: ignore[arg-type]
                elif kind == "clean":
                    self._after_clean(payload)  # type: ignore[arg-type]
                elif kind == "memory":
                    self._after_memory(payload)  # type: ignore[arg-type]
                elif kind == "error":
                    action, error = payload  # type: ignore[misc]
                    self.pending_clean = False
                    self._set_busy(False)
                    self.status_var.set(f"Có lỗi khi {action}.")
                    write_log(f"Lỗi {action}: {error}")
                    messagebox.showerror(APP_NAME, f"Có lỗi khi thực hiện tác vụ:\n{error}")
        except queue.Empty:
            pass
        self.after(100, self._drain_events)


# -------- Small, opt-in command-line utility --------

def run_cli(args: argparse.Namespace) -> int:
    if not IS_WINDOWS:
        print("Asxels Cleaner chỉ hỗ trợ Windows.", file=sys.stderr)
        return 2
    keys = [item.strip() for item in args.categories.split(",") if item.strip()]
    invalid = [key for key in keys if key not in CATEGORY_BY_KEY]
    if invalid:
        print("Hạng mục không hợp lệ: " + ", ".join(invalid), file=sys.stderr)
        return 2
    targets = selected_targets(keys)
    report = scan_targets(targets)
    print(f"Tìm thấy {human_bytes(report.bytes_found)} trong {report.files_found} mục ({len(targets)} vị trí).")
    if args.clean:
        if not args.yes:
            print("Từ chối dọn: cần thêm --yes để xác nhận trong chế độ dòng lệnh.", file=sys.stderr)
            return 3
        result = clean_targets(targets)
        print(f"Đã dọn {human_bytes(result.bytes_removed)} từ {result.files_removed} mục; bỏ qua {result.skipped}.")
        write_log(f"CLI: đã dọn {human_bytes(result.bytes_removed)} từ {result.files_removed} mục")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Asxels Cleaner — Windows cache cleaner")
    parser.add_argument("--scan", action="store_true", help="quét các hạng mục chỉ định và in kết quả")
    parser.add_argument("--clean", action="store_true", help="dọn các hạng mục chỉ định (bắt buộc thêm --yes)")
    parser.add_argument("--yes", action="store_true", help="xác nhận rõ ràng cho --clean")
    parser.add_argument("--categories", default="user_temp", help="danh sách key, cách nhau bằng dấu phẩy; mặc định user_temp")
    args = parser.parse_args()
    if args.scan or args.clean:
        return run_cli(args)
    if not IS_WINDOWS:
        # Keeps packaging/test environments clear; the source itself remains importable for tests.
        print("Giao diện Asxels Cleaner chỉ hỗ trợ Windows.", file=sys.stderr)
        return 2
    app = CleanerApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
