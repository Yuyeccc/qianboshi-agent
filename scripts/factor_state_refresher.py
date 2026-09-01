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
from valuation_calc import compute_valuation, fetch_fundamentals_periods
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
    # 缺数传播修正（71号方案 §4.5，P0-2）：缺数 → 无方向、无置信、summary 不产生方向结论
    is_missing = (
        impact_direction == "unknown"
        or current_state in ("数据缺失", "手工值缺失", "待更新")
        or "无个股观点" in current_state
    )
    if is_missing:
        summary = f"{factor_name}{current_state}，对{asset_id}影响待定（数据待补）。"
        confidence: float | None = None
        impact_direction = "unknown"
    else:
        summary = f"{factor_name}{current_state}，对{asset_id}构成{impact_direction}影响。"
        confidence = 0.8
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
        "confidence": confidence,
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
        # 缺数传播修正（71号方案 §4.5）：manual 缺值/占位 → 方向 unknown，不按 relation 传播
        valid = manual_value not in (None, "", "待更新", "手工值缺失")
        impact = relation if valid else "unknown"
        return _base_state(factor, asset_id, as_of_date, str(manual_value or "手工值缺失"), "unknown", impact, manual_value, [])
    return _base_state(factor, asset_id, as_of_date, "数据缺失", "unknown", "neutral", {"error": f"unknown type: {binding_type}"}, [])


# ---------------------------------------------------------------------------
# 71号方案 #10/#8/#9：资料充分度 / 质量因子卡 / 8问框架（2026-09-01）
# 口径：baostock 免费接口只提供衍生指标，原始科目（减值/净债务）不可得 → 待补不猜
# ---------------------------------------------------------------------------

_STATUS_LABEL = {"available": "已拿到", "pending": "待补", "insufficient": "不足", "na": "不适用"}


def _fund_metrics(config: dict[str, Any], as_of: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """个股卡拉近 2 期财报；ETF/商品卡返回 ([], {})。"""
    symbol = config.get("fundamentals_symbol")
    if not symbol:
        return [], {}
    periods = fetch_fundamentals_periods(symbol, as_of, n_periods=2)
    fund = periods[0] if periods else {"found": False}
    return periods, fund


def _fmt_pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.{digits}f}%"


def _judge_qf(factor_id: str, m: dict[str, Any]) -> dict[str, Any]:
    """质量因子评估（确定性阈值；行业阈值后续按卡校准）。"""
    if factor_id == "LEVERAGE":
        v = m.get("liability_to_asset")
        j = "高杠杆" if (v is not None and v > 0.70) else ("低杠杆" if (v is not None and v < 0.30) else ("待补" if v is None else "正常"))
        return {"value": round(v * 100, 1) if v is not None else None, "unit": "%", "judgement": j}
    if factor_id == "INTEREST_COVERAGE":
        v = m.get("ebit_to_interest")
        j = "充裕" if (v is not None and v > 1.0) else ("偏紧" if (v is not None and v < 0.5) else ("待补" if v is None else "正常"))
        return {"value": round(v, 2) if v is not None else None, "unit": "倍", "judgement": j}
    if factor_id == "CASHFLOW_QUALITY":
        v = m.get("cfo_to_np")
        j = "含金量高" if (v is not None and v > 1.0) else ("含金量低" if (v is not None and v < 0.5) else ("待补" if v is None else "正常"))
        return {"value": round(v, 2) if v is not None else None, "unit": "倍", "judgement": j}
    if factor_id == "ASSET_STRUCTURE":
        # 检修修正（2026-09-01）：tangibleAssetToAsset 对矿业有语义陷阱（采矿权在无形资产，
        # 有形占比低≠轻资产）→ 改用非流动资产占比 NCAToAsset 判据，tangible 仅作辅助展示
        v = m.get("nca_to_asset")
        j = "重资产" if (v is not None and v > 0.75) else ("轻资产" if (v is not None and v < 0.50) else ("待补" if v is None else "正常"))
        return {"value": round(v * 100, 1) if v is not None else None, "unit": "%", "judgement": j}
    if factor_id == "IMPAIRMENT_EXPOSURE":
        # baostock 免费接口无商誉/应收/存货科目 → 诚实待补（不猜）
        return {"value": None, "unit": "-", "judgement": "待补（免费接口无减值科目）"}
    return {"value": None, "unit": "-", "judgement": "待补"}


def _build_quality_factors(config: dict[str, Any], fund: dict[str, Any]) -> list[dict[str, Any]]:
    """质量因子卡评估结果。ETF/商品卡（无 fundamentals_symbol）→ []（渲染层显示不适用）。"""
    if not config.get("fundamentals_symbol"):
        return []
    out = []
    for qf in config.get("quality_factors") or []:
        fid = qf.get("factor_id")
        if fund.get("found"):
            r = _judge_qf(fid, fund["metrics"])
            out.append({
                "factor_id": fid,
                "factor_name": qf.get("factor_name") or fid,
                "category": qf.get("category"),
                "value": r["value"],
                "unit": r["unit"],
                "judgement": r["judgement"],
                "period": fund.get("period"),
                "source": fund.get("source"),
                "status": "available" if r["value"] is not None else "pending",
                "note": qf.get("note"),
            })
        else:
            out.append({
                "factor_id": fid,
                "factor_name": qf.get("factor_name") or fid,
                "category": qf.get("category"),
                "value": None,
                "unit": "-",
                "judgement": "待补",
                "period": None,
                "source": "baostock",
                "status": "pending",
                "note": qf.get("note"),
            })
    return out


def _answer_question(question_id: str, periods: list[dict[str, Any]], fund: dict[str, Any]) -> dict[str, Any]:
    """8问答案（确定性；无数据 → answer=—, status=pending，不猜）。"""
    def p(n: int) -> dict[str, Any]:
        return periods[n]["metrics"] if n < len(periods) and periods[n].get("found") else {}

    if not fund.get("found"):
        return {"answer": "—", "status": "pending"}
    m = fund["metrics"]
    if question_id == "Q1":  # 现金流趋势（经营CF/营收 近2期）
        cur, prev = p(0).get("cfo_to_or"), p(1).get("cfo_to_or")
        if cur is None or prev is None:
            return {"answer": "—", "status": "pending"}
        trend = "改善" if cur > prev else ("恶化" if cur < prev else "持平")
        return {"answer": f"{trend}（{_fmt_pct(cur)} vs 上期 {_fmt_pct(prev)}）", "status": "available"}
    if question_id == "Q2":  # 利息覆盖
        v = m.get("ebit_to_interest")
        if v is None:
            return {"answer": "—", "status": "pending"}
        j = "能覆盖" if v > 1.0 else ("偏紧" if v >= 0.5 else "不能覆盖")
        return {"answer": f"{j}（{v:.2f} 倍）", "status": "available"}
    if question_id == "Q3":  # 杠杆水平与方向
        v, yoy = m.get("liability_to_asset"), m.get("yoy_liability")
        if v is None:
            return {"answer": "—", "status": "pending"}
        j = "高" if v > 0.70 else ("低" if v < 0.30 else "中")
        s = f"{j}（资产负债率 {_fmt_pct(v)}"
        if yoy is not None:
            s += f"，负债同比 {yoy:+.1f}%"
        s += "）"
        return {"answer": s, "status": "available"}
    if question_id == "Q4":  # 短期偿债（流动比率/现金比率）
        cr, ca = m.get("current_ratio"), m.get("cash_ratio")
        if cr is None:
            return {"answer": "—", "status": "pending"}
        j = "充裕" if cr >= 1.5 else ("偏紧" if cr < 1.0 else "正常")
        s = f"{j}（流动比率 {cr:.2f}"
        if ca is not None:
            s += f"，现金比率 {ca:.2f}"
        s += "）"
        return {"answer": s, "status": "available"}
    if question_id == "Q5":  # 盈利含金量
        v = m.get("cfo_to_np")
        if v is None:
            return {"answer": "—", "status": "pending"}
        j = "含金量高" if v > 1.0 else ("含金量低" if v < 0.5 else "正常")
        return {"answer": f"{j}（经营CF/净利 {v:.2f}）", "status": "available"}
    if question_id == "Q6":  # 利润率水平
        np_, gp = m.get("np_margin"), m.get("gp_margin")
        if np_ is None and gp is None:
            return {"answer": "—", "status": "pending"}
        s = f"净利率 {_fmt_pct(np_)}" if np_ is not None else "净利率 —"
        if gp is not None:
            s += f"，毛利率 {_fmt_pct(gp)}"
        return {"answer": s, "status": "available"}
    if question_id == "Q7":  # 资产结构
        nca, tan = m.get("nca_to_asset"), m.get("tangible_to_asset")
        if nca is None and tan is None:
            return {"answer": "—", "status": "pending"}
        s = f"非流动资产占比 {_fmt_pct(nca)}" if nca is not None else "非流动资产占比 —"
        if tan is not None:
            s += f"，有形资产占比 {_fmt_pct(tan)}"
        return {"answer": s, "status": "available"}
    if question_id == "Q8":  # 减值暴露/计提（无科目 → 诚实待补）
        return {"answer": "—", "status": "pending"}
    return {"answer": "—", "status": "pending"}


def _build_analysis_framework(config: dict[str, Any], periods: list[dict[str, Any]], fund: dict[str, Any]) -> list[dict[str, Any]]:
    """8问框架答案。ETF/商品卡（无 fundamentals_symbol）→ 标记 na 不渲染空表。"""
    if not config.get("fundamentals_symbol"):
        return []
    out = []
    for q in config.get("analysis_framework") or []:
        ans = _answer_question(str(q.get("question_id")), periods, fund)
        out.append({
            "question_id": q.get("question_id"),
            "question": q.get("question"),
            "dimension": q.get("dimension"),
            "answer": ans["answer"],
            "status": ans["status"],
        })
    return out


def build_quality_snapshot(config: dict[str, Any], as_of_date: str) -> dict[str, Any]:
    """构建资产卡三维（71号方案）：资料充分度 / 质量因子 / 8问 / 估值。"""
    as_of = _parse_date(as_of_date) or datetime.now().date()
    has_fund = bool(config.get("fundamentals_symbol"))
    periods: list[dict[str, Any]] = []
    fund: dict[str, Any] = {}
    if has_fund:
        periods, fund = _fund_metrics(config, as_of)

    # 资料充分度（值域 available/pending/insufficient/na）
    price_trends = _load_json(DATA_DIR / "price_trends.json")
    market_status = "available" if isinstance(price_trends, dict) and price_trends else "pending"
    views_status = "available" if load_views() else "pending"
    if has_fund:
        if fund.get("found"):
            pub = _parse_date(fund.get("pub_date"))
            stale = pub is not None and (as_of - pub).days > 180  # 财报公告距今 >2 季度
            fundamentals_status = "insufficient" if stale else "available"
        else:
            fundamentals_status = "pending"
    else:
        fundamentals_status = "na"

    data_status = {
        "market": market_status,
        "views": views_status,
        "fundamentals": fundamentals_status,
    }

    # 质量因子卡 + 8问
    quality_factors = _build_quality_factors(config, fund)
    analysis_framework = _build_analysis_framework(config, periods, fund)

    # 估值水位（仅配置了 valuation 的卡）
    valuation = None
    if config.get("valuation") and has_fund:
        val = compute_valuation(str(config.get("fundamentals_symbol")), as_of_date=as_of_date)
        valuation = val
        data_status["valuation"] = {"ok": "available", "insufficient": "insufficient", "pending": "pending"}.get(
            val.get("status"), "pending"
        )
    else:
        data_status["valuation"] = "na"

    return {
        "data_status": data_status,
        "quality_factors": quality_factors,
        "analysis_framework": analysis_framework,
        "valuation": valuation,
    }


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
    # 71号方案 #10/#8/#9：三维补齐（资料充分度 / 质量因子 / 8问 / 估值）
    # 检修加固（2026-09-01）：snapshot 失败（baostock/DB 异常）→ 降级 pending，卡片主体不崩
    try:
        snapshot = build_quality_snapshot(config, as_of_date)
    except Exception as e:
        print(f"  ⚠️ 资产卡三维补齐失败(降级待补) {card_asset_id}: {e}", file=sys.stderr)
        snapshot = {
            "data_status": {"market": "pending", "views": "pending", "fundamentals": "pending", "valuation": "pending"},
            "quality_factors": [],
            "analysis_framework": [],
            "valuation": None,
        }
    card.update(snapshot)
    card["extra"] = {
        "data_status": snapshot["data_status"],
        "quality_factors": snapshot["quality_factors"],
        "valuation": snapshot["valuation"],
    }
    upsert_asset_card(card)
    save_asset_card_version(card_asset_id, version, config, change_reason="auto_refresh", changed_by="system")
    return card
