# ADR-003：报告协议 v2 共享 JSON Schema

- 日期：2026-09-03
- 状态：接受

## 背景

前端演示报告（demoReport.ts）与后端 research_agent 组装报告独立演进，字段命名有漂移风险（如 coreIssue vs core_conflict、pricedIn vs priced_in）。

## 决策

1. 报告协议 v2 落地共享 JSON Schema：`E:\qianboshi-agent\docs\30_报告协议v2.schema.json`
2. **字段名以已实现的前端渲染字段为准**（coreIssue/summary/facts/opinions/crossCheck/expectations/scenarios/watchlist/evidence），前端不再改，后端对齐。
3. P1 后端产出与演示报告都过 jsonschema 校验；版本化演进（v2.x 兼容加字段）。

## 理由

- 消除前后端结构漂移，支持自动测试与回放
- 前端已实现即事实标准，避免返工

## 后果

- research_agent.py 组装结果需按 schema 校验（容忍 _meta 扩展字段）
- demoReport.ts 结构冻结为协议实现
