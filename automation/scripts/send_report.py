"""Build a daily HTML job report and mail it via 163 SMTP. Env: MAIL163_SMTP_USER, MAIL163_SMTP_AUTH_CODE, JOBSINSIGHT_REPORT_TO."""
import json, os, re, smtplib, sys, html, collections, datetime as dt
from email.mime.text import MIMEText
from email.header import Header
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
run_log = Path(sys.argv[1]) if len(sys.argv) > 1 else None
fatal = sys.argv[2] if len(sys.argv) > 2 else ""
to = os.environ.get("JOBSINSIGHT_REPORT_TO", "syidan00@outlook.com")
user = os.environ["MAIL163_SMTP_USER"]; code = os.environ["MAIL163_SMTP_AUTH_CODE"]
now = dt.datetime.now(dt.timezone.utc)

summary = {}
if run_log and run_log.exists():
    raw = run_log.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", errors="replace")
    text = "\n" + text.replace("\r\n", "\n")
    start = text.rfind('\n{\n'); 
    if start >= 0:
        depth = 0
        for i, ch in enumerate(text[start+1:], start+1):
            depth += ch == '{'; depth -= ch == '}'
            if depth == 0:
                try: summary = json.loads(text[start+1:i+1])
                except Exception: pass
                break
errors = list(summary.get("errors", []))
if fatal: errors.insert(0, fatal)
session_errors = [e for e in errors if "登录会话" in e or "验证码" in e or "captcha" in e.lower() or "browser-login" in e]

jobs = []
p = repo / "web/public/data/jobs.json"
if p.exists(): jobs = json.loads(p.read_text(encoding="utf-8"))
def ts(s):
    try: return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception: return None
real = [j for j in jobs if j.get("source_type")]
new = [j for j in real if (ts(j.get("first_seen_at")) or now - dt.timedelta(days=99)) > now - dt.timedelta(hours=26)]
new.sort(key=lambda j: -float(j.get("relevance") or 0))

def table(rows):
    h = "<table border=1 cellpadding=4 cellspacing=0 style='border-collapse:collapse;font-size:13px'><tr><th>岗位</th><th>公司</th><th>城市</th><th>薪资(k)</th><th>经验/学历</th><th>方向</th><th>平台</th><th>发布</th></tr>"
    for j in rows:
        t = html.escape(j.get("title","")); u = j.get("url") or j.get("source_url")
        if u: t = f"<a href='{html.escape(u)}'>{t}</a>"
        sal = f"{j.get('salary_min','')}-{j.get('salary_max','')}" if j.get("salary_min") else "面议"
        h += f"<tr><td>{t}</td><td>{html.escape(j.get('company',''))}</td><td>{html.escape(j.get('city',''))}</td><td>{sal}</td><td>{html.escape(j.get('experience',''))}/{html.escape(j.get('education',''))}</td><td>{html.escape(j.get('category',''))}</td><td>{html.escape(j.get('platform',''))}</td><td>{html.escape(str(j.get('publish_date','')))}</td></tr>"
    return h + "</table>"
def counts(rows, key, n=10):
    c = collections.Counter(j.get(key) or "未知" for j in rows).most_common(n)
    return "、".join(f"{k} {v}" for k, v in c) or "无"
def salary_stats(rows):
    v = sorted((float(j["salary_min"]) + float(j["salary_max"])) / 2 for j in rows if j.get("salary_min") and j.get("salary_max"))
    return f"中位数约 {v[len(v)//2]:.0f}k/月（{len(v)} 条有薪资）" if v else "无数据"

today = dt.datetime.now().strftime("%Y-%m-%d")
parts = [f"<h2>医疗健康 AI 岗位日报 {today}</h2>"]
if errors:
    parts.append("<div style='background:#fff3cd;padding:8px'><b>需要处理：</b><ul>" + "".join(f"<li>{html.escape(e)}</li>" for e in errors) + "</ul>" + ("<p>登录失效时，在仓库目录的 PowerShell 里运行 <code>automation\\.venv\\Scripts\\python.exe -m jobsinsight browser-login 平台名</code> 重新登录。</p>" if session_errors else "") + "</div>")
parts.append(f"<h3>概览</h3><ul><li>今日新增真实岗位：<b>{len(new)}</b> 条</li><li>累计抓取到的真实岗位：{len(real)} 条；数据集总数 {len(jobs)} 条（含样例数据）</li><li>新增岗位方向：{counts(new,'category')}</li><li>新增岗位城市：{counts(new,'city')}</li><li>新增岗位公司：{counts(new,'company')}</li><li>新增岗位薪资：{salary_stats(new)}</li></ul>")
if summary.get("sources"):
    parts.append("<h3>各来源运行情况</h3><ul>" + "".join(f"<li>{html.escape(str(s.get('name')))}：{html.escape(str(s.get('status', '')))} {'采集 ' + str(s.get('collected', 0)) + ' 条'} {html.escape(str(s.get('error','') or ''))}</li>" for s in summary["sources"]) + "</ul>")
parts.append("<h3>今日新增岗位（按相关度排序）</h3>" + (table(new) if new else "<p>今天没有抓到新岗位。</p>"))
older = sorted([j for j in real if j not in new], key=lambda j: str(j.get("first_seen_at")), reverse=True)[:50]
if older: parts.append("<h3>近期已抓到的其他真实岗位（最多 50 条）</h3>" + table(older))
body = "".join(parts)

subj = f"[岗位日报] {today} 新增 {len(new)} 条" + (" ⚠需重新登录" if session_errors else (" ⚠运行有错误" if errors else ""))
msg = MIMEText(body, "html", "utf-8"); msg["Subject"] = Header(subj, "utf-8"); msg["From"] = user; msg["To"] = to
with smtplib.SMTP_SSL("smtp.163.com", 465, timeout=60) as s:
    s.login(user, code); s.sendmail(user, [to], msg.as_string())
print("Report mailed:", subj)
