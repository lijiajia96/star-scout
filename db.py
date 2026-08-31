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
  status     TEXT DEFAULT 'tracked'   -- tracked / candidate / removed
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
  first_response_at TEXT,             -- 首个非作者评论时间（响应时长用）
  snapshot_date    TEXT,
  UNIQUE(full_name, issue_number)
);
"""


def connect(db_path):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
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


def upsert_issue(conn, full_name, number, title, state, created_at, first_response_at, snapshot_date):
    conn.execute(
        "INSERT INTO issue_samples(full_name, issue_number, title, state, created_at, first_response_at, snapshot_date) "
        "VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(full_name, issue_number) DO UPDATE SET "
        "  first_response_at=COALESCE(issue_samples.first_response_at, excluded.first_response_at), "
        "  state=excluded.state, snapshot_date=excluded.snapshot_date",
        (full_name, number, title, state, created_at, first_response_at, snapshot_date),
    )
    conn.commit()


def tracked_repos(conn):
    rows = conn.execute("SELECT full_name FROM repos WHERE status='tracked' ORDER BY first_seen").fetchall()
    return [r[0] for r in rows]


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
