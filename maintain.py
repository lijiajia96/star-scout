#!/usr/bin/env python3
"""Star Scout — 数据维护（纯标准库）

子命令：
  reset-responses   作废旧逻辑采集的响应数据（含机器人污染），等待按新逻辑重采
  archive           归档僵尸 issue（超过 N 天未更新且已关闭），控制 DB 膨胀
  slim-candidates   精简 candidates.json（只留关键字段 + 上限条数），减少 git diff 噪音
  vacuum            SQLite VACUUM 回收空间
  all               archive + slim-candidates + vacuum
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as dbmod

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "data", "radar.db")
CAND_PATH = os.path.join(ROOT, "data", "candidates.json")


def _connect():
    """统一走 db.connect，确保 schema 迁移（新列）已应用"""
    return dbmod.connect(DB_PATH)


def _size_mb(p):
    return round(os.path.getsize(p) / 1024 / 1024, 2) if os.path.exists(p) else 0


def reset_responses(conn):
    """清空 first_response_at / responder，让新逻辑（过滤机器人）重新采集"""
    n = conn.execute("SELECT COUNT(*) FROM issue_samples WHERE first_response_at IS NOT NULL").fetchone()[0]
    conn.execute("UPDATE issue_samples SET first_response_at=NULL, responder=NULL, bot_filtered=0")
    conn.commit()
    print(f"[reset-responses] 作废旧响应数据 {n} 条（含机器人污染），将按新逻辑重采")
    return n


def archive(conn, keep_days=180, keep_per_repo=150):
    """删除过老且已关闭的 issue 记录；每仓最多保留 keep_per_repo 条最新记录"""
    cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    n1 = conn.execute(
        "DELETE FROM issue_samples WHERE state='closed' AND COALESCE(closed_at, created_at) < ?",
        (cutoff,)).rowcount
    # 每仓限量：保留最新的 keep_per_repo 条
    n2 = conn.execute(
        """DELETE FROM issue_samples WHERE id NOT IN (
             SELECT id FROM (
               SELECT id, ROW_NUMBER() OVER (PARTITION BY full_name ORDER BY created_at DESC) rn
               FROM issue_samples
             ) WHERE rn <= ?
           )""", (keep_per_repo,)).rowcount
    conn.commit()
    print(f"[archive] 清理过期已关闭 issue {n1} 条；每仓限量({keep_per_repo}) 清理 {n2} 条")
    return n1 + n2


def slim_candidates(max_items=300):
    """只保留关键字段和前 N 条（按星标降序），减小体积与 git diff 噪音"""
    if not os.path.exists(CAND_PATH):
        print("[slim-candidates] 无候选文件，跳过")
        return 0
    before = os.path.getsize(CAND_PATH) / 1024
    with open(CAND_PATH, encoding="utf-8") as f:
        items = json.load(f)
    items.sort(key=lambda x: (x.get("stars") or 0), reverse=True)
    keep = []
    for c in items[:max_items]:
        keep.append({
            "full_name": c.get("full_name"),
            "stars": c.get("stars"),
            "created_at": c.get("created_at"),
            "pushed_at": c.get("pushed_at"),
            "description": (c.get("description") or "")[:110],
            "topics": (c.get("topics") or [])[:6],
        })
    with open(CAND_PATH, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False, indent=1, sort_keys=True)
    after = os.path.getsize(CAND_PATH) / 1024
    print(f"[slim-candidates] {len(items)} -> {len(keep)} 条，{before:.0f}KB -> {after:.0f}KB")
    return len(keep)


def vacuum():
    before = _size_mb(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("VACUUM")
    conn.close()
    print(f"[vacuum] radar.db {before}MB -> {_size_mb(DB_PATH)}MB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["reset-responses", "archive", "slim-candidates", "vacuum", "all"])
    ap.add_argument("--keep-days", type=int, default=180)
    ap.add_argument("--keep-per-repo", type=int, default=150)
    ap.add_argument("--max-candidates", type=int, default=300)
    args = ap.parse_args()

    if args.cmd in ("reset-responses", "archive"):
        conn = _connect()
        if args.cmd == "reset-responses":
            reset_responses(conn)
        else:
            archive(conn, args.keep_days, args.keep_per_repo)
        conn.close()
    elif args.cmd == "slim-candidates":
        slim_candidates(args.max_candidates)
    elif args.cmd == "vacuum":
        vacuum()
    elif args.cmd == "all":
        conn = _connect()
        archive(conn, args.keep_days, args.keep_per_repo)
        conn.close()
        slim_candidates(args.max_candidates)
        vacuum()


if __name__ == "__main__":
    main()
