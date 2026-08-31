#!/usr/bin/env python3
"""AI Issue Radar — SQLite schema & helpers（纯标准库，无第三方依赖）"""
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
  full_name  TEXT PRIMARY KEY,
  created_at TEXT,
  first_seen TEXT,
  source     TEXT DEFAULT 'search',
  status     TEXT DEFAULT 'tracked',  -- tracked / candidate / removed
  last_collected TEXT                 -- 最近一次成功采集日期（轮转调度用）
);
CREATE TABLE IF NOT EXISTS snapshots (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name   TEXT NOT NULL,
  date        TEXT NOT NULL,          -- YYYY-MM-DD
  stars       INTEGER,
  forks       INTEGER,
  open_issues INTEGER,
  watchers    INTEGER,
  pushed_at   TEXT,
  UNIQUE(full_name, date)
);
CREATE TABLE IF NOT EXISTS issue_samples (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name        TEXT NOT NULL,
  issue_number     INTEGER,
  title            TEXT,
  state            TEXT,
  created_at       TEXT,
  closed_at        TEXT,              -- 关闭时间（关闭率 / 存活时长）
  first_response_at TEXT,             -- 首个「人类非作者」评论时间（响应时长用）
  responder        TEXT,              -- 首个人类响应者 login（可审计）
  bot_filtered     INTEGER DEFAULT 0, -- 该 issue 是否有机器人评论被跳过
  snapshot_date    TEXT,
  UNIQUE(full_name, issue_number)
);
CREATE INDEX IF NOT EXISTS idx_snap_fn_date ON snapshots(full_name, date);
CREATE INDEX IF NOT EXISTS idx_issue_fn ON issue_samples(full_name);
CREATE INDEX IF NOT EXISTS idx_issue_resp ON issue_samples(full_name, first_response_at);
"""

# 旧库平滑升级用（SQLite 缺列时补齐）
MIGRATIONS = [
    ("repos", "last_collected", "TEXT"),
    ("issue_samples", "closed_at", "TEXT"),
    ("issue_samples", "responder", "TEXT"),
    ("issue_samples", "bot_filtered", "INTEGER DEFAULT 0"),
]


def _migrate(conn):
    for table, col, decl in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    conn.commit()


def connect(db_path):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


def upsert_repo(conn, full_name, created_at, source="search"):
    conn.execute(
        "INSERT INTO repos(full_name, created_at, first_seen, source, status) "
        "VALUES(?,?,date('now'),?,'tracked') "
        "ON CONFLICT(full_name) DO UPDATE SET created_at=COALESCE(created_at, excluded.created_at)",
        (full_name, created_at, source),
    )
    conn.commit()


def add_snapshot(conn, full_name, date, stars, forks, open_issues, watchers, pushed_at):
    conn.execute(
        "INSERT OR REPLACE INTO snapshots(full_name, date, stars, forks, open_issues, watchers, pushed_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (full_name, date, stars, forks, open_issues, watchers, pushed_at),
    )
    conn.commit()


def upsert_issue(conn, full_name, number, title, state, created_at, first_response_at, snapshot_date,
                 closed_at=None, responder=None, bot_filtered=0):
    conn.execute(
        "INSERT INTO issue_samples(full_name, issue_number, title, state, created_at, closed_at, "
        "  first_response_at, responder, bot_filtered, snapshot_date) "
        "VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(full_name, issue_number) DO UPDATE SET "
        "  first_response_at=COALESCE(excluded.first_response_at, issue_samples.first_response_at), "
        "  responder=COALESCE(excluded.responder, issue_samples.responder), "
        "  bot_filtered=MAX(issue_samples.bot_filtered, excluded.bot_filtered), "
        "  state=excluded.state, closed_at=COALESCE(excluded.closed_at, issue_samples.closed_at), "
        "  snapshot_date=excluded.snapshot_date",
        (full_name, number, title, state, created_at, closed_at,
         first_response_at, responder, bot_filtered, snapshot_date),
    )
    conn.commit()


def tracked_repos(conn):
    rows = conn.execute("SELECT full_name FROM repos WHERE status='tracked' ORDER BY first_seen").fetchall()
    return [r[0] for r in rows]


def repos_by_staleness(conn, limit=None):
    """按「最久未采集」优先返回 tracked 仓库（NULL 最优先），用于配额受限时的轮转调度"""
    sql = ("SELECT full_name FROM repos WHERE status='tracked' "
           "ORDER BY COALESCE(last_collected, '0000-00-00') ASC, first_seen ASC")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in conn.execute(sql).fetchall()]


def mark_collected(conn, full_name, date_str):
    conn.execute("UPDATE repos SET last_collected=? WHERE full_name=?", (date_str, full_name))
    conn.commit()


def snapshots_for(conn, full_name):
    return conn.execute(
        "SELECT date, stars, forks, open_issues, pushed_at FROM snapshots "
        "WHERE full_name=? ORDER BY date", (full_name,)
    ).fetchall()


def response_samples(conn, full_name):
    return conn.execute(
        "SELECT created_at, first_response_at FROM issue_samples "
        "WHERE full_name=? AND first_response_at IS NOT NULL", (full_name,)
    ).fetchall()
