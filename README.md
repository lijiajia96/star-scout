# AI Issue Radar（MVP）

**腰部 AI 开源项目雷达**：每日采集候选仓库的星标增速、open issues 变化与 issue 响应时长，
输出信号分类，用于验证"腰部项目 × issue 健康度"这个差异化方向的信号质量。

## 为什么做这个

- agents-radar 等竞品只追踪头部名星 / 只按星标增速排序；
- 本 MVP 验证一个假设：**腰部 AI 项目（200–8000 星）的 issue 健康度/积压趋势，能否筛出值得跟进 vs 该避雷的项目**。
- 跑 2 周，看信号分类是否稳定、有区分度。

## 架构

```
GitHub Search API ──discover.py──▶ 候选池（腰部 AI 项目）
GitHub REST API  ──collect.py──▶ 每日快照（stars/forks/open_issues/响应时长）
                        │
                        ▼
              data/radar.db (SQLite)
                        │
                        ▼
              analyze.py ──▶ signal.csv + 每日报告 data/reports/YYYY-MM-DD.md
```

纯 Python 标准库，零第三方依赖。GitHub Actions 定时跑 + 快照提交回仓库，成本 ≈ 0。

## 本地快速跑

```bash
# 1) 发现腰部 AI 候选（Search API；自动做"必须 AI 相关"过滤）
python3 discover.py 10 --prune   # 新增 10 个候选，并清理非 AI 的旧候选
# 2) 每日采集（需 GITHUB_TOKEN 环境变量才有 5000/hr；无 token 仅 60/hr）
GITHUB_TOKEN=ghp_xxx python3 collect.py
# 3) 信号分析
python3 analyze.py
```

无 token 时配额只有 60/hr，建议 `python3 collect.py --limit 5 --responses 0` 缩小范围。

## 部署到 GitHub Actions（两周验证跑）

1. 建一个 GitHub 仓库（私有即可），把本项目推上去；
2. 工作流 `.github/workflows/daily.yml` 每天 01:17 UTC 自动采集+分析+提交；
3. Actions 内置 `secrets.GITHUB_TOKEN` 额度 1000/hr，够用；
4. 想刷新候选池：仓库页 Actions → 手动触发 `workflow_dispatch`（默认每天只采集不新增候选）。

两周后看 `data/reports/*.md` 与 `data/signal.csv`：
- 星速/加速度是否有区分度（爆发 vs 停滞）；
- issue 积压比是否稳定（>5% 才算积压）；
- 响应时长是否可计算、是否有意义。

## 关键参数（config.json）

| 参数 | 默认 | 说明 |
|---|---|---|
| `腰部定义.min/max_stars` | 100 / 20000 | 腰部段位（可调） |
| `腰部定义.recent_push_days` | 14 | 近期活跃 |
| `ai_domain.require` | true | 是否强制"必须 AI 相关" |
| `ai_domain.topics` | 36 个 | 命中任一 topic 即视为 AI（llm/agent/rag/mcp…） |
| `ai_domain.keywords` | 46 个 | 描述命中任一关键词（词边界匹配）即视为 AI（llm/gpt/agentic/copilot…） |
| `采集.response_sample_per_repo` | 10 | 每个仓库采几个 issue 算响应时长 |
| `信号阈值.爆发_stars_per_day` | 50 | ≥50 星/天 = 爆发 |
| `信号阈值.issue积压_ratio` | 0.05 | open_issues/stars ≥5% = 积压 |

> AI 领域过滤：候选仓库满足「topic ∈ ai_domain.topics」**或**「描述命中 ai_domain.keywords」才被收录。
> 想收窄/放宽，直接改 `config.json` 里的 `ai_domain`；想临时关闭过滤，把 `require` 设为 `false`。

## 已知难点（验证时注意）

- **冷启动**：Search API 无历史星标曲线，加速度要攒几天才有意义（这正是要跑 2 周的原因）；
- **限流**：无 token 仅 60/hr，别在本地频繁重跑；日任务一天一次没问题；
- **issue 噪音**：新仓库 issue 少、标签乱，响应时长按"首个非作者评论"近似；
- **Search API 日期语法**：`pushed:`/`created:` 只接受 `YYYY-MM-DD`，不接受 `>14d`。

## 输出示例（analyze.py）

```
| 信号 | 仓库 | 星速(天) | 加速度(x) | 积压比 | 响应(h) |
|---|---|---|---|---|---|
| 爆发但issue积压 | a/b | 85 | 3.2 | 0.08 | 96 |
| 平稳增长 | c/d | 12 | 1.1 | 0.02 | 5 |
```

---

*信号分类为启发式规则，仅用于项目可行性验证，不构成任何投资/技术选型建议。*


## 📊 信号排行榜（每日自动更新）

<!-- STAR_SCOUT_BOARD:START -->
数据截至 **2026-08-31** · 完整图表看板见仓库 `docs/index.html`（GitHub Pages）

### 🔥 星速榜（星/天，需 ≥2 天快照）

⏳ 第 2 天快照后自动出现（所有仓库目前只有 1 天数据）。

### ⚠️ 积压比榜（open issues / stars）

| # | 仓库 | 积压比 | open issues | stars |
|---|---|---|---|---|
| 1 | maximhq/bifrost | 12.81% | 985 | 7689 |
| 2 | elizaOS/eliza | 7.95% | 1528 | 19219 |
| 3 | langchain4j/langchain4j | 6.82% | 885 | 12984 |
| 4 | t8y2/dbx | 6.54% | 1148 | 17565 |
| 5 | livekit/agents | 5.64% | 785 | 13908 |

### 🐢 响应最慢榜（首个非作者评论中位数）

| # | 仓库 | 响应时长 | open issues |
|---|---|---|---|
| 1 | 2FastLabs/agent-squad | 4552.2h | 88 |
| 2 | yusufkaraaslan/Skill_Seekers | 2677.3h | 53 |
| 3 | ggml-org/ggml | 1322.7h | 351 |
| 4 | datawhalechina/llm-universe | 1264.8h | 16 |
| 5 | coderamp-labs/gitingest | 1082.8h | 22 |

> 星速 = 总星差/天数；积压比 ≥5% 视为积压；响应时长 = issue 首个非作者评论时间中位数（小时）。
<!-- STAR_SCOUT_BOARD:END -->


## 🏆 值得跟踪 Top N（每日自动更新）

<!-- STAR_SCOUT_TOP:START -->
数据截至 **2026-08-31** · 评分 = 0.25·发展 + 0.30·响应 + 0.20·issue健康 + 0.25·社区认可

| # | 仓库 | 评分 | 评级 | 星速(天) | 响应时长 | 积压比 |
|---|---|---|---|---|---|---|
| 1 | img2threejs/img2threejs | **92.5** | 优质 | - | 5.6h | 0.50% |
| 2 | e2b-dev/E2B | **92.5** | 优质 | - | 0.0h | 0.35% |
| 3 | eosphoros-ai/DB-GPT | **92.3** | 优质 | - | 0.2h | 2.13% |
| 4 | xming521/WeClone | **89.5** | 优质 | - | 2.2h | 0.22% |
| 5 | superset-sh/superset | **89.0** | 优质 | - | 0.0h | 4.31% |

> 发展=星速+近期提交活跃；响应=issue 首个非作者评论中位数；issue健康=积压比适中；社区认可=星标对数。缺数据取中性，避免冷启动一票否决。
<!-- STAR_SCOUT_TOP:END -->
