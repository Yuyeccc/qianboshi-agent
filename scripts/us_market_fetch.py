#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""us_market_fetch.py —— 美股夜盘采集器（审验-自补 ⑦，新浪 hq.sinajs.cn 实时快照）

定位：22:00 日报生成时刻（美股盘中 EDT 10:00 夏令时）把美股夜盘快照刷入
data/market/us_cache.json——独立于 A 股 market_cache.json（防币种/时区混淆）。

清单：tracking_pool.us_indexes（^DJI/^IXIC/^GSPC）+ 内置 ^VIX（pool 无此键，
int_vix/gb_vix 新浪返回空前科，必须 znb_VIX）+ tracking_pool.us_stocks。
持仓现 3 仓全 A 股：_portfolio_us_codes() 留接口（过滤非纯数字 code），未来加美股仓自动生效。

数据源：https://hq.sinajs.cn/list=<code>,...  单请求全量
  - 头：Referer: https://finance.sina.com.cn + UA（实测无需特殊端口）
  - requests trust_env=False（防本机 Clash 7897 代理劫持）；8s 超时
  - 响应 GBK 编码；行格式 var hq_str_<sina_code>="...";

解析字段（2026-09-05 实测定稿，gb_ 与 int_ 字段顺序相反勿混）：
  int_/znb_ 指数：名称,现价,涨跌额,涨跌幅%                        （znb_ 前 4 字段同构）
  gb_ 股票：     名称,现价,涨跌幅%,报价时间,涨跌额,...,[28]昨收
  空值/无数据（前科 int_vix/gb_vix）→ 该键 missing

降级链（本刀两级，source_mode 强制标注）：
  live（新浪实时/最近快照）→ stale（旧 us_cache 同键快照，_stale_from 记原时戳）
  → missing（price=None，_meta.failures 记录，不伪装实时）

session 标注（零依赖自算 DST 的美东纯函数，不引 tzdata）：
  3月第2周日 02:00 ~ 11月第1周日 02:00 = EDT(UTC-4)，否则 EST(UTC-5)
  → 盘中 9:30-16:00 / 盘前 4:00-9:30 / 盘后 16:00-20:00 / 休市（周末/其余）
  注：冬令时北京 22:00 = 美东 9:00 盘前（非盘中），session_note 如实标注

用法:
    C:/Python314/python.exe scripts/us_market_fetch.py [--dry-run] [--indexes|--pool] [--out <path>]
    # 默认全量（指数+VIX+股票池）；--dry-run 只显示不写盘；exit 0=链路通

产物：data/market/us_cache.json（不入 git，同 market_cache.json 动态行情缓存先例）
     {<yahoo_symbol>: {name, price, change_pct, updated, source_mode, session_note,
                       quote_time?, prev_close?, _stale_from?}, ..., "_meta": {...}}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

PROJ = Path(__file__).resolve().parent.parent
DATA_DIR = PROJ / "data"
POOL_FILE = DATA_DIR / "tracking_pool.json"
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
US_CACHE_FILE = DATA_DIR / "market" / "us_cache.json"

SINA_URL = "https://hq.sinajs.cn/list={codes}"
SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
TIMEOUT_SECONDS = 8

# 指数显式映射（^VIX 必须 znb_VIX——int_vix/gb_vix 返回空前科；实测 2026-09-04/05）
INDEX_MAP = {
    "^DJI": "int_dji",
    "^IXIC": "int_nasdaq",
    "^GSPC": "int_sp500",
    "^VIX": "znb_VIX",
}
VIX_SYMBOL = "^VIX"
ROW_RE = re.compile(r'var hq_str_([^=]+)="([^"]*)";')


def sina_code(symbol: str) -> str | None:
    """雅虎/裸代码 → 新浪代码。指数查表；股票通用规则 gb_+小写（NVDA→gb_nvda）。"""
    if symbol in INDEX_MAP:
        return INDEX_MAP[symbol]
    if symbol.startswith("^"):
        return None  # 未知指数（如 ^HSI 非美股）
    if symbol.isalnum() and symbol.isupper():
        return "gb_" + symbol.lower()
    return None


def load_pool_us() -> tuple[list[str], list[str]]:
    """tracking_pool → (us_indexes 代码, us_stocks 代码)。文件缺失/坏 → 空清单。"""
    try:
        pool = json.loads(POOL_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return [], []
    idx = [k for k in (pool.get("us_indexes") or {}) if k.startswith("^")]
    stk = list((pool.get("us_stocks") or {}).keys())
    return idx, stk


def _portfolio_us_codes() -> list[str]:
    """未来美股持仓接口：portfolio.holdings 中非纯数字 code 视为美股仓（现全 A 股 → []）。"""
    try:
        pf = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return [c for c in (pf.get("holdings") or {}) if not c.isdigit()]


def build_listing() -> list[dict]:
    """目标清单：{symbol, name?, kind}。指数（pool + 内置 ^VIX 去重）→ 股票池 → 持仓接口。"""
    idx, stk = load_pool_us()
    symbols = []
    seen = set()
    for s in [*idx, VIX_SYMBOL]:  # 指数：pool 3 + 内置 VIX
        if s not in seen and s.startswith("^") and sina_code(s):
            seen.add(s)
            symbols.append({"symbol": s, "name": s, "kind": "index"})
    for s in stk:
        if s not in seen and sina_code(s):
            seen.add(s)
            symbols.append({"symbol": s, "name": s, "kind": "stock"})
    for s in _portfolio_us_codes():
        if s not in seen and sina_code(s):
            seen.add(s)
            symbols.append({"symbol": s, "name": s, "kind": "holding"})
    return symbols


# ── 解析（实测样本定稿；gb_ 与 int_ 字段顺序相反）─────────────
def parse_int_fields(fields: list[str]) -> dict | None:
    """int_/znb_：名称,现价,涨跌额,涨跌幅%"""
    if len(fields) < 4 or not fields[1]:
        return None
    try:
        price = float(fields[1])
        change_pct = float(fields[3]) if fields[3] else 0.0
    except ValueError:
        return None
    return {"name": fields[0], "price": price, "change_pct": change_pct,
            "quote_time": "", "prev_close": None}


def parse_gb_fields(fields: list[str]) -> dict | None:
    """gb_：名称,现价,涨跌幅%,报价时间,涨跌额,...,[28]昨收"""
    if len(fields) < 5 or not fields[1]:
        return None
    try:
        price = float(fields[1])
        change_pct = float(fields[2]) if fields[2] else 0.0
        # 昨收 = 串末字段（2026-09-05 五样本验证：NVDA 228.45/AMD 456.16/TSLA 376.365/QQQ 717.67/TSM 417.01）
        prev_close = float(fields[-1]) if len(fields) > 1 and fields[-1] else None
    except ValueError:
        return None
    return {"name": fields[0], "price": price, "change_pct": change_pct,
            "quote_time": fields[3] if len(fields) > 3 else "", "prev_close": prev_close}


def parse_line(line: str) -> tuple[str, dict | None] | None:
    """解析一行 `var hq_str_<code>="...";` → (sina_code, parsed|None)。None=非行/格式错。"""
    m = ROW_RE.match(line.strip())
    if not m:
        return None
    code, payload = m.group(1), m.group(2)
    if not payload:
        return code, None  # 新浪对该代码返回空（int_vix 前科）
    fields = payload.split(",")
    parsed = (parse_gb_fields(fields) if code.startswith("gb_")
              else parse_int_fields(fields))  # int_/znb_/其他同构
    return code, parsed


def fetch_rows(sina_codes: list[str]) -> dict[str, dict | None]:
    """请求新浪并解析全部行。网络失败抛 requests 异常由调用方降级；返回 {sina_code: parsed|None}。"""
    url = SINA_URL.format(codes=",".join(sina_codes))
    sess = requests.Session()
    sess.trust_env = False  # 防本机代理（Clash 7897）劫持——requests.get 不收此参，须走 Session
    resp = sess.get(url, headers=SINA_HEADERS, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    text = resp.content.decode("gbk", errors="replace")
    out: dict[str, dict | None] = {}
    for ln in text.splitlines():
        r = parse_line(ln)
        if r:
            out[r[0]] = r[1]
    return out


# ── 美东 session（零依赖 DST 自算）────────────────────────
def _second_sunday_march(year: int) -> datetime:
    """3月第2周日 美东本地 02:00 EST = UTC 07:00（aware，供与 UTC 入参比较）。"""
    d = datetime(year, 3, 8, 7, 0, tzinfo=timezone.utc)  # 3月第2周日 ≥ 8 日
    return d + timedelta(days=(6 - d.weekday()))


def _first_sunday_november(year: int) -> datetime:
    """11月第1周日 美东本地 02:00 EDT = UTC 06:00（aware）。"""
    d = datetime(year, 11, 1, 6, 0, tzinfo=timezone.utc)  # 11月第1周日 ≤ 7 日
    return d + timedelta(days=(6 - d.weekday()))


def us_eastern_session(dt_utc: datetime) -> str:
    """UTC datetime → 美东时段标注：盘中/盘前/盘后/休市。纯函数零依赖。"""
    y = dt_utc.year
    dst_start = _second_sunday_march(y)
    dst_end = _first_sunday_november(y)
    offset_h = -4 if dst_start <= dt_utc < dst_end else -5
    et = dt_utc + timedelta(hours=offset_h)
    if et.weekday() >= 5:
        return "休市"
    hm = et.hour * 60 + et.minute
    if 9 * 60 + 30 <= hm < 16 * 60:
        return "盘中"
    if 4 * 60 <= hm < 9 * 60 + 30:
        return "盘前"
    if 16 * 60 <= hm < 20 * 60:
        return "盘后"
    return "休市"


# ── 降级链与写盘 ────────────────────────────────────────
def _read_old_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def assemble_entries(rows: dict[str, dict | None], sina_to_symbol: dict[str, str],
                     old_cache: dict, now: datetime) -> tuple[dict, dict]:
    """rows（新浪结果）→ 主条目 dict + failures。降级：live → stale(旧缓存) → missing。"""
    entries: dict[str, dict] = {}
    failures: dict[str, str] = {}
    for scode, parsed in rows.items():
        symbol = sina_to_symbol.get(scode, scode)
        if parsed:
            entries[symbol] = {
                "name": parsed["name"],
                "price": parsed["price"],
                "change_pct": parsed["change_pct"],
                "updated": now.isoformat(timespec="seconds"),
                "source_mode": "live",
                "session_note": us_eastern_session(now),
            }
            if parsed["quote_time"]:
                entries[symbol]["quote_time"] = parsed["quote_time"]
            if parsed["prev_close"] is not None:
                entries[symbol]["prev_close"] = parsed["prev_close"]
        else:
            old = old_cache.get(symbol)
            if old and isinstance(old, dict) and old.get("price") is not None:
                entries[symbol] = dict(old)
                entries[symbol]["source_mode"] = "stale"
                entries[symbol]["_stale_from"] = old.get("updated", "?")
                entries[symbol]["rechecked_at"] = now.isoformat(timespec="seconds")
                failures[symbol] = "sina_empty_stale"
            else:
                entries[symbol] = {"name": symbol, "price": None,
                                   "change_pct": None, "updated": None,
                                   "source_mode": "missing",
                                   "session_note": us_eastern_session(now)}
                failures[symbol] = "sina_empty_no_cache"
    return entries, failures


def save_cache(data: dict, path: Path) -> None:
    """原子写盘（tmp+rename 防半写）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def run_fetch(*, dry_run: bool, only_indexes: bool, only_pool: bool,
              out_path: str | None = None, now: datetime | None = None) -> int:
    """主流程。now 可注入（测试/回放）；返回 exit code。"""
    now = now or datetime.now(timezone.utc).astimezone()
    listing = build_listing()
    if only_indexes:
        listing = [x for x in listing if x["kind"] == "index"]
    if only_pool:
        listing = [x for x in listing if x["kind"] in ("stock", "holding")]
    if not listing:
        print("[us_market_fetch] 清单为空（pool 无美股条目？）")
        return 0

    symbols = [x["symbol"] for x in listing]
    sina_to_symbol = {sina_code(s): s for s in symbols if sina_code(s)}
    sina_codes = list(sina_to_symbol)
    old_cache = _read_old_cache(Path(out_path) if out_path else US_CACHE_FILE)

    try:
        rows = fetch_rows(sina_codes)
    except requests.RequestException as e:
        # 网络失败：整体降级——旧缓存键标 stale，无旧值标 missing（不伪装实时）
        print(f"[us_market_fetch] 新浪请求失败: {e} → 整体降级 stale/missing")
        rows = {}
        for scode in sina_codes:
            rows[scode] = None

    entries, failures = assemble_entries(rows, sina_to_symbol, old_cache, now)
    session = us_eastern_session(now)
    meta = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "session": session,
        "source": "sina_hq_sinajs_cn",
        "failures": failures,
        "listing_count": len(listing),
    }
    data = {**entries, "_meta": meta}

    live_n = sum(1 for e in entries.values() if e.get("source_mode") == "live")
    stale_n = sum(1 for e in entries.values() if e.get("source_mode") == "stale")
    miss_n = sum(1 for e in entries.values() if e.get("source_mode") == "missing")

    if dry_run:
        print(f"[us_market_fetch] dry-run: 清单 {len(listing)} | live={live_n} stale={stale_n} "
              f"missing={miss_n} | session={session}")
        for s in symbols:
            e = entries.get(s)
            if not e:
                continue
            px = e.get("price")
            pct = e.get("change_pct")
            px_s = f"{px:,.2f}" if px is not None else "N/A"
            pct_s = f"{pct:+.2f}%" if pct is not None else "--"
            print(f"  {s:<10} {e.get('source_mode'):<7} {px_s:>12} {pct_s:>9}  {e.get('name','')}")
        return 0

    out = Path(out_path) if out_path else US_CACHE_FILE
    save_cache(data, out)
    print(f"[us_market_fetch] OK 写入 {out} | live={live_n} stale={stale_n} "
          f"missing={miss_n} | session={session} | failures={len(failures)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="美股夜盘采集器（新浪实时快照 → data/market/us_cache.json）")
    ap.add_argument("--dry-run", action="store_true", help="只显示不写盘")
    ap.add_argument("--indexes", action="store_true", help="只拉指数（含 ^VIX）")
    ap.add_argument("--pool", action="store_true", help="只拉股票池（+未来美股持仓）")
    ap.add_argument("--out", default=None, help="输出路径（默认 data/market/us_cache.json）")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    return run_fetch(dry_run=args.dry_run, only_indexes=args.indexes,
                     only_pool=args.pool, out_path=args.out)


if __name__ == "__main__":
    sys.exit(main())
