#!/usr/bin/env python3
"""AI Issue Radar — 看板 & README 排行榜生成器（纯标准库，无第三方依赖）

产出：
  1. docs/index.html   —— GitHub Pages 网页看板（ECharts 图表）
  2. README.md         —— 自动更新「信号排行榜」区块（<!-- STAR_SCOUT_BOARD:START/END --> 之间）
"""
import csv
import datetime
import json
import os
import sqlite3
import sys
from collections import defaultdict
from statistics import median

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "data", "radar.db")
CSV_PATH = os.path.join(ROOT, "data", "signal.csv")
DOCS_HTML = os.path.join(ROOT, "docs", "index.html")
README_PATH = os.path.join(ROOT, "README.md")

BOARD_START = "<!-- STAR_SCOUT_BOARD:START -->"
BOARD_END = "<!-- STAR_SCOUT_BOARD:END -->"


def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def load_data():
    conn = sqlite3.connect(DB_PATH)
    # 每个跟踪仓库的最新快照
    snaps = conn.execute(
        """SELECT s.full_name, s.date, s.stars, s.open_issues
           FROM snapshots s
           JOIN repos r ON r.full_name = s.full_name AND r.status='tracked'
           WHERE s.date = (SELECT MAX(date) FROM snapshots WHERE full_name = s.full_name)
        """
    ).fetchall()
    stats = {
        "repos": conn.execute("SELECT COUNT(*) FROM repos WHERE status='tracked'").fetchone()[0],
        "snapshots": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        "issues": conn.execute("SELECT COUNT(*) FROM issue_samples").fetchone()[0],
        "responded": conn.execute(
            "SELECT COUNT(*) FROM issue_samples WHERE first_response_at IS NOT NULL"
        ).fetchone()[0],
    }
    # 每个仓库响应时长中位数（小时）
    resp_hours = defaultdict(list)
    for fn, ca, fr in conn.execute(
        "SELECT full_name, created_at, first_response_at FROM issue_samples "
        "WHERE first_response_at IS NOT NULL"
    ):
        a, b = parse_dt(ca), parse_dt(fr)
        if a and b:
            resp_hours[fn].append((b - a).total_seconds() / 3600.0)
    resp_med = {fn: round(median(v), 1) for fn, v in resp_hours.items() if v}
    # 趋势（≥2 天快照的仓库）
    trend = defaultdict(list)
    for fn, date, stars, oi in conn.execute(
        """SELECT full_name, date, stars, open_issues FROM snapshots
           WHERE full_name IN (
             SELECT full_name FROM snapshots GROUP BY full_name HAVING COUNT(*) >= 2)
           ORDER BY full_name, date"""
    ):
        trend[fn].append({"date": date, "stars": stars, "open_issues": oi})
    conn.close()

    latest = [{"full_name": fn, "date": d, "stars": s or 0, "open_issues": oi or 0} for fn, d, s, oi in snaps]
    for r in latest:
        r["issue_ratio"] = round(r["open_issues"] / max(r["stars"], 1), 4)
        r["resp_hours"] = resp_med.get(r["full_name"])
    latest.sort(key=lambda r: r["open_issues"], reverse=True)

    # 信号（≥2 天）
    signals = []
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            signals = list(csv.DictReader(f))

    data_date = max((r["date"] for r in latest), default=datetime.date.today().isoformat())
    return {"stats": stats, "latest": latest, "signals": signals, "trend": trend, "date": data_date}


def build_leaderboard_md(data):
    """生成 README 排行榜内容（信号不足时用当前快照兜底）"""
    lines = [f"数据截至 **{data['date']}** · 完整图表看板见仓库 `docs/index.html`（GitHub Pages）", ""]

    # 🔥 星速榜（≥2 天信号）
    lines.append("### 🔥 星速榜（星/天，需 ≥2 天快照）")
    lines.append("")
    sig = [s for s in data["signals"] if float(s.get("stars_per_day") or 0) > 0]
    if sig:
        sig.sort(key=lambda s: float(s["stars_per_day"]), reverse=True)
        lines.append("| # | 仓库 | 星速(天) | 加速度 | 信号 |")
        lines.append("|---|---|---|---|---|")
        for i, s in enumerate(sig[:5], 1):
            lines.append(f"| {i} | {s['full_name']} | {s['stars_per_day']} | {s['accel_x']} | {s['signal']} |")
    else:
        lines.append("⏳ 第 2 天快照后自动出现（所有仓库目前只有 1 天数据）。")
    lines.append("")

    # ⚠️ 积压榜（当前快照兜底）
    lines.append("### ⚠️ 积压比榜（open issues / stars）")
    lines.append("")
    backlog = sorted(data["latest"], key=lambda r: r["issue_ratio"], reverse=True)[:5]
    lines.append("| # | 仓库 | 积压比 | open issues | stars |")
    lines.append("|---|---|---|---|---|")
    for i, r in enumerate(backlog, 1):
        lines.append(f"| {i} | {r['full_name']} | {r['issue_ratio']:.2%} | {r['open_issues']} | {r['stars']} |")
    lines.append("")

    # 🐢 响应最慢榜
    lines.append("### 🐢 响应最慢榜（首个非作者评论中位数）")
    lines.append("")
    slow = [r for r in data["latest"] if r.get("resp_hours") is not None]
    if slow:
        slow.sort(key=lambda r: r["resp_hours"], reverse=True)
        lines.append("| # | 仓库 | 响应时长 | open issues |")
        lines.append("|---|---|---|---|")
        for i, r in enumerate(slow[:5], 1):
            lines.append(f"| {i} | {r['full_name']} | {r['resp_hours']}h | {r['open_issues']} |")
    else:
        lines.append("⏳ 采集到带响应的 issue 后自动出现。")
    lines.append("")

    lines.append("> 星速 = 总星差/天数；积压比 ≥5% 视为积压；响应时长 = issue 首个非作者评论时间中位数（小时）。")
    return "\n".join(lines)


def update_readme(board_md):
    if not os.path.exists(README_PATH):
        print("[dashboard] 未找到 README.md，跳过排行榜更新")
        return
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    section = f"\n## 📊 信号排行榜（每日自动更新）\n\n{BOARD_START}\n{board_md}\n{BOARD_END}\n"
    if BOARD_START in content and BOARD_END in content:
        pre = content.split(BOARD_START)[0]
        post = content.split(BOARD_END)[1]
        content = pre + BOARD_START + "\n" + board_md + "\n" + BOARD_END + post
    else:
        content = content.rstrip() + "\n\n" + section
    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print("[dashboard] README.md 排行榜已更新")


def build_html(data):
    payload = {
        "date": data["date"],
        "stats": data["stats"],
        "latest": data["latest"],
        "signals": data["signals"],
        "trend": data["trend"],
    }
    js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__PAYLOAD__", js)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Star Scout · 腰部 AI 项目雷达</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  :root{
    --bg:#0f1420; --card:#1a2130; --card2:#141a28; --line:#2a3550;
    --text:#e5e9f0; --muted:#8b96ad; --accent:#7aa2ff; --gold:#ffd166; --green:#7ee0c3; --red:#ff7a8a;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:-apple-system,"PingFang SC","Microsoft YaHei",Segoe UI,Roboto,sans-serif;padding:24px 20px 60px}
  header{max-width:1200px;margin:0 auto 20px}
  h1{font-size:26px;letter-spacing:.5px}
  h1 .star{color:var(--gold)}
  .sub{color:var(--muted);font-size:13px;margin-top:6px}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;max-width:1200px;margin:0 auto 20px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
  .card .num{font-size:26px;font-weight:700;margin-top:4px}
  .card .lbl{color:var(--muted);font-size:12px}
  .grid{max-width:1200px;margin:0 auto;display:grid;grid-template-columns:repeat(auto-fit,minmax(520px,1fr));gap:16px}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px 8px}
  .panel h2{font-size:15px;margin-bottom:4px}
  .panel .hint{color:var(--muted);font-size:12px;margin-bottom:8px}
  .chart{width:100%;height:360px}
  .empty{color:var(--muted);text-align:center;padding:40px 0;font-size:13px}
  table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
  th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
  th{color:var(--muted);font-weight:600}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  .pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px}
  .pill.hot{background:rgba(255,209,102,.15);color:var(--gold)}
  .pill.warn{background:rgba(255,122,138,.15);color:var(--red)}
  .pill.ok{background:rgba(126,224,195,.15);color:var(--green)}
  .pill.mid{background:rgba(122,162,255,.15);color:var(--accent)}
  .muted{color:var(--muted)}
  footer{max-width:1200px;margin:24px auto 0;color:var(--muted);font-size:11px;text-align:center}
  @media(max-width:640px){.grid{grid-template-columns:1fr}.chart{height:300px}}
</style>
</head>
<body>
<header>
  <h1><span class="star">★</span> Star Scout · 腰部 AI 项目雷达</h1>
  <div class="sub">每日采集 GitHub 腰部 AI 项目的星速 / open issues / 响应时长，信号为启发式规则，仅用于可行性验证，不构成投资建议。</div>
</header>

<div class="stats" id="stats"></div>

<div class="grid">
  <div class="panel">
    <h2>当前 open issues 最多 Top 15</h2>
    <div class="hint">腰部 AI 项目 issue 堆积程度速览</div>
    <div class="chart" id="cOpen"></div>
  </div>
  <div class="panel">
    <h2>积压比 Top 15（open / stars）</h2>
    <div class="hint">≥5% 视为积压，越高越"该避雷"</div>
    <div class="chart" id="cRatio"></div>
  </div>
  <div class="panel">
    <h2>响应最慢 Top 15</h2>
    <div class="hint">issue 首个非作者评论中位数（小时），越高越冷</div>
    <div class="chart" id="cResp"></div>
  </div>
  <div class="panel">
    <h2>星速榜 Top 15（星/天）</h2>
    <div class="hint">需 ≥2 天快照，第 2 天起自动出现</div>
    <div class="chart" id="cStar"></div>
  </div>
</div>

<div class="grid" style="margin-top:16px">
  <div class="panel" style="grid-column:1/-1">
    <h2>全部跟踪仓库明细</h2>
    <div class="hint">最新快照 · 点击列头可排序（简单实现：已按 open issues 降序）</div>
    <div id="tableWrap" style="overflow-x:auto"></div>
  </div>
</div>

<footer>数据日期 <span id="fdate"></span> · 由 GitHub Actions 每日自动更新 · Star Scout</footer>

<script>
const D = __PAYLOAD__;
document.getElementById('fdate').textContent = D.date;
const stats = D.stats;
const statCards = [
  ['跟踪仓库', stats.repos, 'var(--accent)'],
  ['快照条数', stats.snapshots, 'var(--green)'],
  ['issue 采样', stats.issues, 'var(--gold)'],
  ['有响应时长', stats.responded, 'var(--red)'],
];
document.getElementById('stats').innerHTML = statCards.map(([l,n,c]) =>
  `<div class="card"><div class="lbl">${l}</div><div class="num" style="color:${c}">${n}</div></div>`).join('');

const AXIS = '#8b96ad', TEXT = '#e5e9f0';
function hbar(id, names, vals, color){
  const el = document.getElementById(id);
  if(!names.length){ el.innerHTML = '<div class="empty">暂无数据 · 等待第 2 天快照</div>'; return; }
  const c = echarts.init(el, null, {renderer:'canvas'});
  window.addEventListener('resize', ()=>c.resize());
  c.setOption({
    grid:{left:8,right:36,top:8,bottom:8,containLabel:true},
    tooltip:{trigger:'axis',axisPointer:{type:'shadow'},backgroundColor:'#1a2130',borderColor:'#2a3550',textStyle:{color:TEXT}},
    xAxis:{type:'value',axisLabel:{color:AXIS},splitLine:{lineStyle:{color:'#232c40'}}},
    yAxis:{type:'category',data:names,inverse:true,axisLabel:{color:TEXT,fontSize:11,width:230,overflow:'truncate'}},
    series:[{type:'bar',data:vals,itemStyle:{color},barMaxWidth:14,label:{show:true,position:'right',color:AXIS,fontSize:11}}]
  });
}

const L = D.latest;
hbar('cOpen', L.slice(0,15).map(r=>r.full_name), L.slice(0,15).map(r=>r.open_issues), '#ff7a8a');
const ratio = [...L].sort((a,b)=>b.issue_ratio-a.issue_ratio);
hbar('cRatio', ratio.slice(0,15).map(r=>r.full_name), ratio.slice(0,15).map(r=>+(r.issue_ratio*100).toFixed(2)), '#ffd166');
const resp = [...L].filter(r=>r.resp_hours!=null).sort((a,b)=>b.resp_hours-a.resp_hours);
hbar('cResp', resp.slice(0,15).map(r=>r.full_name), resp.slice(0,15).map(r=>r.resp_hours), '#7aa2ff');

// 星速榜（信号）
const sig = D.signals.filter(s=>+s.stars_per_day>0).sort((a,b)=>+b.stars_per_day-+a.stars_per_day);
hbar('cStar', sig.slice(0,15).map(s=>s.full_name), sig.slice(0,15).map(s=>+s.stars_per_day), '#7ee0c3');

// 明细表
const tbody = D.latest.map(r=>{
  const pct = (r.issue_ratio*100).toFixed(2)+'%';
  const pill = r.issue_ratio>=0.05 ? '<span class="pill warn">积压</span>' : '<span class="pill ok">健康</span>';
  const rh = r.resp_hours==null ? '—' : r.resp_hours+'h';
  return `<tr><td>${r.full_name}</td><td class="num">${r.stars}</td><td class="num">${r.open_issues}</td><td class="num">${pct}</td><td>${pill}</td><td class="num">${rh}</td></tr>`;
}).join('');
document.getElementById('tableWrap').innerHTML =
  `<table><thead><tr><th>仓库</th><th class="num">stars</th><th class="num">open issues</th><th class="num">积压比</th><th>状态</th><th class="num">响应时长</th></tr></thead><tbody>${tbody}</tbody></table>`;
</script>
</body>
</html>
"""


def main():
    data = load_data()
    os.makedirs(os.path.dirname(DOCS_HTML), exist_ok=True)
    with open(DOCS_HTML, "w", encoding="utf-8") as f:
        f.write(build_html(data))
    print(f"[dashboard] 看板 -> {DOCS_HTML}")
    update_readme(build_leaderboard_md(data))
    print(f"[dashboard] 完成：日期 {data['date']}，跟踪 {data['stats']['repos']} 仓库，信号 {len(data['signals'])} 条")


if __name__ == "__main__":
    main()
