# Build a portable SAIPLAN folder with Nuitka (Windows 10/11 x64).
# Requires: MSVC build tools, Python 3.11+, `pip install -e .[build,dev]`
#
# Result: dist\SAIPLAN\SAIPLAN.exe + data/ + themes/ + sounds/ + logs/
# Move/copy the whole folder to move the complete installation (I14).

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "== SAIPLAN portable build =="

python -m pip install --quiet --upgrade nuitka zstandard ordered-set
if ($LASTEXITCODE -ne 0) { throw "nuitka install failed" }

Write-Host "== compiling with Nuitka =="
python -m nuitka `
  --standalone `
  --windows-console-mode=disable `
  --enable-plugin=pyqt6 `
  --assume-yes-for-downloads `
  --include-package=saiplan `
  --output-dir=build `
  main.py
if ($LASTEXITCODE -ne 0) { throw "nuitka compile failed" }

$Dist = "dist\SAIPLAN"
Write-Host "== assembling portable folder: $Dist =="
New-Item -ItemType Directory -Force -Path "$Dist\data\plans" | Out-Null
New-Item -ItemType Directory -Force -Path "$Dist\logs" | Out-Null
Copy-Item -Force -Recurse build\main.dist\* $Dist
if (Test-Path "$Dist\main.exe") {
  Rename-Item -Force "$Dist\main.exe" "SAIPLAN.exe"
}
Copy-Item -Force -Recurse themes $Dist
Copy-Item -Force -Recurse sounds $Dist
if (-not (Test-Path "$Dist\SAIPLAN.exe")) {
  throw "SAIPLAN.exe not found in build output"
}

Write-Host "== verify: launching headless auto-quit smoke =="
$env:SAIPLAN_ROOT = $Dist
$env:QT_QPA_PLATFORM = "offscreen"
$env:SAIPLAN_AUTOQUIT_MS = "1500"
& "$Dist\SAIPLAN.exe"
if ($LASTEXITCODE -ne 0) { throw "built SAIPLAN.exe failed to launch (rc=$LASTEXITCODE)" }

Write-Host ""
Write-Host "DONE: $Dist"
Write-Host "Copy this whole folder anywhere; data lives inside it."
