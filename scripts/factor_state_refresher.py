#!/usr/bin/env python3
"""资产分析卡因素状态刷新器。"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from decision_db import save_asset_card_version, upsert_asset_card, upsert_factor_state
from factor_config_loader import load_asset_card_config
from view_store import load_views

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def _parse_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _as_of(value: str | None = None) -> str:
    return value or datetime.now().strftime("%Y-%m-%d")


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _series_from_price_trends(symbol: str) -> list[tuple[str, float]]:
    data = _load_json(DATA_DIR / "price_trends.json")
    raw = data.get(symbol) if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return []
    rows: list[tuple[str, float]] = []
    for dt, item in raw.items():
        if not isinstance(item, dict):
            continue
        val = item.get("close", item.get("price"))
        try:
            rows.append((str(dt)[:10], float(val)))
        except Exception:
            continue
    rows.sort(key=lambda x: x[0])
    return rows


def _series_from_market_cache(symbol: str) -> list[tuple[str, float]]:
    data = _load_json(DATA_DIR / "market_cache.json")
    raw = data.get(symbol) if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return []
    prices = raw.get("prices")
    if not isinstance(prices, list) or not prices:
        val = raw.get("price")
        try:
            return [(str(raw.get("updated") or datetime.now().date())[:10], float(val))]
        except Exception:
            return []
    end = _parse_date(raw.get("updated")) or datetime.now().date()
    start = end - timedelta(days=len(prices) - 1)
    rows = []
    for idx, val in enumerate(prices):
        try:
            rows.append(((start + timedelta(days=idx)).isoformat(), float(val)))
        except Exception:
            continue
    return rows


def _latest_window(series: list[tuple[str, float]], as_of_date: str) -> list[tuple[str, float]]:
    as_of = _parse_date(as_of_date)
    if not as_of:
        return series
    return [(dt, val) for dt, val in series if (_parse_date(dt) or as_of) <= as_of]


def _pct_change(series: list[tuple[str, float]], days: int) -> float | None:
    if len(series) <= days:
        return None
    base = series[-days - 1][1]
    latest = series[-1][1]
    if base == 0:
        return None
    return round((latest / base - 1) * 100, 4)


def _direction(value: float | None, threshold: float = 0.1) -> str:
    if value is None:
        return "unknown"
    if value > threshold:
        return "up"
    if value < -threshold:
        return "down"
    return "flat"


def _impact_direction(change_direction: str, relation: str) -> str:
    if change_direction not in {"up", "down"}:
        return "neutral"
    if relation == "positive":
        return "positive" if change_direction == "up" else "negative"
    if relation == "negative":
        return "negative" if change_direction == "up" else "positive"
    return "neutral"


def _state_text(change_direction: str, pct_change_5d: float | None) -> str:
    if change_direction == "up":
        word = "走强"
    elif change_direction == "down":
        word = "走弱"
    elif change_direction == "flat":
        word = "持平"
    else:
        return "数据缺失"
    if pct_change_5d is None:
        return f"近5日{word}"
    return f"近5日{word}{pct_change_5d:+.2f}%"


def _view_text(view: dict[str, Any]) -> str:
    parts = [view.get("claim"), view.get("evidence"), view.get("section"), view.get("logic"), view.get("risk")]
    return " ".join(str(x or "") for x in parts)


def _refresh_market_factor(factor: dict[str, Any], asset_id: str, as_of_date: str) -> dict[str, Any]:
    binding = factor.get("data_binding") or {}
    symbol = str(binding.get("symbol") or "")
    relation = (factor.get("impact_rule") or {}).get("relation") or "positive"
    series = _latest_window(_series_from_price_trends(symbol), as_of_date)
    source = "price_trends"
    if not series:
        series = _latest_window(_series_from_market_cache(symbol), as_of_date)
        source = "market_cache"
    if not series:
        return _base_state(factor, asset_id, as_of_date, "数据缺失", "unknown", "neutral", {}, [binding.get("source") or symbol])
    pct5 = _pct_change(series, 5)
    pct20 = _pct_change(series, 20)
    change_direction = _direction(pct5)
    raw = {
        "symbol": symbol,
        "close": series[-1][1],
        "date": series[-1][0],
        "pct_change_5d": pct5,
        "pct_change_20d": pct20,
        "source": source,
    }
    return _base_state(
        factor,
        asset_id,
        as_of_date,
        _state_text(change_direction, pct5),
        change_direction,
        _impact_direction(change_direction, relation),
        raw,
        [binding.get("source") or source],
    )


def _refresh_view_factor(factor: dict[str, Any], asset_id: str, as_of_date: str) -> dict[str, Any]:
    binding = factor.get("data_binding") or {}
    terms = [str(x) for x in binding.get("query_terms") or [] if str(x)]
    lookback_days = int(binding.get("lookback_days") or 14)
    end = _parse_date(as_of_date) or datetime.now().date()
    current_start = end - timedelta(days=lookback_days - 1)
    prev_start = current_start - timedelta(days=lookback_days)
    views = load_views()

    def matched(start: date, stop: date) -> list[dict[str, Any]]:
        out = []
        for view in views:
            vd = _parse_date(view.get("date"))
            if not vd or vd < start or vd > stop:
                continue
            hay = _view_text(view)
            if any(term in hay for term in terms):
                out.append(view)
        return out

    current = matched(current_start, end)
    previous = matched(prev_start, current_start - timedelta(days=1))
    if len(current) > len(previous):
        change_direction = "up"
        heat = "上升"
    elif len(current) < len(previous):
        change_direction = "down"
        heat = "下降"
    else:
        change_direction = "flat"
        heat = "持平"
    relation = (factor.get("impact_rule") or {}).get("relation") or "positive"
    refs = [str(v.get("view_id")) for v in current[:3] if v.get("view_id")]
    raw = {
        "query_terms": terms,
        "lookback_days": lookback_days,
        "current_count": len(current),
        "previous_count": len(previous),
    }
    return _base_state(
        factor,
        asset_id,
        as_of_date,
        f"观点热度{heat}",
        change_direction,
        _impact_direction(change_direction, relation),
        raw,
        refs,
    )


def _refresh_stock_views_factor(factor: dict[str, Any], asset_id: str, as_of_date: str) -> dict[str, Any]:
    """按配置股票统计窗口内的看多、看空和中性观点。"""
    binding = factor.get("data_binding") or {}
    stocks = binding.get("stocks") or []
    lookback_days = int(binding.get("lookback_days") or 14)
    end = _parse_date(as_of_date) or datetime.now().date()
    current_start = end - timedelta(days=lookback_days - 1)
    previous_start = current_start - timedelta(days=lookback_days)
    views = load_views()
    stock_map = {
        str(stock.get("code")): stock
        for stock in stocks
        if isinstance(stock, dict) and stock.get("code")
    }
    # 中文名匹配：结构化 entities.stocks 常缺创新药等个股代码，用名字在观点文本里补匹配（2026-08-06）
    stock_names = [
        (str(stock.get("name")), str(stock.get("code")))
        for stock in stocks
        if isinstance(stock, dict) and stock.get("name") and stock.get("code")
    ]

    def matched(start: date, stop: date) -> list[dict[str, Any]]:
        out = []
        for view in views:
            view_date = _parse_date(view.get("date"))
            if not view_date or view_date < start or view_date > stop:
                continue
            entities = view.get("entities") or {}
            view_stocks = entities.get("stocks") or []
            if any(str(code) in stock_map for code in view_stocks):
                out.append(view)
                continue
            if stock_names and any(name and name in _view_text(view) for name, _ in stock_names):
                out.append(view)
        return out

    current = matched(current_start, end)
    previous = matched(previous_start, current_start - timedelta(days=1))
    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    stance_labels = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}
    by_stock: dict[str, list[dict[str, Any]]] = {code: [] for code in stock_map}

    for view in current:
        stance = str(view.get("stance") or "neutral").lower()
        if stance not in counts:
            stance = "neutral"
        counts[stance] += 1
        hit_codes: list[str] = []
        for code in (view.get("entities") or {}).get("stocks") or []:
            code = str(code)
            if code in by_stock:
                hit_codes.append(code)
        if not hit_codes:  # 中文名命中归属
            hay = _view_text(view)
            hit_codes = [code for name, code in stock_names if name and name in hay]
        for code in hit_codes:
            by_stock[code].append(view)

    total_current = sum(counts.values())
    total_previous = len(previous)
    if total_current > total_previous:
        change_direction = "up"
    elif total_current < total_previous:
        change_direction = "down"
    else:
        change_direction = "flat"

    top_stocks = []
    for code, stock_views in by_stock.items():
        if not stock_views:
            continue
        representative = sorted(
            stock_views,
            key=lambda view: (_parse_date(view.get("date")) or date.min, str(view.get("view_id") or "")),
            reverse=True,
        )[0]
        stance = str(representative.get("stance") or "neutral").lower()
        if stance not in stance_labels:
            stance = "neutral"
        claim = str(representative.get("claim") or "")[:40]
        top_stocks.append(
            {
                "code": code,
                "name": stock_map[code].get("name") or code,
                "stance": stance_labels[stance],
                "analyst": representative.get("analyst") or "",
                "date": str(representative.get("date") or "")[:10],
                "claim": claim,
                "view_count": len(stock_views),
            }
        )
    top_stocks.sort(key=lambda item: (-item["view_count"], item["code"]))
    top_stocks = top_stocks[:3]

    if total_current:
        bullish_ratio = counts["bullish"] / total_current
        if bullish_ratio > 0.5:
            impact_direction = "positive"
        elif bullish_ratio < 0.5:
            impact_direction = "negative"
        else:
            impact_direction = "neutral"
    else:
        impact_direction = "neutral"

    if total_current:
        current_state = (
            f"看多{counts['bullish']}/看空{counts['bearish']}/中性{counts['neutral']}"
            f"（近{lookback_days}天）"
        )
        details = []
        for item in top_stocks:
            item_date = _parse_date(item.get("date"))
            display_date = f"{item_date.month}.{item_date.day}" if item_date else ""
            details.append(f"{item['name']}{item['stance']}({item['analyst']} {display_date})")
        if details:
            current_state += "；" + "、".join(details)
    else:
        current_state = f"近{lookback_days}天无个股观点"

    raw = {
        "counts": counts,
        "top_stocks": top_stocks,
        "lookback_days": lookback_days,
    }
    refs = [str(view.get("view_id")) for view in current[:3] if view.get("view_id")]
    return _base_state(
        factor,
        asset_id,
        as_of_date,
        current_state,
        change_direction,
        impact_direction,
        raw,
        refs,
    )


def _base_state(
    factor: dict[str, Any],
    asset_id: str,
    as_of_date: str,
    current_state: str,
    change_direction: str,
    impact_direction: str,
    raw_value: dict[str, Any] | Any,
    evidence_refs: list[Any],
) -> dict[str, Any]:
    rule = factor.get("impact_rule") or {}
    factor_name = factor.get("factor_name") or factor.get("factor_id")
    strength = rule.get("strength") or "medium"
    summary = f"{factor_name}{current_state}，对{asset_id}构成{impact_direction}影响。"
    return {
        "asset_id": asset_id,
        "factor_id": factor.get("factor_id"),
        "factor_name": factor_name,
        "as_of_date": as_of_date,
        "raw_value": raw_value,
        "current_state": current_state,
        "change_direction": change_direction,
        "impact_direction": impact_direction,
        "impact_strength": strength,
        "confidence": 0.6 if current_state == "数据缺失" else 0.8,
        "evidence_refs": evidence_refs,
        "summary": summary,
    }


def refresh_factor(factor: dict[str, Any], asset_id: str, as_of_date: str) -> dict[str, Any]:
    """按 data_binding.type 刷新单个因素。"""
    binding = factor.get("data_binding") or {}
    binding_type = binding.get("type")
    if binding_type == "market":
        return _refresh_market_factor(factor, asset_id, as_of_date)
    if binding_type == "view_query":
        return _refresh_view_factor(factor, asset_id, as_of_date)
    if binding_type == "stock_views":
        return _refresh_stock_views_factor(factor, asset_id, as_of_date)
    if binding_type == "manual":
        relation = (factor.get("impact_rule") or {}).get("relation") or "positive"
        manual_value = binding.get("manual_value")
        return _base_state(factor, asset_id, as_of_date, str(manual_value or "手工值缺失"), "unknown", relation, manual_value, [])
    return _base_state(factor, asset_id, as_of_date, "数据缺失", "unknown", "neutral", {"error": f"unknown type: {binding_type}"}, [])


def _logic_chain_summary(asset_name: str, factors: list[dict[str, Any]]) -> str:
    positive = [f.get("factor_name") for f in factors if f.get("impact_direction") == "positive"]
    negative = [f.get("factor_name") for f in factors if f.get("impact_direction") == "negative"]
    parts = []
    if positive:
        parts.append(f"正向驱动来自{'、'.join(positive[:3])}")
    if negative:
        parts.append(f"负向压力来自{'、'.join(negative[:3])}")
    if not parts:
        parts.append("主要因素暂未形成明确方向")
    return f"当前{asset_name}的" + "，".join(parts) + "。"


def refresh_asset_card(asset_id: str, as_of_date: str | None = None) -> dict[str, Any]:
    """刷新资产分析卡并写入因素状态表。"""
    as_of_date = _as_of(as_of_date)
    config = load_asset_card_config(asset_id)
    card_asset_id = str(config.get("asset_id") or asset_id).upper()
    version = int(config.get("version") or 1)
    factors = []
    for factor in config.get("factors") or []:
        state = refresh_factor(factor, card_asset_id, as_of_date)
        state["card_version"] = version
        state["state_id"] = f"{card_asset_id}_{version}_{state.get('factor_id')}_{as_of_date}"
        factors.append(state)
        upsert_factor_state(state)
    card = {
        "asset_id": card_asset_id,
        "asset_name": config.get("asset_name") or card_asset_id,
        "asset_type": config.get("asset_type"),
        "version": version,
        "default_horizon": config.get("default_horizon"),
        "description": config.get("description"),
        "config_path": config.get("config_path"),
        "as_of_date": as_of_date,
        "factors": factors,
    }
    card["logic_chain_summary"] = _logic_chain_summary(card["asset_name"], factors)
    upsert_asset_card(card)
    save_asset_card_version(card_asset_id, version, config, change_reason="auto_refresh", changed_by="system")
    return card
