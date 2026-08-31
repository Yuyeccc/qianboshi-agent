#!/usr/bin/env python3
"""EvidencePack 统一证据包构建器（决策台阶段五）。"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from asset_card_builder import build_asset_card
from debate_card_builder import build_debate_card
from decision_db import fetch_analyst_scores, fetch_decisions
from view_store import get_latest_views

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

ASSET_MAP: dict[str, tuple[str, list[str]]] = {
    "GOLD": ("黄金", ["159992.SZ"]),
    "SEMI": ("半导体", ["159813.SZ", "159770.SZ"]),
    "AI": ("AI应用", ["NVDA", "159813.SZ"]),
    "ROBOT": ("机器人", ["159770.SZ"]),
    "BAIJIU": ("白酒", ["512690.SS"]),
}

# 板块名 -> 代表代码。与 debate_card_builder 的板块分数映射保持同一思路。
SECTOR_SYMBOL_MAP: dict[str, list[str]] = {
    "半导体": ["159813.SZ", "159770.SZ"],
    "光模块": ["300308.SZ", "300502.SZ"],
    "创新药": ["159992.SZ"],
    "机器人": ["159770.SZ"],
    "黄金": ["159992.SZ"],
    "有色": ["601899.SS"],
    "存储": ["159813.SZ"],
    "白酒": ["512690.SS"],
    "AI应用": ["NVDA", "159813.SZ"],
}

PACK_FIELDS = [
    "asset_id",
    "asset_name",
    "as_of_date",
    "asset_card",
    "factor_states",
    "debate_card",
    "latest_views",
    "analyst_scores",
    "market_snapshot",
    "user_decision_history",
    "rag_evidence",
    "summary",
]


def _asset_info(asset_id: str) -> tuple[str, list[str]]:
    key = str(asset_id or "").strip().upper()
    if key in ASSET_MAP:
        return ASSET_MAP[key]
    fallback = str(asset_id or "").strip() or "UNKNOWN"
    return fallback, [fallback]


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _related_symbols(asset_id: str, asset_name: str) -> list[str]:
    mapped = list(ASSET_MAP.get(asset_id, ("", []))[1])
    mapped.extend(SECTOR_SYMBOL_MAP.get(asset_name, []))
    mapped.append(asset_id)
    return _dedupe([str(x) for x in mapped])


def _view_text(view: dict[str, Any]) -> str:
    parts = [
        view.get("section"),
        view.get("claim"),
        view.get("logic"),
        view.get("evidence"),
        view.get("risk"),
        view.get("source_file"),
    ]
    entities = view.get("entities") if isinstance(view.get("entities"), dict) else {}
    for value in entities.values():
        if isinstance(value, list):
            parts.extend(str(x) for x in value)
        else:
            parts.append(str(value))
    return " ".join(str(x or "") for x in parts)


def _is_related_view(view: dict[str, Any], asset_name: str, symbols: list[str]) -> bool:
    text = _view_text(view)
    keys = [asset_name] + symbols + [s.split(".", 1)[0] for s in symbols if "." in s]
    return any(key and key in text for key in keys)


def _extract_factor_states(asset_card: dict[str, Any]) -> list[dict[str, Any]]:
    states = []
    for factor in asset_card.get("factors") or []:
        if not isinstance(factor, dict):
            continue
        states.append({
            "factor_id": factor.get("factor_id"),
            "factor_name": factor.get("factor_name"),
            "current_state": factor.get("current_state"),
            "impact_direction": factor.get("impact_direction"),
            "evidence_refs": factor.get("evidence_refs") or [],
        })
    return states


def _fetch_scores(asset_id: str, asset_name: str, symbols: list[str]) -> list[dict[str, Any]]:
    entities = _dedupe([asset_id, asset_name] + symbols + SECTOR_SYMBOL_MAP.get(asset_name, []))
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for entity in entities:
        try:
            scores = fetch_analyst_scores(entity)
        except Exception:
            continue
        for score in scores:
            key = (
                score.get("analyst"),
                score.get("entity"),
                score.get("window_days"),
                score.get("updated_at"),
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(score)
    return rows


def _market_snapshot(symbols: list[str]) -> dict[str, dict[str, Any]]:
    path = DATA_DIR / "market_cache.json"
    if not path.exists():
        return {}
    try:
        cache = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    if not isinstance(cache, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        info = cache.get(symbol)
        if not isinstance(info, dict):
            continue
        out[symbol] = {
            "price": info.get("price"),
            "change_pct": info.get("change_pct"),
            "updated": info.get("updated"),
            "name": info.get("name"),
        }
    return out


def _decision_history(asset_id: str, asset_name: str) -> list[dict[str, Any]]:
    try:
        decisions = fetch_decisions()
    except Exception:
        return []
    out = []
    for item in decisions:
        item_asset_id = str(item.get("asset_id") or "")
        item_asset_name = str(item.get("asset_name") or "")
        if item_asset_id == asset_id or item_asset_name == asset_name or asset_name in item_asset_name:
            out.append(item)
    return out


def _rag_evidence(asset_name: str, symbols: list[str]) -> list[dict[str, Any]]:
    try:
        from query_rag import QianboshiRAG

        query = " ".join([asset_name] + symbols)
        return QianboshiRAG().query(query, top_k=3)
    except Exception:
        return []


def _summary(asset_name: str, asset_card: dict[str, Any], debate_card: dict[str, Any], analyst_scores: list[dict[str, Any]], latest_views: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> str:
    counts = debate_card.get("counts") if isinstance(debate_card, dict) else {}
    bull = len(debate_card.get("bullish") or []) if isinstance(debate_card, dict) else 0
    bear = len(debate_card.get("bearish") or []) if isinstance(debate_card, dict) else 0
    if isinstance(counts, dict):
        bull = int(counts.get("bullish", bull) or 0)
        bear = int(counts.get("bearish", bear) or 0)
    has_factors = "有" if asset_card.get("factors") else "无"
    return (
        f"{asset_name}：分析卡{has_factors}factors，多空对照{bull}多{bear}空，"
        f"分析师{len(analyst_scores)}条历史分，近期观点{len(latest_views)}条，"
        f"用户决策{len(decisions)}条。"
    )


def build_evidence_pack(asset_id: str = "GOLD", horizon: str = "medium", as_of_date: str | None = None) -> dict[str, Any]:
    """构建单资产 EvidencePack；任一子项失败时返回空值，不中断整个包。"""
    normalized_asset_id = str(asset_id or "GOLD").strip().upper()
    asset_name, base_symbols = _asset_info(normalized_asset_id)
    as_of = as_of_date or date.today().isoformat()
    symbols = _related_symbols(normalized_asset_id, asset_name) or base_symbols

    asset_card: dict[str, Any] = {}
    try:
        asset_card = build_asset_card(normalized_asset_id, as_of_date=as_of)
    except Exception:
        asset_card = {}

    factor_states = _extract_factor_states(asset_card)

    debate_card: dict[str, Any] = {}
    try:
        debate_card = build_debate_card(asset_name, horizon=horizon, lookback_days=60)
    except Exception:
        debate_card = {}

    latest_views: list[dict[str, Any]] = []
    try:
        all_latest = get_latest_views(days=14, limit=20)
        latest_views = [v for v in all_latest if _is_related_view(v, asset_name, symbols)]
    except Exception:
        latest_views = []

    analyst_scores = _fetch_scores(normalized_asset_id, asset_name, symbols)
    market_snapshot = _market_snapshot(symbols)
    decisions = _decision_history(normalized_asset_id, asset_name)
    rag_evidence = _rag_evidence(asset_name, symbols)
    summary = _summary(asset_name, asset_card, debate_card, analyst_scores, latest_views, decisions)

    return {
        "asset_id": normalized_asset_id,
        "asset_name": asset_name,
        "as_of_date": as_of,
        "asset_card": asset_card,
        "factor_states": factor_states,
        "debate_card": debate_card,
        "latest_views": latest_views,
        "analyst_scores": analyst_scores,
        "market_snapshot": market_snapshot,
        "user_decision_history": decisions,
        "rag_evidence": rag_evidence,
        "summary": summary,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="构建 EvidencePack 统一证据包")
    parser.add_argument("--asset", default="GOLD")
    parser.add_argument("--horizon", default="medium")
    parser.add_argument("--as-of-date")
    args = parser.parse_args()
    pack = build_evidence_pack(args.asset, horizon=args.horizon, as_of_date=args.as_of_date)
    print(json.dumps(pack, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
