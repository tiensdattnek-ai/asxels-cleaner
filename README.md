# Asxels Cleaner — Native C++ Engine

A Windows desktop cleaner built as a **native C++20 engine** with a deliberately thin EXE loader. It is designed around one principle: clean known disposable data without becoming a dangerous “delete everything” tool.

[![Native build](https://img.shields.io/badge/engine-C%2B%2B20-4E8CFF?style=flat-square)](CMakeLists.txt)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-3DDBC0?style=flat-square)](#requirements)
[![License](https://img.shields.io/badge/license-MIT-9CADCB?style=flat-square)](LICENSE)

## Runtime architecture

```text
AsxelsCleaner.exe     Tiny native bootstrapper / loader only
        │  LoadLibrary (absolute sibling path)
        ▼
AsxelsEngine.dll      Native C++20 engine
        ├─ custom Win32 / GDI desktop UI
        ├─ fixed-scope cache discovery and scanning
        ├─ safe recursive cleanup engine
        ├─ process working-set optimization
        ├─ local activity logs
        └─ background workers + UI event bridge
```

The launcher finds `AsxelsEngine.dll` in **its own folder** and invokes the single exported engine entry point. This means the EXE stays thin; all functionality and logic are executed by C++ in the engine DLL. Distribute the two files together, preferably through the supplied ZIP.

## Features

- **Native C++20 only:** no Python runtime, no PyInstaller, no Electron, and no third-party runtime dependency.
- **Premium dark Windows UI:** custom-rendered native interface, high-DPI aware, responsive background workers, memory meter, keyboard shortcuts (`F5` preview, `Enter` clean, `Esc` close while idle).
- **Preview before delete:** scanning runs immediately before confirmation, so the shown amount is current.
- **Transparent reporting:** actual removed bytes/count are recorded only when a deletion succeeds; locked/protected items are reported as skipped.
- **Safe memory action:** calls Windows `EmptyWorkingSet` on accessible user processes while excluding core Windows processes. It does not kill apps or claim to create extra physical RAM.
- **Local logs:** `%LOCALAPPDATA%\AsxelsCleaner\logs\activity.log`.
- **GitHub Actions:** native x64 compilation and ZIP artifact on every push to `main`, tag `v*`, or manual dispatch.

## Cleanup scope

| Area | Default | Exact intent |
|---|:---:|---|
| User temporary files | ✓ | User TEMP only when it is inside Local AppData |
| Thumbnail & icon cache | ✓ | Explorer thumbnail and icon cache files |
| DirectX / GPU shaders | ✓ | Known D3D, NVIDIA and AMD shader-cache folders |
| Windows error reports | ✓ | Current user’s WER archive, queue, and temp folders |
| Internet cache | ✓ | Current user’s Windows INetCache |
| Browser cache |  | Chrome, Edge, Brave and Firefox cache folders only |
| Windows Temp |  | `C:\Windows\Temp`; may require Administrator permission |
| Delivery Optimization |  | Windows Update download cache; may require Administrator permission |

The engine does **not** access Documents, Downloads, Desktop, personal photos, project folders, browser history, cookies, passwords, the Registry, services, or startup settings.

### Important browser note

Close browsers before selecting browser cache. Cookies, browsing history and saved passwords are never targets; files in use are skipped rather than forced out.

## Safety model

- No arbitrary path field exists in the UI or the engine API.
- Every cleanup target is constructed in code from Windows known folders and fixed cache subpaths.
- Recursive walking uses Win32 enumeration and refuses to traverse `FILE_ATTRIBUTE_REPARSE_POINT` (junctions and symbolic links).
- Read-only cache entries may be retried after their readonly attribute is cleared. Locked or protected entries are never forced by ownership changes, process termination, or unsafe shell commands.
- The destructive action requires scan → explicit confirmation → cleanup.

See [SECURITY.md](SECURITY.md) for the full policy.

## Requirements

- Windows 10 or Windows 11, x64
- For source builds: CMake 3.24+ and Visual Studio 2022 Build Tools / Visual Studio with **Desktop development with C++**

## Build a distributable package

### Fast route

Run `BUILD_EXE.bat` on Windows. It configures, compiles, installs, and creates:

```text
dist/
 ├─ AsxelsCleaner.exe             # thin native loader
 ├─ AsxelsEngine.dll              # full C++ engine
 └─ AsxelsCleaner-Windows-x64.zip # distribute this file
```

### PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\BUILD_EXE.ps1
```

### CMake directly

```powershell
cmake -S . -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release --parallel
cmake --install build --config Release --prefix dist
```

## CI / download an EXE package

The workflow at `.github/workflows/build-windows.yml` builds on `windows-latest` and uploads artifact **`AsxelsCleaner-Windows-x64`**. The artifact contains both runtime files and the ZIP. Download it from the relevant GitHub Actions run.

## Engineering notes

- Engine/UI code: `src/engine.cpp`
- Exported ABI: `src/engine.hpp`
- Minimal secure loader: `src/launcher.cpp`
- Build system: `CMakeLists.txt`
- Version information for the loader: `src/app.rc`

This application is intentionally conservative. “Cleaning more aggressively” is not considered an improvement if it expands into personal data or makes a system unstable.

## License

MIT © 2026 Asxels
