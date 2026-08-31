# 67_prediction_confidence消费层_执行记录_20260901.md

> 执行：老手 | 方案：66 号（用户批准）| 日期：2026-09-01
> 状态：✅ 完成（git 5811cce）

---

## 一、完成总览

| 模块 | 状态 | 关键产出 |
|---|---|---|
| prediction_confidence 模块 | ✅ | scripts/prediction_confidence.py：实证查表（authority×tuple_status），未知组合→0.5 保守；语义注释（预测力≠证据可信度） |
| RAG 排序校正 | ✅ | view_store.score_view：`prediction_confidence` 优先，缺失回退原 confidence（版本兼容） |
| load_views 注入 | ✅ | 按 view_id 查 view_authority.json + view_tuple_status.json 注入（映射缓存一次加载）；缺失文件静默跳过 |
| 显示层 | ✅ | brief_renderer 不动（#5 定稿证据语义；预测力徽标登记 P2） |
| 测试 | ✅ | 5 passed（查表/未知中性/attach/score_view 优先回退/值域）；全量 93 passed |
| 注入验证 | ✅ | 10702 views 中 7476 带 prediction_confidence（值域 0.49-0.65） |
| git | ✅ | 5811cce（3 文件可 revert） |

## 二、实证查表（65 号阈值校准定值）

| tuple_status | A | B | C | D |
|---|---|---|---|---|
| ok | 0.59 | 0.65 | 0.50* | 0.50* |
| partial_anchor | 0.50* | 0.50* | 0.50* | 0.49 |
| template_only | 0.57 | 0.60 | 0.50 | 0.56 |

*探索性单元格（n<30）→ 保守 0.5。定值规则：n>=30 采用命中率（收缩向 0.5）；n<30 不据此定值。

## 三、坑记录（本刀 0 条新增）

无（方案自审充分：映射缺失回退、注入点缓存、显示层不动已提前规避）

## 四、遗留登记

- brief_renderer 显示层预测力徽标（P2，可选增强：置信列旁加"预测力"标注）
- 8 月 error 事件行情补拉 → #14v2 复跑对照（补行情后查表样本扩大可再校准）
- position ledger（P2）
- 置换检验（可选）

## 五、回滚

`git revert 5811cce` 即还原（只 3 文件，排序回退原逻辑）。
