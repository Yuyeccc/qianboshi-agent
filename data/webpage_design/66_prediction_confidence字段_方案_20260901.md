# 66_prediction_confidence消费层字段_方案_20260901.md

> 生成：老手（侦察+自审）| 日期：2026-09-01 | 上游：65 号执行记录遗留第 1 项（阈值校准下半场）
> 状态：**待用户拍板** → 执行 → 验证

---

## 一、目标

把阈值校准实证落地到消费层：新增 `prediction_confidence`（authority×tuple_status 查表），
RAG 排序校正（证据权威不再被当预测概率加权），显示层保持 #5 证据语义不动（登记 P2）。

## 二、现状（侦察自审）

- **view_store.score_view**（排序）：`ent*0.35 + claim_quality*0.25 + source*0.15 + evidence*0.15 + confidence*0.10`
  ——confidence 是 view_extractor 提取分，但 claim 的 evidence_confidence（conf3 0.9/0.7/0.5/0.3）也参与观点评分
- **brief_renderer.confidence_badge**：显示"最低维置信分档"（#5 定稿，证据语义）——**不动**（破坏定稿语义）
- **实证依据**（65 号，view 级 w5）：authority 主口径全≈0.5；交叉表可区分（A×ok 59% / B×ok 70% / C×template 50% 等）
- 消费方：view_store 排序（本地）、brief_renderer 显示（本地）；claim 表在 Mac 不动

## 三、方案

### A. scripts/prediction_confidence.py（新模块）
```python
# 实证查表（65 号阈值校准，view 级主窗口 w5；n<30 探索性 → 保守 0.5）
TABLE = {
  "ok":             {"A": 0.59, "B": 0.65, "C": 0.50, "D": 0.50},
  "partial_anchor": {"A": 0.50, "B": 0.50, "C": 0.50, "D": 0.49},
  "template_only":  {"A": 0.57, "B": 0.60, "C": 0.50, "D": 0.56},
}
def prediction_confidence(authority: str, tuple_status: str) -> float:
    """实证校准的预测置信度（0-1）。authority 未知/tuple_status 未知 → 0.5（保守中性）。"""
```
- 值来源：65 号交叉表命中率（n>=30 直接采用/收缩；n<30 探索性用 0.5）
- 语义注释：预测置信度 ≠ 证据可信度（conf3 不动）

### B. view_store.score_view 校正
- `float(v.get("confidence", 0.5)) * 0.10` → `float(v.get("prediction_confidence") or v.get("confidence", 0.5)) * 0.10`
  （prediction_confidence 优先，缺失回退 confidence——版本兼容，gpt 意见 6 回退策略）
- view 数据组装处（filter_views/load_views 后）注入 prediction_confidence：
  view 带 authority + tuple_status 字段时查表注入；无则不加（回退）

### C. brief_renderer 显示层
- **本刀不动**（#5 定稿"最低维置信分档"= 证据语义；预测维度展示登记 P2，避免破坏定稿）
- 方案文档记录显示层可选增强（P2：置信列旁加"预测力"徽标）

### D. 测试（tests/test_prediction_confidence.py）
1. 查表：A×ok=0.59 / C×template=0.50 / 未知组合=0.5
2. score_view：带 prediction_confidence 的 view 用预测值；缺失回退 confidence
3. 边界：authority/tuple_status 未知 → 0.5 不崩
4. 只读：数据文件 hash 不变

## 四、影响面与回滚

- 新增 1 模块 + 1 测试 + 改 view_store.py（排序一行 + 注入点）
- 不触碰 Mac / claim 表 / brief_renderer / conf3
- git 独立提交可 revert

## 五、验证清单（交付门）

```bash
# 1. 新测试（期望 4 passed）
C:/Python314/python.exe -m pytest tests/test_prediction_confidence.py -q
# 2. 全量回归（期望 88 passed）
C:/Python314/python.exe -m pytest tests/ -q
# 3. 排序行为验证（带/不带 prediction_confidence 的 score 对比）
C:/Python314/python.exe -c "import sys; sys.path.insert(0,'scripts'); from prediction_confidence import prediction_confidence; print(prediction_confidence('A','ok'), prediction_confidence('X','ok'), prediction_confidence('A','unknown'))"
```
