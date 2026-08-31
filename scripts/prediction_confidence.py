#!/usr/bin/env python3
"""预测置信度（consumption layer，66 号方案 2026-09-01）。

阈值校准实证落地：authority × tuple_status → prediction_confidence（0-1）。

核心（65 号阈值校准 + gpt 意见 1 语义解耦）：
- evidence_confidence（conf3 A0.9/B0.7/C0.5/D0.3）= **证据可信度**，语义不动
- prediction_confidence = **预测力实证值**（view 级独立样本主窗口 w5 命中率），
  供 RAG 排序等消费层使用，防止"证据权威高"被误读为"预测准确率高"
- n<30 的探索性单元格 → 保守 0.5（不据此定值）
- 未知组合 → 0.5（保守中性）

用法:
    from prediction_confidence import prediction_confidence
    prediction_confidence("A", "ok")   # 0.59
"""
from __future__ import annotations

# 实证查表（65 号阈值校准，view 级主窗口 w5 交叉表命中率）
# 定值规则：n>=30 采用命中率（收缩向 0.5）；n<30 探索性 → 0.5 保守
TABLE: dict[str, dict[str, float]] = {
    "ok": {
        "A": 0.59,   # n=509
        "B": 0.65,   # n=53（70% 收缩）
        "C": 0.50,   # n=39 探索性 → 保守
        "D": 0.50,   # n=10 探索性 → 保守
    },
    "partial_anchor": {
        "A": 0.50,   # n=30 探索性 → 保守
        "B": 0.50,   # n<30 → 保守
        "C": 0.50,   # n<30 → 保守
        "D": 0.49,   # n=206
    },
    "template_only": {
        "A": 0.57,   # n=1292
        "B": 0.60,   # n=287
        "C": 0.50,   # n=154
        "D": 0.56,   # n=112
    },
}

DEFAULT_CONFIDENCE = 0.5  # 未知/探索性 → 保守中性


def prediction_confidence(authority: str, tuple_status: str) -> float:
    """实证校准的预测置信度（0-1）。

    authority: A/B/C/D（evidence_authority）
    tuple_status: ok / partial_anchor / template_only
    未知组合 → 0.5（保守中性，不崩）
    """
    if not authority or not tuple_status:
        return DEFAULT_CONFIDENCE
    row = TABLE.get(tuple_status)
    if row is None:
        return DEFAULT_CONFIDENCE
    return row.get(authority, DEFAULT_CONFIDENCE)


def attach_to_view(view: dict) -> dict:
    """给 view 注入 prediction_confidence 字段（view 带 authority/tuple_status 时）。

    返回新 dict 或原 dict（无 authority/tuple_status 时不注入，调用方回退 confidence）。
    """
    authority = (view.get("evidence_authority") or "").strip().upper()
    ts = view.get("tuple_status") or view.get("layer") or ""
    if not authority or not ts:
        return view
    pc = prediction_confidence(authority, ts)
    if pc is not None:
        view = dict(view)
        view["prediction_confidence"] = pc
    return view
