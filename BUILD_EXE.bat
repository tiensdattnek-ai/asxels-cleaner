@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================
echo  Asxels Cleaner v2 - Native C++ Windows Builder
echo ================================================

where cmake >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Khong tim thay CMake. Cai Visual Studio 2022 Build Tools voi Desktop development with C++.
  echo https://visualstudio.microsoft.com/downloads/
  pause
  exit /b 1
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

cmake -S . -B build -G "Visual Studio 17 2022" -A x64
if errorlevel 1 goto :failed
cmake --build build --config Release --parallel
if errorlevel 1 goto :failed
cmake --install build --config Release --prefix dist
if errorlevel 1 goto :failed

powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\AsxelsCleaner.exe','dist\AsxelsEngine.dll' -DestinationPath 'dist\AsxelsCleaner-Windows-x64.zip' -Force"
echo.
echo [OK] Da tao:
echo      dist\AsxelsCleaner.exe   ^(thin native loader^)
echo      dist\AsxelsEngine.dll    ^(C++ cleanup and UI engine^)
echo      dist\AsxelsCleaner-Windows-x64.zip
pause
exit /b 0

:failed
echo.
echo [ERROR] Build that bai. Xem thong bao ben tren.
pause
exit /b 1
