"""Build a daily HTML job report and mail it via 163 SMTP. Env: MAIL163_SMTP_USER, MAIL163_SMTP_AUTH_CODE, JOBSINSIGHT_REPORT_TO."""

from __future__ import annotations

import collections
import contextlib
import datetime as dt
import html
import json
import os
import smtplib
import sys
from email.header import Header
from email.mime.text import MIMEText
from pathlib import Path

# Keep in step with jobsinsight.sources.overseas.OVERSEAS_SOURCE_TYPES.
OVERSEAS_SOURCE_TYPES = frozenset({"greenhouse", "ashby", "lever", "workable", "remoteok", "weworkremotely"})
OVERSEAS_TABLE_LIMIT = 20


def is_overseas(job: dict) -> bool:
    if str(job.get("region") or "") == "海外":
        return True
    return str(job.get("source_type") or "") in OVERSEAS_SOURCE_TYPES


def _keep_real(job: dict) -> bool:
    """Sample rows have an empty source_type. Company and listing pages are not jobs."""

    if not job.get("source_type"):
        return False
    from jobsinsight.sources.urlutil import is_publishable_record

    return is_publishable_record(job)


def parse_run_summary(raw: bytes) -> dict:
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", errors="replace")
    text = "\n" + text.replace("\r\n", "\n")
    start = text.rfind("\n{\n")
    if start < 0:
        return {}
    with contextlib.suppress(Exception):
        parsed = json.JSONDecoder().raw_decode(text[start + 1 :])[0]
        if isinstance(parsed, dict):
            return parsed
    return {}


def build_report(
    jobs: list[dict],
    summary: dict,
    errors: list[str],
    *,
    now: dt.datetime,
    today: str,
    previous_master_eligible: int | None = None,
) -> tuple[str, str]:
    """Return ``(subject, html)``. Jobs with an empty source_type are sample rows, not real postings."""

    real = [job for job in jobs if _keep_real(job)]
    started = _timestamp(summary.get("started_at"))
    new = [job for job in real if _is_new(job, now=now, started=started)]
    new.sort(key=lambda job: -float(job.get("relevance") or 0))
    overseas = [job for job in real if is_overseas(job)]
    overseas_new = [job for job in new if is_overseas(job)]
    domestic_new = [job for job in new if not is_overseas(job)]
    session_errors = [
        item
        for item in errors
        if "登录会话" in item or "验证码" in item or "captcha" in item.lower() or "browser-login" in item
    ]

    parts = [f"<h2>医疗健康 AI 岗位日报 {html.escape(today)}</h2>"]
    if errors:
        parts.append(
            "<div style='background:#fff3cd;padding:8px'><b>需要处理：</b><ul>"
            + "".join(f"<li>{html.escape(item)}</li>" for item in errors)
            + "</ul>"
            + (
                "<p>登录失效时，在仓库目录的 PowerShell 里运行 "
                "<code>automation\\.venv\\Scripts\\python.exe -m jobsinsight browser-login 平台名</code> 重新登录。</p>"
                if session_errors
                else ""
            )
            + "</div>"
        )
    parts.append(
        "<h3>概览</h3><ul>"
        f"<li>今日新增真实岗位：<b>{len(new)}</b> 条（国内 {len(domestic_new)}，海外 {len(overseas_new)}）</li>"
        f"<li>累计抓取到的真实岗位：{len(real)} 条；数据集总数 {len(jobs)} 条（含样例数据）</li>"
        f"<li>新增岗位方向：{counts(new, 'category')}</li>"
        f"<li>新增岗位城市：{counts(new, 'city')}</li>"
        f"<li>新增岗位公司：{counts(new, 'company')}</li>"
        f"<li>新增岗位薪资：{salary_stats(new)}</li>"
        "</ul>"
    )
    parts.append(_cadd_section(real, new, previous_master_eligible=previous_master_eligible))
    if summary.get("sources"):
        parts.append(
            "<h3>各来源运行情况</h3><ul>"
            + "".join(
                f"<li>{html.escape(str(source.get('name')))}：{html.escape(str(source.get('status', '')))} "
                f"{'采集 ' + str(source.get('collected', 0)) + ' 条'} "
                f"{html.escape(str(source.get('error') or source.get('note') or ''))}</li>"
                for source in summary["sources"]
            )
            + "</ul>"
        )
    parts.append(
        "<h3>今日新增国内岗位（按相关度排序）</h3>"
        + (table(domestic_new) if domestic_new else "<p>今天没有抓到新的国内岗位。</p>")
    )
    shown = overseas_new or overseas
    shown = sorted(shown, key=lambda job: -float(job.get("relevance") or 0))[:OVERSEAS_TABLE_LIMIT]
    extra = ""
    if len(overseas_new) > OVERSEAS_TABLE_LIMIT:
        extra = f"下表为相关度最高的 {OVERSEAS_TABLE_LIMIT} 条。"
    elif not overseas_new and overseas:
        extra = "今日没有新增，下表是相关度最高的海外岗位。"
    parts.append(
        "<h3>海外岗位</h3>"
        f"<p>海外岗位 <b>{len(overseas)}</b> 条，其中今日新增 {len(overseas_new)} 条。{extra}</p>"
        + (table(shown) if shown else "<p>今天没有海外岗位。</p>")
    )
    older = sorted(
        [job for job in real if job not in new and not is_overseas(job)],
        key=lambda job: str(job.get("first_seen_at")),
        reverse=True,
    )[:50]
    if older:
        parts.append("<h3>近期已抓到的其他真实岗位（最多 50 条）</h3>" + table(older))
    subject = f"[岗位日报] {today} 新增 {len(new)} 条" + (
        " ⚠需重新登录" if session_errors else (" ⚠运行有错误" if errors else "")
    )
    return subject, "".join(parts)


def table(rows: list[dict]) -> str:
    header = (
        "<table border=1 cellpadding=4 cellspacing=0 style='border-collapse:collapse;font-size:13px'>"
        "<tr><th>岗位</th><th>公司</th><th>城市</th><th>薪资</th><th>经验/学历</th><th>方向</th><th>平台</th><th>发布</th></tr>"
    )
    body = []
    for job in rows:
        title = html.escape(str(job.get("title", "")))
        url = job.get("url") or job.get("source_url")
        if url:
            title = f"<a href='{html.escape(str(url))}'>{title}</a>"
        salary = html.escape(_salary_label(job))
        body.append(
            "<tr>"
            f"<td>{title}</td>"
            f"<td>{html.escape(str(job.get('company', '')))}</td>"
            f"<td>{html.escape(str(job.get('city', '')))}</td>"
            f"<td>{salary}</td>"
            f"<td>{html.escape(_requirement(job.get('experience')))}/{html.escape(_requirement(job.get('education')))}</td>"
            f"<td>{html.escape(str(job.get('category', '')))}</td>"
            f"<td>{html.escape(str(job.get('platform', '')))}</td>"
            f"<td>{html.escape(str(job.get('publish_date', '')))}</td>"
            "</tr>"
        )
    return header + "".join(body) + "</table>"


def counts(rows: list[dict], key: str, limit: int = 10) -> str:
    ranked = collections.Counter(job.get(key) or "未知" for job in rows).most_common(limit)
    return "、".join(f"{name} {count}" for name, count in ranked) or "无"


def salary_stats(rows: list[dict]) -> str:
    """Median per currency and pay period. USD annual ranges are not labeled as monthly CNY."""

    from jobsinsight.heuristics import parse_salary_quote

    grouped: dict[tuple[str, str, str], list[tuple[float, int]]] = {}
    for job in rows:
        quote = parse_salary_quote(str(job.get("salary_text") or ""))
        if quote is not None:
            key = (quote.currency, quote.period, quote.unit)
            grouped.setdefault(key, []).append((quote.midpoint, quote.pay_months))
            continue
        # Numeric fields are the legacy monthly-CNY-in-thousands store. Ignore them
        # when salary_text already described another currency.
        if job.get("salary_min") and job.get("salary_max") and not str(job.get("salary_text") or "").strip():
            midpoint = (float(job["salary_min"]) + float(job["salary_max"])) / 2
            grouped.setdefault(("CNY", "month", "k"), []).append((midpoint, 0))
    if not grouped:
        return "无数据"
    order = [("CNY", "month", "k"), ("CNY", "year", "wan"), ("USD", "year", "k"), ("USD", "month", "k")]
    labels = {
        ("CNY", "month", "k"): "人民币/月",
        ("CNY", "year", "wan"): "人民币/年",
        ("USD", "year", "k"): "美元/年",
        ("USD", "month", "k"): "美元/月",
    }
    parts: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for key in [*order, *sorted(grouped)]:
        if key in seen or key not in grouped:
            continue
        seen.add(key)
        values = sorted(grouped[key])
        median = values[len(values) // 2][0]
        pay_counts = {months for _mid, months in values}
        months = next(iter(pay_counts))
        note = f"·{months}薪" if len(pay_counts) == 1 and months else ""
        unit = "万" if key[2] == "wan" else "k"
        label = labels.get(key, "/".join(key))
        parts.append(f"{label}中位数约 {median:.0f}{unit}{note}（{len(values)} 条）")
    return "；".join(parts)


CADD_NEW_TABLE_LIMIT = 20
# 硕士可投：岗位接受硕士，或学历只要本科 / 不限 / 没写。博士岗位不计入。
_MASTER_OK = frozenset({"", "不限", "学历不限", "硕士", "本科"})


def _matches_cadd(job: dict) -> bool:
    from jobsinsight.heuristics import matches_cadd_focus

    return matches_cadd_focus(job)


def _master_eligible(job: dict) -> bool:
    return str(job.get("education") or "").strip() in _MASTER_OK


def _master_trend(current: int, previous: int | None) -> str:
    if previous is None:
        return "硕士可投数量首次统计，尚无上次可比。"
    delta = current - previous
    if delta > 0:
        return f"硕士可投比上次多 {delta} 条。"
    if delta < 0:
        return f"硕士可投比上次少 {-delta} 条。"
    return "硕士可投与上次相同。"


def _education_label(job: dict) -> str:
    return str(job.get("education") or "").strip() or "未注明"


def _cadd_section(real: list[dict], new: list[dict], *, previous_master_eligible: int | None) -> str:
    """Statistics for CADD / AI药物研发, placed after the daily summary."""

    chosen = [job for job in real if _matches_cadd(job)]
    added = [job for job in new if _matches_cadd(job)]
    eligible = sum(1 for job in chosen if _master_eligible(job))
    domestic = sum(1 for job in chosen if not is_overseas(job))
    overseas = len(chosen) - domestic
    trend = _master_trend(eligible, previous_master_eligible)
    if not chosen:
        return (
            "<h3>CADD / AI药物研发</h3>"
            f"<p>累计 <b>0</b> 条，本次新增 <b>0</b> 条。没有来源的样例岗位不计入。{html.escape(trend)}</p>"
        )
    education_rows = [{**job, "education": _education_label(job)} for job in chosen]
    return (
        "<h3>CADD / AI药物研发</h3><ul>"
        f"<li>累计 <b>{len(chosen)}</b> 条，本次新增 <b>{len(added)}</b> 条"
        "（和上面的今日新增同一套规则：这次运行第一次见到的岗位）。</li>"
        f"<li>国内 {domestic} 条，海外 {overseas} 条。</li>"
        f"<li>学历：{counts(education_rows, 'education')}。"
        f"其中硕士可投 <b>{eligible}</b> 条（要求为硕士、本科、不限或未注明）。{html.escape(trend)}</li>"
        f"<li>经验：{counts(chosen, 'experience')}</li>"
        f"<li>城市：{counts(chosen, 'city')}</li>"
        f"<li>薪资：{salary_stats(chosen)}</li>"
        "</ul>"
        "<h4>本次新增的 CADD 岗位</h4>" + _cadd_new_table(added)
    )


def _cadd_new_table(rows: list[dict]) -> str:
    if not rows:
        return "<p>今天没有新增的 CADD 岗位。</p>"
    shown = rows[:CADD_NEW_TABLE_LIMIT]
    note = ""
    if len(rows) > CADD_NEW_TABLE_LIMIT:
        note = f"<p>新增 {len(rows)} 条，下表只列出前 {CADD_NEW_TABLE_LIMIT} 条。</p>"
    header = (
        "<table border=1 cellpadding=4 cellspacing=0 style='border-collapse:collapse;font-size:13px'>"
        "<tr><th>岗位</th><th>公司</th><th>城市</th><th>薪资</th><th>学历</th><th>链接</th></tr>"
    )
    body = []
    for job in shown:
        url = str(job.get("url") or job.get("source_url") or "").strip()
        link = f"<a href='{html.escape(url, quote=True)}'>打开</a>" if url else "无链接"
        body.append(
            "<tr>"
            f"<td>{html.escape(str(job.get('title', '')))}</td>"
            f"<td>{html.escape(str(job.get('company', '')))}</td>"
            f"<td>{html.escape(str(job.get('city', '')))}</td>"
            f"<td>{html.escape(_salary_label(job))}</td>"
            f"<td>{html.escape(_education_label(job))}</td>"
            f"<td>{link}</td>"
            "</tr>"
        )
    return note + header + "".join(body) + "</table>"


def cadd_state_counts(jobs: list[dict]) -> tuple[int, int]:
    """Cumulative CADD jobs and how many of them accept a master's degree."""

    chosen = [job for job in jobs if _keep_real(job) and _matches_cadd(job)]
    return len(chosen), sum(1 for job in chosen if _master_eligible(job))


def previous_master_eligible(state_dir: Path) -> int | None:
    from jobsinsight.store import StateStore

    raw = StateStore(state_dir).load_cadd_report_state().get("master_eligible")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def record_cadd_state(state_dir: Path, jobs: list[dict]) -> None:
    from jobsinsight.store import StateStore

    cumulative, eligible = cadd_state_counts(jobs)
    StateStore(state_dir).save_cadd_report_state(master_eligible=eligible, cumulative=cumulative)


def _salary_label(job: dict) -> str:
    salary_text = str(job.get("salary_text") or "").strip()
    if salary_text:
        return salary_text
    if job.get("salary_min"):
        return f"{job.get('salary_min', '')}-{job.get('salary_max', '')}k"
    return "面议"


def _requirement(value: object) -> str:
    text = str(value or "").strip()
    return text or "未知"


def _is_new(job: dict, *, now: dt.datetime, started: dt.datetime | None) -> bool:
    """A job is new when this run is the first time it was seen.

    ``started_at`` from the run log is the boundary. A second run the same day
    keeps the earlier ``first_seen_at`` and therefore reports no new jobs.
    Without a run start, fall back to the previous 26-hour window.
    """

    seen = _timestamp(job.get("first_seen_at"))
    if seen is None:
        return False
    if started is not None:
        if started.tzinfo is None:
            started = started.replace(tzinfo=dt.UTC)
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=dt.UTC)
        # first_seen is stamped during the run, after started_at. A later run
        # the same day keeps the earlier stamp and is not "new".
        return seen >= started
    anchor = now if now.tzinfo else now.replace(tzinfo=dt.UTC)
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=dt.UTC)
    return seen > anchor - dt.timedelta(hours=26)


def _timestamp(value: object) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def load_mail_env(repo: Path) -> None:
    """Fill unset variables from ``.env`` / ``.env.local``. Process env wins."""

    automation = repo / "automation"
    if str(automation) not in sys.path:
        sys.path.insert(0, str(automation))
    from jobsinsight.env import load_environment

    load_environment(repo)


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    load_mail_env(repo)
    run_log = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    fatal = sys.argv[2] if len(sys.argv) > 2 else ""
    to = os.environ.get("JOBSINSIGHT_REPORT_TO", "syidan00@outlook.com")
    user = os.environ["MAIL163_SMTP_USER"]
    code = os.environ["MAIL163_SMTP_AUTH_CODE"]
    summary = parse_run_summary(run_log.read_bytes()) if run_log and run_log.is_file() else {}
    errors = list(summary.get("errors", []))
    if fatal:
        errors.insert(0, fatal)
    jobs_path = repo / "web/public/data/jobs.json"
    jobs = json.loads(jobs_path.read_text(encoding="utf-8")) if jobs_path.is_file() else []
    if not isinstance(jobs, list):
        jobs = []
    now = dt.datetime.now(dt.UTC)
    today = dt.datetime.now().strftime("%Y-%m-%d")
    state_dir = repo / "automation" / "state"
    subject, body = build_report(
        jobs,
        summary,
        errors,
        now=now,
        today=today,
        previous_master_eligible=previous_master_eligible(state_dir),
    )
    message = MIMEText(body, "html", "utf-8")
    message["Subject"] = Header(subject, "utf-8")
    message["From"] = user
    message["To"] = to
    with smtplib.SMTP_SSL("smtp.163.com", 465, timeout=60) as smtp:
        smtp.login(user, code)
        smtp.sendmail(user, [to], message.as_string())
    record_cadd_state(state_dir, jobs)
    print("Report mailed:", subject)


if __name__ == "__main__":
    main()
