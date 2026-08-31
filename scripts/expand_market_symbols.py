#!/usr/bin/env python3
"""Expand market symbols from sector themes and overseas abnormal movers.

The output is a conservative symbol list for market_data_sources.py. It keeps
BaoStock-friendly A-share codes separate from overseas tickers so batch jobs can
run sequentially and politely.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WATCHLIST_PATH = ROOT / "config" / "sector_watchlist.yaml"
OUT_DIR = ROOT / "data" / "tmp"

THEME_SYMBOLS: dict[str, dict[str, str]] = {
    "AI算力/光模块": {
        "中际旭创": "300308.SZ", "新易盛": "300502.SZ", "天孚通信": "300394.SZ",
        "源杰科技": "688498.SS", "光迅科技": "002281.SZ", "华工科技": "000988.SZ",
        "太辰光": "300570.SZ", "剑桥科技": "603083.SS", "博创科技": "300548.SZ",
        "仕佳光子": "688313.SS", "德科立": "688205.SS", "联特科技": "301205.SZ",
        "东田微": "301183.SZ", "腾景科技": "688195.SS", "光库科技": "300620.SZ",
        "铭普光磁": "002902.SZ", "永鼎股份": "600105.SS", "亨通光电": "600487.SS",
        "中天科技": "600522.SS", "长飞光纤": "601869.SS",
    },
    "半导体/国产算力": {
        "中芯国际": "688981.SS", "寒武纪": "688256.SS", "海光信息": "688041.SS",
        "华海清科": "688120.SS", "北方华创": "002371.SZ", "中微公司": "688012.SS",
        "拓荆科技": "688072.SS", "芯源微": "688037.SS", "盛美上海": "688082.SS",
        "沪硅产业": "688126.SS", "立昂微": "605358.SS", "TCL中环": "002129.SZ",
        "韦尔股份": "603501.SS", "兆易创新": "603986.SS", "澜起科技": "688008.SS",
        "龙芯中科": "688047.SS", "华虹公司": "688347.SS", "通富微电": "002156.SZ",
        "长电科技": "600584.SS", "芯原股份": "688521.SS",
    },
    "PCB/服务器链": {
        "沪电股份": "002463.SZ", "胜宏科技": "300476.SZ", "深南电路": "002916.SZ",
        "生益科技": "600183.SS", "景旺电子": "603228.SS", "鹏鼎控股": "002938.SZ",
        "世运电路": "603920.SS", "崇达技术": "002815.SZ", "兴森科技": "002436.SZ",
        "宏和科技": "603256.SS", "金安国纪": "002636.SZ", "方正科技": "600601.SS",
    },
    "机器人/特斯拉链": {
        "三花智控": "002050.SZ", "拓普集团": "601689.SS", "鸣志电器": "603728.SS",
        "绿的谐波": "688017.SS", "中大力德": "002896.SZ", "双环传动": "002472.SZ",
        "柯力传感": "603662.SS", "五洲新春": "603667.SS", "北特科技": "603009.SS",
        "鸣志电器": "603728.SS", "江苏雷利": "300660.SZ", "步科股份": "688160.SS",
        "埃斯顿": "002747.SZ", "汇川技术": "300124.SZ", "机器人": "300024.SZ",
        "禾川科技": "688320.SS", "奥比中光": "688322.SS", "汉宇集团": "300403.SZ",
    },
    "创新药/CXO": {
        "恒瑞医药": "600276.SS", "百济神州": "688235.SS", "药明康德": "603259.SS",
        "荣昌生物": "688331.SS", "君实生物": "688180.SS", "科伦药业": "002422.SZ",
        "迈威生物": "688062.SS", "康龙化成": "300759.SZ", "泰格医药": "300347.SZ",
        "昭衍新药": "603127.SS", "凯莱英": "002821.SZ", "博腾股份": "300363.SZ",
        "贝达药业": "300558.SZ", "复星医药": "600196.SS", "信立泰": "002294.SZ",
    },
    "大金融/指数": {
        "东方财富": "300059.SZ", "中信证券": "600030.SS", "招商银行": "600036.SS",
        "中国平安": "601318.SS", "同花顺": "300033.SZ", "指南针": "300803.SZ",
        "天风证券": "601162.SS", "国盛金控": "002670.SZ", "太平洋": "601099.SS",
        "工商银行": "601398.SS", "农业银行": "601288.SS", "宁波银行": "002142.SZ",
    },
    "黄金有色/资源": {
        "紫金矿业": "601899.SS", "山东黄金": "600547.SS", "洛阳钼业": "603993.SS",
        "中金黄金": "600489.SS", "赤峰黄金": "600988.SS", "西部黄金": "601069.SS",
        "江西铜业": "600362.SS", "铜陵有色": "000630.SZ", "云南铜业": "000878.SZ",
        "中国铝业": "601600.SS", "天齐锂业": "002466.SZ", "赣锋锂业": "002460.SZ",
    },
}

OVERSEAS_TO_A: dict[str, dict[str, str]] = {
    "NVDA": {**THEME_SYMBOLS["AI算力/光模块"], **THEME_SYMBOLS["半导体/国产算力"], **THEME_SYMBOLS["PCB/服务器链"]},
    "AMD": {**THEME_SYMBOLS["半导体/国产算力"], **THEME_SYMBOLS["PCB/服务器链"]},
    "AVGO": {**THEME_SYMBOLS["AI算力/光模块"], **THEME_SYMBOLS["PCB/服务器链"]},
    "MRVL": {**THEME_SYMBOLS["AI算力/光模块"], **THEME_SYMBOLS["PCB/服务器链"]},
    "SMCI": {**THEME_SYMBOLS["PCB/服务器链"], **THEME_SYMBOLS["AI算力/光模块"]},
    "TSLA": THEME_SYMBOLS["机器人/特斯拉链"],
    "AAPL": {"立讯精密": "002475.SZ", "歌尔股份": "002241.SZ", "蓝思科技": "300433.SZ", "领益智造": "002600.SZ", "鹏鼎控股": "002938.SZ"},
    "MSFT": {**THEME_SYMBOLS["AI算力/光模块"], **THEME_SYMBOLS["半导体/国产算力"]},
    "GOOGL": {**THEME_SYMBOLS["AI算力/光模块"], **THEME_SYMBOLS["半导体/国产算力"]},
    "META": {**THEME_SYMBOLS["AI算力/光模块"], **THEME_SYMBOLS["半导体/国产算力"]},
}


def load_yaml_symbols() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        import yaml
        data = yaml.safe_load(WATCHLIST_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return out
    for cfg in data.values():
        if not isinstance(cfg, dict):
            continue
        for key in ["market_proxy", "benchmark"]:
            val = cfg.get(key)
            if val:
                out[str(val)] = str(val)
        for val in cfg.get("etfs") or []:
            if val:
                out[str(val)] = str(val)
        codes = cfg.get("core_symbol_codes") or {}
        if isinstance(codes, dict):
            for name, code in codes.items():
                if code:
                    out[str(name)] = str(code)
    return out


def load_existing_abnormal(path: Path, threshold: float) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    symbols = data.get("symbols") if isinstance(data, dict) else {}
    out = []
    if isinstance(symbols, dict):
        for sym, info in symbols.items():
            try:
                if not str(sym).endswith((".SS", ".SZ")) and abs(float(info.get("change_pct") or 0)) >= threshold:
                    out.append(str(sym))
            except Exception:
                continue
    return out


def build_symbols(include_all_themes: bool, abnormal_only: bool, threshold: float) -> dict[str, Any]:
    selected: dict[str, str] = load_yaml_symbols()
    overseas_abnormal = load_existing_abnormal(ROOT / "data" / "market_snapshot_10d.json", threshold)
    if include_all_themes or not abnormal_only:
        for theme in THEME_SYMBOLS.values():
            selected.update(theme)
    for ticker in overseas_abnormal:
        selected.update(OVERSEAS_TO_A.get(ticker, {}))
    symbols = sorted(set(selected.values()))
    return {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "a_share_count": len(symbols),
        "overseas_abnormal_threshold": threshold,
        "overseas_abnormal": overseas_abnormal,
        "symbols": symbols,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="生成大批量相关A股标的列表")
    ap.add_argument("--all-themes", action="store_true", help="纳入全部预置产业链股票")
    ap.add_argument("--abnormal-only", action="store_true", help="只根据海外异动映射，不纳入全部主题")
    ap.add_argument("--threshold", type=float, default=2.0, help="海外异动阈值，默认绝对涨跌2%%")
    ap.add_argument("--output", default=str(OUT_DIR / "expanded_a_symbols.json"))
    args = ap.parse_args()
    data = build_symbols(include_all_themes=args.all_themes, abnormal_only=args.abnormal_only, threshold=args.threshold)
    p = Path(args.output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved={p} count={data['a_share_count']} overseas_abnormal={','.join(data['overseas_abnormal'])}")
    print(",".join(data["symbols"]))


if __name__ == "__main__":
    main()
