#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor.py —— L2/L3 自治监控最小版（P1，蓝图 G）

定位（架构文档 v5 §3.2 / 01_gpt_plan §4.2）：
    L2 定时巡检（持仓/关注范围）→ 确定性触发规则
        ├─ 未命中 → 低成本摘要（stdout）
        └─ 命中   → 升级 L3：写 monitor_events/ 事件 job（供人工/Orchestrator 消费）
    L4 主动补缺（补采证据）→ 本最小版仅留扩展位，不实现

调用形态：
    python -m scripts.monitor --once            # 跑一轮 L2 巡检（默认，cron/launchd 用）
    python -m scripts.monitor --simulate "518880.SS=-6.5"   # 注入模拟变动验证规则触发

数据源（全部本地缓存，不主动拉网络；数据时效在摘要中标注）：
    - 持仓:    data/portfolio.json（holdings → market_code）
    - 行情:    data/market_cache.json（{symbol: {price, change_pct, updated}}）优先
               回退 data/price_trends.json（{symbol: {date: {price, change_pct}}} 取最新日）
    - 合规:    事件只做“异动提示 + 触发规则 + 数据快照”，绝不生成买卖建议

规则集（最小版，对应 01_gpt_plan §6 子集）：
    P0-PRICE-01  持仓单日 |变动| ≥ 5%        → L3 事件（P0）
    P2-CACHE-01  行情缓存超过 MAX_CACHE_HOURS  → 摘要降级提示（不入事件）
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from config_loader import load_config, get_data_dir  # noqa: E402

CONFIG = load_config()
DATA_DIR = get_data_dir(CONFIG)
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
MARKET_CACHE_FILE = DATA_DIR / "market_cache.json"
PRICE_TRENDS_FILE = DATA_DIR / "price_trends.json"
EVENTS_DIR = DATA_DIR / "monitor_events"

MAX_CACHE_HOURS = 26          # 行情缓存超过此小时数 → P2-CACHE-01 降级提示（覆盖隔夜+开盘前）
PRICE_THRESHOLD_PCT = 5.0     # P0-PRICE-01: 持仓单日变动阈值（%）
EVENT_STATUS_QUEUED = "queued"


def _read_json(path: Path) -> dict | None:
    """读带 BOM 的 json（仓内 data 文件均为 utf-8-sig）。"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except Exception:
        return None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_holdings() -> list[dict]:
    """读持仓：返回 [{code, name, sector, market_code}]（market_code 缺失的跳过价格规则）。"""
    p = _read_json(PORTFOLIO_FILE)
    holdings_raw = (p or {}).get("holdings") or {}
    out = []
    for code, h in holdings_raw.items():
        out.append({
            "code": code,
            "name": h.get("name", code),
            "sector": h.get("sector", ""),
            "market_code": (h.get("market_code") or "").strip(),
            "shares": h.get("shares"),
        })
    return out


def _latest_quote(market_code: str) -> dict | None:
    """从缓存取最新报价：market_cache 优先（含 updated），回退 price_trends 最新日。

    返回 {price, change_pct, updated, source} 或 None。
    """
    cache = _read_json(MARKET_CACHE_FILE) or {}
    if market_code in cache:
        q = cache[market_code]
        return {
            "price": q.get("price"),
            "change_pct": q.get("change_pct"),
            "updated": q.get("updated", ""),
            "source": "market_cache",
        }
    trends = _read_json(PRICE_TRENDS_FILE) or {}
    if market_code in trends:
        days = trends[market_code]
        if days:
            last_date = sorted(days.keys())[-1]
            last = days[last_date]
            return {
                "price": last.get("price"),
                "change_pct": last.get("change_pct"),
                "updated": last_date,
                "source": "price_trends",
            }
    return None


def _cache_age_hours(quote: dict | None) -> float | None:
    """报价数据时效（小时）；无法解析返回 None。"""
    if not quote or not quote.get("updated"):
        return None
    u = str(quote["updated"])
    # price_trends 只有日期（YYYY-MM-DD）→ 视为当日 15:00 收盘
    if len(u) == 10:
        try:
            dt = datetime.strptime(u, "%Y-%m-%d").replace(hour=15, minute=0)
        except ValueError:
            return None
    else:
        try:
            dt = datetime.fromisoformat(u)
        except ValueError:
            return None
    return (datetime.now() - dt).total_seconds() / 3600.0


# ── L2 巡检 ────────────────────────────────────────────────
def run_l2_check(simulate: dict[str, float] | None = None,
                 threshold_pct: float = PRICE_THRESHOLD_PCT) -> dict:
    """跑一轮 L2 巡检：持仓 + 缓存行情 → 确定性规则。

    simulate: {market_code: change_pct} 注入模拟变动（验证规则触发，不读真实缓存价）。
    threshold_pct: P0-PRICE-01 单日变动阈值（%）。
    返回 {"checked": [...], "events": [event_job...], "degraded": [...], "generated_at"}
    """
    holdings = _load_holdings()
    result = {"checked": [], "events": [], "degraded": [], "generated_at": _now()}

    for h in holdings:
        code = h["market_code"]
        row = {"code": h["code"], "name": h["name"], "market_code": code or "(无代码)"}

        if not code:
            row["note"] = "无 market_code（场外/联接），跳过价格规则"
            result["checked"].append(row)
            continue

        if simulate and code in simulate:
            # 模拟注入：不读缓存，直接构造报价
            quote = {
                "price": None,
                "change_pct": simulate[code],
                "updated": _now(),
                "source": "simulate",
            }
        else:
            quote = _latest_quote(code)
            if quote is None:
                row["note"] = "缓存无该标的行情（未覆盖），跳过价格规则"
                result["checked"].append(row)
                continue

        age_h = _cache_age_hours(quote)
        change = quote.get("change_pct")
        row.update({
            "price": quote.get("price"),
            "change_pct": change,
            "quote_updated": quote.get("updated"),
            "quote_source": quote.get("source"),
            "cache_age_hours": round(age_h, 1) if age_h is not None else None,
        })

        # P0-PRICE-01: 持仓单日 |变动| ≥ 阈值 → L3 事件
        if isinstance(change, (int, float)) and abs(change) >= threshold_pct:
            event = {
                "event_id": uuid.uuid4().hex,
                "level": "L3",
                "rule_id": "P0-PRICE-01",
                "priority": "P0",
                "status": EVENT_STATUS_QUEUED,
                "triggered_at": _now(),
                "entity": {"code": h["code"], "name": h["name"], "market_code": code},
                "trigger": {
                    "metric": "change_pct",
                    "value": change,
                    "threshold": threshold_pct,
                    "direction": "涨" if change > 0 else "跌",
                },
                "snapshot": {"price": quote.get("price"), "quote_source": quote.get("source"),
                             "quote_updated": quote.get("updated")},
                "note": "持仓异动提示（规则触发），需人工复核；不构成任何交易建议",
            }
            result["events"].append(event)
            row["event"] = event["event_id"][:8]
        else:
            # P2-CACHE-01: 缓存超期 → 降级提示（摘要标注，不入事件）
            if age_h is not None and age_h > MAX_CACHE_HOURS:
                result["degraded"].append({"code": h["code"], "name": h["name"],
                                           "cache_age_hours": round(age_h, 1)})
                row["note"] = f"行情缓存 {age_h:.0f}h 超期（> {MAX_CACHE_HOURS}h），数据仅供参考"
            else:
                row["note"] = "无异常"
        result["checked"].append(row)

    return result


def _save_events(events: list[dict]) -> list[str]:
    """L3 事件落盘 data/monitor_events/<ts>_<id8>.json。"""
    if not events:
        return []
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for ev in events:
        fname = EVENTS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{ev['event_id'][:8]}.json"
        fname.write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")
        saved.append(str(fname))
    return saved


def _render(result: dict) -> str:
    lines = [f"L2 巡检 @ {result['generated_at']}"]
    for row in result["checked"]:
        tail = []
        if row.get("price") is not None:
            tail.append(f"价 {row['price']}")
        if row.get("change_pct") is not None:
            cp = row["change_pct"]
            tail.append(f"变动 {cp:+.2f}%")
        if row.get("quote_source"):
            tail.append(f"[{row['quote_source']}]")
        if row.get("event"):
            tail.append(f"→ L3事件 {row['event']}")
        note = row.get("note", "")
        # 无异常/超期/跳过已在 note 中表达，不用重复挂 tail
        lines.append(f"  [{row['code']}] {row['name']:<12} " + " ".join(tail))
        if note:
            lines.append(f"      {note}")
    if result["degraded"]:
        lines.append("  ⚠ P2-CACHE-01 缓存超期: " + ", ".join(f"{d['name']}({d['cache_age_hours']}h)" for d in result["degraded"]))
    if result["events"]:
        lines.append(f"  🚨 命中 {len(result['events'])} 条 P0 规则 → L3 事件已落盘")
    else:
        lines.append("  未命中 P0 触发规则")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="L2/L3 自治监控最小版")
    ap.add_argument("--once", action="store_true", help="跑一轮 L2 巡检（默认行为，cron 用）")
    ap.add_argument("--simulate", default=None, metavar="CODE=CHANGE[,CODE=CHANGE...]",
                    help="注入模拟变动验证规则触发，如 518880.SS=-6.5,601668.SS=5.2")
    ap.add_argument("--threshold", type=float, default=PRICE_THRESHOLD_PCT,
                    help=f"P0-PRICE-01 阈值%%（默认 {PRICE_THRESHOLD_PCT}）")
    args = ap.parse_args()

    simulate = {}
    if args.simulate:
        for pair in args.simulate.split(","):
            if "=" not in pair:
                continue
            code, _, val = pair.partition("=")
            try:
                simulate[code.strip()] = float(val)
            except ValueError:
                pass

    result = run_l2_check(simulate=simulate or None, threshold_pct=args.threshold)
    print(_render(result))
    if result["events"]:
        saved = _save_events(result["events"])
        for s in saved:
            print(f"  📄 {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
