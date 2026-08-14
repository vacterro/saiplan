param([switch]$AllowDirty, [switch]$SkipBuild)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Version = (Get-Content (Join-Path $Root "VERSION") -Raw).Trim()
$GitStatus = git -C $Root status --porcelain
if ($LASTEXITCODE -ne 0) { throw "git status failed" }
if (-not $AllowDirty -and $GitStatus) { throw "portable release requires a clean tracked worktree" }
if (-not $SkipBuild) {
  & (Join-Path $Root "build_windows.ps1") -AllowDirty:$AllowDirty
  if ($LASTEXITCODE -ne 0) { throw "portable build failed" }
}
$Dist = Join-Path $Root "dist\SAIPLAN"
python (Join-Path $Root "scripts\verify_release.py") portable --source $Root --root $Dist
if ($LASTEXITCODE -ne 0) { throw "portable verification failed" }
$Zip = Join-Path $Root "dist\SAIPLAN-$Version-windows-x64.zip"
Remove-Item -Force $Zip -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $Dist "*") -DestinationPath $Zip -CompressionLevel Optimal
Write-Host "PASS: $Zip"
