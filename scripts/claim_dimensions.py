#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""claim_dimensions.py — 蓝图#4/#7/#13 渲染底座（确定性，零LLM）
把 Mac 标注库导出的维度映射（data/views/dimensions_export.json）+ 冲突中心
（data/views/conflicts_export.json）挂载到视图上，供 brief_renderer 分层渲染。

红线（gpt审核 0901 + #13 定稿，必须遵守）:
  claim_level(fact/interpretation/forecast) 是"表达类型"，不是可信度等级；
  渲染必须与 source_layer/verification_status 并列展示，禁止任何视觉手段
  把 forecast 伪装成 fact。无维度数据的 view 一律标 unknown，禁止猜测。
  #13: evidence 原文指针 anchored/missing/hash_mismatch 三态，missing 禁猜时间戳；
  冲突组只报分歧存在，不合并结论、不做方向暗示。

数据刷新: Mac `python3 ~/qianboshi_task/export_dimensions.py` + `conflict_detector.py`
  后 scp 两个 json 到 data/views/，进程重启或 cd.reload() 生效。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DIM_PATH = ROOT / "data" / "views" / "dimensions_export.json"
CONFLICT_PATH = ROOT / "data" / "views" / "conflicts_export.json"

# ---- 表达类型徽标（并列展示，不做可信度暗示）----
CLAIM_LEVEL_LABEL = {
    "fact": "📖 事实",
    "interpretation": "🧩 解读",
    "causal_claim": "🔗 因果",
    "correlation": "〰️ 相关",
    "hypothesis": "❓ 假设",
    "forecast": "🔮 预测",
    "unknown": "❔ 未标",
}

# ---- 证据层级徽标（来源层级 + 核验状态 同时给出）----
SOURCE_LAYER_LABEL = {
    "primary": "🅰 一手",
    "secondary": "🅱 二手",
    "inferred": "🅳 推断",
    "unknown": "未标",
}
VERIFIED_MARK = {"verified": "✅核验", "unverified": "⚠️未验", "unknown": "未验"}

# ---- #5: 置信徽标（只显最低维+分档，缺失=未评估禁当低置信；不依赖颜色）----
CONF_BAND_LABEL = {
    "high": "置信高",
    "medium": "置信中",
    "low": "置信低",
    "unrated": "未评估",
}
MIN_DIM_CN = {"evidence": "证据", "reasoning": "推理", "forecast": "预测"}

# ---- #5: 疑点标签（确定性，文案短以适配表格）----
UNCERTAINTY_LABEL = {
    "unsupported": "无支撑",
    "missing_data": "数据缺",
    "stale": "过期",
    "inferred": "推断",
    "low_sample_topic": "样本少",
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_conf_lock = threading.Lock()
_conf_cache: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        try:
            _cache = json.loads(DIM_PATH.read_text(encoding="utf-8"))
        except Exception:
            _cache = {"dimensions": {}, "crowding": {}, "rule_version": "unavailable"}
    return _cache


def _load_conflicts() -> dict[str, Any]:
    """冲突中心导出（懒加载）：预构建 gid→摘要 索引 + view_id→组摘要列表。"""
    global _conf_cache
    with _conf_lock:
        if _conf_cache is not None:
            return _conf_cache
        try:
            raw = json.loads(CONFLICT_PATH.read_text(encoding="utf-8"))
        except Exception:
            _conf_cache = {"groups": {}, "view_map": {}}
            return _conf_cache
        groups = {}
        for c in raw.get("conflicts", []):
            groups[c["conflict_group_id"]] = {
                "topic": c.get("topic", ""),
                "entity": c.get("subject_entity", ""),
                "level": c.get("level", "background"),
                "n_bull": c.get("n_bull", 0),
                "n_bear": c.get("n_bear", 0),
            }
        view_map = {}
        for vid, gids in (raw.get("view_conflict_map") or {}).items():
            entries = []
            for gid in gids:
                g = groups.get(gid)
                if g:
                    entries.append({"group_id": gid, **g})
            # 优先级：primary 在前 → 组小在前 → 组内对立量适中在前（gpt复审：按优先级不按大小）
            entries.sort(key=lambda e: (
                0 if e["level"] == "primary" else 1,
                e["n_bull"] + e["n_bear"],
            ))
            view_map[vid] = entries
        _conf_cache = {"groups": groups, "view_map": view_map}
    return _conf_cache


def reload() -> None:
    """导出文件更新后强制重载（测试用）。"""
    global _cache, _conf_cache
    with _lock:
        _cache = None
    with _conf_lock:
        _conf_cache = None


def dims_for(view_id: str) -> dict[str, Any]:
    return _load().get("dimensions", {}).get(view_id) or {}


def attach_dimensions(v: dict[str, Any]) -> dict[str, Any]:
    """把标注维度合并进 view dict（幂等，返回新 dict）。无数据 = unknown，不猜测。
    #13: 同时挂 evidence（原文指针）+ conflict_groups（所属冲突组，按优先级排序）。"""
    d = dims_for(v.get("view_id", ""))
    vv = dict(v)
    if d:
        vv["claim_level"] = d.get("claim_level", "unknown")
        vv["source_layer"] = d.get("source_layer", "unknown")
        vv["verification_status"] = d.get("verification_status", "unknown")
        vv["supported"] = bool(d.get("supported"))
        vv["match_quality"] = d.get("match_quality")
        vv["evidence_topic"] = d.get("topic", "其他")
        vv["confidence"] = d.get("confidence") or {"band": "unrated"}
        vv["uncertainty_tags"] = d.get("uncertainty_tags") or []
        vv["materiality"] = d.get("materiality", "unknown")
        vv["evidence"] = d.get("evidence") or None
    else:
        # 强制覆盖：旧视图 JSONL 自带遗留 confidence(float)，必须清掉，
        # 无标注维度 = 未评估（红线：不猜测、不当低置信）
        vv["claim_level"] = "unknown"
        vv["source_layer"] = "unknown"
        vv["verification_status"] = "unknown"
        vv["confidence"] = {"band": "unrated"}
        vv["uncertainty_tags"] = []
        vv["materiality"] = "unknown"
        vv["evidence"] = None
    # #13: 冲突组（视图维度来自 annotation，冲突 map 来自 claim——同 view_id 体系）
    vv["conflict_groups"] = _load_conflicts()["view_map"].get(v.get("view_id", ""), [])
    # #6: reasoning 五元组（论证链渲染用）
    vv["reasoning"] = (d or {}).get("reasoning") if d else None
    return vv


def reasoning_chain(v: dict[str, Any]) -> str:
    """#6: 论证链短文本（前提→机制→结论 + 触发/失效条件）。无 → 空串。"""
    r = v.get("reasoning")
    if not isinstance(r, dict):
        return ""
    if r.get("tuple_status") == "template_only":
        return ""  # 模板句无论证链
    parts = []
    premise = r.get("premise")
    mech = r.get("mechanism")
    concl = r.get("conclusion")
    if premise:
        parts.append(f"前提：{premise[:80]}")
    if mech:
        parts.append(f"机制：{mech[:80]}")
    if concl:
        parts.append(f"结论：{concl[:80]}")
    if r.get("trigger_condition"):
        parts.append(f"触发：{r['trigger_condition'][:60]}")
    if r.get("invalid_condition"):
        parts.append(f"失效：{r['invalid_condition'][:60]}")
    return " → ".join(parts) if parts else ""


def confidence_badge(v: dict[str, Any]) -> str:
    """#5: 只显最低维分档，如 '置信低(证据)'；未评估显式区分，禁当低置信。"""
    c = v.get("confidence")
    if not isinstance(c, dict):  # 防御：遗留 float/None 一律按未评估
        return CONF_BAND_LABEL["unrated"]
    band = c.get("band", "unrated")
    label = CONF_BAND_LABEL.get(band, band)
    dim = c.get("min_dimension")
    if band in ("high", "medium", "low") and dim:
        return f"{label}({MIN_DIM_CN.get(dim, dim)})"
    return label


def uncertainty_badge(v: dict[str, Any]) -> str:
    """#5: 疑点标签串。无标签返回空串（表格里显示干净）。"""
    tags = v.get("uncertainty_tags") or []
    return " ".join(UNCERTAINTY_LABEL.get(t, t) for t in tags)


def evidence_badge(v: dict[str, Any]) -> str:
    """#13: 原文指针徽标。missing 禁猜时间戳（红线#2），hash_mismatch 标记不阻断。"""
    ev = v.get("evidence")
    if not isinstance(ev, dict):  # 防御：旧视图 JSONL 的 evidence 是 str（遗留字段）
        return "❔原文缺失"
    st = ev.get("extraction_status", "ok")
    if st == "ok":
        ts = ev.get("ts_display") or ""
        return f"🔍原文 {ts}" if ts else "🔍原文"
    if st == "hash_mismatch":
        return "⚠️原文存疑"
    return "❔原文缺失"


def evidence_detail(v: dict[str, Any]) -> dict[str, Any] | None:
    """#13: 原文详情数据（详情页/展开用）。无则 None。"""
    ev = v.get("evidence")
    if not isinstance(ev, dict) or ev.get("extraction_status") == "segment_missing":
        return None
    return {
        "quote_text": ev.get("quote_text") or "",
        "segment_text": ev.get("segment_text") or "",
        "ts_display": ev.get("ts_display"),
        "bv_id": ev.get("bv_id"),
        "segment_source": ev.get("segment_source"),
        "content_hash": ev.get("content_hash"),
        "extraction_status": ev.get("extraction_status"),
        "url": f"https://www.bilibili.com/video/{ev.get('bv_id')}?t={max(0, int(ev.get('anchor_start_ms') or 0)) // 1000}s"
        if ev.get("bv_id") else None,
    }


def conflict_badge(v: dict[str, Any]) -> str:
    """#13: 冲突组徽标。只取前 2 组（防 26 徽标爆炸），余量 +N。"""
    groups = v.get("conflict_groups") or []
    if not groups:
        return ""
    top = groups[:2]
    parts = []
    for g in top:
        lvl = "🔀" if g["level"] == "primary" else "🔀⃠"
        parts.append(f"{lvl}{g['entity']}·{g['n_bull']}多/{g['n_bear']}空")
    extra = len(groups) - 2
    if extra > 0:
        parts.append(f"+{extra}")
    return " ".join(parts)


def claim_level_badge(v: dict[str, Any]) -> str:
    return CLAIM_LEVEL_LABEL.get(v.get("claim_level"), CLAIM_LEVEL_LABEL["unknown"])


def source_evidence_badge(v: dict[str, Any]) -> str:
    """证据层级徽标（🅰 一手·✅核验）——与 #13 的 evidence_badge（原文指针）区分。"""
    layer = SOURCE_LAYER_LABEL.get(v.get("source_layer"), SOURCE_LAYER_LABEL["unknown"])
    verif = VERIFIED_MARK.get(v.get("verification_status"), VERIFIED_MARK["unknown"])
    return f"{layer}·{verif}"


def crowding_note(topic: str) -> str | None:
    """该 topic 是否观点集中（蓝图共识#3，v2 对称版）。只报告集中度，禁止反向交易暗示。"""
    info = _load().get("crowding", {}).get(topic)
    if not info:
        return None
    n = info.get("n")
    if info.get("kind") == "bear":
        return (f"⚠️ 看空集中：看空占比 {info['bear_ratio']:.0%}（n={n}），"
                f"空方观点高度集中，注意多空对照完整性")
    return (f"⚠️ 预期打满：看多占比 {info['bull_ratio']:.0%}（n={n}），"
            f"14天热度 {info['heat_14d']}x，观点高度集中")


def crowding_for_entity(entity: str) -> str | None:
    """渲染层入口：实体名直查 topic 拥挤度（实体名与 topic 命名基本对齐，
    如 大盘/半导体/光模块；未命中返回 None）。"""
    if not entity:
        return None
    data = _load().get("crowding", {})
    if entity in data:
        return crowding_note(entity)
    # 宽松匹配：topic 含实体名（如 "黄金有色" vs topic "黄金"）
    for topic in data:
        if entity in topic or topic in entity:
            return crowding_note(topic)
    return None


def rule_version() -> str:
    return _load().get("rule_version", "unknown")


if __name__ == "__main__":
    # 自检：导出文件可读 + 徽标映射完整 + 抽样挂载（含 evidence/冲突）
    data = _load()
    n_dims = len(data.get("dimensions", {}))
    n_crowd = len(data.get("crowding", {}))
    conf = _load_conflicts()
    n_conf = len(conf.get("groups", {}))
    n_cmap = len(conf.get("view_map", {}))
    print(f"[claim_dimensions] dims={n_dims} crowded_topics={n_crowd} "
          f"conflicts={n_conf} view_conflict={n_cmap} rule={rule_version()}")
    assert n_dims > 0, "维度导出为空，先在 Mac 跑 export_dimensions.py"
    sample_id = next(iter(data["dimensions"]))
    vv = attach_dimensions({"view_id": sample_id, "claim": "样例"})
    print(f"[sample] {sample_id}: {claim_level_badge(vv)} | {evidence_badge(vv)} | "
          f"冲突: {conflict_badge(vv) or '(无)'}")
    print(f"[sample] 原文详情: {str(evidence_detail(vv))[:160]}")
    ghost = attach_dimensions({"view_id": "nonexistent", "claim": "无维度"})
    assert ghost["claim_level"] == "unknown" and ghost["source_layer"] == "unknown"
    assert ghost["evidence"] is None and ghost["conflict_groups"] == []
    print("[selfcheck] 未知 view_id → unknown + 无 evidence/冲突（不猜测）✅")
