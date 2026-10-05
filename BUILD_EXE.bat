@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ===============================================
echo  Asxels Cleaner v3 - Python EXE Builder
echo ===============================================

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Khong tim thay Python trong PATH.
  echo Cai Python 3.10+ tai https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto :failed

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name "AsxelsCleaner" ^
  --version-file "version_info.txt" ^
  --collect-all tkinter ^
  main.py
if errorlevel 1 goto :failed

echo.
echo [OK] Da tao: dist\AsxelsCleaner.exe
echo EXE nay la app Python da dong goi day du bang PyInstaller, khong can C++ DLL hay Python cai san.
pause
exit /b 0

:failed
echo.
echo [ERROR] Build that bai. Xem thong bao ben tren.
pause
exit /b 1
