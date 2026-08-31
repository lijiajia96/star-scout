#!/usr/bin/env python3
"""AI Issue Radar — 每日采集器
快照：stars / forks / open_issues / watchers / pushed_at
采样：open issues（标题、创建时间、首个非作者评论时间 = 响应时长）

用法：
  python3 collect.py                       # 采集所有 tracked 仓库
  python3 collect.py --repos a/b,c/d       # 只采集指定仓库
  python3 collect.py --discover            # 先跑 discover 发现候选，再采集
  python3 collect.py --responses 0         # 跳过响应时长采样（省配额）
"""
import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import github_api as gh

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def today():
    return datetime.date.today().isoformat()


def first_response_at(full_name, issue):
    """返回该 issue 首个非作者评论的 created_at；无则 None"""
    st, comments = gh.get_json(f"/repos/{full_name}/issues/{issue['number']}/comments", {"per_page": 100})
    if st != 200 or not comments:
        return None
    author = (issue.get("user") or {}).get("login")
    for c in comments:
        if (c.get("user") or {}).get("login") != author:
            return c.get("created_at")
    return None


def collect_repo(conn, full_name, cfg, date_str, with_responses):
    cfg_collect = cfg["采集"]
    st, info = gh.get_json(f"/repos/{full_name}")
    if st != 200 or not info:
        print(f"  [skip] {full_name} http={st}")
        return 0

    db.upsert_repo(conn, full_name, info.get("created_at"), source="search")
    db.add_snapshot(
        conn, full_name, date_str,
        stars=info.get("stargazers_count"),
        forks=info.get("forks_count"),
        open_issues=info.get("open_issues_count"),
        watchers=info.get("subscribers_count"),
        pushed_at=info.get("pushed_at"),
    )

    # open issues 采样（issues 端点会混入 PR，需过滤）
    sample = []
    pages = cfg_collect.get("max_open_issue_pages", 2)
    for page in range(1, pages + 1):
        st, items = gh.get_json(f"/repos/{full_name}/issues",
                                {"state": "open", "per_page": 100, "page": page})
        if st != 200 or not items:
            break
        for it in items:
            if "pull_request" in it:
                continue
            sample.append(it)

    resp_nums = set()
    if with_responses:
        resp_nums = {it["number"] for it in sample[: cfg_collect.get("response_sample_per_repo", 10)]}

    for it in sample:
        first_resp = first_response_at(full_name, it) if it["number"] in resp_nums else None
        db.upsert_issue(conn, full_name, it.get("number"), it.get("title"),
                        it.get("state"), it.get("created_at"), first_resp, date_str)

    print(f"  [ok] {full_name}: stars={info.get('stargazers_count')} "
          f"open_issues={info.get('open_issues_count')} sampled_issues={len(sample)}")
    return 1


def preflight_rate_limit(cfg):
    """启动前查一次配额（/rate_limit 不计配额）；不足则优雅退出，等明天 cron"""
    floor = cfg["采集"].get("min_rate_limit_floor", 25)
    st, data = gh.get_json("/rate_limit")
    if st == 200 and data:
        core = data.get("resources", {}).get("core", {})
        rem = core.get("remaining")
        print(f"  配额检查：core remaining={rem}/{core.get('limit')}（下限 {floor}）")
        if rem is not None and rem < floor and not gh.TOKEN:
            print("  [abort] 核心配额不足，提前退出（明天再跑）；建议配置 GITHUB_TOKEN 提升到 5000/hr")
            sys.exit(0)
    return True


def bootstrap_from_candidates(conn, cfg, limit):
    """仓库表为空时，从候选清单引导出种子池（适合全新部署/克隆）"""
    path = os.path.join(ROOT, "data", "candidates.json")
    try:
        with open(path, encoding="utf-8") as f:
            cands = json.load(f)
    except Exception as e:
        print(f"  [bootstrap] 读取候选清单失败: {e}")
        return []
    cands.sort(key=lambda x: (x.get("stars") or 0), reverse=True)
    added = 0
    tracked = set(db.tracked_repos(conn))
    for c in cands:
        fn = c.get("full_name")
        if not fn or fn in tracked:
            continue
        db.upsert_repo(conn, fn, c.get("created_at"), source="seed")
        tracked.add(fn)
        added += 1
        if added >= limit:
            break
    print(f"  [bootstrap] 从候选清单引导 {added} 个种子仓库")
    return db.tracked_repos(conn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", help="逗号分隔 owner/name，仅采集这些")
    ap.add_argument("--discover", action="store_true", help="先发现候选再采集")
    ap.add_argument("--responses", type=int, default=1, help="是否做响应时长采样（0/1）")
    ap.add_argument("--limit", type=int, default=0, help="最多采集仓库数（0=不限）")
    ap.add_argument("--date", help="快照日期 YYYY-MM-DD（默认今天，用于回填历史快照）")
    args = ap.parse_args()

    cfg = load_config()
    db_path = os.path.join(ROOT, cfg.get("db_path", "data/radar.db"))
    conn = db.connect(db_path)
    date_str = args.date or today()
    preflight_rate_limit(cfg)

    if args.repos:
        targets = [r.strip() for r in args.repos.split(",") if r.strip()]
    else:
        if args.discover:
            import discover
            discover.main(["auto"])
            conn = db.connect(db_path)  # discover 可能重建连接
        targets = db.tracked_repos(conn)
        if not targets:
            targets = bootstrap_from_candidates(conn, cfg, cfg["采集"].get("max_repos_per_run", 30))

    if args.limit and len(targets) > args.limit:
        targets = targets[: args.limit]

    print(f"== 采集 {len(targets)} 个仓库 @ {date_str} ==", flush=True)
    done = 0
    for i, full_name in enumerate(targets, 1):
        rem = gh.remaining()
        floor = cfg["采集"].get("min_rate_limit_floor", 25)
        if rem is not None and rem < floor and not gh.TOKEN:
            print(f"  [stop] 剩余配额 {rem} < 下限 {floor}，提前停止（明天继续）", flush=True)
            break
        print(f"[{i}/{len(targets)}] {full_name}")
        try:
            done += collect_repo(conn, full_name, cfg, date_str, bool(args.responses))
        except Exception as e:
            print(f"  [error] {full_name}: {e}")
        time.sleep(0.5)  # 温和节奏，避开并发突发限制

    print(f"== 完成：成功 {done}/{len(targets)}，剩余配额 {gh.remaining()} ==")
    conn.close()


if __name__ == "__main__":
    main()
