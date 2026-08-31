#!/usr/bin/env python3
"""Star Scout — 推荐评分算法（纯标准库）

目标：找出「值得跟踪 issue / 提 PR」的优质仓库 = 发展好 + 响应快 + 可参与 + 社区认可。

综合分(0-100) = 100 × (0.25·growth + 0.30·responsiveness + 0.20·issue_health + 0.25·quality)

因子（各 0~1；缺数据取中性 0.5，避免冷启动一票否决）：
  growth          0.6·星速分(min(1, 日均星/10)) + 0.4·近期活跃分(最近 push ≤7 天=1 → 60 天=0)
  responsiveness  issue 响应时长连续分档 × 样本量可靠性(≥8 样本全信，少则向中性收缩)
  issue_health    0.5·可参与度(open issues 30~400 最佳) + 0.5·积压健康(积压比越低越好)
  quality         log10(stars+1)/4（1 万星 ≈ 1.0）

分级：≥75 优质 · 60-74 较活跃 · 45-59 一般 · <45 观望
"""
import datetime
import math


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def freshness_days(data_date, pushed_at):
    """最近 push 距今的天数（按数据日期），无数据返回 None"""
    pt = parse_dt(pushed_at)
    if not pt:
        return None
    try:
        dd = datetime.date.fromisoformat(str(data_date))
    except Exception:
        return None
    return max(0, (dd - pt.date()).days)


def growth_score(vel, fresh_days):
    """发展势头：星速(无数据中性 0.5) + 近期活跃度"""
    vel_norm = clamp(vel / 10.0) if vel is not None else 0.5
    if fresh_days is None:
        fresh = 0.5
    elif fresh_days <= 7:
        fresh = 1.0
    else:
        fresh = clamp(1.0 - (fresh_days - 7) / 53.0)   # 60 天后归零
    return 0.6 * vel_norm + 0.4 * fresh


def responsiveness_score(resp_hours, sample_n=0):
    """维护响应：issue 首个非作者评论中位数（小时）。连续分档 + 样本量可靠性。
    样本少(<8)时向中性 0.5 收缩，避免 1 个样本的 0 小时误导排名。"""
    if resp_hours is None:
        return 0.5
    if resp_hours <= 6:
        s = 1.0
    elif resp_hours <= 24:
        s = 1.0 - (resp_hours - 6) / 18 * 0.15          # 6h~24h: 1.0→0.85
    elif resp_hours <= 72:
        s = 0.85 - (resp_hours - 24) / 48 * 0.25         # 24h~72h: 0.85→0.60
    elif resp_hours <= 168:
        s = 0.60 - (resp_hours - 72) / 96 * 0.20         # 72h~168h: 0.60→0.40
    elif resp_hours <= 720:
        s = 0.40 - (resp_hours - 168) / 552 * 0.20       # 168h~720h: 0.40→0.20
    else:
        s = max(0.05, 0.20 - (resp_hours - 720) / 4000 * 0.15)
    rel = clamp(sample_n / 8.0)
    return 0.5 + (s - 0.5) * rel


def opportunity_score(open_issues):
    """可参与度：open issues 30~400 最理想（有活可干又不被淹没）"""
    if open_issues is None:
        return 0.5
    if open_issues <= 30:
        return open_issues / 30.0
    if open_issues <= 400:
        return 1.0
    return max(0.5, 1.0 - (open_issues - 400) / 1200.0)


def ratio_health(ratio):
    """积压健康：open_issues/stars 越低越好"""
    if ratio < 0.03:
        return 1.0
    if ratio < 0.06:
        return 0.8
    if ratio < 0.10:
        return 0.55
    if ratio < 0.15:
        return 0.30
    return 0.15


def issue_health_score(open_issues, ratio):
    return 0.5 * opportunity_score(open_issues) + 0.5 * ratio_health(ratio or 0)


def quality_score(stars):
    """社区认可：星标对数（1 万星 ≈ 满分）"""
    return clamp(math.log10(max(stars, 0) + 1) / 4.0)


def grade(score):
    if score >= 75:
        return "优质"
    if score >= 60:
        return "较活跃"
    if score >= 45:
        return "一般"
    return "观望"


def compute_scores(repos, data_date, weights=None):
    """repos: [{full_name, stars, open_issues, issue_ratio, resp_hours, resp_samples, pushed_at, stars_per_day?}]
    返回按综合分降序的列表，每项含 score/grade/breakdown。"""
    w = weights or {"growth": 0.25, "responsiveness": 0.30, "issue_health": 0.20, "quality": 0.25}
    out = []
    for r in repos:
        growth = growth_score(r.get("stars_per_day"), freshness_days(data_date, r.get("pushed_at")))
        resp = responsiveness_score(r.get("resp_hours"), r.get("resp_samples") or 0)
        health = issue_health_score(r.get("open_issues"), r.get("issue_ratio"))
        qual = quality_score(r.get("stars") or 0)
        score = 100 * (w["growth"] * growth + w["responsiveness"] * resp +
                       w["issue_health"] * health + w["quality"] * qual)
        out.append({
            "full_name": r["full_name"],
            "score": round(score, 1),
            "grade": grade(score),
            "breakdown": {
                "growth": round(growth, 3),
                "responsiveness": round(resp, 3),
                "issue_health": round(health, 3),
                "quality": round(qual, 3),
            },
            "stars": r.get("stars"),
            "open_issues": r.get("open_issues"),
            "issue_ratio": r.get("issue_ratio"),
            "resp_hours": r.get("resp_hours"),
            "resp_samples": r.get("resp_samples"),
            "stars_per_day": r.get("stars_per_day"),
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out
