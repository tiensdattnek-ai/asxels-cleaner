"""Bounded cleanup engine.

There is intentionally no arbitrary path API. Targets are generated solely from
known Windows cache locations. The deletion walker never follows symbolic links
or junction/reparse points.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import platform
import stat
from typing import Callable, Iterable, Optional

IS_WINDOWS = platform.system() == "Windows"
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


class TargetKind(str, Enum):
    CONTENTS = "contents"       # Delete children, preserve the container.
    FILE = "file"               # Delete exactly this file.
    RECYCLE_BIN = "recycle_bin" # Windows Shell special folder API.


@dataclass(frozen=True)
class Target:
    path: Path
    kind: TargetKind
    boundary: Path
    label: str


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    subtitle: str
    default: bool
    caution: str
    resolver: Callable[[], list[Target]]


@dataclass
class ScanReport:
    bytes_found: int = 0
    items_found: int = 0
    inaccessible: int = 0
    targets_found: int = 0
    cancelled: bool = False


@dataclass
class CleanReport:
    bytes_removed: int = 0
    files_removed: int = 0
    folders_removed: int = 0
    skipped: int = 0
    errors: int = 0
    cancelled: bool = False


ProgressCallback = Optional[Callable[[str], None]]
CancelCheck = Optional[Callable[[], bool]]


def _absolute(path: Path) -> Path:
    """Normalize without resolving a symlink/junction."""
    return Path(os.path.abspath(os.fspath(path)))


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(_absolute(path))))


def _is_under(path: Path, root: Path) -> bool:
    child, parent = _norm(path), _norm(root)
    if not child or not parent:
        return False
    return child == parent or child.startswith(parent + os.sep)


def _safe_dir(path: Path) -> bool:
    """A cleanup root must be a genuine directory, not a mounted/junction target."""
    try:
        return path.is_dir() and not _is_reparse(path)
    except OSError:
        return False


def _is_reparse(path: Path) -> bool:
    """Detect Windows links/junctions without following them."""
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    if IS_WINDOWS:
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(wintypes.LPCWSTR(os.fspath(path)))
            return attrs != INVALID_FILE_ATTRIBUTES and bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
        except (AttributeError, OSError):
            return True
    return False


def _local_app_data() -> Path:
    """Use the conventional per-user location and reject a broad/malformed env path."""
    profile = Path.home()
    fallback = profile / "AppData" / "Local"
    candidate = Path(os.environ.get("LOCALAPPDATA", os.fspath(fallback)))
    # Normal LocalAppData belongs to the user profile. Falling back is safer
    # than trusting an environment variable pointing at an arbitrary disk path.
    return candidate if candidate.name.lower() == "local" and _is_under(candidate, profile) else fallback


def _roaming_app_data() -> Path:
    profile = Path.home()
    fallback = profile / "AppData" / "Roaming"
    candidate = Path(os.environ.get("APPDATA", os.fspath(fallback)))
    return candidate if candidate.name.lower() == "roaming" and _is_under(candidate, profile) else fallback


def _windows_dir() -> Path:
    if IS_WINDOWS:
        buffer = ctypes.create_unicode_buffer(32768)
        try:
            length = ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer))
            if length:
                return Path(buffer.value)
        except (AttributeError, OSError):
            pass
    return Path(r"C:\Windows")


def _user_temp() -> Path:
    local = _local_app_data()
    for name in ("TEMP", "TMP"):
        value = os.environ.get(name)
        if value:
            candidate = Path(value)
            if candidate.name.lower() in {"temp", "tmp"} and _is_under(candidate, local):
                return candidate
    return local / "Temp"


def _contents(path: Path, label: str) -> list[Target]:
    return [Target(_absolute(path), TargetKind.CONTENTS, _absolute(path), label)] if _safe_dir(path) else []


def _files(folder: Path, pattern: str, label: str) -> list[Target]:
    if not _safe_dir(folder):
        return []
    found: list[Target] = []
    try:
        for item in folder.glob(pattern):
            if item.is_file() or _is_reparse(item):
                found.append(Target(_absolute(item), TargetKind.FILE, _absolute(folder), label))
    except OSError:
        pass
    return found


def _browser_caches() -> list[Target]:
    local, roaming = _local_app_data(), _roaming_app_data()
    result: list[Target] = []
    roots = (
        local / "Google" / "Chrome" / "User Data",
        local / "Microsoft" / "Edge" / "User Data",
        local / "BraveSoftware" / "Brave-Browser" / "User Data",
    )
    for root in roots:
        if not _safe_dir(root):
            continue
        try:
            profiles = [entry for entry in root.iterdir() if _safe_dir(entry)]
        except OSError:
            continue
        for profile in profiles:
            for relative in (Path("Cache"), Path("Code Cache"), Path("GPUCache"), Path("Service Worker") / "CacheStorage"):
                result.extend(_contents(profile / relative, "Browser cache"))
    firefox = roaming / "Mozilla" / "Firefox" / "Profiles"
    if _safe_dir(firefox):
        try:
            for profile in firefox.iterdir():
                if _safe_dir(profile):
                    result.extend(_contents(profile / "cache2", "Firefox cache"))
        except OSError:
            pass
    return _dedupe(result)


def _user_temp_targets() -> list[Target]:
    return _contents(_user_temp(), "User temporary files")


def _thumbnail_targets() -> list[Target]:
    explorer = _local_app_data() / "Microsoft" / "Windows" / "Explorer"
    return _files(explorer, "thumbcache*.db", "Thumbnail cache") + _files(explorer, "iconcache*.db", "Icon cache")


def _shader_targets() -> list[Target]:
    local = _local_app_data()
    paths = (
        local / "D3DSCache",
        local / "NVIDIA" / "DXCache",
        local / "NVIDIA" / "GLCache",
        local / "AMD" / "DxCache",
        local / "AMD" / "GLCache",
    )
    return [target for path in paths for target in _contents(path, "GPU shader cache")]


def _report_targets() -> list[Target]:
    base = _local_app_data() / "Microsoft" / "Windows" / "WER"
    return [target for path in (base / "ReportArchive", base / "ReportQueue", base / "Temp")
            for target in _contents(path, "Windows Error Reporting")]


def _internet_targets() -> list[Target]:
    local = _local_app_data()
    paths = (local / "Microsoft" / "Windows" / "INetCache", _user_temp() / "INetCache")
    return _dedupe([target for path in paths for target in _contents(path, "Internet cache")])


def _windows_temp_targets() -> list[Target]:
    return _contents(_windows_dir() / "Temp", "Windows Temp")


def _delivery_targets() -> list[Target]:
    return _contents(_windows_dir() / "SoftwareDistribution" / "DeliveryOptimization" / "Cache", "Delivery Optimization cache")


def _recycle_targets() -> list[Target]:
    return [Target(Path("::recycle-bin::"), TargetKind.RECYCLE_BIN, Path("::recycle-bin::"), "Windows Recycle Bin")] if IS_WINDOWS else []


CATEGORIES: tuple[Category, ...] = (
    Category("user_temp", "Tệp tạm người dùng", "TEMP/TMP trong Local AppData", True, "", _user_temp_targets),
    Category("thumbnails", "Thumbnail & icon cache", "Windows Explorer sẽ tự tạo lại", True, "", _thumbnail_targets),
    Category("shaders", "DirectX / GPU shader cache", "Cache đồ họa có thể tạo lại", True, "", _shader_targets),
    Category("reports", "Báo cáo lỗi Windows", "Windows Error Reporting của tài khoản hiện tại", True, "", _report_targets),
    Category("internet", "Internet cache hệ thống", "INetCache của tài khoản hiện tại", True, "", _internet_targets),
    Category("browser", "Cache trình duyệt", "Chrome, Edge, Brave, Firefox", False, "Đóng trình duyệt để dọn được nhiều hơn.", _browser_caches),
    Category("windows_temp", "Windows Temp", r"C:\Windows\Temp", False, "Có thể cần quyền Administrator.", _windows_temp_targets),
    Category("delivery", "Delivery Optimization", "Cache tải Windows Update", False, "Windows có thể tải lại dữ liệu khi cần.", _delivery_targets),
    Category("recycle", "Recycle Bin", "Dọn toàn bộ Thùng rác Windows", False, "Không thể hoàn tác sau khi xác nhận.", _recycle_targets),
)
CATEGORY_BY_KEY = {category.key: category for category in CATEGORIES}


def _dedupe(targets: Iterable[Target]) -> list[Target]:
    result: list[Target] = []
    seen: set[tuple[str, TargetKind]] = set()
    for target in targets:
        key = (_norm(target.path), target.kind)
        if key not in seen:
            seen.add(key)
            result.append(target)
    return result


def resolve_targets(keys: Iterable[str]) -> list[Target]:
    """Resolve a whitelisted category collection; invalid keys are ignored."""
    targets: list[Target] = []
    for key in keys:
        category = CATEGORY_BY_KEY.get(key)
        if category:
            try:
                targets.extend(category.resolver())
            except OSError:
                continue
    return _dedupe(targets)


def _cancelled(cancel: CancelCheck) -> bool:
    return bool(cancel and cancel())


def _iter_target_entries(target: Target):
    if target.kind == TargetKind.FILE:
        yield target.path
        return
    if target.kind != TargetKind.CONTENTS:
        return
    try:
        with os.scandir(target.path) as entries:
            for entry in entries:
                yield Path(entry.path)
    except (FileNotFoundError, PermissionError, OSError):
        return


def _is_target_safe(target: Target) -> bool:
    if target.kind == TargetKind.RECYCLE_BIN:
        return IS_WINDOWS
    # Re-check the fixed container just before every scan/delete. This prevents
    # a target directory being swapped for a junction after resolution.
    if not _is_under(target.path, target.boundary) or not _safe_dir(target.boundary):
        return False
    if target.kind == TargetKind.CONTENTS:
        return _safe_dir(target.path)
    # A FILE target may itself be a link: deleting that link is safe, provided
    # its containing cache boundary remains a real directory.
    return True


def _scan_entry(path: Path, report: ScanReport, cancel: CancelCheck, depth: int = 0) -> None:
    if _cancelled(cancel):
        report.cancelled = True
        return
    if depth > 128:
        report.inaccessible += 1
        return
    try:
        info = path.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        report.inaccessible += 1
        return
    if _is_reparse(path):
        report.items_found += 1
        return
    if not stat.S_ISDIR(info.st_mode):
        report.bytes_found += max(0, info.st_size)
        report.items_found += 1
        return
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                _scan_entry(Path(entry.path), report, cancel, depth + 1)
                if report.cancelled:
                    return
    except (PermissionError, OSError):
        report.inaccessible += 1


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]


def _recycle_info() -> tuple[int, int, bool]:
    if not IS_WINDOWS:
        return 0, 0, False
    info = _SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    try:
        code = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        return (max(0, int(info.i64Size)), max(0, int(info.i64NumItems)), code == 0)
    except (AttributeError, OSError):
        return 0, 0, False


def scan_targets(targets: list[Target], progress: ProgressCallback = None, cancel: CancelCheck = None) -> ScanReport:
    report = ScanReport(targets_found=len(targets))
    for target in targets:
        if _cancelled(cancel):
            report.cancelled = True
            break
        if not _is_target_safe(target):
            report.inaccessible += 1
            continue
        if progress:
            progress(f"Đang kiểm tra: {target.label}")
        if target.kind == TargetKind.RECYCLE_BIN:
            size, items, ok = _recycle_info()
            report.bytes_found += size
            report.items_found += items
            report.inaccessible += 0 if ok else 1
            continue
        if not target.path.exists() and not _is_reparse(target.path):
            continue
        for entry in _iter_target_entries(target):
            _scan_entry(entry, report, cancel)
            if report.cancelled:
                break
    return report


def _make_writable(path: Path) -> None:
    """Retry only a read-only attribute; never takes ownership or ACL control."""
    if IS_WINDOWS:
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(wintypes.LPCWSTR(os.fspath(path)))
            if attrs != INVALID_FILE_ATTRIBUTES:
                ctypes.windll.kernel32.SetFileAttributesW(wintypes.LPCWSTR(os.fspath(path)), attrs & ~0x0001)
                return
        except (AttributeError, OSError):
            pass
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass


def _record_delete_failure(report: CleanReport) -> None:
    # Sharing/permission errors are normal on an active Windows session.
    report.skipped += 1


def _delete_entry(path: Path, report: CleanReport, cancel: CancelCheck, depth: int = 0) -> None:
    if _cancelled(cancel):
        report.cancelled = True
        return
    if depth > 128:
        report.skipped += 1
        return
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except (PermissionError, OSError):
        _record_delete_failure(report)
        return
    try:
        is_reparse = _is_reparse(path)
        is_dir = stat.S_ISDIR(info.st_mode)
        if is_reparse:
            # Unlink only the link itself; never descend into its destination.
            try:
                (os.rmdir if is_dir else os.unlink)(path)
            except PermissionError:
                _make_writable(path)
                (os.rmdir if is_dir else os.unlink)(path)
            report.files_removed += 1
            return
        if not is_dir:
            size = max(0, info.st_size)
            try:
                os.unlink(path)
            except PermissionError:
                _make_writable(path)
                os.unlink(path)
            report.bytes_removed += size
            report.files_removed += 1
            return
        try:
            with os.scandir(path) as entries:
                children = [Path(entry.path) for entry in entries]
        except (PermissionError, OSError):
            _record_delete_failure(report)
            return
        for child in children:
            _delete_entry(child, report, cancel, depth + 1)
            if report.cancelled:
                return
        try:
            os.rmdir(path)
            report.folders_removed += 1
        except PermissionError:
            _make_writable(path)
            try:
                os.rmdir(path)
                report.folders_removed += 1
            except OSError:
                _record_delete_failure(report)
        except OSError:
            _record_delete_failure(report)
    except (PermissionError, OSError):
        _record_delete_failure(report)


def _empty_recycle_bin(report: CleanReport) -> None:
    size, items, available = _recycle_info()
    if not available:
        report.errors += 1
        return
    flags = 0x00000001 | 0x00000002 | 0x00000004  # no confirmation, progress UI, or sound — app already confirmed.
    try:
        result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    except (AttributeError, OSError):
        result = 1
    if result == 0:
        report.bytes_removed += size
        report.files_removed += items
    else:
        report.skipped += 1


def clean_targets(targets: list[Target], progress: ProgressCallback = None, cancel: CancelCheck = None) -> CleanReport:
    report = CleanReport()
    for target in targets:
        if _cancelled(cancel):
            report.cancelled = True
            break
        if not _is_target_safe(target):
            report.errors += 1
            continue
        if progress:
            progress(f"Đang dọn: {target.label}")
        if target.kind == TargetKind.RECYCLE_BIN:
            _empty_recycle_bin(report)
            continue
        for entry in _iter_target_entries(target):
            # Preserve each CONTENTS target root by deleting only its children.
            _delete_entry(entry, report, cancel)
            if report.cancelled:
                break
    return report


def human_bytes(value: int) -> str:
    value = max(0, int(value))
    units = ("B", "KB", "MB", "GB", "TB")
    number = float(value)
    for unit in units:
        if number < 1024.0 or unit == units[-1]:
            return f"{int(number)} B" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024.0
    return f"{number:.1f} TB"
