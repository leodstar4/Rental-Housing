# Windows wrapper for the hour-16 runbook.
#   .\scripts\hour16.ps1 path\to\ordinance.pdf [-Jurisdiction "Cambridge, MA"] [-DryRun] [-NoGit]
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$Jurisdiction,
    [switch]$DryRun,
    [switch]$NoGit
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
if (-not ($env:Path -like "*Git\cmd*")) { $env:Path += ";C:\Program Files\Git\cmd" }
$env:PYTHONIOENCODING = "utf-8"
$args_ = @((Join-Path $root "scripts\hour16.py"), $Path)
if ($Jurisdiction) { $args_ += @("--jurisdiction", $Jurisdiction) }
if ($DryRun) { $args_ += "--dry-run" }
if ($NoGit) { $args_ += "--no-git" }
Push-Location $root
try { & $python @args_; exit $LASTEXITCODE } finally { Pop-Location }
