#!/usr/bin/env python3
"""
市场数据缓存 + 趋势追踪
- 拉取数据后存缓存，下次优先读缓存
- 记录每个标的的历史收盘价，判断趋势
"""
import json, os, time
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "market_cache.json"
TREND_FILE = DATA_DIR / "price_trends.json"

# 跟踪的标的列表（含美股+持仓+常用板块ETF）
# 注意：A股在yfinance需要加后缀 .SS(沪) / .SZ(深)
TRACKED_SYMBOLS = [
    # A股指数
    "000001.SS", "399001.SZ", "399006.SZ",
    # 美股指数
    "^DJI", "^IXIC", "^GSPC",
    # 美股AI链
    "NVDA", "AMD", "AVGO", "MRVL", "SMCI", "TSLA", "AAPL", "MSFT", "GOOGL", "META",
    # 创新药ETF
    "159992.SZ",
    # 光模块/通信
    "300502.SZ", "300308.SZ", "300394.SZ",
    # 半导体
    "600745.SS", "688981.SS", "688012.SS",
    # 黄金/周期
    "601899.SS", "600547.SS",
    # 消费
    "600519.SS",
    # 白酒ETF（决策台 BAIJIU 决策验证用）
    "512690.SS",
    # 半导体ETF（决策台 TECH 代理，159813 折算跳变）
    "512480.SS",
]


def fetch_prices(symbols=None):
    """批量拉取行情，自动切换代理策略"""
    import yfinance as yf
    import pandas as pd
    
    if symbols is None:
        symbols = TRACKED_SYMBOLS
    
    symbols_list = list(symbols)
    results = {}
    batch_size = 10
    
    # 策略1: 先直连（A股用直连更快）
    _clear_proxy()
    for i in range(0, len(symbols_list), batch_size):
        batch = symbols_list[i:i+batch_size]
        try:
            data = yf.download(batch, period="2d", progress=False, timeout=20)
            if data is not None and not data.empty:
                results.update(_parse_data(data, batch))
        except Exception:
            pass
    
    # 策略2: 直连失败的走代理（美股用代理）
    _proxy_env()
    failed = [s for s in symbols_list if s not in results]
    if failed:
        for i in range(0, len(failed), batch_size):
            batch = failed[i:i+batch_size]
            try:
                data = yf.download(batch, period="2d", progress=False, timeout=20)
                if data is not None and not data.empty:
                    results.update(_parse_data(data, batch))
            except Exception:
                pass
    
    # 策略3: 仍然失败的逐只查询（走代理）
    _proxy_env()
    still_failed = [s for s in symbols_list if s not in results]
    for sym in still_failed:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="2d")
            if not hist.empty:
                closes = hist["Close"].dropna()
                if len(closes) >= 1:
                    prices = [round(float(c), 2) for c in closes]
                    change = round((prices[-1] - prices[0]) / prices[0] * 100, 2) if len(prices) > 1 else 0
                    results[sym] = {
                        "price": prices[-1], "change_pct": change,
                        "prices": prices, "updated": datetime.now().isoformat(),
                    }
        except Exception:
            pass
        time.sleep(0.5)
    
    return results


def _parse_data(data, symbols):
    """解析yfinance批量下载结果"""
    import pandas as pd
    results = {}
    is_multi = isinstance(data.columns, pd.MultiIndex)
    for sym in symbols:
        try:
            if is_multi:
                col = data.xs(sym, level=1, axis=1)
            else:
                col = data
            closes = col["Close"].dropna()
            if len(closes) >= 1:
                prices = [round(float(c), 2) for c in closes]
                change = round((prices[-1] - prices[0]) / prices[0] * 100, 2) if len(prices) > 1 else 0
                results[sym] = {
                    "price": prices[-1], "change_pct": change,
                    "prices": prices, "updated": datetime.now().isoformat(),
                }
        except Exception:
            pass
    return results


def _clear_proxy():
    for k in ['HTTP_PROXY', 'HTTPS_PROXY']:
        os.environ.pop(k, None)


def _proxy_env():
    """设置代理环境变量"""
    proxy = "http://127.0.0.1:7897"
    os.environ['HTTP_PROXY'] = proxy
    os.environ['HTTPS_PROXY'] = proxy


def get_cached_prices():
    """读缓存"""
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(data):
    """写缓存"""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def update_trends(prices):
    """更新趋势数据（每日收盘价历史）"""
    trends = {}
    if TREND_FILE.exists():
        trends = json.loads(TREND_FILE.read_text(encoding="utf-8"))
    
    today = datetime.now().strftime("%Y-%m-%d")
    for sym, info in prices.items():
        if sym not in trends:
            trends[sym] = {}
        trends[sym][today] = {
            "price": info["price"],
            "change_pct": info.get("change_pct", 0),
        }
    
    TREND_FILE.write_text(
        json.dumps(trends, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return trends


def get_trend(sym, trends=None, days=5):
    """判断趋势：涨/跌/横盘"""
    if trends is None:
        if TREND_FILE.exists():
            trends = json.loads(TREND_FILE.read_text(encoding="utf-8"))
        else:
            return "暂无数据"
    
    history = trends.get(sym, {})
    sorted_dates = sorted(history.keys())
    
    if len(sorted_dates) < 2:
        return "数据不足"
    
    # 最近N天
    recent = sorted_dates[-days:]
    if len(recent) < 2:
        return "数据不足"
    
    first = history[recent[0]]["price"]
    last = history[recent[-1]]["price"]
    change = (last - first) / first * 100
    
    if change > 3:
        return f"📈 上涨趋势 ({change:+.1f}%/{days}天)"
    elif change < -3:
        return f"📉 下跌趋势 ({change:+.1f}%/{days}天)"
    else:
        return f"➡️ 横盘震荡 ({change:+.1f}%/{days}天)"


def refresh_all():
    """一键刷新：提取简报标的 → 拉取 → 缓存 → 趋势"""
    print("📊 读取近期简报提及的标的...")
    import importlib
    bp = importlib.import_module('brief_parser')
    symbols = bp.get_tracking_symbols()
    print(f"  共 {len(symbols)} 个标的（默认+简报提取）")
    prices = fetch_prices(symbols)
    if prices:
        save_cache(prices)
        trends = update_trends(prices)
        print(f"✅ {len(prices)} 个标的已更新")
        for sym in ["^DJI", "^IXIC", "^GSPC", "NVDA", "159992"]:
            if sym in prices:
                p = prices[sym]
                trend = get_trend(sym, trends)
                print(f"  {sym}: {p['price']} ({p['change_pct']:+.2f}%) | {trend}")
    else:
        print("❌ 全部获取失败")
    
    # 读缓存保底
    cache = get_cached_prices()
    if cache and not prices:
        print(f"📂 使用缓存数据 ({len(cache)} 个标的)")
        for sym in ["^DJI", "^IXIC", "^GSPC"]:
            if sym in cache:
                p = cache[sym]
                print(f"  {sym}: {p['price']} ({p.get('change_pct', 0):+.2f}%)")


if __name__ == "__main__":
    refresh_all()
