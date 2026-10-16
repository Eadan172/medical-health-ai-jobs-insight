#!/usr/bin/env bash
# 一次性准备本机环境：automation/.venv、依赖、本地配置、LLM API Key。
# 可重复运行。已有的 config.local.toml、accounts.toml 和已填写的 Key 不会被覆盖。
# 不会激活、修改或删除 conda，也不会往系统 Python 里装包。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$ROOT/automation/.venv"
PYTHON="$VENV/bin/python"
BROWSERS="$VENV/ms-playwright"
ENV_FILE="$ROOT/.env.local"

die() {
  printf '%s\n' "$1" >&2
  exit 1
}

if [[ -n "${CONDA_PREFIX:-}" || -n "${CONDA_DEFAULT_ENV:-}" ]]; then
  printf '%s\n' "当前终端里有 conda。本脚本不会改它，只使用单独的 Python 3.12 创建 automation/.venv。"
fi

if ! command -v python3.12 >/dev/null 2>&1; then
  die "找不到 python3.12。请从 https://www.python.org/downloads/ 安装 Python 3.12。不要使用 conda，也不要在全局环境里 pip install。"
fi

BASE="$(command -v python3.12)"
if ! "$BASE" -c 'import sys; conda = "conda" in sys.prefix.lower() or "conda" in sys.base_prefix.lower(); raise SystemExit(0 if sys.version_info[:2] == (3, 12) and not conda else 1)'; then
  die "python3.12 不是 3.12，或指向 conda。请安装 python.org / 系统包里的 Python 3.12。本脚本不会改动 conda。"
fi

if [[ ! -x "$PYTHON" ]]; then
  if ! "$BASE" -m venv "$VENV"; then
    die "创建 automation/.venv 失败。Debian/Ubuntu 请先安装系统包 python3.12-venv（不是 conda）。"
  fi
fi

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)'; then
  die "automation/.venv 不是 Python 3.12。删除该目录后重跑本脚本。不要改用 conda。"
fi

"$PYTHON" -m pip install --upgrade pip
(
  cd "$ROOT/automation"
  "$PYTHON" -m pip install -e ".[browser,yaml]"
)
export PLAYWRIGHT_BROWSERS_PATH="$BROWSERS"
"$PYTHON" -m playwright install chromium

copy_if_missing() {
  local src="$1" dest="$2"
  if [[ -f "$dest" ]]; then
    printf '已有 %s，未覆盖\n' "$dest"
  else
    cp "$src" "$dest"
    printf '已复制 %s\n' "$dest"
  fi
}

copy_if_missing "$ROOT/automation/config.local.example.toml" "$ROOT/automation/config.local.toml"
copy_if_missing "$ROOT/automation/config/accounts.example.toml" "$ROOT/automation/config/accounts.toml"

upsert_env() {
  "$PYTHON" - "$ENV_FILE" "$1" "$2" <<'PY'
import sys
from pathlib import Path

path, name, value = sys.argv[1:]
file = Path(path)
lines = file.read_text(encoding="utf-8").splitlines() if file.is_file() else []
prefix = name + "="
found = False
out: list[str] = []
for line in lines:
    stripped = line.strip()
    body = stripped[7:].strip() if stripped.startswith("export ") else stripped
    if body.startswith(prefix):
        out.append(prefix + value)
        found = True
    else:
        out.append(line)
if not found:
    if out and out[-1] != "":
        out.append("")
    out.append(prefix + value)
file.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

read_env_value() {
  "$PYTHON" - "$ENV_FILE" "$1" <<'PY'
import sys
from pathlib import Path

path, name = sys.argv[1:]
file = Path(path)
if not file.is_file():
    raise SystemExit(0)
prefix = name + "="
for line in file.read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if stripped.startswith("export "):
        stripped = stripped[7:].strip()
    if stripped.startswith(prefix):
        print(stripped[len(prefix) :], end="")
        break
PY
}

existing="$(read_env_value JOBSINSIGHT_LLM_API_KEY || true)"
if [[ -n "$existing" ]]; then
  printf '%s\n' "已有 JOBSINSIGHT_LLM_API_KEY，未覆盖。要更换请编辑 .env.local。"
elif [[ -n "${JOBSINSIGHT_LLM_API_KEY:-}" ]]; then
  upsert_env JOBSINSIGHT_LLM_API_KEY "$JOBSINSIGHT_LLM_API_KEY"
  printf '%s\n' "已把当前环境中的 JOBSINSIGHT_LLM_API_KEY 写入 .env.local。"
elif [[ -t 0 ]]; then
  read -r -p "DeepSeek API Key（直接回车表示暂不填写，流水线用规则解析）: " key
  if [[ -n "${key:-}" ]]; then
    upsert_env JOBSINSIGHT_LLM_API_KEY "$key"
    printf '%s\n' "已写入 .env.local。该文件已被 gitignore，不要提交。"
  else
    printf '%s\n' "未填写 API Key。没有密钥时不会请求模型，富化和日报洞察回退到规则解析。"
  fi
else
  printf '%s\n' "没有交互终端。请把 JOBSINSIGHT_LLM_API_KEY 写入 $ENV_FILE 后重跑。"
fi

if [[ -t 0 ]]; then
  mail_user="$(read_env_value MAIL163_SMTP_USER || true)"
  mail_code="$(read_env_value MAIL163_SMTP_AUTH_CODE || true)"
  mail_to="$(read_env_value JOBSINSIGHT_REPORT_TO || true)"
  if [[ -n "$mail_user" && -n "$mail_code" && -n "$mail_to" ]]; then
    printf '%s\n' "邮件变量已在 .env.local 中，未覆盖。"
  else
    read -r -p "现在配置 163 日报吗？直接回车跳过。[y/N] " answer
    if [[ "${answer:-}" == "y" || "${answer:-}" == "Y" ]]; then
      read -r -p "MAIL163_SMTP_USER（完整邮箱，如 name@163.com）: " mail_user
      read -r -p "MAIL163_SMTP_AUTH_CODE（SMTP 授权码，不是登录密码）: " mail_code
      read -r -p "JOBSINSIGHT_REPORT_TO（收件人）: " mail_to
      [[ -n "$mail_user" ]] && upsert_env MAIL163_SMTP_USER "$mail_user"
      [[ -n "$mail_code" ]] && upsert_env MAIL163_SMTP_AUTH_CODE "$mail_code"
      [[ -n "$mail_to" ]] && upsert_env JOBSINSIGHT_REPORT_TO "$mail_to"
      printf '%s\n' "邮件变量已写入 .env.local。发信使用 smtp.163.com:465。"
    fi
  fi
fi

cat <<EOF

准备完成。虚拟环境：automation/.venv
浏览器目录：\$PLAYWRIGHT_BROWSERS_PATH=$BROWSERS

下一步（在仓库根目录，登录需要图形界面）：
  export PLAYWRIGHT_BROWSERS_PATH="$BROWSERS"
  automation/.venv/bin/python -m jobsinsight browser-login liepin
  automation/.venv/bin/python -m jobsinsight browser-login job51
  automation/.venv/bin/python -m jobsinsight browser-login boss
  automation/.venv/bin/python -m jobsinsight run

本流水线不下载模型。若你另外从 Hugging Face 下载模型，中国大陆请先执行：
  export HF_ENDPOINT=https://hf-mirror.com
EOF
