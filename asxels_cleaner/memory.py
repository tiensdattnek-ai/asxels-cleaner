"""Conservative Windows memory telemetry and working-set trim helper."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import platform
from typing import Callable, Optional

IS_WINDOWS = platform.system() == "Windows"


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
    """Return total RAM, available RAM and Windows' current used percent."""
    if not IS_WINDOWS:
        return 0, 0, 0
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys), int(status.ullAvailPhys), int(status.dwMemoryLoad)
    except (AttributeError, OSError):
        pass
    return 0, 0, 0


def _configure_apis() -> tuple[object, object]:
    kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    psapi.EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    psapi.EnumProcesses.restype = wintypes.BOOL
    psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    psapi.EmptyWorkingSet.restype = wintypes.BOOL
    return kernel32, psapi


def _image_name(kernel32: object, handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buffer))
    try:
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name.lower()
    except (AttributeError, OSError):
        pass
    return ""


def trim_working_sets(progress: Optional[Callable[[str], None]] = None,
                      cancel: Optional[Callable[[], bool]] = None) -> tuple[int, int]:
    """Ask Windows to trim accessible user-process working sets.

    It never closes a process and intentionally excludes critical Windows
    processes. Windows remains responsible for physical-memory management.
    """
    if not IS_WINDOWS:
        return 0, 0
    try:
        kernel32, psapi = _configure_apis()
        pids = (wintypes.DWORD * 8192)()
        required = wintypes.DWORD()
        if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(required)):
            return 0, 0
        excluded = {
            "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
            "lsass.exe", "fontdrvhost.exe", "dwm.exe", "memory compression",
        }
        process_access = 0x1000 | 0x0100  # PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_QUOTA
        own_pid = os.getpid()
        tried = trimmed = 0
        count = min(len(pids), required.value // ctypes.sizeof(wintypes.DWORD))
        for pid_raw in pids[:count]:
            if cancel and cancel():
                break
            pid = int(pid_raw)
            if pid <= 4 or pid == own_pid:
                continue
            handle = kernel32.OpenProcess(process_access, False, pid)
            if not handle:
                continue
            try:
                name = _image_name(kernel32, handle)
                # Do not trim an unnamed process: it may be a protected/system process.
                if not name or name in excluded:
                    continue
                tried += 1
                if psapi.EmptyWorkingSet(handle):
                    trimmed += 1
            finally:
                kernel32.CloseHandle(handle)
        if progress:
            progress(f"Windows đã xử lý {trimmed}/{tried} tiến trình người dùng phù hợp")
        return tried, trimmed
    except (AttributeError, OSError):
        return 0, 0
