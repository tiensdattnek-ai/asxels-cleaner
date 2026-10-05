@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ===========================================
echo  Asxels Cleaner - Windows EXE Builder
echo ===========================================

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Khong tim thay Python trong PATH.
  echo Cai Python 3.10+ tai https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name "AsxelsCleaner" ^
  --version-file "version_info.txt" ^
  --add-data "LICENSE;." ^
  main.py

if errorlevel 1 (
  echo.
  echo [ERROR] Build that bai. Xem thong bao ben tren.
  pause
  exit /b 1
)

echo.
echo [OK] Da tao: dist\AsxelsCleaner.exe
echo Kiem tra Microsoft Defender SmartScreen neu day la ban build moi chua ky code.
pause
