# jobsinsight

医药健康 + AI 岗位数据的自动化后端：按用户设定的时间采集岗位、调用 LLM 规范化与分析、
产出前端消费的 JSON，并可由 Windows 计划任务发 HTML 日报。

本机安装、API Key、163 邮件和每天 21:00 的计划任务见仓库根目录 [README](../README.md)。
请使用 `automation/.venv` 里的 Python 3.12。不要激活或修改 conda，也不要往全局环境里装包。
核心流水线本身只用标准库；浏览器采集才需要 `pip install -e ".[browser,yaml]"`（Windows 再加 `tzdata`）。

```bash
python -m jobsinsight --help
```

## 命令

| 命令 | 说明 |
| --- | --- |
| `run` | 立即执行一次流水线。`--dry-run` 不写文件，`--limit N` 限量，`--no-llm` 只用规则解析，`--if-due` 只在到点时执行 |
| `schedule` | 常驻运行，按设定时间自动执行（`--once` 只跑一轮，便于调试） |
| `serve` | 启动 HTTP 接口，默认同时启动调度器（`--no-scheduler` 只提供接口） |
| `next-runs` | 打印未来若干次触发时刻 |
| `set-schedule` | 改运行时间：`--at 08:30,20:30` / `--cron "..."` / `--every 90` / `--mode manual` / `--timezone` / `--enable` / `--disable` |
| `config` | 校验并打印当前配置（默认脱敏，`--raw` 显示明文） |
| `doctor` | 预检配置、数据源、凭据/会话、输出目录与前端数据；`--json` 可供 CI 使用 |
| `browser-login ACCOUNT` | 打开可见浏览器，人工登录并保存会话（需要可选 Playwright） |
| `llm` | 直接调用一次 LLM，验证 provider 是否配通；`--providers` 列出内置 provider |
| `sync-cron` | 把运行时间同步进 GitHub Actions workflow（`--check` 只校验） |
| `history` | 打印运行历史 |

## 一次运行做了什么

1. **采集**：遍历 `[[sources]]`，按 `fingerprint`（平台+公司+岗位+城市）跨来源去重。
   单个来源抛错只记录进报告，不中断整次运行。
2. **富化**：`Enricher` 把原始岗位按 `batch_size` 分批交给 LLM，要求返回规范化字段。
   每个字段都会校验（枚举必须在词表内、薪资必须是合理区间），不合格就用
   `heuristics.py` 的规则结果。LLM 未启用、没配 Key 或调用失败时，全量走规则解析。
   生产配置的 provider 是 `deepseek`、模型是 `deepseek-flash`；只有
   `JOBSINSIGHT_LLM_API_KEY` 有值时才会请求 `https://api.deepseek.com/v1`。
3. **过滤**：丢掉 `relevance < output.min_relevance` 的岗位（默认 30），
   把明显与「医药健康 + AI」无关的岗位挡在外面。
4. **聚合**：`analysis.build_stats()` 生成前端需要的全部统计，
   并与上一次快照对比得出今日新增 / 更新 / 下架。
5. **落盘**：原子写入 `jobs.json`、`stats.json`、`insights.json`、`manifest.json`，
   更新 `state/` 下的快照、运行历史与上次运行时间。

发布前还会计算数据质量与新鲜度。`required = true` 的来源失败、采集量低于
`min_collected`、全部岗位被过滤，或质量分低于 `output.min_quality_score` 时，
不会覆盖上一版数据。每个来源的最近成功时间、连续失败次数和耗时保存在
`state/sources_health.json`。

## 关键模块

- `cron.py` —— 自己实现的 5 字段 cron 解析器。支持 `*`、`a`、`a-b`、`a-b/n`、`*/n`、
  逗号列表、月份与星期名、`@daily` 等宏；day-of-month 与 day-of-week 同时受限时按
  cron 传统的 OR 语义处理。
- `scheduler.py` —— `next_run_after` / `upcoming_runs` 是纯函数（好测试也好展示），
  `is_due` 供 CI 的粗粒度 cron 使用，`Scheduler` 是可从其它线程 `stop()` /
  `trigger_now()` / `refresh()` 的守护循环。运行失败只记日志，不会终止循环。
- `llm/` —— `LLMProvider` 是唯一需要实现的接口；重试、限流、JSON 解析与修复、
  用量统计都在 `LLMClient` 里，所有 provider 共享。
- `heuristics.py` —— 规则解析：薪资（`25-40K·14薪`、`30-60万/年`）、经验分档、学历、
  级别、技能词典（别名映射到标准写法）、岗位方向、相关度打分。
- `store.py` —— 所有 JSON 都经临时文件 + `os.replace` 原子写入，运行中断不会留下半个文件。

## 加一个数据源

```python
from jobsinsight.collectors import Collector, register_collector
from jobsinsight.models import RawPosting

class MyCollector(Collector):
    type = "my-source"

    def collect(self):
        for item in fetch_somehow(self.settings.urls):
            yield RawPosting(
                source_id=item["id"],
                platform=self.settings.platform,
                title=item["title"],
                company=item["company"],
                city=item.get("city", ""),
                salary_text=item.get("salary", ""),
                description=item.get("detail", ""),
            )

register_collector("my-source", MyCollector)
```

之后配置里写 `type = "my-source"` 即可。`self.context.llm` 是当前运行的 LLM 客户端
（可能为 `None`），`self.resolve_path()` 把相对路径按项目根目录展开。

### 需要登录的动态招聘页面

GitHub Actions 只读 `automation/config.toml`。那个文件可以有 51job 的 `json_api`，
但不要启用 `browser`：云端 IP 会被风控拦住。本机用 gitignore 的 `config.local.toml`。

安装用根目录 README 里的 `automation/scripts/setup.ps1` 或 `setup.sh`。
不要在 conda 或系统 Python 里执行 `pip install`。登录必须在有窗口的终端里进行
（`browser-login` 用 `input()` 等 Enter），账号名是 `boss`、`liepin`、`job51`：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\automation\.venv\ms-playwright"
& .\automation\.venv\Scripts\python.exe -m jobsinsight browser-login boss
& .\automation\.venv\Scripts\python.exe -m jobsinsight browser-login liepin
& .\automation\.venv\Scripts\python.exe -m jobsinsight browser-login job51

powershell -NoProfile -ExecutionPolicy Bypass -File .\automation\scripts\run-local.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\automation\scripts\register-daily-task.ps1 -At 21:00
```

`run-local.ps1` 会 `git pull --ff-only origin main`（当前分支必须是 `main`），
用 `.venv` 的 Python 和 `config.local.toml` 跑流水线，再检查
`jobs.json` 非空且 `manifest.counts.valid == len(jobs)`，然后用 163 SMTP 发 HTML 日报。
邮件发出后会把 `web/public/data` 还原成仓库里的示例占位，不提交、不推送。
路径都相对仓库根目录；计划任务只在注册时记住这台电脑上的脚本位置，那个绝对路径不入库。
跨次快照在已忽略的 `automation/state/`。
计划任务是当前用户、`RunLevel Limited`，不需要管理员，并且只在该用户已登录时才会跑。

三个 browser 来源都是 `required = false`。会话文件缺失、登录墙或验证码只让该来源
失败，seed 和其他来源仍会发布。selector 写在 `accounts.example.toml`，里面注明了
哪些是对着线上包核对过的、哪些还没在渲染后的页面上确认。密码和 storage state 不入库。
验证码必须人工完成，采集器不会尝试绕过风控。

生产部署可执行 `python -m jobsinsight doctor --strict`，此时包括“仍使用 mock”或
“只有 fixture 来源”在内的警告也会返回非零退出码。运行服务后还可读取
`/api/health`、`/api/status`、`/api/doctor` 获取数据版本、年龄、质量和来源健康。

## 测试

在 `automation` 目录里用 `.venv` 安装开发依赖。不要装进 conda 或系统 Python：

```bash
cd automation
.venv/bin/python -m pip install -e ".[dev]"    # Windows：.venv\Scripts\python.exe
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

覆盖范围：cron 解析与边界、调度与错过窗口补跑、配置层叠（文件/环境变量/运行时覆盖）、
LLM 重试与 JSON 修复、字段校验、规则解析、统计聚合、增量对比、HTTP 接口、CLI。
所有测试都不联网：网络层通过注入 transport 打桩，LLM 用内置 `mock` provider。
