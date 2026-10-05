# Asxels Cleaner — Python Edition

A polished, safety-first Windows cache cleaner written **entirely in Python** and packaged as one standalone `.exe` using PyInstaller.

![Engine](https://img.shields.io/badge/engine-Python%203.10%2B-4D8CFF?style=flat-square) ![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-42D8C0?style=flat-square) ![License](https://img.shields.io/badge/license-MIT-9DAECB?style=flat-square)

## What changed in v3

- **100% Python source:** the C++ loader/DLL architecture was removed.
- **One-file distribution:** `AsxelsCleaner.exe` is created by PyInstaller and does not require a C++ DLL or a preinstalled Python runtime.
- **Improved engine boundaries:** every cleanup target carries its own fixed root boundary; an out-of-bound target is refused before scan or deletion.
- **Cancelable background tasks:** scanning, cleanup, and memory trim run off the UI thread and can be stopped between items.
- **Optional Recycle Bin cleanup:** opt-in only, unselected by default, and always included in the final irreversible-action warning.
- **More transparent results:** actual removed bytes are counted only after a successful deletion; skipped/blocked files are shown separately.

## Features

- Modern dark Windows desktop UI using Tkinter/ttk — no web browser, Electron, telemetry, or adware.
- Scan before cleanup, then scan again immediately before the destructive confirmation.
- User Temp, thumbnail/icon cache, DirectX/GPU shader cache, Windows Error Reporting, and current-user Internet cache enabled by default.
- Optional browser cache, Windows Temp, Delivery Optimization, and Recycle Bin cleanup.
- Browser cleanup targets cache folders only: **no** passwords, cookies, or browsing history.
- Safe link handling: symbolic links and Windows junction/reparse points are never traversed.
- Files locked by an app or protected by Windows are skipped — no ownership takeover, forced process termination, or blind shell-delete commands.
- Local-only history and activity log: `%LOCALAPPDATA%\AsxelsCleaner\logs\activity.log`.
- Windows memory telemetry plus conservative `EmptyWorkingSet` optimization for accessible non-critical user processes.
- Keyboard shortcuts: `F5` preview, `Enter` safe cleanup flow, `Esc` request cancellation.

## Cleanup scope

| Category | Default | Scope |
|---|:---:|---|
| User temporary files | ✓ | User TEMP/TMP only when inside Local AppData |
| Thumbnail & icon cache | ✓ | Explorer cache files only |
| DirectX / GPU shader cache | ✓ | Known D3D, NVIDIA, and AMD cache locations |
| Windows error reports | ✓ | Current user WER archive, queue, and temp folders |
| Internet cache | ✓ | Current-user Windows INetCache |
| Browser cache |  | Chrome, Edge, Brave, and Firefox cache folders only |
| Windows Temp |  | `C:\Windows\Temp`; may need Administrator permission |
| Delivery Optimization |  | Windows Update download cache; may be regenerated |
| Recycle Bin |  | Entire Windows Recycle Bin; irreversible after confirmation |

The app does **not** target Documents, Downloads, Desktop, personal files, project folders, the Registry, startup settings, Windows services, cookies, passwords, or browser history.

## Build the EXE with PyInstaller

### Fast route

On a Windows machine with Python 3.10 or newer, run:

```bat
BUILD_EXE.bat
```

Output:

```text
dist\AsxelsCleaner.exe
```

The result is a **single, windowed EXE** with Python and the app code embedded by PyInstaller.

### PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\BUILD_EXE.ps1
```

### Manual build

```bat
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean --windowed --onefile --name AsxelsCleaner --version-file version_info.txt --collect-all tkinter main.py
```

A new unsigned executable may trigger Microsoft SmartScreen. Build from this reviewed source or sign the EXE before commercial release.

## GitHub Actions

`.github/workflows/build-windows.yml` runs safety tests and packages `AsxelsCleaner.exe` on Windows x64 whenever `main` is pushed, a `v*` tag is pushed, or the workflow is started manually. Download artifact **`AsxelsCleaner-Windows-x64`** from the completed run.

## Optional command line usage

The GUI is the recommended mode. A narrowly scoped CLI exists for controlled automation:

```bat
:: Preview only the per-user temporary cache
python main.py --scan

:: Explicitly clean two safe categories
python main.py --clean --yes --categories user_temp,thumbnails
```

Valid keys: `user_temp`, `thumbnails`, `shaders`, `reports`, `internet`, `browser`, `windows_temp`, `delivery`, `recycle`.

`--clean` refuses to execute unless `--yes` is also present.

## Project layout

```text
asxels_cleaner/
  engine.py      fixed-scope scan/delete engine
  memory.py      Windows memory telemetry and working-set trim
  storage.py     local-only log and small history summary
  ui.py          responsive Tkinter desktop UI
main.py          GUI / explicit CLI entry point
BUILD_EXE.*      PyInstaller packaging scripts
requirements.txt build-only dependency declaration
tests/           portable safety and accounting tests
```

## Safety policy

See [SECURITY.md](SECURITY.md). More aggressive deletion is not treated as an improvement if it expands into personal data or destabilizes Windows.

## License

MIT © 2026 Asxels
