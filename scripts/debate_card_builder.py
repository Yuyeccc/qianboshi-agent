#!/usr/bin/env python3
"""多空对照卡构建器（决策台阶段一）。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from decision_db import fetch_analyst_scores, upsert_debate_card
from view_store import load_views, parse_date, query_views_by_entity

ENTITY_FIELDS = ("stocks", "sectors", "etfs", "themes")
STANCE_BUCKETS = ("bullish", "bearish", "risk", "neutral", "watch")


def _today(views: list[dict[str, Any]] | None = None) -> date:
    today = date.today()
    dates = [parse_date(v.get("date")) for v in (views if views is not None else load_views())]
    # 2026-08-06 修复：观点库存在未来日期（8-31 解析错误），会污染窗口——只取 <= 今天
    valid = [d for d in dates if d and d <= today]
    return max(valid) if valid else today


def _clean_id(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_.-]+", "_", str(value)).strip("_")


def _view_text(v: dict[str, Any]) -> str:
    return " ".join(str(v.get(k) or "") for k in ("section", "claim", "logic", "evidence", "risk"))


def _views_in_window(views: list[dict[str, Any]], date_start: str, date_end: str, horizon: str | None = None) -> list[dict[str, Any]]:
    """按日期窗口（含 horizon 可选）过滤全部观点——2026-08-06 修复：原 query_views_by_entity 的 filter_views 对 entities.sectors 弱匹配漏掉大量观点（黄金有色748条只匹配5条）"""
    out = []
    for v in views:
        d = v.get("date") or ""
        if d and date_start <= d <= date_end:
            if horizon and v.get("horizon") != horizon:
                continue
            out.append(v)
    return out


def _entity_match(v: dict[str, Any], entity: str) -> bool:
    entities = v.get("entities") if isinstance(v.get("entities"), dict) else {}
    for field in ENTITY_FIELDS:
        if entity in (entities.get(field) or []):
            return True
    return entity in f"{v.get('section', '')} {v.get('claim', '')}"


def _entity_type(entity: str, views: list[dict[str, Any]]) -> str:
    type_map = {"stocks": "stock", "sectors": "sector", "etfs": "etf", "themes": "theme"}
    counts: Counter[str] = Counter()
    for v in views:
        entities = v.get("entities") if isinstance(v.get("entities"), dict) else {}
        for field, label in type_map.items():
            if entity in (entities.get(field) or []):
                counts[label] += 1
    if counts:
        return counts.most_common(1)[0][0]
    return "macro" if entity in {"大盘", "宏观", "美元", "黄金"} else "theme"


def _date_between(v: dict[str, Any], start: date, end: date) -> bool:
    d = parse_date(v.get("date"))
    return bool(d and start <= d <= end)


def _normalize_stance(stance: Any) -> str:
    s = str(stance or "neutral").lower()
    return s if s in STANCE_BUCKETS else "neutral"


def _counts(views: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(_normalize_stance(v.get("stance")) for v in views)
    return {bucket: int(counter.get(bucket, 0)) for bucket in STANCE_BUCKETS}


def _net_stance_score(counts: dict[str, int]) -> float:
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    return (counts.get("bullish", 0) - counts.get("bearish", 0) - counts.get("risk", 0) * 0.5) / total


def _sign(value: float) -> int:
    if value > 0.05:
        return 1
    if value < -0.05:
        return -1
    return 0


def _item(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "view_id": v.get("view_id"),
        "stance": _normalize_stance(v.get("stance")),
        "analyst": v.get("analyst", ""),
        "date": v.get("date", ""),
        "claim": v.get("claim", ""),
        "logic": v.get("logic", ""),
        "risk": v.get("risk", ""),
        "evidence": v.get("evidence", ""),
        "confidence": float(v.get("confidence") or 0.0),
        "cluster_id": v.get("cluster_id", ""),
        "cluster_label": v.get("cluster_label", ""),
        "analyst_score_snapshot": v.get("analyst_score_snapshot"),
        "source_file": v.get("source_file", ""),
    }


def _score_snapshot(score: dict[str, Any] | None) -> float | None:
    if not score:
        return None
    try:
        return float(score.get("hit_rate"))
    except Exception:
        return None


def _analyst_score_map(entity: str, preferred_window_days: int = 5) -> dict[str, dict[str, Any]]:
    # 板块名 → 代表标的代码（analyst_scores 里 entity 是代码）
    SECTOR_SYMBOL_MAP = {
        "半导体": ["159813.SZ", "159770.SZ"],
        "光模块": ["300308.SZ", "300502.SZ"],
        "创新药": ["159992.SZ"],
        "机器人": ["159770.SZ"],
        "黄金": ["159992.SZ"],
        "有色": ["601899.SS"],
        "存储": ["159813.SZ"],
    }
    symbols = SECTOR_SYMBOL_MAP.get(entity) or [entity]
    all_scores: dict[str, list[dict[str, Any]]] = {}
    for sym in symbols:
        for score in fetch_analyst_scores(sym):
            analyst = str(score.get("analyst") or "")
            if not analyst:
                continue
            all_scores.setdefault(analyst, []).append(score)

    selected: dict[str, dict[str, Any]] = {}
    for analyst, rows in all_scores.items():
        preferred = [row for row in rows if row.get("window_days") == preferred_window_days]
        pool = preferred or rows
        pool.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        selected[analyst] = pool[0]
    return selected


def _public_item(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "view_id": v.get("view_id"),
        "analyst": v.get("analyst", ""),
        "claim": v.get("claim", ""),
        "logic": v.get("logic", ""),
        "confidence": float(v.get("confidence") or 0.0),
        "evidence": v.get("evidence", ""),
        "analyst_score": v.get("analyst_score"),
    }


def _confidence_level(views: list[dict[str, Any]]) -> float:
    if not views:
        return 0.0
    high = [
        v for v in views
        if float(v.get("confidence") or 0.0) >= 0.75
        and len(str(v.get("logic") or "")) >= 30
        and len(str(v.get("evidence") or "")) >= 40
    ]
    return round(len(high) / len(views), 4)


def _consensus_direction(counts: dict[str, int]) -> str:
    bull = counts.get("bullish", 0)
    bear = counts.get("bearish", 0) + counts.get("risk", 0)
    neutral = counts.get("neutral", 0) + counts.get("watch", 0)
    total = sum(counts.values())
    if total == 0:
        return "neutral"
    if bull > bear and bull >= neutral:
        return "bullish"
    if bear > bull and bear >= neutral:
        return "bearish"
    if neutral > bull and neutral > bear:
        return "neutral"
    return "mixed"


def _summary(entity: str, counts: dict[str, int], direction: str, disagreement: float) -> str:
    return (
        f"{entity}：多头{counts.get('bullish', 0)}条，空头{counts.get('bearish', 0)}条，"
        f"风险{counts.get('risk', 0)}条，中性{counts.get('neutral', 0)}条，"
        f"共识方向={direction}，分歧度={disagreement:.2f}。"
    )


def _top_claims(views: list[dict[str, Any]], limit: int = 3) -> list[str]:
    ranked = sorted(views, key=lambda v: (float(v.get("confidence") or 0.0), v.get("date", "")), reverse=True)
    return [str(v.get("claim") or "") for v in ranked[:limit] if v.get("claim")]


def _all_entities(views: list[dict[str, Any]]) -> list[str]:
    counts: Counter[str] = Counter()
    for v in views:
        entities = v.get("entities") if isinstance(v.get("entities"), dict) else {}
        for field in ENTITY_FIELDS:
            for name in entities.get(field) or []:
                counts[str(name)] += 1
    return [name for name, _ in counts.most_common()]


def build_debate_card(
    entity: str,
    horizon: str | None = None,
    lookback_days: int = 14,
    views: list[dict[str, Any]] | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    """构建并写入一张实体多空对照卡。"""
    if views is None:
        views = load_views()
    end = _today(views)
    start = end - timedelta(days=max(lookback_days - 1, 0))
    prev_start = start - timedelta(days=14)
    prev_end = start - timedelta(days=1)

    current = _views_in_window(views, start.isoformat(), end.isoformat(), horizon=horizon)
    current = [v for v in current if _entity_match(v, entity)]
    analyst_scores = _analyst_score_map(entity)
    for v in current:
        score = analyst_scores.get(str(v.get("analyst") or ""))
        v["analyst_score"] = score
        v["analyst_score_snapshot"] = _score_snapshot(score)
    previous = _views_in_window(views, prev_start.isoformat(), prev_end.isoformat(), horizon=horizon)
    previous = [v for v in previous if _entity_match(v, entity)]

    buckets: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in STANCE_BUCKETS}
    for v in current:
        buckets[_normalize_stance(v.get("stance"))].append(v)
    for values in buckets.values():
        values.sort(key=lambda v: (float(v.get("confidence") or 0.0), v.get("date", "")), reverse=True)

    counts = _counts(current)
    total = sum(counts.values())
    bull_ratio = counts["bullish"] / total if total else 0.0
    bear_ratio = counts["bearish"] / total if total else 0.0
    disagreement = round(min(bull_ratio, bear_ratio) * 2, 4)
    confidence = _confidence_level(current)
    current_net = _net_stance_score(counts)
    previous_net = _net_stance_score(_counts(previous))
    novelty = 1.0 if _sign(current_net) and _sign(previous_net) and _sign(current_net) != _sign(previous_net) else 0.0
    direction = _consensus_direction(counts)

    highlights: list[str] = []
    if confidence > 0:
        highlights.append("高置信")
    if counts["bullish"] >= 2 and counts["bearish"] >= 2 and disagreement >= 0.6:
        highlights.append("强分歧")
    if novelty:
        highlights.append("新变化")

    now = datetime.now().isoformat(timespec="seconds")
    card_id = f"debate_{_clean_id(entity)}_{_clean_id(horizon or 'all')}_{start.isoformat()}_{end.isoformat()}"
    disagreements = []
    if counts["bullish"] and counts["bearish"]:
        disagreements.append({
            "topic": f"{entity}方向分歧",
            "bullish_side": _top_claims(buckets["bullish"]),
            "bearish_side": _top_claims(buckets["bearish"]),
        })
    consensus = _top_claims(buckets[direction], limit=3) if direction in buckets else []
    new_changes = []
    if novelty:
        new_changes.append({
            "topic": "净方向反转",
            "previous_net_stance_score": round(previous_net, 4),
            "current_net_stance_score": round(current_net, 4),
        })

    card = {
        "card_id": card_id,
        "entity_id": entity,
        "entity_name": entity,
        "entity_type": _entity_type(entity, current or previous),
        "horizon": horizon or "all",
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "highlights": highlights,
        "counts": counts,
        "metrics": {
            "consensus_direction": direction,
            "disagreement_level": disagreement,
            "confidence_level": confidence,
            "novelty_level": novelty,
            "net_stance_score": round(current_net, 4),
        },
        "summary": _summary(entity, counts, direction, disagreement),
        "bullish": [_public_item(v) for v in buckets["bullish"]],
        "bearish": [_public_item(v) for v in buckets["bearish"]],
        "risk": [_public_item(v) for v in buckets["risk"]],
        "neutral": [_public_item(v) for v in buckets["neutral"]],
        "watch": [_public_item(v) for v in buckets["watch"]],
        "disagreements": disagreements,
        "consensus": consensus,
        "new_changes": new_changes,
        "items": [_item(v) for v in current],
        "created_at": now,
        "updated_at": now,
    }
    if write_db:
        upsert_debate_card(card)
    return card


def main() -> None:
    parser = argparse.ArgumentParser(description="生成多空对照卡")
    parser.add_argument("--entity", help="实体名称，不指定时扫描观点库全部实体")
    parser.add_argument("--horizon", choices=["intraday", "short", "medium", "long", "unknown"])
    parser.add_argument("--lookback", type=int, default=14)
    args = parser.parse_args()

    if args.entity:
        result: dict[str, Any] | list[dict[str, Any]] = build_debate_card(args.entity, horizon=args.horizon, lookback_days=args.lookback)
    else:
        views = load_views()
        result = [
            build_debate_card(entity, horizon=args.horizon, lookback_days=args.lookback)
            for entity in _all_entities(views)
        ]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
