# 钱博士Agent 交接（HANDOFF，2026-09-03）

> 新会话从这里开始。项目全貌/启动/env/合规见 `README.md`；架构唯一权威见 `架构文档.md`。
> 施工蓝图与逐项交接在 workspace `qianboshi-autonomy-design/`（P1_施工蓝图.md /
> P1_施工交接_20260903.md）。本文件记「当前状态 + 遗留 + 铁律」。

## 当前形态（2026-09-03）

**研究型 Agent 定档**：研究目标 → 拆解 → 三桶报告（事实/观点/推演 + 概率 + 观察清单）。
产品入口 = portfolio 前端 `/agent`（安检 → API → research_agent 真跑 → 报告渲染）。

### P1 施工状态（7 项：A/E/B/C/D 完成 ✅；F/G/H/README 已由 2026-09-03 会话续完）

| 项 | 内容 | 落点 |
|---|---|---|
| A | ArchitecturePage 文案 v5 + 模块状态 | portfolio @18e0aaa |
| E | intent_gate.py 后端化（1:1 移植前端规则） | agent @2d916f3 |
| B | 报告协议 v2 schema 校验接入 | agent @2d916f3（3 份已落库产物回验） |
| C | backend 研究 API（job 状态机 + 子进程） | portfolio @faf7642 |
| D | 前端去 mock 真接（提交/轮询/live 渲染/demo 降级） | portfolio @c61bc28 |
| F | Orchestrator 最小版（队列/重试/定时/事件骨架） | agent @de6acaa，`-m scripts.orchestrator --dry-run` |
| G | L2/L3 monitor 最小版（--once + 模拟触发） | agent @730d546 |
| H | my_views 结构化（views 逐字保留 + rule_engine 区） | data/my_views.json（gitignore 敏感文件，不入库） |

提交纪律：**两仓各自精确 add，禁 `git add -A`**（portfolio 有大量脏快照/数据文件）。

## 遗留 TODO（下会话候选）

- P2 未动：多用户 workspace/Auth/Quota、四 Agent 协作、概率校准闭环、研究工作台
- monitor 规则集仅 P0-PRICE-01 + P2-CACHE-01；P1-HOT/SENT 需涨停池/情绪数据接入
- my_views quiet_hours 未配置（P2 通知升级时填）
- agent.py run_schedule 迁入 orchestrator 定时（ADR-001 提及，未动现役）
- 记忆体系 P0/P0.5/P1 全 ✅（P0=8f0a97c 状态机骨架 / P0.5=e1138ad 自动评估 249 falsified / P1=44c470e+76ad14b 信念版本链+决策冻结 / 2e24cb2+e9baa16 事件时间轴 12835 事件+MCP timeline）；P0.5b ✅（252f6fc horizon↔窗口匹配：316 confirmed+87 falsified 落库，87 为 P0.5 漏判修正）；P2 冲突治理/规则闭环/报告互链；flag 仍默认关待观察

## 铁律与坑（触犯必返工）

1. **跑批 python**：`C:/Python314/python.exe` + 清 PYTHONPATH（hermes venv 劫持）
2. **代理**：requests 一律 `trust_env=False`（Clash 7897 劫持 → SSLEOF）
3. **LLM 链路**：deepseek 官方主力（DEEPSEEK_API_KEY）；GLM 备用。json_object 空返回
   是窗口性波动 → llm_json retries=4 + 递增 backoff；勿降级 plain（必截断）
4. **编码**：portfolio.json 等 data 文件带 BOM → utf-8-sig；.py/.md read_file 报
   binary 是工具误判，python 读写正常
5. **编排防双头**：orchestrator 只认领 `source=="orchestrator"` 任务
6. **合规**：block 类输入（买卖/目标价）一律拒；报告不得编造素材；
   事件/简报只触发研究与提醒，不含交易指令
7. **数据**：data/research、research_jobs、monitor_events 为运行时产物；
   my_views.json 敏感个人数据 gitignore——改动后**备份再改**，勿强加提交
8. **Mac 部署副本**：改动同步后须在 Mac 侧重测（SSL 并发 SIGSEGV 坑 → 用
   multiprocessing；nohup 勿 `| tail`）
9. headless 浏览器长等待：tab ~3min 无 CDP 操作被回收，须 ~40s 探活一次
10. portfolio 路由带 locale 前缀：/agent 真实 URL = `#/zh/agent`

## 关键文件索引

- `scripts/research_agent.py`：六步研究管线（LLM 提取/观点库/东财+新浪/B站/组装/落盘）
- `scripts/orchestrator.py`：统一编排（--dry-run 演示；submit/list/status/retry/drain/schedule）
- `scripts/monitor.py`：L2/L3 巡检（--once；--simulate 注入验证）
- `scripts/intent_gate.py`：后端安检（block/clarify 拒收）
- `scripts/qianboshi_mcp.py`：MCP 13 工具
- `docs/30_报告协议v2.schema.json`：报告协议共享 schema
- `docs/adr/`：ADR-001/002/003
- `data/my_views.json`：用户规则（views 原文 + rule_engine 区）
