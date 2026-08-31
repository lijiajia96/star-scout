#!/usr/bin/env python3
"""Star Scout — 推荐 Top N（值得跟踪 issue / 提 PR 的仓库）

算法见 scoring.py：综合分 = 0.30·发展 + 0.30·响应 + 0.20·issue健康 + 0.20·社区认可。

产出：
  1. data/recommendations.json —— Top N 完整评分明细
  2. README.md —— 「🏆 值得跟踪 Top N」区块（<!-- STAR_SCOUT_TOP:START/END -->）
"""
import argparse
import json
import os

from build_dashboard import DOCS_HTML, load_data  # 复用数据加载（含 pushed_at / 信号合并）
import scoring

ROOT = os.path.dirname(os.path.abspath(__file__))
RECO_PATH = os.path.join(ROOT, "data", "recommendations.json")
README_PATH = os.path.join(ROOT, "README.md")

TOP_START = "<!-- STAR_SCOUT_TOP:START -->"
TOP_END = "<!-- STAR_SCOUT_TOP:END -->"


def build_top_md(top):
    lines = [
        f"数据截至 **{top['date']}** · 评分 = 0.25·发展 + 0.30·响应 + 0.20·issue健康 + 0.25·社区认可",
        "",
        "| # | 仓库 | 评分 | 评级 | 星速(天) | 响应时长 | 积压比 |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(top["items"], 1):
        lines.append(
            f"| {i} | {r['full_name']} | **{r['score']}** | {r['grade']} | "
            f"{r.get('stars_per_day') or '-'} | {r.get('resp_hours') or '-'}h | "
            f"{((r.get('issue_ratio') or 0)*100):.2f}% |"
        )
    lines.append("")
    lines.append("> 发展=星速+近期提交活跃；响应=issue 首个非作者评论中位数；issue健康=积压比适中；"
                 "社区认可=星标对数。缺数据取中性，避免冷启动一票否决。")
    return "\n".join(lines)


def update_readme(board_md):
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    block = f"\n## 🏆 值得跟踪 Top N（每日自动更新）\n\n{TOP_START}\n{board_md}\n{TOP_END}\n"
    if TOP_START in content and TOP_END in content:
        pre = content.split(TOP_START)[0]
        post = content.split(TOP_END)[1]
        content = pre + TOP_START + "\n" + board_md + "\n" + TOP_END + post
    else:
        content = content.rstrip() + "\n\n" + block
    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[recommend] README.md Top 榜单已更新")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    data = load_data()
    scored = scoring.compute_scores(data["latest"], data["date"])
    top_items = scored[: args.top]

    top = {"date": data["date"], "top_n": len(top_items), "items": top_items, "all": scored,
           "weights": {"growth": 0.25, "responsiveness": 0.30, "issue_health": 0.20, "quality": 0.25}}
    with open(RECO_PATH, "w", encoding="utf-8") as f:
        json.dump(top, f, ensure_ascii=False, indent=2)
    print(f"[recommend] 明细 -> {RECO_PATH}")

    update_readme(build_top_md(top))

    print(f"== 推荐 Top {len(top_items)}（{data['date']}）==")
    for i, r in enumerate(top_items, 1):
        b = r["breakdown"]
        print(f"  #{i} {r['full_name']:<38} {r['score']:>5} {r['grade']:<4} "
              f"(发展{b['growth']:.2f} 响应{b['responsiveness']:.2f} "
              f"健康{b['issue_health']:.2f} 认可{b['quality']:.2f})")


if __name__ == "__main__":
    main()
