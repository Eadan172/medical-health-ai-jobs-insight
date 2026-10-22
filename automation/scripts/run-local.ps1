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
if (-not $env:JOBSINSIGHT_BROWSER_CHANNEL) { $env:JOBSINSIGHT_BROWSER_CHANNEL = 'chrome' }
if (-not $env:JOBSINSIGHT_USER_AGENT) { $env:JOBSINSIGHT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36' }

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

$Reporter = Join-Path $PSScriptRoot "send_report.py"
$RunLog = Join-Path $LogDir "last-run.json.log"
foreach ($n in 'MAIL163_SMTP_USER','MAIL163_SMTP_AUTH_CODE','JOBSINSIGHT_REPORT_TO') {
    if (-not (Get-Item "env:$n" -ErrorAction SilentlyContinue)) {
        $v = [Environment]::GetEnvironmentVariable($n, 'User'); if ($v) { Set-Item "env:$n" $v }
    }
}
$env:PYTHONIOENCODING = "utf-8"
# Data is NOT pushed. The run writes web/public/data locally, the report is mailed, then the data files are restored.
$prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
& $VenvPython -m jobsinsight --config $LocalConfig run --trigger local-windows 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $RunLog | Out-Host
$runExit = $LASTEXITCODE; $ErrorActionPreference = $prevEap
$fatal = ""
if ($runExit -ne 0) { $fatal = "jobsinsight run 退出码 $runExit，详见 $RunLog" }
else {
    & $VenvPython $Validator $RepoRoot
    if ($LASTEXITCODE -ne 0) { $fatal = "数据校验失败（publish validation）" }
}
& $VenvPython $Reporter $RunLog $fatal
$mailExit = $LASTEXITCODE
# 岗位正文在 web/public/data，发信后还原，避免把抓取结果提交或推送。
# automation/state/jobs_snapshot.json 不入库，但必须留在本机：里面记着 first_seen，用来判断「今日新增」。
# automation/state/cadd_report_state.json 同样留在本机，用来比较上次「硕士可投」数量。
git -C $RepoRoot checkout -- web/public/data
git -C $RepoRoot clean -fdq -- web/public/data
if ($mailExit -ne 0) { Exit-Run "report mail failed" $mailExit }
if ($fatal) { exit 1 }
exit 0