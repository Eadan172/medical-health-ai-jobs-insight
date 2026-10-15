#Requires -Version 5.1
<#
.SYNOPSIS
  Pull main, run the jobs pipeline with the gitignored local config, and push data only if it validates.

.DESCRIPTION
  Uses automation\.venv\Scripts\python.exe explicitly and sets PLAYWRIGHT_BROWSERS_PATH to
  automation\.venv\ms-playwright. Does not activate or modify conda environments.
  Browser login is not performed here; run browser-login in a visible terminal first.
#>
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvPython = Join-Path $RepoRoot "automation\.venv\Scripts\python.exe"
$Browsers = Join-Path $RepoRoot "automation\.venv\ms-playwright"
$LocalConfig = Join-Path $RepoRoot "automation\config.local.toml"
$Validator = Join-Path $RepoRoot "automation\scripts\validate_publish.py"
$LogDir = Join-Path $RepoRoot "automation\state"

function Exit-Run {
    param([string]$Message, [int]$Code = 1)
    Write-Host $Message
    exit $Code
}

function Assert-Exit {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        Exit-Run "$Step failed with exit code $LASTEXITCODE" $LASTEXITCODE
    }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Exit-Run "Missing $VenvPython. Use the Python 3.12 venv at automation\.venv. Do not change conda environments."
}
if (-not (Test-Path -LiteralPath $LocalConfig)) {
    Exit-Run "Missing $LocalConfig. Copy automation\config.local.example.toml to automation\config.local.toml."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
try { Start-Transcript -Path (Join-Path $LogDir "local-run.log") -Append | Out-Null } catch { }

$env:PLAYWRIGHT_BROWSERS_PATH = $Browsers
$env:PYTHONPATH = Join-Path $RepoRoot "automation"
$env:JOBSINSIGHT_CONFIG = $LocalConfig

Write-Host "Repo: $RepoRoot"
Write-Host "Python: $VenvPython"
Write-Host "PLAYWRIGHT_BROWSERS_PATH: $Browsers"
Write-Host "Config: $LocalConfig"

git -C $RepoRoot fetch origin main
Assert-Exit "git fetch"
$branch = "$(git -C $RepoRoot rev-parse --abbrev-ref HEAD)".Trim()
Assert-Exit "git rev-parse"
if ($branch -ne "main") {
    Exit-Run "The daily task must run on branch main (current: $branch). Use a clone that tracks main."
}
git -C $RepoRoot pull --ff-only origin main
Assert-Exit "git pull"

& $VenvPython -m jobsinsight run --config $LocalConfig --trigger local-windows
Assert-Exit "jobsinsight run"

& $VenvPython $Validator $RepoRoot
Assert-Exit "publish validation"

$porcelain = @(git -C $RepoRoot status --porcelain -- web/public/data)
Assert-Exit "git status"
if (-not $porcelain) {
    Write-Host "No changes under web/public/data. Nothing to commit."
    exit 0
}

git -C $RepoRoot add -- web/public/data
Assert-Exit "git add"
$when = Get-Date -Format "yyyy-MM-dd HH:mm"
git -C $RepoRoot commit -m "chore(data): local job data update $when" -- web/public/data
Assert-Exit "git commit"
git -C $RepoRoot push origin main
Assert-Exit "git push"
Write-Host "Pushed web/public/data."
