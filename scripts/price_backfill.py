import json
import sys
import os
import re
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_TRENDS_PATH = Path("E:/qianboshi-agent/data/price_trends.json")
EASTMONEY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class PriceBackfillError(Exception):
    """价格补抓过程中的业务异常。"""


def _resolve_path(path: Path | str | None) -> Path:
    return Path(path) if path is not None else DEFAULT_TRENDS_PATH


def _is_valid_price(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PriceBackfillError(f"无效日期: {value}") from exc


def _request_text(url: str) -> str:
    last_error: Exception | None = None

    import http.client
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers=EASTMONEY_HEADERS)
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8")
        except (ConnectionError, TimeoutError, OSError,
                http.client.HTTPException) as exc:
            # RemoteDisconnected 属于 HTTPException；OSError 兜底连接类错误
            last_error = exc
            if attempt < 3:
                time.sleep(min(2 ** attempt * 2, 8))

    raise PriceBackfillError(f"请求失败: {url}: {last_error}") from last_error


def _calculate_change_pct(previous: float | None, current: float) -> float | None:
    if previous is None or previous == 0:
        return None
    return (current - previous) / previous * 100


def load_trends(path: Path | str | None = None) -> dict:
    trends_path = _resolve_path(path)
    if not trends_path.exists():
        return {}

    try:
        with trends_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise PriceBackfillError(f"读取价格数据失败: {trends_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise PriceBackfillError(f"价格数据格式错误: {trends_path}")

    return data


def save_trends(trends: dict, path: Path | str | None = None) -> None:
    trends_path = _resolve_path(path)
    temporary_path = trends_path.with_name(f"{trends_path.name}.tmp")

    try:
        trends_path.parent.mkdir(parents=True, exist_ok=True)
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(trends, file, ensure_ascii=False, indent=1)
            file.write("\n")
        os.replace(temporary_path, trends_path)
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise PriceBackfillError(f"保存价格数据失败: {trends_path}: {exc}") from exc


def last_price_date(trends: dict, symbol: str) -> str | None:
    symbol_trends = trends.get(symbol)
    if not isinstance(symbol_trends, dict):
        return None

    valid_dates: list[str] = []
    for date_iso, record in symbol_trends.items():
        if not isinstance(date_iso, str) or not isinstance(record, dict):
            continue
        if _is_valid_price(record.get("price")):
            try:
                _parse_iso_date(date_iso)
            except PriceBackfillError:
                continue
            valid_dates.append(date_iso)

    return max(valid_dates) if valid_dates else None


def is_fresh(
    trends: dict,
    symbol: str,
    as_of: str | None = None,
    max_stale_days: int = 5,
) -> bool:
    reference_date = date.today() if as_of is None else _parse_iso_date(as_of)
    latest = last_price_date(trends, symbol)
    if latest is None:
        return False

    latest_date = _parse_iso_date(latest)
    age = (reference_date - latest_date).days
    return 0 <= age <= max_stale_days


def _classify_symbol(symbol: str) -> str:
    if re.fullmatch(r"\d{6}\.(SS|SZ)", symbol):
        return "a_share"
    if re.fullmatch(r"\d{6}", symbol):
        return "fund"
    return "unsupported"


def _bars_to_result(bars: list[tuple[str, float]]) -> dict[str, dict]:
    """[(date_iso, close)] → {date: {"price", "change_pct"}}，涨跌幅由相邻bar算。"""
    result: dict[str, dict] = {}
    prev_close: float | None = None
    for day, close in sorted(bars):
        change_pct = None
        if prev_close:
            change_pct = round((close - prev_close) / prev_close * 100, 4)
        result[day] = {"price": close, "change_pct": change_pct}
        prev_close = close
    return result


def _fetch_a_share_history(symbol: str, start: str, end: str) -> dict[str, dict]:
    """A股/ETF日线。腾讯主源（稳），东财kline兜底；返回 {date: {"price","change_pct"}}."""
    market_prefix = "sh" if symbol.endswith(".SS") else "sz"
    code = symbol[:6]

    # —— 主源：腾讯 ifzq 日线 ——
    try:
        tx_url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={market_prefix}{code},day,{start},{end},40,qfq"
        )
        req = urllib.request.Request(
            tx_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": "https://gu.qq.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        node = payload["data"][f"{market_prefix}{code}"]
        rows = node.get("qfqday") or node.get("day") or []
        bars: list[tuple[str, float]] = []
        for row in rows:
            # 行格式 [date, open, close, high, low, volume, ...]
            bars.append((str(row[0]), float(row[2])))
        return _bars_to_result(bars)
    except Exception as exc:
        print(f"[warn] 腾讯源失败({symbol}): {exc}; 转东财兜底", file=sys.stderr)

    # —— 兜底：东财 push2his kline ——
    market = "1" if symbol.endswith(".SS") else "0"
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={market}.{code}"
        "&fields1=f1,f2,f3"
        "&fields2=f51,f53"
        "&klt=101"
        "&fqt=1"
        f"&beg={start.replace('-', '')}"
        f"&end={end.replace('-', '')}"
    )
    text = _request_text(url)
    payload = json.loads(text)
    data = payload.get("data") or {}
    raw_klines = data.get("klines") or []
    bars = []
    for item in raw_klines:
        parts = str(item).split(",")
        if len(parts) >= 2:
            bars.append((parts[0], float(parts[-1])))
    return _bars_to_result(bars)



def _fetch_fund_history(symbol: str, start: str, end: str) -> dict[str, dict]:
    url = f"https://fund.eastmoney.com/pingzhongdata/{symbol}.js"

    text = _request_text(url)
    match = re.search(
        r"Data_netWorthTrend\s*=\s*(\[[\s\S]*?\])\s*;",
        text,
    )
    if match is None:
        raise PriceBackfillError(f"基金净值数据不存在: {symbol}")

    try:
        trend_data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise PriceBackfillError(f"基金净值数据格式错误: {symbol}") from exc

    start_date = _parse_iso_date(start)
    end_date = _parse_iso_date(end)
    result: dict[str, dict] = {}
    previous_price: float | None = None

    if not isinstance(trend_data, list):
        raise PriceBackfillError(f"基金净值列表格式错误: {symbol}")

    for item in trend_data:
        if not isinstance(item, dict):
            continue

        timestamp = item.get("x")
        net_value = item.get("y")

        try:
            timestamp_value = float(timestamp)
            price = float(net_value)
            item_date = datetime.utcfromtimestamp(timestamp_value / 1000).date()
        except (TypeError, ValueError, OverflowError, OSError):
            continue

        if item_date < start_date or item_date > end_date:
            continue

        date_iso = item_date.isoformat()
        result[date_iso] = {
            "price": price,
            "change_pct": _calculate_change_pct(previous_price, price),
        }
        previous_price = price

    return result


def fetch_symbol_history(
    symbol: str,
    start: str,
    end: str,
) -> dict[str, dict]:
    _parse_iso_date(start)
    _parse_iso_date(end)

    if _parse_iso_date(start) > _parse_iso_date(end):
        raise PriceBackfillError(f"开始日期晚于结束日期: {start} > {end}")

    symbol_type = _classify_symbol(symbol)
    if symbol_type == "a_share":
        return _fetch_a_share_history(symbol, start, end)
    if symbol_type == "fund":
        return _fetch_fund_history(symbol, start, end)

    raise PriceBackfillError(f"不支持的symbol: {symbol}")


def _has_price_in_window(
    trends: dict,
    symbol: str,
    start: date,
    end: date,
) -> bool:
    symbol_trends = trends.get(symbol)
    if not isinstance(symbol_trends, dict):
        return False

    for date_iso, record in symbol_trends.items():
        if not isinstance(date_iso, str) or not isinstance(record, dict):
            continue
        if not _is_valid_price(record.get("price")):
            continue
        try:
            item_date = _parse_iso_date(date_iso)
        except PriceBackfillError:
            continue
        if start <= item_date <= end:
            return True

    return False


def _merge_trends(trends: dict, symbol: str, history: dict[str, dict]) -> None:
    symbol_trends = trends.setdefault(symbol, {})
    if not isinstance(symbol_trends, dict):
        symbol_trends = {}
        trends[symbol] = symbol_trends

    for date_iso, record in history.items():
        existing = symbol_trends.get(date_iso)
        if isinstance(existing, dict) and _is_valid_price(existing.get("price")):
            continue
        symbol_trends[date_iso] = record


def ensure_price_window(
    spec: dict,
    t0: str,
    t1: str,
    trends: dict | None = None,
    path: Path | str | None = None,
) -> dict:
    start_date = _parse_iso_date(t0) - timedelta(days=5)
    end_date = _parse_iso_date(t1)

    if start_date > end_date:
        raise PriceBackfillError(f"开始日期晚于结束日期: {t0} > {t1}")

    working_trends = load_trends(path) if trends is None else trends
    result: dict = {
        "primary": {},
        "benchmark": {},
        "backfilled": [],
        "errors": [],
    }
    changed = False

    for result_key, spec_key in (
        ("primary", "primary_symbol"),
        ("benchmark", "benchmark_symbol"),
    ):
        symbol = spec.get(spec_key)
        symbol_result = {
            "symbol": symbol,
            "ok": False,
            "last_date": last_price_date(working_trends, symbol)
            if isinstance(symbol, str)
            else None,
        }
        result[result_key] = symbol_result

        if not isinstance(symbol, str) or not symbol:
            result["errors"].append(f"{result_key}缺少symbol")
            continue

        needs_fetch = not _has_price_in_window(
            working_trends,
            symbol,
            start_date,
            end_date,
        )

        latest = last_price_date(working_trends, symbol)
        if latest is not None:
            latest_date = _parse_iso_date(latest)
            if (end_date - latest_date).days > 5:
                needs_fetch = True

        if needs_fetch:
            try:
                history = fetch_symbol_history(
                    symbol,
                    start_date.isoformat(),
                    end_date.isoformat(),
                )
                _merge_trends(working_trends, symbol, history)
                changed = changed or bool(history)
                if symbol not in result["backfilled"]:
                    result["backfilled"].append(symbol)
            except Exception as exc:
                result["errors"].append(f"{symbol}: {exc}")

        symbol_result["last_date"] = last_price_date(working_trends, symbol)
        symbol_result["ok"] = _has_price_in_window(
            working_trends,
            symbol,
            start_date,
            end_date,
        )

        if not symbol_result["ok"] and not any(
            str(symbol) in error for error in result["errors"]
        ):
            result["errors"].append(f"{symbol}: 目标区间无价格数据")

    if changed:
        save_trends(working_trends, path)

    result["ok"] = (
        bool(result["primary"].get("ok"))
        and bool(result["benchmark"].get("ok"))
        and not result["errors"]
    )
    return result


def refresh_registry_symbols(
    registry_assets: dict[str, dict],
    days: int = 30,
    path: Path | str | None = None,
) -> list[dict]:
    if days < 1:
        raise PriceBackfillError("days必须大于等于1")

    trends = load_trends(path)
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    summaries: list[dict] = []
    changed = False

    for asset_id, asset in registry_assets.items():
        if not isinstance(asset, dict) or not asset.get("active", False):
            continue

        symbol = asset.get("primary_symbol") or asset.get("symbol")
        summary = {
            "asset_id": asset_id,
            "symbol": symbol,
            "fetched_days": 0,
            "error": None,
        }

        if not isinstance(symbol, str) or not symbol:
            summary["error"] = "缺少primary_symbol或symbol"
            summaries.append(summary)
            continue

        try:
            history = fetch_symbol_history(
                symbol,
                start_date.isoformat(),
                end_date.isoformat(),
            )
            _merge_trends(trends, symbol, history)
            summary["fetched_days"] = len(history)
            changed = changed or bool(history)
        except Exception as exc:
            summary["error"] = str(exc)

        summaries.append(summary)

    if changed:
        save_trends(trends, path)

    return summaries


if __name__ == "__main__":
    loaded_trends = load_trends()
    print(f"symbol总数: {len(loaded_trends)}")

    check_result = ensure_price_window(
        spec={
            "primary_symbol": "512460.SS",
            "benchmark_symbol": "000001.SS",
        },
        t0="2026-08-20",
        t1="2026-08-27",
    )
    print(json.dumps(check_result, ensure_ascii=False, indent=1))

    if check_result.get("errors"):
        print("FAIL")
        raise SystemExit(1)
