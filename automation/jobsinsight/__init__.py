"""医药健康 + AI 岗位洞察的自动化后端。

三块能力：

* **采集**：可插拔的 collector（本地文件 / JSON 接口 / 让 LLM 读网页）
* **LLM 调用接口**：统一封装多家厂商，带重试、JSON 模式、用量统计与规则兜底
* **自定义运行时间**：每天定点、cron 表达式、固定间隔或纯手动，支持运行中修改

入口：``python -m jobsinsight --help``
"""

from .config import Config, LLMSettings, ScheduleSettings, load_config
from .models import Job, RawPosting, RunDiff
from .pipeline import Pipeline, RunReport
from .scheduler import Scheduler, is_due, next_run_after, upcoming_runs

__version__ = "1.0.0"

__all__ = [
    "Config",
    "Job",
    "LLMSettings",
    "Pipeline",
    "RawPosting",
    "RunDiff",
    "RunReport",
    "ScheduleSettings",
    "Scheduler",
    "__version__",
    "is_due",
    "load_config",
    "next_run_after",
    "upcoming_runs",
]
