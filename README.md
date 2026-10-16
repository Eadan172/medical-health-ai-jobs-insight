# 医药健康 + AI 岗位洞察 · 使用手册

这个仓库做四件事：

1. **采集**医药、健康、医疗 AI 相关岗位（海外公开职位板、Remote OK、企业招聘页，以及你自己登录后的 51job / 猎聘 / BOSS直聘）。
2. **整理**岗位字段。填了 LLM API Key 就用模型；没有 Key 就用规则解析，流水线仍然能跑完。
3. **发一封 HTML 日报**到你的邮箱（Windows 计划任务通过 163 邮箱 SMTP 发送）。
4. **在网页看板**里查看已经落盘的岗位、统计和洞察。

第一次使用按下面的顺序做：装 Python 3.12 → 第 0 步看网络通不通 → 一条安装命令 → 一条运行命令。

| 你想做的事 | 命令 |
| --- | --- |
| 看哪些网站能连通 | 第 0 步的 `check_connectivity.py` |
| Windows 安装并填写 API Key | `automation\scripts\setup.ps1` |
| macOS / Linux 安装并填写 API Key | `automation/scripts/setup.sh` |
| Windows 跑一次并发邮件 | `automation\scripts\run-local.ps1` |
| 每天 21:00 自动跑 | `register-daily-task.ps1 -At 21:00` |

开发者命令、接口和测试在文末 [给开发者](#给开发者)。

---

## 准备

只使用 **Python 3.12**，并且只放在本仓库的 **`automation/.venv`**。

- 从 [python.org](https://www.python.org/downloads/) 安装 Python 3.12（Windows 请保留 **py launcher**）。
- **不要使用 conda / Anaconda / Miniconda。** 安装脚本不会激活、修改或删除 conda 环境。
- **不要在系统 Python 或全局环境里 `pip install`。** 依赖只进 `automation/.venv`。
- Windows 还要在这个虚拟环境里安装 **`tzdata`**（时区数据）。`setup.ps1` 会装。没有它时，`Asia/Shanghai` 会报 `unknown timezone`。
- 看板另需 **Node.js 22**（与 CI、Docker 镜像一致）。只跑采集和邮件可以不装 Node。

中国大陆的默认模型是 **DeepSeek**（`deepseek-flash`，`https://api.deepseek.com/v1`）。**不挂代理时，OpenAI（`api.openai.com`）和 Gemini（`generativelanguage.googleapis.com`）从大陆访问不了。** 本仓库没有内置 Gemini。请先跑第 0 步确认 DeepSeek 是「可达」，再把 Key 配成 DeepSeek。

本仓库的采集和富化 **不会下载模型**。如果你另外从 Hugging Face 下载模型（第 0 步会探测 BGE-M3），在大陆请先设置镜像，再下载：

```bash
# Windows PowerShell
$env:HF_ENDPOINT = "https://hf-mirror.com"

# macOS / Linux
export HF_ENDPOINT=https://hf-mirror.com
```

---

## 第 0 步：先看哪些网站通

克隆仓库后、安装依赖前，用系统里的 Python 3.12 跑连通性检查。脚本只用标准库，**不需要 API Key，也不会发送账号或 Cookie**。

```powershell
git clone https://github.com/Eadan172/medical-health-ai-jobs-insight.git
cd medical-health-ai-jobs-insight
py -3.12 automation\scripts\check_connectivity.py
```

```bash
git clone https://github.com/Eadan172/medical-health-ai-jobs-insight.git
cd medical-health-ai-jobs-insight
python3.12 automation/scripts/check_connectivity.py
```

大约 1–5 分钟。连不上的地址会把超时时间用满。测的是**当前这条网络**：开着代理时，结果是代理的连通性。要看直连，先关掉代理再跑。

可选参数（都在脚本里）：

| 参数 | 作用 |
| --- | --- |
| `--only qa` | 只测问答 / 模型组（含 DeepSeek、OpenAI、Gemini、Hugging Face） |
| `--only jobs` | 只测岗位站点 |
| `--targets extra.txt` | 追加目标。每行可以是 `URL`、`名称,URL` 或 `分组,名称,URL`。`#` 开头是注释 |
| `--tries 3` | 每个目标测几次，默认 3 |
| `--timeout 10` | 单次超时秒数，默认 10 |
| `--outdir 目录` | 结果写到哪里，默认当前目录 |

终端每一行是一个站点，同时生成 `connectivity_result_<时间>.csv`（Excel 可打开）和同名 `.json`。这两个文件已在 `.gitignore` 里。

怎么读：

- `dns_ok`：域名解析成功次数。0 次多半是解析不到。
- `tls_ok`：TLS 握手成功次数。DNS 成功但 TLS 失败，多半是连接被重置。
- `http_status`：HTTP 状态码。**401 / 403 / 404 / 405 / 422 / 429 也算「可达」**，因为没带 Key 被拒绝是正常的。
- `verdict`：`可达` 或 `不可达`。
- DeepSeek 应为可达。OpenAI、Gemini 在大陆直连下经常不可达，这时不要把 `[llm]` 改成这两家。
- `huggingface.co` 不可达而 `hf-mirror.com` 可达时，下载模型前设置上面的 `HF_ENDPOINT`。
- We Work Remotely 返回 403 时，站点能连上，但采集阶段仍可能失败。见 [常见问题](#常见问题)。

---

## Windows：五分钟开始

在仓库根目录打开 **PowerShell**。下面的命令都假设当前目录是克隆下来的仓库。

### 1. 安装

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\automation\scripts\setup.ps1
```

这条命令会：

- 用 `py -3.12` 创建 `automation\.venv`（已存在且是 3.12 就跳过）
- 在这个虚拟环境里执行 `pip install -e ".[browser,yaml]" tzdata`
- 设置 `PLAYWRIGHT_BROWSERS_PATH` 为 `automation\.venv\ms-playwright`，并执行 `python -m playwright install chromium`
- 若还没有，则把 `automation\config.local.example.toml` 复制为 `automation\config.local.toml`，把 `automation\config\accounts.example.toml` 复制为 `automation\config\accounts.toml`
- 提示输入 **DeepSeek API Key**，写入仓库根目录的 `.env.local`

直接回车可以先不填 Key。没有 Key 时不会请求模型，字段和洞察走规则解析。已经填写过的 Key、已经存在的 `config.local.toml` / `accounts.toml` 再跑一次也不会被覆盖。

脚本如果发现当前终端开着 conda，只会提示一句，然后继续用 `py -3.12`。它不会 `conda activate`，也不会改 conda 里的包。

### 2. 邮件（不配也能采集，但不会发日报）

`setup.ps1` 会问要不要现在配置 163。也可以事后自己把下面三行加进 **仓库根目录** 的 `.env.local`（这个文件已被 gitignore）：

```text
MAIL163_SMTP_USER=你的邮箱@163.com
MAIL163_SMTP_AUTH_CODE=授权码
JOBSINSIGHT_REPORT_TO=收件人@example.com
```

怎么拿到授权码：

1. 浏览器打开 <https://mail.163.com> 并登录。
2. 进入 **设置 → POP3/SMTP/IMAP**。
3. 开启 **SMTP**。
4. 按页面提示完成短信验证，得到 **客户端授权码**。
5. `MAIL163_SMTP_USER` 填完整邮箱。`MAIL163_SMTP_AUTH_CODE` 填授权码，**不是**网页登录密码。

发信代码使用 `smtp.163.com` 端口 **465**（SSL）。收件人可以是 outlook.com 或其他邮箱。**不要改成用 outlook.com 发信**：outlook.com 的 SMTP 基本认证（用账号密码登录 SMTP）已经关闭，本仓库也没有 outlook SMTP 的实现。

`run-local.ps1` 还会读取同名的 **Windows 用户级环境变量**（进程里没有时才读）。`.env.local` 由发信脚本补上仍然缺失的变量。已经存在的进程变量不会被文件覆盖。请设置 `JOBSINSIGHT_REPORT_TO`。不设置时，`send_report.py` 会把信发到脚本里的默认收件人 `syidan00@outlook.com`。

### 3. 需要登录的网站（可跳过）

海外职位板、Remote OK、企业公开招聘页不需要登录。51job、猎聘、BOSS直聘需要你在 **看得到窗口的终端** 里登录一次。计划任务里没有窗口，不能代替这一步。账号名只有这三个：`boss`、`liepin`、`job51`。

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\automation\.venv\ms-playwright"
& .\automation\.venv\Scripts\python.exe -m jobsinsight browser-login liepin
& .\automation\.venv\Scripts\python.exe -m jobsinsight browser-login job51
& .\automation\.venv\Scripts\python.exe -m jobsinsight browser-login boss
```

浏览器打开后自己登录。遇到验证码就手动完成，程序不会去绕过。回到终端按 Enter，会话写到 `automation\state\browser\`（不入库）。

BOSS直聘目前会拦截自动化浏览器，页面可能是空白，登录也未必能用于后续采集。猎聘登录页会出现验证码。这两个来源失败不会挡住其他来源。

### 4. 跑一次

当前分支必须是 `main`（刚克隆就是）。电脑需要能 `git pull`。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\automation\scripts\run-local.ps1
```

它会拉取 `main`，用 `automation\.venv` 和 `config.local.toml` 跑流水线，检查产出，再发 HTML 邮件。邮件发出后，脚本把 `web\public\data` **还原成仓库里的版本**，不提交、不推送。日报在邮箱里。看板若只读静态文件，看到的仍是仓库里的那份；想在看板上看刚抓到的数据，见 [网页看板](#网页看板)。

### 5. 每天 21:00

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\automation\scripts\register-daily-task.ps1 -At 21:00
```

这是当前 Windows 用户的计划任务，名称 `JobsInsightDaily`，`RunLevel Limited`，不需要管理员。触发方式是「只在用户已登录时运行」。**关机、睡眠，或人已经注销时，任务不会跑，邮箱里也不会有信。**

取消：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\automation\scripts\register-daily-task.ps1 -Unregister
```

---

## macOS / Linux：五分钟开始

同样在仓库根目录。不要用 conda 的 `python`，用 `python3.12`。

```bash
bash automation/scripts/setup.sh
```

脚本创建 `automation/.venv`，在里面执行 `pip install -e ".[browser,yaml]"`，把 Chromium 装到 `automation/.venv/ms-playwright`，复制本地配置，并提示输入 DeepSeek API Key（写入 `.env.local`）。macOS / Linux 使用系统时区数据，所以这里 **不** 安装 Python 包 `tzdata`。若以后报 `unknown timezone 'Asia/Shanghai'`，用系统包安装 `tzdata`（例如 `apt install tzdata`），不要用 conda。

Debian/Ubuntu 若创建虚拟环境失败，先安装系统包 `python3.12-venv`，再重跑 `setup.sh`。

填邮件时同样写入 `.env.local` 的 `MAIL163_SMTP_USER`、`MAIL163_SMTP_AUTH_CODE`、`JOBSINSIGHT_REPORT_TO`。获取授权码的步骤与 Windows 相同。

登录（可跳过；需要图形界面）：

```bash
export PLAYWRIGHT_BROWSERS_PATH="$PWD/automation/.venv/ms-playwright"
automation/.venv/bin/python -m jobsinsight browser-login liepin
automation/.venv/bin/python -m jobsinsight browser-login job51
automation/.venv/bin/python -m jobsinsight browser-login boss
```

跑一次采集（这条命令不会发信，也不会还原数据目录）：

```bash
export PLAYWRIGHT_BROWSERS_PATH="$PWD/automation/.venv/ms-playwright"
automation/.venv/bin/python -m jobsinsight run
```

接着发日报：

```bash
automation/.venv/bin/python automation/scripts/send_report.py
```

仓库里的每日计划任务只有 Windows 脚本 `register-daily-task.ps1`。macOS / Linux 没有对应的注册脚本。要用 cron，请调用上面这两条真实命令，并写成绝对路径。它不等于 `run-local.ps1`：没有 `git pull`，也不会在发信后还原 `web/public/data`。

---

## 配置

本地文件是 `automation/config.local.toml`（gitignore）。云端和 CI 读 `automation/config.toml`，**不会**加载 `config.local.toml`。不要把浏览器来源写进 `config.toml`。

加载顺序：命令行 `--config` → 环境变量 `JOBSINSIGHT_CONFIG` → `config.local.toml` → `config.toml`。  
环境变量再盖过文件。空白的 `JOBSINSIGHT_LLM_PROVIDER` / `JOBSINSIGHT_LLM_MODEL` 会被忽略，避免把 DeepSeek 擦掉。  
仓库根目录的 `.env.local` 优先于 `.env`，但 **不会覆盖** 进程里已经设置的变量。

### LLM

默认（`config.local.example.toml` 和 `config.toml` 都是这样）：

```toml
[llm]
provider = "deepseek"
model = "deepseek-flash"
api_key = "${JOBSINSIGHT_LLM_API_KEY:-}"
base_url = "https://api.deepseek.com/v1"
```

Key 只放在环境变量或 `.env.local` 的 `JOBSINSIGHT_LLM_API_KEY`。不要把 Key 写进 toml。客户端请求的地址是 `{base_url}/chat/completions`，所以 DeepSeek 要带 `/v1`。

没有 Key、Key 为空，或模型调用失败时，富化和洞察退回 `heuristics.py` 的规则解析，这次运行不会因此失败。单次不想调模型：`python -m jobsinsight run --no-llm`。

换其他 **OpenAI 兼容** 服务时，改 `config.local.toml` 的 `provider`、`model`、`base_url`，Key 仍用 `JOBSINSIGHT_LLM_API_KEY`。内置别名和默认地址：

| provider | base_url |
| --- | --- |
| `deepseek` | `https://api.deepseek.com/v1` |
| `moonshot` / `kimi` | `https://api.moonshot.cn/v1` |
| `dashscope` / `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4` |
| `siliconflow` | `https://api.siliconflow.cn/v1` |
| `openai` | `https://api.openai.com/v1`（大陆不挂代理通常不可达） |
| `groq` | `https://api.groq.com/openai/v1` |
| `ollama` | `http://localhost:11434/v1`（不需要 Key） |

自建网关：

```toml
[llm]
provider = "openai_compatible"
model = "你的模型名"
api_key = "${JOBSINSIGHT_LLM_API_KEY:-}"
base_url = "https://你的网关/v1"
```

也可以不改文件，用环境变量覆盖（留空则继续用文件里的值）：`JOBSINSIGHT_LLM_PROVIDER`、`JOBSINSIGHT_LLM_MODEL`、`JOBSINSIGHT_LLM_BASE_URL`。  
Claude 使用 `provider = "anthropic"`。离线测试使用 `JOBSINSIGHT_LLM_PROVIDER=mock` 和 `JOBSINSIGHT_LLM_MODEL=mock-1`。

先确认 Key 能通：

```bash
automation/.venv/bin/python -m jobsinsight llm --providers
automation/.venv/bin/python -m jobsinsight llm "用一句话介绍医疗 AI 岗位"
```

Windows 把 python 换成 `.\automation\.venv\Scripts\python.exe`。

### 数据源

`config.local.toml` 里启用的来源如下。标成失败的来源默认 `required = false`，不会挡住其余来源和邮件。

| 来源 | 要登录吗 | 说明 |
| --- | --- | --- |
| 海外 ATS | 否，无 API Key | Greenhouse、Lever、Ashby、Workable。公司名单在 `automation/config/overseas_companies.yaml` |
| Remote OK | 否 | 公开接口 `https://remoteok.com/api` |
| We Work Remotely | 否 | RSS。经常返回 403，该来源失败，其他来源继续 |
| 企业招聘页 | 公开页不需要 | `automation/config/company_sources.yaml`，仓库里默认是空列表 |
| 公开搜索 | 可选 | 有 `SERPER_API_KEY`、`BING_SEARCH_API_KEY` 或 `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_ID` 时用对应服务；都没有时用 DuckDuckGo，状态记为 degraded |
| 51job | 是 | 本机：`browser-login job51`。GitHub Actions 用的是 `config.toml` 里的 json_api，Cookie 来自 Secret `JOB51_COOKIE` |
| 猎聘 | 是 | `browser-login liepin`。页面有腾讯验证码，必须人工完成 |
| BOSS直聘 | 是 | `browser-login boss`。目前会拦截自动化浏览器，采集时页面可能是空白 |
| seed | 否 | `automation/data/seed_postings.json` 里的样例，不是当天抓到的职位 |

**加一家海外公司**：编辑 `automation/config/overseas_companies.yaml`，在 `companies:` 下追加一项，只使用这四个字段：

```yaml
  - name: "公司展示名"
    ats: greenhouse          # greenhouse、lever、ashby、workable 四选一
    token: "职位板标识"
    sector: "AI制药"          # 行业短词，例如临床AI、医学影像AI
```

`token` 是职位板标识，不是 API Key。对应的公开地址是：

- greenhouse：`https://boards-api.greenhouse.io/v1/boards/{token}/jobs`
- lever：`https://api.lever.co/v0/postings/{token}?mode=json`
- ashby：`https://api.ashbyhq.com/posting-api/job-board/{token}`
- workable：`https://apply.workable.com/api/v1/widget/accounts/{token}`

一家公司只留一行。采集器按标题优先保留 AI / 工程岗位，并用 `per_company_limit` 限制条数（本地示例里是 3）。

**加一家企业招聘页**：编辑 `automation/config/company_sources.yaml`。只填写你核对过的公开地址，不要编造网址。字段是 `name`、`domains`、`careers_urls`、`enabled`。

---

## 网页看板

看板读取 `web/public/data` 里的 JSON。后端没开时，开发服务器退回这些静态文件。

注意：`run-local.ps1` 发完邮件会把 `web/public/data` 还原。要在看板上看到刚抓的结果，用虚拟环境直接跑，不要接着执行那个还原：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\automation\.venv\ms-playwright"
& .\automation\.venv\Scripts\python.exe -m jobsinsight run
```

然后在 **另一个** 终端启动页面。二选一。

只看开发页面（Vite 把 `/api` 代理到 `127.0.0.1:8787`）：

```powershell
& .\automation\.venv\Scripts\python.exe -m jobsinsight serve --no-scheduler
```

```bash
cd web
npm install
npm run dev
```

终端会打印地址，Vite 默认是 <http://localhost:5173>。后端没启动时，页面仍能打开静态数据。

或者先构建，再由后端同时提供页面和接口（配置里的地址是 `127.0.0.1:8787`）：

```bash
cd web
npm install
npm run build
cd ..
automation/.venv/bin/python -m jobsinsight serve
```

浏览器打开 <http://127.0.0.1:8787>。`serve` 默认还会按配置里的时间启动调度器；只想要接口时加上已有参数 `--no-scheduler`。

---

## 常见问题

**BOSS 页面是空白的。**  
BOSS直聘会拦截自动化浏览器。`browser-login boss` 打开的是有界面的 Chromium（本机每日任务还会设置 `JOBSINSIGHT_BROWSER_CHANNEL=chrome`），采集阶段则是无头浏览器。空白页、登录墙或验证码都会让这个来源失败。程序不会绕过风控。该来源是 `required = false`，海外职位板和其他来源照常进入日报。

**猎聘出现验证码。**  
登录和采集都可能看到验证码（页面脚本来自腾讯验证码）。在 `browser-login liepin` 的窗口里手动完成，再回终端按 Enter。采集过程中若再出现验证码，该来源停止，邮件主题会带「需重新登录」。不要期待程序自动识别验证码。

**邮件说登录会话过期。**  
主题里出现「需重新登录」，或正文黄框写着 `browser-login`，表示 51job / 猎聘 / BOSS 的会话文件失效、出现登录墙或验证码。在有窗口的终端里对对应账号重跑 `browser-login`。会话路径在 `automation/state/browser/`。

**报 unknown timezone 'Asia/Shanghai'。**  
Windows：确认用的是 `automation\.venv`，并在 **这个** 环境里执行过 `pip install tzdata`（`setup.ps1` 已包含）。不要装到 conda 或系统 Python。macOS / Linux 安装系统时区包 `tzdata`。Docker 镜像里已经用系统包安装了 `tzdata`。

**到点了但没收到邮件。**  
计划任务只在 **你已登录 Windows** 时运行。电脑关机、睡眠或已注销，就不会跑。另外检查 `.env.local` 里的三个邮件变量。缺少 `MAIL163_SMTP_USER` 或 `MAIL163_SMTP_AUTH_CODE` 时发信会失败，`run-local.ps1` 以非零退出。日志在 `automation/state/local-run.log` 和 `automation/state/last-run.json.log`。

**We Work Remotely 403。**  
RSS 地址经常返回 403。HTTP 客户端把 403 视为拦截且不重试，这个来源记失败。它是 `required = false`，不会挡住海外 ATS、Remote OK 和邮件。第 0 步里 403 仍显示「可达」，因为服务器有响应；采集时非 200 仍算失败。

**想确认配置而不是猜。**

```bash
automation/.venv/bin/python -m jobsinsight doctor
automation/.venv/bin/python -m jobsinsight config
```

`config` 默认打码 API Key。`--raw` 会打印明文，不要截图。

---

## 安全

不要提交 API Key、163 授权码、招聘网站密码、Cookie 或浏览器会话。下面这些路径已经在 `.gitignore` 里：

- `.env`、`.env.local`（LLM Key 和邮件变量放这里）
- `automation/config.local.toml`，以及同名的 `.json` / `.yaml` / `.yml`
- `automation/config/accounts.toml`、`automation/config/*.local.toml`
- `automation/state/`（含 `automation/state/browser/` 里的登录 Cookie / storage state，以及运行日志）
- `automation/.venv/`、仓库根目录的 `.venv/` 和 `venv/`
- `connectivity_result_*.csv`、`connectivity_result_*.json`

可以提交的是示例：`config.local.example.toml`、`accounts.example.toml`。`jobsinsight config --raw` 的输出不要贴到 Issue 或聊天里。

---

## 给开发者

后端说明也在 [automation/README.md](automation/README.md)，前端在 [web/README.md](web/README.md)。下面的命令都对着当前代码，请用 `automation/.venv` 里的解释器。

### 流水线

一次运行的顺序是：采集 → 富化 → 按相关度过滤 → 质量检查 → 原子写入 `web/public/data/` 的 `jobs.json`、`stats.json`、`insights.json`、`manifest.json`。必需来源失败、条数不够或质量分过低时，不覆盖上一版。

`python -m jobsinsight` 的子命令：

| 命令 | 作用 |
| --- | --- |
| `run` | 立即跑。`--dry-run` 不写文件；`--limit N` 只限制每个来源本次新处理的条数；`--replace-with-limit` 才用本次结果替换全库；`--no-llm` 只用规则；`--if-due` 没到点就跳过；`--trigger 名称` 记入历史 |
| `schedule` | 常驻，到点执行。`--once` 只跑一轮 |
| `serve` | HTTP 接口，默认同时启动调度器。`--host`、`--port`、`--no-scheduler` |
| `next-runs` | 打印之后几次触发时间。`-n` / `--count` |
| `set-schedule` | `--at 08:30,20:30`、`--cron "..."`、`--every 90`、`--timezone`、`--enable`、`--disable` |
| `config` | 校验并打印配置。`--raw` 不打码 |
| `doctor` | 预检。`--json`、`--strict`（警告也失败） |
| `browser-login 账号` | 打开可见浏览器。`--accounts-file` 默认 `automation/config/accounts.toml` |
| `llm` | 试一次模型。`--providers` 列出内置 provider；`--json` 要求 JSON |
| `sync-cron` | 把运行时间写进 GitHub Actions。`--check` 只比较，不改文件 |
| `history` | 运行历史 |
| `sources health` | 最近一次来源健康 |
| `sources test` | `--source zhipin\|51job\|liepin` 或 `--all`。不绕过登录和验证码 |
| `search providers` | 搜索提供方是否已配置 |
| `search test` | `--provider serper\|bing\|google_cse\|ddgs`，`--query` |
| `ingest preview` | 只预览候选，不写 `jobs.json`。`--query` |

全局参数：`-c` / `--config`，`--log-level`。

调度在 `config.toml` 的 `[schedule]`：`daily`（`daily_times`）、`cron`、`interval`（`interval_minutes`）、`manual`。时区默认 `Asia/Shanghai`。GitHub Actions 的 cron 是 UTC，是否真的执行由 `run --if-due` 决定。改完本地时间后执行 `python -m jobsinsight sync-cron`。workflow 路径按仓库根目录解析，不依赖当前目录。

HTTP 接口在 `serve` 之后可用，默认 <http://127.0.0.1:8787>。写操作在配置了 `server.auth_token`（环境变量 `JOBSINSIGHT_API_TOKEN`）时需要 `Authorization: Bearer <token>`。常用路径：`GET /api/health`、`/api/doctor`、`/api/status`、`/api/config`，`GET/PUT /api/schedule`，`GET/POST /api/runs`，`POST /api/llm/chat` 与 `/api/llm/ask`，`GET /api/data/<name>.json`。

Docker（镜像内是 Python 3.12，并安装了系统包 tzdata）：

```bash
LLM_API_KEY=你的Key docker compose up -d
```

`docker-compose.yml` 把 `LLM_API_KEY` 映射为 `JOBSINSIGHT_LLM_API_KEY`。留空 `LLM_PROVIDER` / `LLM_MODEL` 时继续用配置文件里的 DeepSeek，不会被空字符串擦掉。

### 测试

CI（`.github/workflows/ci.yml`）在 Python 3.12 上跑 `ruff check`、`ruff format --check`、`pytest`，并在 Node.js 22 上跑前端 `npm run lint` 和 `npm run build`。

```bash
cd automation
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .

cd ../web
npm ci
npm run lint
npm run build
```

Windows 用 `.venv\Scripts\python.exe`。这些包装在 `automation/.venv` 里，不要装进 conda 或系统 Python。
