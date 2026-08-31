"""A股决策复盘判定模块（v2）。"""

import json
from datetime import date, timedelta
from pathlib import Path


def horizon_to_days(horizon: str) -> int:
    """将复盘周期映射为自然日天数。"""
    return {"short": 5, "medium": 20, "long": 60}.get(horizon, 20)


def classify(
    direction: str,
    outcome_return: float,
    benchmark_return: float | None,
    horizon: str,
    conviction: float | None,
    rules: dict,
) -> dict:
    """按方向、绝对收益和置信度给出兼容旧表的复盘判定。"""
    noise = float(rules["noise_band_pct"][horizon])
    abs_band = float(rules["neutral_abs_band_pct"][horizon])
    excess_return = (
        round(outcome_return - benchmark_return, 4)
        if benchmark_return is not None
        else None
    )

    normalized_direction = str(direction).lower()
    if normalized_direction == "neutral":
        result_label = "right" if abs(outcome_return) < abs_band else "mixed"
    elif normalized_direction == "bullish":
        if outcome_return > noise:
            result_label = "right"
        elif outcome_return < -noise:
            result_label = "wrong"
        else:
            result_label = "mixed"
    elif normalized_direction == "bearish":
        if outcome_return < -noise:
            result_label = "right"
        elif outcome_return > noise:
            result_label = "wrong"
        else:
            result_label = "mixed"
    else:
        result_label = "mixed"

    result_grade: str | None = None
    if result_label == "wrong":
        grades = rules["conviction_grades"]
        if conviction is not None and conviction >= float(
            grades["strong_wrong_min_conviction"]
        ):
            result_grade = "strong_wrong"
        elif conviction is not None and conviction <= float(
            grades["weak_wrong_max_conviction"]
        ):
            result_grade = "weak_wrong"
        else:
            result_grade = "normal_wrong"

    return {
        "result_label": result_label,
        "result_grade": result_grade,
        "excess_return": excess_return,
    }


def _symbol_prices(trends: dict, symbol: str) -> dict[str, float]:
    """兼容常见的 price_trends 字典和列表存储形式。"""
    source = trends.get(symbol)
    if source is None and isinstance(trends.get("price_trends"), dict):
        source = trends["price_trends"].get(symbol)

    if isinstance(source, dict) and isinstance(source.get("prices"), (dict, list)):
        source = source["prices"]

    prices: dict[str, float] = {}
    if isinstance(source, dict):
        for raw_day, raw_price in source.items():
            if isinstance(raw_price, dict):
                raw_price = raw_price.get("close", raw_price.get("price"))
            try:
                prices[str(raw_day)] = float(raw_price)
            except (TypeError, ValueError):
                continue
    elif isinstance(source, list):
        for item in source:
            if not isinstance(item, dict):
                continue
            raw_day = item.get("date", item.get("day"))
            raw_price = item.get("close", item.get("price"))
            if raw_day is None:
                continue
            try:
                prices[str(raw_day)] = float(raw_price)
            except (TypeError, ValueError):
                continue
    return prices


def price_on(trends: dict, symbol: str, day: str) -> float | None:
    """获取标的在精确日期的收盘价。"""
    return _symbol_prices(trends, symbol).get(day)


def nearest_price(
    trends: dict,
    symbol: str,
    day: str,
    window: int = 5,
) -> tuple[float, str] | None:
    """从目标日向前后逐日扩散，获取窗口内最近价格。"""
    try:
        target_day = date.fromisoformat(day)
    except ValueError:
        return None

    prices = _symbol_prices(trends, symbol)
    for offset in range(window + 1):
        offsets = (0,) if offset == 0 else (-offset, offset)
        for signed_offset in offsets:
            candidate = (target_day + timedelta(days=signed_offset)).isoformat()
            price = prices.get(candidate)
            if price is not None:
                return price, candidate
    return None


def _resolve_symbol(decision: dict) -> str:
    """从兼容字段中确定决策标的代码。"""
    value = decision.get(
        "primary_symbol",
        decision.get("symbol", decision.get("asset_id", "")),
    )
    return str(value)


def review_decision(decision: dict, trends: dict, rules: dict) -> dict:
    """计算复盘区间收益、基准收益并执行 v2 判定。"""
    asset_id = decision.get("asset_id")
    decision_id = decision.get("decision_id")
    decision_date = str(decision["decision_date"])
    horizon = str(decision.get("horizon", "medium"))
    if horizon not in rules["noise_band_pct"]:
        horizon = "medium"

    review_date = (
        date.fromisoformat(decision_date) + timedelta(days=horizon_to_days(horizon))
    ).isoformat()
    primary_symbol = _resolve_symbol(decision)

    start_price = nearest_price(
        trends,
        primary_symbol,
        decision_date,
        int(rules["price_nearest_window_days"]),
    )
    end_price = nearest_price(
        trends,
        primary_symbol,
        review_date,
        int(rules["price_nearest_window_days"]),
    )
    if start_price is None or end_price is None:
        missing_parts: list[str] = []
        if start_price is None:
            missing_parts.append("p0")
        if end_price is None:
            missing_parts.append("p1")
        return {
            "status": "no_price",
            "detail": f"{primary_symbol} 缺少价格: {', '.join(missing_parts)}",
        }

    p0, p0_date = start_price
    p1, p1_date = end_price
    if p0 == 0:
        return {
            "status": "no_price",
            "detail": f"{primary_symbol} 起始价格为零，无法计算收益",
        }

    outcome_return = round((p1 / p0 - 1) * 100, 4)
    benchmark_symbol = decision.get(
        "benchmark_symbol",
        rules.get("benchmark_symbol", ""),
    )
    benchmark_symbol = str(benchmark_symbol) if benchmark_symbol else None
    benchmark_return: float | None = None
    benchmark_status = "missing"

    if benchmark_symbol:
        benchmark_p0 = nearest_price(
            trends,
            benchmark_symbol,
            p0_date,
            int(rules["price_nearest_window_days"]),
        )
        benchmark_p1 = nearest_price(
            trends,
            benchmark_symbol,
            p1_date,
            int(rules["price_nearest_window_days"]),
        )
        if benchmark_p0 is not None and benchmark_p1 is not None:
            benchmark_start, benchmark_p0_date = benchmark_p0
            benchmark_end, benchmark_p1_date = benchmark_p1
            max_offset = int(rules["benchmark_max_offset_days"])
            p0_offset = abs(
                (date.fromisoformat(benchmark_p0_date) - date.fromisoformat(p0_date)).days
            )
            p1_offset = abs(
                (date.fromisoformat(benchmark_p1_date) - date.fromisoformat(p1_date)).days
            )
            if p0_offset > max_offset or p1_offset > max_offset:
                benchmark_status = "misaligned"
            elif benchmark_start != 0:
                benchmark_return = round(
                    (benchmark_end / benchmark_start - 1) * 100,
                    4,
                )
                benchmark_status = "ok"

    result = {
        "asset_id": asset_id,
        "decision_id": decision_id,
        "decision_date": decision_date,
        "review_date": review_date,
        "primary_symbol": primary_symbol,
        "p0": p0,
        "p1": p1,
        "p0_date": p0_date,
        "p1_date": p1_date,
        "outcome_return": outcome_return,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_return": benchmark_return,
        "benchmark_status": benchmark_status,
        "rule_version": rules.get("rule_version"),
    }
    result.update(
        classify(
            str(decision.get("direction", "neutral")),
            outcome_return,
            benchmark_return,
            horizon,
            decision.get("conviction"),
            rules,
        )
    )
    return result


if __name__ == "__main__":
    rules_path = Path("E:/qianboshi-agent/config/review_rules.json")
    rules = json.loads(rules_path.read_text(encoding="utf-8")) if rules_path.exists() else {
        "rule_version": "v2",
        "noise_band_pct": {"short": 2.0, "medium": 1.5, "long": 1.0},
        "neutral_abs_band_pct": {"short": 3.0, "medium": 2.0, "long": 1.5},
        "conviction_grades": {
            "strong_wrong_min_conviction": 0.7,
            "weak_wrong_max_conviction": 0.4,
        },
    }

    cases = [
        ("bullish涨大", classify("bullish", 3.0, 1.0, "short", 0.5, rules), "right"),
        ("bullish横盘", classify("bullish", 1.0, 0.0, "short", 0.5, rules), "mixed"),
        ("bearish跌大", classify("bearish", -3.0, 0.0, "short", 0.8, rules), "right"),
        (
            "bearish微涨但跑输大盘",
            classify("bearish", 1.0, 5.0, "short", 0.8, rules),
            "mixed",
        ),
        ("neutral窄幅", classify("neutral", 2.0, 1.0, "short", 0.5, rules), "right"),
    ]
    for name, result, expected in cases:
        assert result["result_label"] == expected, f"{name}: {result}"
        print(name, result)

    assert classify("bullish", -3.0, 0.0, "short", 0.8, rules)["result_grade"] == "strong_wrong"
    assert classify("bullish", -3.0, 0.0, "short", 0.3, rules)["result_grade"] == "weak_wrong"
    print("ALL PASS")
