$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host '== Asxels Cleaner v3 - Python EXE Builder ==' -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
python -m PyInstaller --noconfirm --clean --windowed --onefile `
  --name 'AsxelsCleaner' `
  --version-file 'version_info.txt' `
  --collect-all tkinter `
  main.py
Write-Host 'Done: dist\AsxelsCleaner.exe' -ForegroundColor Green
