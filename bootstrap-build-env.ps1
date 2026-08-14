$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".build-venv"
Remove-Item -Recurse -Force $Venv -ErrorAction SilentlyContinue
python -m venv $Venv
$Python = Join-Path $Venv "Scripts\python.exe"
& $Python -m pip install --upgrade "pip==26.0.1"
& $Python -m pip install -r (Join-Path $Root "requirements-build.lock")
if ($LASTEXITCODE -ne 0) { throw "build environment bootstrap failed" }
& $Python -m pip install --no-deps --no-build-isolation -e "$Root"
if ($LASTEXITCODE -ne 0) { throw "editable install failed" }
Write-Host "PASS: $Venv"
