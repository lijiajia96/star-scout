#!/usr/bin/env python3
"""AI Issue Radar — 极简 GitHub API 客户端（限流感知、指数退避、纯标准库）"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

# 最近一次响应的限流状态（模块级维护）
_remaining = None
_limit = None
_reset = None


def _default_headers():
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-issue-radar-mvp",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _request(path, params=None):
    global _remaining, _limit, _reset
    url = API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_default_headers())
    if TOKEN:
        req.add_header("Authorization", "Bearer " + TOKEN)

    delay = 1.0
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                _update_remaining(resp.headers)
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            _update_remaining(e.headers)
            if e.code in (403, 429) and "rate limit" in body.lower():
                if not TOKEN:
                    # 无 token 时配额耗尽直接放弃，等下次任务（避免傻等）
                    return e.code, None
                wait = 60
                if e.headers and e.headers.get("X-RateLimit-Reset"):
                    wait = max(int(e.headers.get("X-RateLimit-Reset")) - int(time.time()) + 5, 10)
                print(f"  [rate-limit] hit, sleeping {wait}s (attempt {attempt+1}/4)", flush=True)
                time.sleep(min(wait, 1800))
                continue
            if e.code in (502, 503, 504):
                time.sleep(delay)
                delay *= 2
                continue
            return e.code, None
        except Exception:
            time.sleep(delay)
            delay *= 2
    return 0, None


def _update_remaining(headers):
    global _remaining, _limit, _reset
    if headers is None:
        return
    if headers.get("X-RateLimit-Remaining"):
        _remaining = int(headers["X-RateLimit-Remaining"])
    if headers.get("X-RateLimit-Limit"):
        _limit = int(headers["X-RateLimit-Limit"])
    if headers.get("X-RateLimit-Reset"):
        _reset = int(headers["X-RateLimit-Reset"])


def get_json(path, params=None):
    """返回 (status_code, data)；data 为 dict/list 或 None"""
    return _request(path, params)


def remaining():
    return _remaining


def rate_status():
    return {"remaining": _remaining, "limit": _limit, "reset": _reset}
