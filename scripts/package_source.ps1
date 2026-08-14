param([switch]$AllowDirty)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Version = (Get-Content (Join-Path $Root "VERSION") -Raw).Trim()
$Stage = Join-Path $Root "build\source-package\SAIPLAN-$Version-source"
$Zip = Join-Path $Root "dist\SAIPLAN-$Version-source.zip"
$GitStatus = git -C $Root status --porcelain
if ($LASTEXITCODE -ne 0) { throw "git status failed" }
if (-not $AllowDirty -and $GitStatus) {
  throw "source release requires a clean tracked worktree"
}
Remove-Item -Recurse -Force (Split-Path -Parent $Stage) -ErrorAction SilentlyContinue
Remove-Item -Force $Zip -ErrorAction SilentlyContinue
$AllowedDirs = @("src/", "tests/", "docs/", "themes/", "sounds/", "scripts/")
$AllowedFiles = @("README.md", "CHANGELOG.md", "VERSION", "pyproject.toml", ".gitignore", "main.py", "build_windows.ps1", "bootstrap-build-env.ps1", "requirements-build.lock")
$Files = git -C $Root ls-files
if ($AllowDirty) {
  $Files += git -C $Root ls-files --others --exclude-standard
  if ($LASTEXITCODE -ne 0) { throw "git untracked-file scan failed" }
  $Files = $Files | Sort-Object -Unique
}
foreach ($Relative in $Files) {
  $Normalized = $Relative.Replace("\", "/")
  $Allowed = $AllowedFiles -contains $Normalized
  foreach ($Prefix in $AllowedDirs) { if ($Normalized.StartsWith($Prefix)) { $Allowed = $true } }
  if (-not $Allowed) { continue }
  $Destination = Join-Path $Stage $Relative
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
  Copy-Item -LiteralPath (Join-Path $Root $Relative) -Destination $Destination
}
python (Join-Path $Root "scripts\verify_release.py") source --root $Stage
if ($LASTEXITCODE -ne 0) { throw "source package verification failed" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Zip) | Out-Null
Compress-Archive -Path $Stage -DestinationPath $Zip -CompressionLevel Optimal
Write-Host "PASS: $Zip"
