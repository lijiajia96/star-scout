#!/usr/bin/env python3
"""AI Issue Radar — 候选发现器（腰部 AI 项目）
用 GitHub Search API 按「topic + 星标区间 + 近期活跃」找出候选，
再做「必须 AI 相关」领域过滤（topic 命中 或 描述关键词命中），
插入 repos 表（status=tracked）供每日采集。

用法：
  python3 discover.py [N]        # 新增 N 个候选（默认按配置 max_repos_per_run）
  python3 discover.py 10 --prune # 新增候选，并移除已跟踪但非 AI 领域的仓库
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import github_api as gh

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
CANDIDATES_PATH = os.path.join(ROOT, "data", "candidates.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_ai_filter(cfg):
    """返回 (ai_topics, [compiled patterns])。require=false 时返回空过滤（放行一切）"""
    ad = cfg.get("ai_domain", {})
    if not ad.get("require", True):
        return set(), []
    topics = {t.strip().lower() for t in ad.get("topics", []) if t.strip()}
    patterns = []
    for kw in ad.get("keywords", []):
        kw = str(kw).strip().lower()
        if not kw:
            continue
        try:
            patterns.append(re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE))
        except re.error:
            continue
    return topics, patterns


def is_ai_related(description, topics, ai_topics, patterns):
    """topic 命中 或 描述命中关键词 → 视为 AI 相关"""
    if topics:
        tl = {str(t).lower() for t in topics}
        if tl & ai_topics:
            return True
    if description:
        for p in patterns:
            if p.search(description):
                return True
    return False


def build_query(cfg, topic):
    d = cfg["腰部定义"]
    today = datetime.date.today()
    pushed_after = (today - datetime.timedelta(days=d["recent_push_days"])).isoformat()
    created_after = (today - datetime.timedelta(days=d["min_created_days"])).isoformat()
    created_before = (today - datetime.timedelta(days=d["max_created_days"])).isoformat()
    return (f"topic:{topic} stars:{d['min_stars']}..{d['max_stars']} "
            f"pushed:>{pushed_after} created:{created_after}..{created_before}")


def discover(cfg, limit):
    conn = db.connect(os.path.join(ROOT, cfg.get("db_path", "data/radar.db")))
    already = set(db.tracked_repos(conn))
    topics = cfg.get("搜索主题", ["ai", "llm", "agent"])
    ai_topics, patterns = load_ai_filter(cfg)
    require_ai = cfg.get("ai_domain", {}).get("require", True)
    found = {}

    for topic in topics:
        q = build_query(cfg, topic)
        st, data = gh.get_json("/search/repositories",
                               {"q": q, "sort": "stars", "order": "desc", "per_page": 100})
        if st != 200 or not data:
            print(f"  [warn] search topic={topic} http={st}")
            time.sleep(8)
            continue
        for r in data.get("items", []):
            fn = r["full_name"]
            if fn in already or fn in found:
                continue
            if r.get("archived"):
                continue
            desc = r.get("description") or ""
            rtopics = r.get("topics") or []
            if require_ai and not is_ai_related(desc, rtopics, ai_topics, patterns):
                continue
            found[fn] = {
                "full_name": fn,
                "stars": r.get("stargazers_count"),
                "forks": r.get("forks_count"),
                "created_at": r.get("created_at"),
                "pushed_at": r.get("pushed_at"),
                "description": desc[:160],
                "topics": rtopics,
                "topic": topic,
            }
        print(f"  [search] topic={topic} -> {len(data.get('items', []))} hits, "
              f"AI 相关累计唯一候选 {len(found)}"
              + ("" if require_ai else "（领域过滤已关闭）"))
        time.sleep(8)  # Search API 未认证约 10/min

    # 按星标降序取前 N 个新候选
    ranked = sorted(found.values(), key=lambda x: x["stars"], reverse=True)[:limit]
    print(f"== 新增 AI 候选 {len(ranked)} 个（已跟踪 {len(already)}）==")
    for r in ranked:
        db.upsert_repo(conn, r["full_name"], r["created_at"], source="search")
        print(f"  + {r['full_name']}  ⭐{r['stars']}  [{(r['topics'] or ['-'])[:3]}]  {(r['description'] or '')[:60]}")

    with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
        json.dump(list(found.values()), f, ensure_ascii=False, indent=2)
    print(f"AI 候选全量清单 -> {CANDIDATES_PATH}")
    conn.close()
    return len(ranked)


def prune(cfg, conn, ai_topics, patterns):
    """移除已跟踪但非 AI 领域的仓库（用候选清单的描述判定，避免额外 API 调用）"""
    removed = 0
    try:
        with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
            known = {c["full_name"]: c for c in json.load(f)}
    except Exception:
        known = {}
    for fn in db.tracked_repos(conn):
        meta = known.get(fn)
        if not meta:
            continue  # 不在候选清单里（无法核验描述），保持不动
        if is_ai_related(meta.get("description") or "", meta.get("topics") or [],
                         ai_topics, patterns):
            continue
        conn.execute("UPDATE repos SET status='removed' WHERE full_name=?", (fn,))
        removed += 1
        print(f"  [prune] 移除非 AI 领域: {fn}")
    conn.commit()
    return removed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("limit", nargs="?", default="auto", help="新增候选数量，auto=按配置")
    ap.add_argument("--prune", action="store_true", help="同时移除已跟踪但非 AI 的仓库")
    args = ap.parse_args(argv)
    cfg = load_config()
    limit = cfg["采集"].get("max_repos_per_run", 30) if args.limit == "auto" else int(args.limit)

    ai_topics, patterns = load_ai_filter(cfg)
    n = discover(cfg, limit)
    if args.prune:
        conn = db.connect(os.path.join(ROOT, cfg.get("db_path", "data/radar.db")))
        r = prune(cfg, conn, ai_topics, patterns)
        print(f"== 清理完成：移除 {r} 个非 AI 仓库 ==")
        conn.close()
    return n


if __name__ == "__main__":
    main()
