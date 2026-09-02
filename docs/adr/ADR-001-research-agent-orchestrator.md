# ADR-001：研究执行器分层（research_agent / agent.py / orchestrator）

- 日期：2026-09-03
- 状态：接受（P1 落地中）

## 背景

v3 前 agent.py 是唯一 Agent 入口（ReAct 循环 + run_schedule）。9-3 研究型 Agent 定档后，research_agent.py 落地六步研究管线（多源自主采集 + 报告协议 v2 组装）。出现两套 Agent 入口，需裁决关系。

## 决策

1. **research_agent = 研究领域执行器**：面向"单次研究任务"的领域流程（实体提取→观点库→新闻→B站→报告组装），保留六步主流程。
2. **agent.py = 通用 ReAct 推理子模块**：多轮工具调用、深度推理能力保留，供 Orchestrator 或其他流程调用，不再作为研究主入口。
3. **新增 orchestrator.py（P1）**：统一承载任务生命周期（ResearchJob 状态机）、队列、重试、超时、定时（run_schedule 迁入）、事件分发（L2/L3/L4）、并发限制。
4. **8-29 四 Agent（Analyst RAG / Independent Analysis / Portfolio Risk / Decision Review）**：P2 作为 Orchestrator 可插拔协作角色，不与研究管线并列抢入口。

## 理由

- 避免两套入口和状态管理漂移
- 保留 ReAct 通用能力（问题未定形态时复用）
- 为自治监控、多用户工作台预留统一编排点

## 后果

- 研究提交路径唯一化：前端 → intent_gate → Orchestrator → research_agent
- agent.py 后续改动需向后兼容作为子模块被调用
