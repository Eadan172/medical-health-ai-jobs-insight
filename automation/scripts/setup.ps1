#Requires -Version 5.1
<#
.SYNOPSIS
  Create automation\.venv, install deps, copy local config, and prompt for the LLM API key.

.DESCRIPTION
  Idempotent. Existing config.local.toml, accounts.toml, and a non-empty API key are left in place.
  Does not activate, modify, or delete conda, and does not install into the global Python.
#>
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvDir = Join-Path $RepoRoot "automation\.venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Browsers = Join-Path $VenvDir "ms-playwright"
$EnvFile = Join-Path $RepoRoot ".env.local"
$Automation = Join-Path $RepoRoot "automation"

function Exit-Setup {
    param([string]$Message, [int]$Code = 1)
    Write-Host $Message
    exit $Code
}

if ($env:CONDA_PREFIX -or $env:CONDA_DEFAULT_ENV) {
    Write-Host "当前终端里有 conda。本脚本不会改它，只使用 py -3.12 创建 automation\.venv。"
}

$base = $null
try {
    $base = (& py -3.12 -c "import sys; print(sys.executable)").Trim()
} catch {
    Exit-Setup "找不到 Python 3.12（py -3.12）。请从 https://www.python.org/downloads/windows/ 安装，并保留 py launcher。不要使用 conda，也不要在全局环境里 pip install。"
}
if (-not $base) {
    Exit-Setup "py -3.12 没有返回解释器路径。"
}

& $base -c "import sys; conda = 'conda' in sys.prefix.lower() or 'conda' in sys.base_prefix.lower(); raise SystemExit(0 if sys.version_info[:2] == (3, 12) and not conda else 1)"
if ($LASTEXITCODE -ne 0) {
    Exit-Setup "py -3.12 不是 Python 3.12，或指向 conda。请安装 python.org 的 Python 3.12。本脚本不会改动 conda。"
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $base -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Exit-Setup "创建 automation\.venv 失败。" $LASTEXITCODE }
}

& $VenvPython -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) {
    Exit-Setup "automation\.venv 不是 Python 3.12。删除该目录后重跑本脚本。不要改用 conda。"
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Exit-Setup "pip 升级失败。" $LASTEXITCODE }

Push-Location $Automation
try {
    & $VenvPython -m pip install -e ".[browser,yaml]" tzdata
    if ($LASTEXITCODE -ne 0) { Exit-Setup "pip install -e `".[browser,yaml]`" tzdata 失败。" $LASTEXITCODE }
} finally {
    Pop-Location
}

$env:PLAYWRIGHT_BROWSERS_PATH = $Browsers
& $VenvPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Exit-Setup "playwright install chromium 失败。" $LASTEXITCODE }

function Copy-IfMissing {
    param([string]$Source, [string]$Dest)
    if (Test-Path -LiteralPath $Dest) {
        Write-Host "已有 $Dest，未覆盖"
    } else {
        Copy-Item -LiteralPath $Source -Destination $Dest
        Write-Host "已复制 $Dest"
    }
}

Copy-IfMissing (Join-Path $Automation "config.local.example.toml") (Join-Path $Automation "config.local.toml")
Copy-IfMissing (Join-Path $Automation "config\accounts.example.toml") (Join-Path $Automation "config\accounts.toml")

function Invoke-EnvEdit {
    param([string]$Code)
    $env:JOBSINSIGHT_SETUP_FILE = $EnvFile
    & $VenvPython -c $Code
    $exit = $LASTEXITCODE
    Remove-Item Env:JOBSINSIGHT_SETUP_FILE -ErrorAction SilentlyContinue
    Remove-Item Env:JOBSINSIGHT_SETUP_NAME -ErrorAction SilentlyContinue
    Remove-Item Env:JOBSINSIGHT_SETUP_VALUE -ErrorAction SilentlyContinue
    if ($exit -ne 0) { Exit-Setup "写入 .env.local 失败。" $exit }
}

function Get-EnvFileValue {
    param([string]$Name)
    $env:JOBSINSIGHT_SETUP_FILE = $EnvFile
    $env:JOBSINSIGHT_SETUP_NAME = $Name
    $value = & $VenvPython -c @"
import os
from pathlib import Path
path = Path(os.environ['JOBSINSIGHT_SETUP_FILE'])
name = os.environ['JOBSINSIGHT_SETUP_NAME']
prefix = name + '='
if not path.is_file():
    raise SystemExit(0)
for line in path.read_text(encoding='utf-8').splitlines():
    stripped = line.strip()
    if stripped.startswith('export '):
        stripped = stripped[7:].strip()
    if stripped.startswith(prefix):
        print(stripped[len(prefix):], end='')
        break
"@
    Remove-Item Env:JOBSINSIGHT_SETUP_NAME -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -ne 0) { Exit-Setup "读取 .env.local 失败。" $LASTEXITCODE }
    return "$value".Trim()
}

function Set-EnvFileValue {
    param([string]$Name, [string]$Value)
    $env:JOBSINSIGHT_SETUP_NAME = $Name
    $env:JOBSINSIGHT_SETUP_VALUE = $Value
    Invoke-EnvEdit @"
import os
from pathlib import Path
path = Path(os.environ['JOBSINSIGHT_SETUP_FILE'])
name = os.environ['JOBSINSIGHT_SETUP_NAME']
value = os.environ['JOBSINSIGHT_SETUP_VALUE']
lines = path.read_text(encoding='utf-8').splitlines() if path.is_file() else []
prefix = name + '='
found = False
out = []
for line in lines:
    stripped = line.strip()
    body = stripped[7:].strip() if stripped.startswith('export ') else stripped
    if body.startswith(prefix):
        out.append(prefix + value)
        found = True
    else:
        out.append(line)
if not found:
    if out and out[-1] != '':
        out.append('')
    out.append(prefix + value)
path.write_text('\n'.join(out) + '\n', encoding='utf-8')
"@
}

$existing = Get-EnvFileValue "JOBSINSIGHT_LLM_API_KEY"
if ($existing) {
    Write-Host "已有 JOBSINSIGHT_LLM_API_KEY，未覆盖。要更换请编辑 .env.local。"
} elseif ($env:JOBSINSIGHT_LLM_API_KEY) {
    Set-EnvFileValue "JOBSINSIGHT_LLM_API_KEY" $env:JOBSINSIGHT_LLM_API_KEY
    Write-Host "已把当前环境中的 JOBSINSIGHT_LLM_API_KEY 写入 .env.local。"
} else {
    $interactive = $false
    try { $interactive = -not [Console]::IsInputRedirected } catch { $interactive = $true }
    if ($interactive) {
        $key = Read-Host "DeepSeek API Key（直接回车表示暂不填写，流水线用规则解析）"
        if ($key) {
            Set-EnvFileValue "JOBSINSIGHT_LLM_API_KEY" $key
            Write-Host "已写入 .env.local。该文件已被 gitignore，不要提交。"
        } else {
            Write-Host "未填写 API Key。没有密钥时不会请求模型，富化和日报洞察回退到规则解析。"
        }
    } else {
        Write-Host "没有交互终端。请把 JOBSINSIGHT_LLM_API_KEY 写入 $EnvFile 后重跑。"
    }
}

$interactive = $false
try { $interactive = -not [Console]::IsInputRedirected } catch { $interactive = $true }
if ($interactive) {
    $mailUser = Get-EnvFileValue "MAIL163_SMTP_USER"
    $mailCode = Get-EnvFileValue "MAIL163_SMTP_AUTH_CODE"
    $mailTo = Get-EnvFileValue "JOBSINSIGHT_REPORT_TO"
    if ($mailUser -and $mailCode -and $mailTo) {
        Write-Host "邮件变量已在 .env.local 中，未覆盖。"
    } else {
        $answer = Read-Host "现在配置 163 日报吗？直接回车跳过。[y/N]"
        if ($answer -eq "y" -or $answer -eq "Y") {
            $mailUser = Read-Host "MAIL163_SMTP_USER（完整邮箱，如 name@163.com）"
            $mailCode = Read-Host "MAIL163_SMTP_AUTH_CODE（SMTP 授权码，不是登录密码）"
            $mailTo = Read-Host "JOBSINSIGHT_REPORT_TO（收件人）"
            if ($mailUser) { Set-EnvFileValue "MAIL163_SMTP_USER" $mailUser }
            if ($mailCode) { Set-EnvFileValue "MAIL163_SMTP_AUTH_CODE" $mailCode }
            if ($mailTo) { Set-EnvFileValue "JOBSINSIGHT_REPORT_TO" $mailTo }
            Write-Host "邮件变量已写入 .env.local。发信使用 smtp.163.com:465。"
        }
    }
}

Write-Host ""
Write-Host "准备完成。虚拟环境：automation\.venv"
Write-Host "浏览器目录：PLAYWRIGHT_BROWSERS_PATH=$Browsers"
Write-Host "Windows 已在该虚拟环境中安装 tzdata，供 Asia/Shanghai 使用。"
Write-Host ""
Write-Host "下一步（在仓库根目录、有窗口的终端里）："
Write-Host "  `$env:PLAYWRIGHT_BROWSERS_PATH = `"$Browsers`""
Write-Host "  & .\automation\.venv\Scripts\python.exe -m jobsinsight browser-login liepin"
Write-Host "  & .\automation\.venv\Scripts\python.exe -m jobsinsight browser-login job51"
Write-Host "  & .\automation\.venv\Scripts\python.exe -m jobsinsight browser-login boss"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\automation\scripts\run-local.ps1"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\automation\scripts\register-daily-task.ps1 -At 21:00"
Write-Host ""
Write-Host "本流水线不下载模型。若你另外从 Hugging Face 下载模型，中国大陆请先执行："
Write-Host "  `$env:HF_ENDPOINT = 'https://hf-mirror.com'"
