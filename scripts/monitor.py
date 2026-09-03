#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor.py —— L2/L3 自治监控最小版（P1，蓝图 G）

定位（架构文档 v5 §3.2 / 01_gpt_plan §4.2）：
    L2 定时巡检（持仓/关注范围）→ 确定性触发规则
        ├─ 未命中 → 低成本摘要（stdout）
        └─ 命中   → 升级 L3：写 monitor_events/ 事件 job（供人工/Orchestrator 消费）
    L4 主动补缺（P0 命中 → 自动写 source=monitor 补缺 job 进 orchestrator 队列，
       由 drain 调度归因研究；幂等防重复，P1/P2 事件仅落盘不自动补）

调用形态：
    python -m scripts.monitor --once            # 跑一轮 L2 巡检（默认，cron/launchd 用；命中 P0 → L4 补缺 job 入队）
    python -m scripts.monitor --simulate "518880.SS=-6.5"   # 注入模拟变动验证规则触发
    python -m scripts.monitor --hot             # P1-HOT 热度规则（现拉东财涨停池/概念板块，8s 超时失败降级）
    python -m scripts.monitor --once --simulate "518880.SS=-6.5" --jobs-dir <tmp>  # L4 补缺验证（隔离队列）
    python -m scripts.monitor --once --no-fill  # 命中 P0 仅落 L3 事件，不写补缺 job（调试用）

数据源（L2 价格规则全部本地缓存，不主动拉网络；数据时效在摘要中标注）：
    - 持仓:    data/portfolio.json（holdings → market_code）
    - 行情:    data/market_cache.json（{symbol: {price, change_pct, updated}}）优先
               回退 data/price_trends.json（{symbol: {date: {price, change_pct}}} 取最新日）
    - P1-HOT 例外: 热度规则 --hot 现拉东财 push2 涨停池/概念板块（8s 超时 + trust_env=False，
               失败降级标注不触发；L2 默认巡检保持纯本地回归）
    - 合规:    事件只做“异动提示 + 触发规则 + 数据快照”，绝不生成买卖建议

规则集（最小版，对应 01_gpt_plan §6 子集）：
    P0-PRICE-01  持仓单日 |变动| ≥ 5%        → L3 事件（P0）+ L4 补缺 job（--hot 外默认开启）
    P2-CACHE-01  行情缓存超过 MAX_CACHE_HOURS  → 摘要降级提示（不入事件）
    P1-HOT-01  涨停家数 ≥ HOT_TC_ABS        → P1 L3 事件（暂代 20 日均值+2σ，历史积累后换统计口径）
    P1-HOT-02  连板最高高度 ≥ HOT_LBC_ABS   → P1 L3 事件（题材高度，启动风险关注）
    P1-HOT-03  概念板块涨幅与成交额同进前 HOT_BOARD_TOP_PCT% → P1 L3 事件（板块拥挤/扩散信号）
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

# ── L4 补缺联动（P0 → source=monitor job 入 orchestrator 队列）──
JOBS_DIR = DATA_DIR / "research_jobs"   # 与 orchestrator 同源（config_loader）
FILL_SOURCE = "monitor"                 # drain 认领白名单成员（orchestrator.CLAIM_SOURCES）
FILL_AGENT = "analyst"                  # 补缺归因研究走现役 research_agent
FILL_CATEGORY = "monitor_fill"
FILL_MAX_ATTEMPTS = 3

# ── P1-HOT 热度规则（--hot 现拉东财；绝对阈值暂代 20 日均值±2σ 统计口径）──
HOT_TC_ABS = 80.0          # P1-HOT-01 涨停家数阈值
HOT_LBC_ABS = 6            # P1-HOT-02 连板最高高度阈值
HOT_BOARD_TOP_PCT = 10.0   # P1-HOT-03 概念板块涨幅/成交额前 N%
EM_UA = "Mozilla/5.0"
EM_ZT_URL = ("https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989"
             "&dpt=wz.ztzt&Pageindex=0&pagesize=600&sort=fbt%3Aasc&date={date}")
EM_BOARD_URL = ("https://push2delay.eastmoney.com/api/qt/clist/get?pn={pn}&pz=100&po=1&np=1&fltt=2&invt=2"
                "&fid=f3&fs=m:90+t:3&fields=f3,f14,f20")  # push2 直域拒绝 requests TLS 指纹 → delay 备域（实测通）
EM_FETCH_TIMEOUT = 8


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


# ── L4 主动补缺（P0 命中 → source=monitor 补缺 job 入队）────────────────
def _fill_goal(event: dict) -> str:
    """补缺 job goal 模板：实体 + 异动方向/幅度 + 归因研究意图。"""
    ent = event.get("entity") or {}
    trg = event.get("trigger") or {}
    code = ent.get("code", "")
    name = ent.get("name", code)
    direction = trg.get("direction", "异动")
    val = trg.get("value")
    v = f"{abs(val):.1f}" if isinstance(val, (int, float)) else "?"
    return (f"[monitor补缺] {name}({code}) 单日{direction}{v}%"
            f"（{event.get('rule_id')}触发），归因分析及对当前持仓影响")


def submit_fill_jobs(events: list[dict], jobs_dir: Path | None = None) -> list[dict]:
    """L4 主动补缺：P0 事件 → source=monitor 补缺 job 入 orchestrator 队列。

    - 只处理 priority == P0 的事件（P1/P2 仅落盘事件，不自动补——见 P2 蓝图 D5）
    - 幂等：同 rule_id + market_code 已有 source=monitor 且 queued/running 的 job → 跳过
    - job schema 与 orchestrator.submit_job 同构但独立实现：orchestrator 顶层
      load_config 有副作用不宜 import（P2 坑 8 同精神）
    """
    jobs_dir = jobs_dir or JOBS_DIR
    jobs_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for ev in events:
        if ev.get("priority") != "P0":
            continue
        ent = ev.get("entity") or {}
        rule = ev.get("rule_id")
        mc = ent.get("market_code")
        dup = False
        for p in jobs_dir.glob("*.json"):
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if j.get("source") != FILL_SOURCE or j.get("status") not in ("queued", "running"):
                continue
            if j.get("rule_id") == rule and (j.get("_meta") or {}).get("market_code") == mc:
                dup = True
                break
        if dup:
            continue
        job = {
            "job_id": uuid.uuid4().hex,
            "status": "queued",
            "goal": _fill_goal(ev),
            "category": FILL_CATEGORY,
            "gate": {"origin": "monitor", "rule_id": rule, "event_id": ev.get("event_id")},
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "report_path": None,
            "error": None,
            # orchestrator 编排字段（drain 认领要求）
            "source": FILL_SOURCE,
            "attempts": 0,
            "max_attempts": FILL_MAX_ATTEMPTS,
            "next_retry_at": None,
            "agent_type": FILL_AGENT,
            # L4 溯源
            "rule_id": rule,
            "_meta": {"event_id": ev.get("event_id"), "market_code": mc,
                      "entity_code": ent.get("code"), "triggered_at": ev.get("triggered_at")},
        }
        tmp = jobs_dir / f".{job['job_id']}.tmp"
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(jobs_dir / f"{job['job_id']}.json")
        written.append(job)
    return written


# ── P1-HOT 热度规则（--hot，现拉东财，失败降级不触发）──────────
def _fetch_hot_snapshot(date: str | None = None) -> dict:
    """现拉东财涨停池 + 概念板块涨幅榜全量（trust_env=False 防代理劫持，8s 超时）。

    返回 {tc, max_lbc, boards:[{name, change_pct, amount}], fetched_at, trade_date}
    date: YYYYMMDD（默认今天）；失败抛异常（调用方降级）。
    """
    import requests
    date = date or datetime.now().strftime("%Y%m%d")
    s = requests.Session()
    s.trust_env = False          # 防 Clash/系统代理劫持（铁律：requests 必 trust_env=False）
    s.proxies = {"http": None, "https": None}
    s.headers["User-Agent"] = EM_UA
    # 涨停池
    r1 = s.get(EM_ZT_URL.format(date=date), timeout=EM_FETCH_TIMEOUT)
    d1 = r1.json().get("data") or {}
    tc = d1.get("tc") or 0
    pool = d1.get("pool") or []
    max_lbc = max((p.get("lbc") or 1) for p in pool) if pool else 0
    # 概念板块涨幅榜全量（pz=100 翻页至空）
    boards = []
    for pn in range(1, 7):
        r2 = s.get(EM_BOARD_URL.format(pn=pn), timeout=EM_FETCH_TIMEOUT)
        diff = (r2.json().get("data") or {}).get("diff") or []
        if not diff:
            break
        for x in diff:
            try:
                boards.append({"name": x.get("f14"), "change_pct": float(x.get("f3") or 0),
                               "amount": float(x.get("f20") or 0)})
            except (TypeError, ValueError):
                continue
        if len(diff) < 100:
            break
    return {"tc": tc, "max_lbc": max_lbc, "boards": boards,
            "fetched_at": _now(), "trade_date": d1.get("qdate") or date}


def _hot_event(rule_id: str, note: str, trigger: dict, snap: dict) -> dict:
    return {
        "event_id": uuid.uuid4().hex,
        "level": "L3",
        "rule_id": rule_id,
        "priority": "P1",
        "status": EVENT_STATUS_QUEUED,
        "triggered_at": _now(),
        "entity": {"market": "A股", "scope": "全市场热度"},
        "trigger": trigger,
        "snapshot": {"trade_date": snap.get("trade_date"), "tc": snap.get("tc"),
                     "max_lbc": snap.get("max_lbc"), "fetched_at": snap.get("fetched_at")},
        "note": note + "；仅情绪提示，不构成任何交易建议",
    }


def run_hot_check(fetch=None) -> dict:
    """P1-HOT 热度规则：现拉东财涨停池 + 概念板块，阈值命中 → P1 L3 事件。

    fetch: 可注入数据源（单测 mock）；None → 真实 _fetch_hot_snapshot。
    返回 {checked, events, degraded, generated_at}；数据源失败 → degraded 不触发。
    """
    result = {"checked": [], "events": [], "degraded": [], "generated_at": _now()}
    try:
        snap = (fetch or _fetch_hot_snapshot)()
    except Exception as exc:
        result["degraded"].append({"check": "P1-HOT", "reason": f"数据源不可用: {exc}"})
        return result
    tc = snap.get("tc") or 0
    max_lbc = snap.get("max_lbc") or 0
    boards = snap.get("boards") or []
    result["checked"].append({"metric": "涨停家数", "value": tc, "threshold": HOT_TC_ABS})
    result["checked"].append({"metric": "连板最高", "value": max_lbc, "threshold": HOT_LBC_ABS})
    result["checked"].append({"metric": "概念板块样本", "value": len(boards), "threshold": "-"})
    # P1-HOT-01 涨停家数过热
    if tc >= HOT_TC_ABS:
        result["events"].append(_hot_event(
            "P1-HOT-01", f"涨停家数 {tc} 家 ≥ {HOT_TC_ABS:g}（情绪过热；暂代 20 日均值+2σ 口径）",
            {"metric": "limitup_count", "value": tc, "threshold": HOT_TC_ABS}, snap))
    # P1-HOT-02 连板高度过高
    if max_lbc >= HOT_LBC_ABS:
        result["events"].append(_hot_event(
            "P1-HOT-02", f"连板最高 {max_lbc} 板 ≥ {HOT_LBC_ABS} 板（题材高度过高）",
            {"metric": "max_lianban", "value": max_lbc, "threshold": HOT_LBC_ABS}, snap))
    # P1-HOT-03 板块拥挤：涨幅 top10% ∩ 成交额 top10%
    valid = [b for b in boards if b.get("change_pct") is not None and b.get("amount")]
    if valid:
        k = max(1, round(len(valid) * HOT_BOARD_TOP_PCT / 100))
        by_chg = sorted(valid, key=lambda b: b["change_pct"], reverse=True)[:k]
        by_amt = sorted(valid, key=lambda b: b["amount"], reverse=True)[:k]
        hot = [b for b in by_chg if b in by_amt]
        if hot:
            names = "、".join(b["name"] for b in hot[:3])
            result["events"].append(_hot_event(
                "P1-HOT-03", f"板块拥挤: 涨幅与成交额双前 {HOT_BOARD_TOP_PCT:g}% 交集 {names}",
                {"metric": "crowded_boards", "value": [b["name"] for b in hot[:5]],
                 "top_pct": HOT_BOARD_TOP_PCT}, snap))
    return result


def _render_hot(result: dict) -> str:
    lines = [f"P1-HOT 热度巡检 @ {result['generated_at']}"]
    for row in result["checked"]:
        lines.append(f"  {row['metric']}: {row.get('value')}（阈值 {row.get('threshold', '-')}）")
    if result["events"]:
        for ev in result["events"]:
            lines.append(f"  🚨 {ev['rule_id']}（{ev['priority']}）: {ev['note']}")
    else:
        lines.append("  未命中 P1-HOT 触发规则")
    for d in result["degraded"]:
        lines.append(f"  ⚠ {d.get('check')} 降级: {d.get('reason')}")
    return "\n".join(lines)


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
    ap = argparse.ArgumentParser(description="L2/L3 自治监控 + L4 补缺联动 + P1-HOT 热度规则")
    ap.add_argument("--once", action="store_true",
                    help="跑一轮 L2 巡检（默认行为，cron 用；命中 P0 自动写 L4 补缺 job）")
    ap.add_argument("--simulate", default=None, metavar="CODE=CHANGE[,CODE=CHANGE...]",
                    help="注入模拟变动验证规则触发，如 518880.SS=-6.5,601668.SS=5.2")
    ap.add_argument("--threshold", type=float, default=PRICE_THRESHOLD_PCT,
                    help=f"P0-PRICE-01 阈值%%（默认 {PRICE_THRESHOLD_PCT}）")
    ap.add_argument("--hot", action="store_true",
                    help="跑 P1-HOT 热度规则（现拉东财涨停池/概念板块，8s 超时，失败降级不触发）")
    ap.add_argument("--jobs-dir", default=None,
                    help="L4 补缺 job 目录覆盖（默认 DATA_DIR/research_jobs；验证/测试用隔离目录）")
    ap.add_argument("--no-fill", action="store_true",
                    help="命中 P0 只落 L3 事件，不写补缺 job（调试用）")
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

    if args.hot:
        # P1-HOT：独立开关（需现拉网络；默认 --once 保持纯本地回归）
        h = run_hot_check()
        print(_render_hot(h))
        if h["events"]:
            for s in _save_events(h["events"]):
                print(f"  📄 {s}")
        return 0

    jobs_dir = Path(args.jobs_dir) if args.jobs_dir else JOBS_DIR
    result = run_l2_check(simulate=simulate or None, threshold_pct=args.threshold)
    print(_render(result))
    if result["events"]:
        saved = _save_events(result["events"])
        for s in saved:
            print(f"  📄 {s}")
        if not args.no_fill:
            filled = submit_fill_jobs(result["events"], jobs_dir=jobs_dir)
            if filled:
                for j in filled:
                    print(f"  🔄 L4 补缺 job 入队: {j['job_id'][:8]}  goal={j['goal'][:44]}…")
            else:
                print("  🔄 L4 补缺: 同规则同标的已有进行中 job（幂等跳过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
