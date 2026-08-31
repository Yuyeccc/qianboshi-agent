#!/usr/bin/env python3
"""
从简报中提取标的代码，加入行情追踪列表
"""
import json, re, os
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path(__file__).parent.parent / "data"
BRIEFS_DIR = DATA_DIR / "briefs"
CACHE_FILE = DATA_DIR / "market_cache.json"
TRACKED_FILE = DATA_DIR / "auto_tracked.json"

# 默认跟踪列表
DEFAULT_SYMBOLS = [
    "000001.SS", "399001.SZ", "399006.SZ",
    "^DJI", "^IXIC", "^GSPC",
    "NVDA", "AMD", "AVGO", "MRVL", "SMCI", "TSLA", "AAPL", "MSFT", "GOOGL", "META",
    "159992.SZ",
    "300502.SZ", "300308.SZ", "300394.SZ",
    "600745.SS", "688981.SS", "688012.SS",
    "601899.SS", "600547.SS",
    "600519.SS",
    "512690.SS",  # 白酒ETF（决策台 BAIJIU 决策验证用）
    "512480.SS",  # 半导体ETF（决策台 TECH 代理，159813 折算跳变）
]


def save_brief(text):
    """保存简报到 data/briefs/ 目录"""
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{datetime.now().strftime('%Y-%m-%d')}.md"
    path = BRIEFS_DIR / fname
    path.write_text(text, encoding="utf-8")
    print(f"  💾 简报已保存: {path}", file=__import__('sys').stderr)
    return path


def get_latest_brief_path():
    """获取最近一期简报路径"""
    if not BRIEFS_DIR.exists():
        return None
    files = sorted(BRIEFS_DIR.glob("*.md"))
    if not files:
        return None
    return files[-1]


def extract_stock_codes(text):
    """从文本中提取股票代码"""
    codes = set()
    
    # A股代码：6位数字
    for m in re.finditer(r'\b(\d{6})\b', text):
        code = m.group(1)
        if code.startswith(('60', '68')):       # 沪市
            codes.add(f"{code}.SS")
        elif code.startswith(('00', '30', '15')):  # 深市
            codes.add(f"{code}.SZ")
        elif code.startswith('159'):            # 深市ETF（159xxx）
            codes.add(f"{code}.SZ")
        elif code.startswith('5'):              # 沪市ETF/LOF（510/511/512/513/515/516/517/518/560/561/562/563/588/589）
            codes.add(f"{code}.SS")
        elif code.startswith(('0', '1')):       # 其他ETF/指数
            codes.add(f"{code}.SZ")
    
    # 美股代码：2-5个大写字母（排除常见单词）
    us_tickers = set()
    for m in re.finditer(r'\b([A-Z]{2,5})\b', text):
        ticker = m.group(1)
        # 排除非股票单词
        if ticker in ('SS', 'SZ', 'DJI', 'IXIC', 'GSPC', 'USD', 'CPU', 'GPU', 'AI',
                       'PE', 'PB', 'ROE', 'EPS', 'IPO', 'CEO', 'CFO', 'FDA', 'API',
                       'RAG', 'ETF', 'PCB', 'MLCC', 'WIFI', 'HBM', 'CAGR', 'TMT',
                       'LD', 'LG', 'TV', 'OK', 'ID', 'PM', 'AM', 'PM', 'VS', 'ETC',
                       'USD', 'HKD', 'CNY', 'JPY', 'EUR', 'GBP'):
            continue
        us_tickers.add(ticker)
    
    codes.update(us_tickers)
    return codes


def extract_sectors(text):
    """提取板块关键词（中文字段）"""
    # 常用板块名 → 映射到对应ETF或代表性标的
    sector_map = {
        '半导体': '159813.SZ', '芯片': '159813.SZ',
        '光模块': '300502.SZ', '光通讯': '300502.SZ', 'CPO': '300502.SZ',
        '创新药': '159992.SZ', '医药': '159992.SZ',
        '机器人': '159770.SZ',
        'AI': 'NVDA', '人工智能': 'NVDA',
        '存储': '688981.SS', '存储芯片': '688981.SS',
        '黄金': '601899.SS', '有色': '601899.SS',
        'PCB': '600745.SS', '电子': '600745.SS',
        '新能源': '159806.SZ', '锂矿': '159806.SZ',
        '消费': '600519.SS', '白酒': '600519.SS',
        '证券': '512880.SS', '券商': '512880.SS',
        '军工': '512660.SS', '航天': '512660.SS',
        '云计算': '159890.SZ', '算力': 'NVDA',
        '低空经济': '159779.SZ', '飞行汽车': '159779.SZ',
        '银发经济': '159809.SZ', '养老': '159809.SZ',
        '恒生科技': '159740.SZ', '港股': '159740.SZ',
    }
    
    codes = set()
    for sector, etf in sector_map.items():
        if sector in text:
            codes.add(etf)
    
    return codes


def extract_from_brief(text=None):
    """从简报文本提取所有要跟踪的标的"""
    if text is None:
        path = get_latest_brief_path()
        if path:
            print(f"  📖 读取上一期简报: {path.name}", file=__import__('sys').stderr)
            text = path.read_text(encoding="utf-8")
        else:
            return set()
    
    codes = set()
    codes.update(extract_stock_codes(text))
    codes.update(extract_sectors(text))
    return codes


def get_tracking_symbols(text=None):
    """获取最终跟踪列表：默认 + 简报提取"""
    symbols = set(DEFAULT_SYMBOLS)
    
    # 从简报提取
    brief_codes = extract_from_brief(text)
    symbols.update(brief_codes)
    
    # 保存到文件以便后续使用
    TRACKED_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACKED_FILE.write_text(
        json.dumps(sorted(symbols), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    return sorted(symbols)


if __name__ == "__main__":
    # 测试
    test_text = "光模块龙头新易盛(300502)和中际旭创(300308)表现强势，NVDA涨了2%，创新药ETF(159992)横盘"
    codes = get_tracking_symbols(test_text)
    print(f"提取到 {len(codes)} 个标的: {codes[:10]}...")
