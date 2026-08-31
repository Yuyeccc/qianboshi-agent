#!/usr/bin/env python3
"""
决策台上下文组装。

只读 data/qianboshi_decision.db 和 data/price_trends.json，供 agent.py
盘前简报链路注入结构化决策台数据。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "qianboshi_decision.db"
PRICE_PATH = ROOT / "data" / "price_trends.json"

ASSET_SYMBOLS = {
    "GOLD": "518880.SS",
    "INNOV_DRUG": "159992.SZ",
    "TECH": "512480.SS",  # 半导体ETF（159813 yfinance折算跳变不可靠，2026-08-06）
    "BAIJIU": "512690.SS",
    "ALUMINUM": "601899.SS",
}

ENTITY_MAP = {
    "GOLD": "黄金",
    "INNOV_DRUG": "创新药",
    "TECH": "半导体",
    "BAIJIU": "白酒",
    "ALUMINUM": "黄金有色",
}

# 命中率关联实体：决策资产 → 观点库高频实体（代理标的无评分时用于匹配分析师历史命中率，2026-08-06）
HIT_RATE_ENTITY_MAP: dict[str, list[str]] = {
    "GOLD": ["601899.SS", "600547.SS"],
    "INNOV_DRUG": ["159992.SZ", "600276.SS"],
    "TECH": ["688981.SS", "300308.SZ", "300502.SZ", "300394.SZ"],
    "BAIJIU": ["512690.SS", "600519.SS"],
    "ALUMINUM": ["601899.SS"],
}

HORIZON_DAYS = {
    "short": 5,
    "medium": 20,
    "long": 60,
}

REVIEW_LABELS = {
    "right": "✅正确",
    "wrong": "❌错误",
    "mixed": "⚠️混合",
    "too_early": "⏳过早",
}


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def _json_or_raw(value: str | None) -> Any:
    if value is None or value == "":
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _load_prices() -> dict[str, dict[str, Any]]:
    if not PRICE_PATH.exists():
        return {}
    with PRICE_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _price_value(record: Any) -> float | None:
    if isinstance(record, dict):
        value = record.get("price")
    else:
        value = record
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nearest_price(prices: dict[str, Any], symbol: str, target: date) -> float | None:
    series = prices.get(symbol)
    if not isinstance(series, dict):
        return None
    for offset in range(0, 6):
        key = (target - timedelta(days=offset)).isoformat()
        if key in series:
            price = _price_value(series[key])
            if price is not None:
                return price
    return None


def _latest_price(prices: dict[str, Any], symbol: str) -> float | None:
    series = prices.get(symbol)
    if not isinstance(series, dict):
        return None
    dated_rows: list[tuple[date, Any]] = []
    for key, record in series.items():
        parsed = _parse_date(key)
        if parsed is not None:
            dated_rows.append((parsed, record))
    for _, record in sorted(dated_rows, key=lambda item: item[0], reverse=True):
        price = _price_value(record)
        if price is not None:
            return price
    return None


def _status_label(
    direction: str | None,
    days_left: int,
    p0: float | None,
    p1: float | None,
    ret_pct: float | None,
    review_result: str | None,
) -> str:
    if p0 is None or p1 is None or ret_pct is None:
        return "待验证（缺基准/当前价）"

    if days_left > 0:
        if direction == "bullish":
            if ret_pct >= 1:
                return "验证中（偏兑现）"
            if ret_pct <= -1:
                return "验证中（偏证伪）"
            return "验证中（未分胜负）"
        if direction == "bearish":
            if ret_pct <= -1:
                return "验证中（偏兑现）"
            if ret_pct >= 1:
                return "验证中（偏证伪）"
            return "验证中（未分胜负）"
        if abs(ret_pct) < 1:
            return "验证中（未分胜负）"
        return "验证中（偏兑现）" if ret_pct > 0 else "验证中（偏证伪）"

    if review_result:
        return REVIEW_LABELS.get(review_result, review_result)
    return "到期待复盘"


def _format_hit_rate(row: sqlite3.Row | None) -> str:
    if row is None:
        return "暂无数据"
    sample_count = row["sample_count"] or 0
    hit_rate = row["hit_rate"]
    if isinstance(hit_rate, (int, float)):
        hit_rate_text = f"{hit_rate:.2%}" if 0 <= hit_rate <= 1 else str(hit_rate)
    else:
        hit_rate_text = "N/A"
    suffix = "，小样本" if sample_count < 10 else ""
    return f"{row['analyst']}: {hit_rate_text}（n={sample_count}）{suffix}"


def _build_user_decisions(con: sqlite3.Connection, prices: dict[str, Any]) -> list[dict[str, Any]]:
    today = date.today()
    decisions = con.execute(
        """
        SELECT decision_id, asset_id, asset_name, direction, horizon, conviction,
               decision_date, thesis, key_reasons, invalidation_conditions, status
        FROM user_decision_logs
        WHERE status = 'open'
        ORDER BY decision_date, decision_id
        """
    ).fetchall()

    out: list[dict[str, Any]] = []
    for row in decisions:
        decision = dict(row)
        asset_id = decision.get("asset_id")
        symbol = ASSET_SYMBOLS.get(asset_id)
        decision_date = _parse_date(decision.get("decision_date"))
        window_days = HORIZON_DAYS.get(decision.get("horizon"), 0)
        review_date = decision_date + timedelta(days=window_days) if decision_date else None
        days_left = (review_date - today).days if review_date else 0
        p0 = _nearest_price(prices, symbol, decision_date) if symbol and decision_date else None
        p1 = _latest_price(prices, symbol) if symbol else None
        ret_pct = round((p1 - p0) / p0 * 100, 4) if p0 and p1 is not None else None
        review = con.execute(
            """
            SELECT result_label
            FROM decision_reviews
            WHERE decision_id = ?
            ORDER BY review_date DESC, created_at DESC
            LIMIT 1
            """,
            (decision.get("decision_id"),),
        ).fetchone()
        # hit_rate：优先匹配代理标的；代理无评分时匹配该决策资产关联实体（2026-08-06 多实体回测后）
        score_entities = [symbol] if symbol else []
        score_entities += HIT_RATE_ENTITY_MAP.get(asset_id, [])
        placeholders = ",".join("?" for _ in score_entities)
        score = (
            con.execute(
                f"""
                SELECT analyst, hit_rate, sample_count
                FROM analyst_scores
                WHERE entity IN ({placeholders})
                ORDER BY sample_count DESC, updated_at DESC
                LIMIT 1
                """,
                score_entities,
            ).fetchone()
            if score_entities
            else None
        )
        result_label = review["result_label"] if review else None

        decision.update(
            {
                "key_reasons": _json_or_raw(decision.get("key_reasons")),
                "invalidation_conditions": _json_or_raw(decision.get("invalidation_conditions")),
                "review_date": review_date.isoformat() if review_date else None,
                "days_left": days_left,
                "symbol": symbol,
                "proxy_note": "（代理标的口径）" if symbol else "N/A",
                "p0": p0,
                "p1": p1,
                "ret_pct": ret_pct,
                "status_label": _status_label(
                    decision.get("direction"),
                    days_left,
                    p0,
                    p1,
                    ret_pct,
                    result_label,
                ),
                "result_label": REVIEW_LABELS.get(result_label, result_label) if result_label else None,
                "hit_rate": _format_hit_rate(score),
            }
        )
        out.append(decision)
    return out


def _build_debate_cards(con: sqlite3.Connection, asset_ids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        entity_id = ENTITY_MAP.get(asset_id, asset_id)
        card = con.execute(
            """
            SELECT card_id, entity_id, bullish_count, bearish_count, neutral_count,
                   consensus_direction, disagreement_level, confidence_level, summary, updated_at
            FROM debate_cards
            WHERE entity_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (entity_id,),
        ).fetchone()
        if card is None:
            out.append({"asset_id": asset_id, "entity_id": entity_id, "status": "该卡未建"})
            continue

        card_dict = dict(card)
        items: dict[str, list[dict[str, Any]]] = {}
        for stance in ("bullish", "bearish"):
            rows = con.execute(
                """
                SELECT stance, analyst, date, claim, confidence, source_file
                FROM debate_card_items
                WHERE card_id = ? AND stance = ? AND confidence >= 0.7
                ORDER BY date DESC, id DESC
                LIMIT 2
                """,
                (card_dict["card_id"], stance),
            ).fetchall()
            items[stance] = [dict(row) for row in rows]

        card_dict.update(
            {
                "asset_id": asset_id,
                "proxy_card_note": "铝无独立卡，使用黄金有色代理卡" if asset_id == "ALUMINUM" else "",
                "items": items,
            }
        )
        out.append(card_dict)
    return out


def _build_factor_states(con: sqlite3.Connection, asset_ids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        latest = con.execute(
            "SELECT MAX(as_of_date) AS as_of_date FROM factor_states WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        as_of_date = latest["as_of_date"] if latest else None
        if not as_of_date:
            out.append({"asset_id": asset_id, "status": "无因素状态"})
            continue

        rows = con.execute(
            """
            SELECT factor_name, current_state, change_direction, impact_direction,
                   impact_strength, confidence, summary, as_of_date
            FROM factor_states
            WHERE asset_id = ? AND as_of_date = ?
            ORDER BY confidence DESC, factor_name
            LIMIT 5
            """,
            (asset_id, as_of_date),
        ).fetchall()
        out.append(
            {
                "asset_id": asset_id,
                "as_of_date": as_of_date,
                "factors": [dict(row) for row in rows] if rows else "无因素状态",
            }
        )
    return out


def _build_discipline() -> dict:
    """组合纪律检查段（#17v2）：独立 try/except，失败只影响本段不拖垮其他段。

    复用 discipline_checker.check_discipline（只读 data/portfolio.json +
    config/discipline_rules.json，只比对不输出调仓，红线 9 不破）。
    """
    try:
        from discipline_checker import check_discipline  # scripts/ 下同级模块

        portfolio = json.loads((ROOT / "data" / "portfolio.json").read_text(encoding="utf-8-sig"))
        rules = json.loads((ROOT / "config" / "discipline_rules.json").read_text(encoding="utf-8-sig"))
        return check_discipline(portfolio, rules)
    except Exception as e:
        return {"status": "error", "error": str(e)}


def build_decision_desk_context() -> dict[str, Any]:
    """构建盘前简报使用的决策台上下文；异常兜底为 error 字典。"""
    try:
        prices = _load_prices()
        with sqlite3.connect(DB_PATH) as con:
            con.row_factory = sqlite3.Row
            user_decisions = _build_user_decisions(con, prices)
            asset_ids = [row["asset_id"] for row in user_decisions if row.get("asset_id")]
            return {
                "user_decisions": user_decisions,
                "debate_cards": _build_debate_cards(con, asset_ids),
                "factor_states": _build_factor_states(con, asset_ids),
                "discipline": _build_discipline(),
            }
    except Exception as e:
        return {"error": str(e)}
