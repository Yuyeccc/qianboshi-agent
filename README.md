# 钱博士Agent（qianboshi-agent）

独立 AI 金融投研系统：多 UP 主内容采集 → GPU 转写 → ASR 纠错 → LLM 结构化 →
ChromaDB RAG → 盘前简报 / 日报 / 决策台 → 研究 Agent（多源自主采集 + 报告协议 v2）。

2026-09-03 定档为**研究型 Agent**：研究目标 → 拆解 → 三桶报告（事实/观点/推演
+ 概率 + 观察清单）。定位是研究助手，不做交易执行、不给买卖指令。

> 作品集展示站（Vite+React+FastAPI）在 `E:\qianboshi-portfolio`（另一仓库），
> 前端 `/agent` 页与本仓 research_agent 通过 HTTP API + 共享数据目录联通。

## 双端职责（重要）

| 端 | 职责 | 说明 |
|---|---|---|
| **Windows（本机 E:\qianboshi-agent）** | 开发 / 测试 / 跑批权威端 | 代码以本仓为准，改完 git 提交 |
| **Mac（a1@1deiMac，7x24 驻场）** | 生产运行（简报/监控/研究 API） | 部署副本 + 环境变量注入，运维见 portfolio 仓 `deploy/` 与 docs |

流水线 cron 在 Windows 由 Hermes cron 驱动；Mac 侧由 launchd 驱动
（`QIANBOSHI_AGENT_DIR / QIANBOSHI_DATA_DIR / QIANBOSHI_NOTES_DIR` 环境变量注入）。

## 启动命令 / 环境

所有脚本统一入口 `C:/Python314/python.exe`（跑批权威解释器），**必须清 PYTHONPATH**
（hermes-web-ui venv 会劫持 python 导入）：

```bash
cd E:\qianboshi-agent
# 研究任务（单次，全链路）
C:/Python314/python.exe scripts/research_agent.py "复盘 8 月地产板块，推演 9 月政策情景"
# 意图闸门（后端安检）
C:/Python314/python.exe scripts/intent_gate.py "黄金现在能买吗"
# 统一编排（任务队列/重试/定时，dry-run 演示）
C:/Python314/python.exe -m scripts.orchestrator --dry-run
# L2/L3 自治监控（一轮巡检）
C:/Python314/python.exe -m scripts.monitor --once
```

LLM 配置在 `config.yaml`（`llm.api_key_env` 指向环境变量，如 `DEEPSEEK_API_KEY`）。
模型策略：deepseek-v4-flash 主力（官方），premium gpt-5.6-sol（fluxionai）用于
深度分析/简报；GLM 仅备用。`.env` 不入库。

## 数据目录（data/）

| 路径 | 内容 |
|---|---|
| `data/research/` | 研究产物报告 JSON（`_meta.job_id` 关联任务） |
| `data/research_jobs/` | 研究任务 job 状态机文件（queued→running→done/failed） |
| `data/monitor_events/` | L2/L3 巡检命中事件（P0-PRICE-01 等） |
| `data/my_views.json` | 用户个人规则（views 原文 + rule_engine 结构化区；**敏感，gitignore**） |
| `data/portfolio.json` | 持仓（含 BOM，读用 utf-8-sig） |
| `data/views/` | 分析师结构化观点库 |
| `data/vector_db/` | ChromaDB RAG（可重建） |
| `data/briefs/` | 盘前简报产物 |

## 研究任务 API 与协议

API 由 portfolio backend 提供（uvicorn 8010/8011，见该仓 README）：

```text
POST /api/v1/research/jobs              # 提交研究任务
     body: {"goal": "黄金 9 月情景推演"}
     202  -> {"job": {job_id, status: queued, ...}}
     422  -> {"detail": {"error": "intent_blocked", "gate": {...}}}   # intent_gate fail-closed
GET  /api/v1/research/jobs/{job_id}     # 轮询；done 时附完整报告
GET  /api/v1/research/jobs?limit=20     # 任务列表
```

提交链路：前端安检 → POST → `intent_gate.classify_question()`（block/clarify 一律
拒收）→ job 落盘 + 子进程调 `research_agent.py --job-id` → 报告 schema 校验 →
产物关联 job_id → GET 轮询读回。

报告协议 v2：`docs/30_报告协议v2.schema.json`（jsonschema Draft202012 共享校验，
前端渲染结构对齐）。顶层 `_meta` 含 schema_valid/schema_errors/job_id。
产物示例：`data/research/*.json`（facts 带 source+date、opinions 标来源与 side、
scenarios 带 probability+rationale+invalidation、watchlist 每项带 trigger）。

## 合规红线（不可越）

- 只做研究：不给买卖指令/目标价/仓位建议；block 类输入一律拒
- 安检双闸：前端 agentScreening.ts（体验层）+ 后端 intent_gate.py（安全边界，
  fail-closed）；规则漂移用 `RULE_VERSION` 对账
- 输出侧 compliance_gate；报告合规约束在 prompt 层，禁止编造素材
- avoid_list（my_views）语义：回避标的只能出风险提示，不得生成买入建议

## 故障排查速查

| 症状 | 原因/处理 |
|---|---|
| 脚本导入被劫持 | 用 C:/Python314 + `unset PYTHONPATH` |
| 行情/新闻拉取 SSL 错 | 系统代理劫持 → requests 一律 `trust_env=False`（Clash 7897 坑） |
| LLM json_object 空返回 | 服务端窗口性波动 → llm_json 已 retries=4 + 递增 backoff，勿降级 plain |
| 大素材截断 | max_tokens 5000 不够 → 重试逐轮 +1500 |
| 文件 read_file 报 binary | 工具误判 UTF-8，python 读写正常（架构文档.md 同理） |
| portfolio.json 读报 BOM 错 | 用 utf-8-sig |
| 研究任务超时 | 600s 上限，超时置 failed（research_service / orchestrator） |
| 双头执行同一 job | orchestrator 只认领 `source=="orchestrator"` 的任务，不抢 research_service 的 |

## 开发者入口：DSH / MCP / Hermes 三角色

| 角色 | 定位 | 入口 |
|---|---|---|
| **MCP** | 标准化工具协议，向 Hermes 暴露流水线/决策台只读工具 | `scripts/qianboshi_mcp.py`（13 工具：pipeline_status/queue_list/logs_tail/rag_stats + 资产卡/辩论卡/证据包/决策复盘） |
| **Hermes** | 工具宿主与调用环境（本机维护/跑批/cron 调度） | Hermes qianboshi profile |
| **DSH** | 开发者调试入口（**非产品壳**） | `~/.dsh/profiles/qianboshi`（3080）；ADRs 见 `docs/adr/` |

关键 ADR：ADR-001（research_agent 领域执行器 / agent.py ReAct 子模块 /
orchestrator 统一编排分层）、ADR-002（DSH 定位）、ADR-003（报告协议 v2 共享 schema）。

## 架构与文档

- `架构文档.md`：v5 六层研究 Agent 架构（唯一权威，编码 UTF-8）
- `docs/adr/`：决策记录
- 施工交接/蓝图：`HANDOFF.md` + workspace `qianboshi-autonomy-design/`
