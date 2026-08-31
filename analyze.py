#!/usr/bin/env python3
"""AI Issue Radar — 信号分析器
对每个跟踪 ≥2 天的仓库计算：
  · 星速（总/日均、最近一天、加速度）
  · open issues 变化与积压比
  · issue 响应时长中位数（小时）
输出：data/signal.csv + data/reports/YYYY-MM-DD.md（验证信号质量）
"""
import argparse
import csv
import datetime
import json
import os
import sys
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def classify(cfg, stars_per_day, issue_ratio, resp_hours, open_issues):
    t = cfg["信号阈值"]
    if stars_per_day >= t.get("爆发_stars_per_day", 50):
        if issue_ratio >= t.get("issue积压_ratio", 0.05):
            return "爆发但issue积压"
        return "爆发且健康"
    if stars_per_day >= t.get("增长_stars_per_day", 8):
        return "平稳增长"
    return "停滞/冷却"


def robust_star_velocity(snaps):
    """抗断档星速：用相邻快照的『日均增量』中位数，而不是首末差/总天数。
    某天 Actions 失败导致断档时，首末法会低估；中位数法只受影响一段，且更稳健。
    返回 (稳健星速, 最近一天日均增量)"""
    rates = []
    for (d0, s0, *_), (d1, s1, *_) in zip(snaps, snaps[1:]):
        try:
            gap = (datetime.date.fromisoformat(d1) - datetime.date.fromisoformat(d0)).days
        except Exception:
            continue
        if gap <= 0 or s0 is None or s1 is None:
            continue
        rates.append((s1 - s0) / gap)
    if not rates:
        return 0.0, 0.0
    return median(rates), rates[-1]


def analyze(cfg):
    conn = db.connect(os.path.join(ROOT, cfg.get("db_path", "data/radar.db")))
    repos = db.tracked_repos(conn)
    t = cfg["信号阈值"]
    rows = []

    for fn in repos:
        snaps = db.snapshots_for(conn, fn)
        if len(snaps) < 2:
            continue
        d0, s0, f0, i0, _ = snaps[0]
        d1, s1, f1, i1, _ = snaps[-1]
        span = (datetime.date.fromisoformat(d1) - datetime.date.fromisoformat(d0)).days or 1
        star_delta = (s1 or 0) - (s0 or 0)
        avg_per_day, recent_per_day = robust_star_velocity(snaps)   # 抗断档
        accel = (recent_per_day / avg_per_day) if avg_per_day else 0.0
        issue_delta = (i1 or 0) - (i0 or 0)
        issue_ratio = (i1 or 0) / max(s1 or 1, 1)

        # 响应时长（小时）—— 仅统计过滤机器人后的人类响应
        samples = db.response_samples(conn, fn)
        resp_hours = None
        if samples:
            hours = []
            for ca, fr in samples:
                a, b = parse_dt(ca), parse_dt(fr)
                if a and b:
                    hours.append((b - a).total_seconds() / 3600.0)
            if hours:
                resp_hours = round(median(hours), 1)

        sig = classify(cfg, avg_per_day, issue_ratio, resp_hours, i1)
        rows.append({
            "full_name": fn,
            "days": span,
            "stars_from": s0, "stars_to": s1,
            "star_delta": star_delta, "stars_per_day": round(avg_per_day, 2),
            "recent_per_day": round(recent_per_day, 2), "accel_x": round(accel, 2),
            "open_issues_from": i0, "open_issues_to": i1, "issue_delta": issue_delta,
            "issue_ratio": round(issue_ratio, 4),
            "resp_hours": resp_hours,
            "signal": sig,
        })

    rows.sort(key=lambda r: r["stars_per_day"], reverse=True)
    write_outputs(cfg, rows)
    print(f"== 分析完成：{len(rows)} 个仓库有 ≥2 天数据 ==")
    for r in rows[:15]:
        print(f"  {r['signal']:<8} {r['full_name']:<40} "
              f"星速 {r['stars_per_day']:>7}/天  积压比 {r['issue_ratio']:.3f}  "
              f"响应 {r['resp_hours']}h")
    conn.close()


def write_outputs(cfg, rows):
    csv_path = os.path.join(ROOT, cfg.get("csv_path", "data/signal.csv"))
    fieldnames = ["full_name", "days", "stars_from", "stars_to", "star_delta",
                  "stars_per_day", "recent_per_day", "accel_x", "open_issues_from",
                  "open_issues_to", "issue_delta", "issue_ratio", "resp_hours", "signal"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in fieldnames})

    date_str = datetime.date.today().isoformat()
    report_dir = os.path.join(ROOT, cfg.get("report_dir", "data/reports"))
    os.makedirs(report_dir, exist_ok=True)
    lines = [
        f"# AI Issue Radar · 信号质量报告 {date_str}",
        "",
        f"覆盖仓库数（≥2 天快照）：**{len(rows)}**",
        "",
        "| 信号 | 仓库 | 星速(天) | 加速度(x) | 积压比 | 响应(h) | 说明 |",
        "|---|---|---|---|---|---|---|",
    ]
    t = cfg["信号阈值"]
    for r in rows:
        lines.append(
            f"| {r['signal']} | {r['full_name']} | {r['stars_per_day']} | {r['accel_x']} | "
            f"{r['issue_ratio']:.3f} | {r['resp_hours'] or '-'} | "
            f"Δ星 {r['star_delta']:+} / Δissue {r['issue_delta']:+} |"
        )
    lines += [
        "",
        "## 口径",
        f"- 星速 = 总星差/天数；加速度 = 最近一天增量 / 日均星速（>1 表示在加速）",
        f"- 积压比 = open_issues / stars；响应时长 = issue 首个非作者评论时间中位数（小时）",
        f"- 阈值：爆发≥{t.get('爆发_stars_per_day', 50)}/天，增长≥{t.get('增长_stars_per_day', 8)}/天，"
        f"积压比≥{t.get('issue积压_ratio', 0.05)}，响应快<{t.get('响应快_hours', 24)}h，慢>{t.get('响应慢_hours', 168)}h",
        f"- 数据：GitHub REST API 每日快照；本报告为信号质量验证，非投资建议",
    ]
    report_path = os.path.join(report_dir, f"{date_str}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"报告 -> {report_path}")


if __name__ == "__main__":
    cfg = load_config()
    analyze(cfg)
