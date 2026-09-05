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
| `机器人过滤.enable` | true | **过滤机器人评论**，只统计真人响应 |
| `机器人过滤.deny_logins` | 18 个 | 已知 AI agent 账号黑名单（含伪装成 User 的） |
| `机器人过滤.deny_login_substrings` | 15 个 | 子串匹配（`[bot]`、coderabbit、dosubot、dependabot…） |
| `采集.request_budget` | 800 | **每次运行 API 请求预算**（Actions 额度 1000/hr） |
| `采集.max_repos_per_day` | 60 | 每日采集仓库上限（超出的按最久未采集轮转） |
| `采集.response_sample_per_repo` | 8 | 每个仓库采几个 issue 算响应时长 |
| `信号阈值.issue积压_ratio` | 0.05 | open_issues/stars ≥5% = 积压 |

> AI 领域过滤：候选仓库满足「topic ∈ ai_domain.topics」**或**「描述命中 ai_domain.keywords」才被收录。

## 数据质量设计（重要）

这几点直接决定信号是否可信：

1. **机器人过滤**：`coderabbitai[bot]`、`dosubot[bot]`、`agent-cortex` 等会在几分钟内自动回复 issue。
   不过滤的话「响应快」测的是「谁装了 CI 机器人」而非「维护者是否活跃」。
   实测过滤后 LangBot 响应时长从 5.3h 修正为 8.9h（+68%）。
2. **消除生存者偏差**：采样用 `state=all` 而非只采 open。
   只采 open 会漏掉「响应快 → 早已关闭」的 issue，系统性高估响应时长。
3. **配额预算**：按 `request_budget` 反推每次采多少仓库，并按「最久未采集」轮转，
   保证仓库数增长后每个仓库仍能轮到，而不是永远只采前 N 个。
4. **抗断档星速**：用相邻快照的日增量**中位数**，某天 Actions 失败不会让星速被低估。
5. **数据治理**：`maintain.py` 归档僵尸 issue、精简候选清单、VACUUM，防止 DB 与 git 仓库无限膨胀。

## 数据维护

```bash
python3 maintain.py all              # 归档 + 精简候选 + VACUUM（每日随 workflow 自动执行）
python3 maintain.py reset-responses  # 作废历史响应数据，按新逻辑重采（改过滤规则后用）
```

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
数据截至 **2026-09-05** · 完整图表看板见仓库 `docs/index.html`（GitHub Pages）

### 🔥 星速榜（星/天，需 ≥2 天快照）

| # | 仓库 | 星速(天) | 加速度 | 信号 |
|---|---|---|---|---|
| 1 | debpalash/VoiceStudio | 1379.0 | 1.11 | 爆发且健康 |
| 2 | every-app/open-seo | 325.0 | 0.84 | 爆发且健康 |
| 3 | ifixai-ai/iFixAi | 198.0 | 0.67 | 爆发且健康 |
| 4 | lidge-jun/opencodex | 157.0 | 0.88 | 爆发且健康 |
| 5 | semantica-agi/semantica | 125.5 | 1.02 | 爆发且健康 |

### ⚠️ 积压比榜（open issues / stars）

| # | 仓库 | 积压比 | open issues | stars |
|---|---|---|---|---|
| 1 | maximhq/bifrost | 12.31% | 959 | 7791 |
| 2 | aden-hive/hive | 12.20% | 1344 | 11018 |
| 3 | elizaOS/eliza | 9.02% | 1736 | 19242 |
| 4 | XiaomiMiMo/MiMo-Code | 7.57% | 980 | 12948 |
| 5 | FlagOpen/FlagEmbedding | 7.48% | 908 | 12131 |

### 🐢 响应最慢榜（首个非作者评论中位数）

| # | 仓库 | 响应时长 | open issues |
|---|---|---|---|
| 1 | datawhalechina/llm-universe | 2341.3h | 17 |
| 2 | bentoml/OpenLLM | 1648.9h | 17 |
| 3 | GoogleCloudPlatform/generative-ai | 905.2h | 88 |
| 4 | OpenMOSS/MOSS | 903.9h | 243 |
| 5 | microsoft/promptflow | 880.1h | 68 |

> 星速 = 总星差/天数；积压比 ≥5% 视为积压；响应时长 = issue 首个非作者评论时间中位数（小时）。
<!-- STAR_SCOUT_BOARD:END -->


## 🏆 值得跟踪 Top N（每日自动更新）

<!-- STAR_SCOUT_TOP:START -->
数据截至 **2026-09-05** · 评分 = 0.25·发展 + 0.30·响应 + 0.20·issue健康 + 0.25·社区认可

| # | 仓库 | 评分 | 评级 | 星速(天) | 响应时长 | 积压比 |
|---|---|---|---|---|---|---|
| 1 | pipecat-ai/pipecat | **100.0** | 优质 | 42.0 | 2.3h | 1.97% |
| 2 | semantica-agi/semantica | **100.0** | 优质 | 125.5 | 1.6h | 1.00% |
| 3 | lidge-jun/opencodex | **100.0** | 优质 | 157.0 | 0.3h | 0.88% |
| 4 | The-PR-Agent/pr-agent | **100.0** | 优质 | 17.75 | 2.2h | 0.68% |
| 5 | MemTensor/MemOS | **100.0** | 优质 | 18.0 | 0.0h | 0.58% |

> 发展=星速+近期提交活跃；响应=issue 首个非作者评论中位数；issue健康=积压比适中；社区认可=星标对数。缺数据取中性，避免冷启动一票否决。
<!-- STAR_SCOUT_TOP:END -->
