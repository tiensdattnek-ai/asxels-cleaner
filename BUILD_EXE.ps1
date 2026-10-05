$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host '== Asxels Cleaner v2 - Native C++ Builder ==' -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
cmake -S . -B build -G 'Visual Studio 17 2022' -A x64
cmake --build build --config Release --parallel
cmake --install build --config Release --prefix dist
Compress-Archive -Path 'dist\AsxelsCleaner.exe', 'dist\AsxelsEngine.dll' -DestinationPath 'dist\AsxelsCleaner-Windows-x64.zip' -Force
Write-Host 'Done: dist\AsxelsCleaner-Windows-x64.zip' -ForegroundColor Green
