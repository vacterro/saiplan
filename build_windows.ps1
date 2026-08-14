param([switch]$AllowDirty)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Build = Join-Path $Root "build"
$DistRoot = Join-Path $Root "dist"
$Dist = Join-Path $DistRoot "SAIPLAN"

$GitStatus = git -C $Root status --porcelain
if ($LASTEXITCODE -ne 0) { throw "git status failed" }
if (-not $AllowDirty -and $GitStatus) {
  throw "release build requires a clean tracked worktree"
}
if (-not $IsWindows -and $PSVersionTable.PSVersion.Major -ge 6) {
  throw "Windows build requires Windows"
}
$Python = Join-Path $Root ".build-venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "run bootstrap-build-env.ps1 first" }
$PythonBits = & $Python -c "import struct; print(struct.calcsize('P') * 8)"
if ($LASTEXITCODE -ne 0 -or $PythonBits -ne "64") { throw "64-bit Python required" }
$VersionOutput = & $Python -m nuitka --version
if ($LASTEXITCODE -ne 0) { throw "Nuitka version check failed" }
$NuitkaVersion = $VersionOutput[0]
if ($NuitkaVersion -ne "4.1.3") {
  throw "Nuitka 4.1.3 required; run bootstrap-build-env.ps1"
}

Remove-Item -Recurse -Force $Build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $Dist -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Build, $Dist | Out-Null
$IdentityBefore = Join-Path $Build "source-before.sha256"
$IdentityAfter = Join-Path $Build "source-after.sha256"
& $Python (Join-Path $Root "scripts\verify_release.py") identity --root $Root --output $IdentityBefore
if ($LASTEXITCODE -ne 0) { throw "pre-build source identity failed" }

& $Python -m nuitka `
  --standalone `
  --windows-console-mode=disable `
  --enable-plugin=pyqt6 `
  --assume-yes-for-downloads `
  --include-package=saiplan `
  --output-dir=$Build `
  (Join-Path $Root "main.py")
if ($LASTEXITCODE -ne 0) { throw "Nuitka compile failed" }
& $Python (Join-Path $Root "scripts\verify_release.py") identity --root $Root --output $IdentityAfter
if ($LASTEXITCODE -ne 0) { throw "post-build source identity failed" }
if ((Get-Content $IdentityBefore -Raw) -ne (Get-Content $IdentityAfter -Raw)) {
  throw "source changed during build; artifact rejected"
}

Copy-Item -Force -Recurse (Join-Path $Build "main.dist\*") $Dist
if (Test-Path (Join-Path $Dist "main.exe")) {
  Rename-Item (Join-Path $Dist "main.exe") "SAIPLAN.exe"
}
Copy-Item -Force -Recurse (Join-Path $Root "themes") $Dist
Copy-Item -Force -Recurse (Join-Path $Root "sounds") $Dist
New-Item -ItemType Directory -Force -Path (Join-Path $Dist "data\plans") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Dist "logs") | Out-Null

Copy-Item -Force $IdentityBefore (Join-Path $Dist "BUILD-SOURCE.sha256")
& $Python (Join-Path $Root "scripts\verify_release.py") portable --source $Root --root $Dist --write-manifest
if ($LASTEXITCODE -ne 0) { throw "portable manifest verification failed" }

$Smoke = Join-Path $env:TEMP ("SAIPLAN-smoke-" + [guid]::NewGuid().ToString("N"))
Copy-Item -Recurse $Dist $Smoke
try {
  $env:SAIPLAN_ROOT = $Smoke
  $env:QT_QPA_PLATFORM = "offscreen"
  $env:SAIPLAN_AUTOQUIT_MS = "1500"
  $Process = Start-Process -FilePath (Join-Path $Smoke "SAIPLAN.exe") -PassThru -Wait
  if ($Process.ExitCode -ne 0) { throw "portable smoke failed: rc=$($Process.ExitCode)" }
} finally {
  Remove-Item Env:SAIPLAN_ROOT -ErrorAction SilentlyContinue
  Remove-Item Env:SAIPLAN_AUTOQUIT_MS -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force $Smoke -ErrorAction SilentlyContinue
}

Write-Host "PASS: $Dist"
