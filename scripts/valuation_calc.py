#!/usr/bin/env python3
"""绝对估值确定性计算（71号方案 #9）。

设计约束（红线）：
- 零 LLM，纯确定性计算（baostock 数据 + 分位查表）
- 不猜数据：闸门不达标 → level=数据不足；财报科目不可得 → 风险分栏 pending
- 不产生买卖建议：只输出水位档位 + 风险分栏 + 固定提示

口径说明（2026-09-01 实测校准）：
- baostock 免费版财报接口只提供衍生指标（无原始科目）：
  balance: currentRatio/quickRatio/cashRatio/YOYLiability/liabilityToAsset/assetToEquity
  profit:  roeAvg/npMargin/gpMargin/netProfit/epsTTM/MBRevenue
  cashflow: CAToAsset/NCAToAsset/tangibleAssetToAsset/ebitToInterest/CFOToOR/CFOToNP/CFOToGr
- 因此：净有息债务→杠杆（资产负债率+负债同比）；减值暴露→资产结构（有形资产占比），
  原始减值科目（商誉/应收/存货）不可得 → 标 pending 不猜。
"""
from __future__ import annotations

import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

try:
    import baostock as bs
except ImportError:  # 测试环境可无 baostock
    bs = None


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PE_PB_MIN_SAMPLES = 250        # 有效样本数门槛（约1年交易日）
PE_PB_MIN_SPAN_DAYS = 730      # 覆盖跨度门槛（2年）
PE_PB_MAX_AGE_DAYS = 30        # 最近观测时效门槛
MIN_QUARTERS_BACK = 6          # 财报回退查询季度数

DATA_STATUS_VALUES = {"available", "pending", "insufficient", "na"}

# 风险分栏判读阈值（确定性查表，行业阈值后续按卡校准）
LEVERAGE_HIGH = 0.70           # 资产负债率 >70% 高杠杆
LEVERAGE_LOW = 0.30            # <30% 低杠杆
CFO_NP_HIGH = 1.0              # 经营CF/净利 >1 含金量高
CFO_NP_LOW = 0.5               # <0.5 低
TANGIBLE_HIGH = 0.70           # 有形资产占比 >70% 重资产
TANGIBLE_LOW = 0.40            # <40% 轻资产

NOTE_FIXED = (
    "⚠️ 估值≠安全边际：便宜可能含价值陷阱（如 0.5x PB 假低估），"
    "须结合质量因子与资料充分度综合判断，本卡不构成买卖建议。"
)

FORBIDDEN_PHRASES = ("值得买", "可以买", "买入", "低估可入", "建议买入")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _to_bs_code(symbol: str) -> str:
    """601899.SS → sh.601899；159992.SZ → sz.159992。"""
    code, _, mkt = symbol.partition(".")
    if mkt.upper() in ("SS", "SH"):
        return f"sh.{code}"
    return f"sz.{code}"


def _parse_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _as_of(value: str | None = None) -> date:
    return _parse_date(value) or date.today()


def _percentile_rank(values: list[float], current: float) -> float | None:
    """当前值在历史序列中的经验百分位（0-100），确定性。

    口径：sorted 序列中 <= current 的占比。None 条件：空序列或 current 缺失。
    """
    if not values or current is None:
        return None
    n = len(values)
    if n == 0:
        return None
    le_count = sum(1 for v in values if v <= current)
    return round(le_count / n * 100, 1)


# ---------------------------------------------------------------------------
# 估值序列（PE/PB 分位）
# ---------------------------------------------------------------------------

def _bs_login() -> bool:
    if bs is None:
        return False
    try:
        lg = bs.login()
        return str(lg.error_code) == "0"
    except Exception:
        return False


def _bs_logout() -> None:
    if bs is not None:
        try:
            bs.logout()
        except Exception:
            pass


def fetch_pe_pb_series(symbol: str, start_date: date, end_date: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """拉取 PE/PB 日频序列并清洗。

    清洗规则（71号方案 §6.1 步骤1）：
    - PE<=0（亏损）或 PB<=0 或 NaN/None → 剔除，不进分位
    - 按交易日去重（重复日期只留一条）
    返回 (清洗后序列, 统计信息)。
    序列元素: {date, pe, pb}；统计: {fetched, valid, dropped, span_days, last_date}。
    """
    stats: dict[str, Any] = {"fetched": 0, "valid": 0, "dropped": 0, "span_days": 0, "last_date": None, "error": None}
    if bs is None:
        stats["error"] = "baostock 未安装"
        return [], stats
    ok = _bs_login()
    if not ok:
        stats["error"] = "baostock 登录失败"
        return [], stats
    try:
        rs = bs.query_history_k_data_plus(
            _to_bs_code(symbol),
            "date,peTTM,pbMRQ",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            frequency="d",
        )
        raw: list[tuple[str, float, float]] = []
        seen: set[str] = set()
        while (rs.error_code == "0") and rs.next():
            row = rs.get_row_data()
            if len(row) < 3:
                continue
            d, pe_s, pb_s = row[0], row[1], row[2]
            stats["fetched"] += 1  # 接口原始行数（含重复/脏）
            if d in seen:
                stats["dropped"] += 1  # 重复日期去重
                continue
            seen.add(d)
            try:
                pe = float(pe_s)
                pb = float(pb_s)
            except (TypeError, ValueError):
                stats["dropped"] += 1
                continue
            # NaN/负值/无效剔除（亏损公司 PE<=0 不进分位；NaN 不进分位）
            if math.isnan(pe) or math.isnan(pb) or pe <= 0 or pb <= 0:
                stats["dropped"] += 1
                continue
            raw.append((d, pe, pb))
        raw.sort(key=lambda x: x[0])
        if raw:
            stats["span_days"] = (date.fromisoformat(raw[-1][0]) - date.fromisoformat(raw[0][0])).days
            stats["last_date"] = raw[-1][0]
        stats["valid"] = len(raw)
        series = [{"date": d, "pe": pe, "pb": pb} for d, pe, pb in raw]
        return series, stats
    except Exception as exc:  # 网络/接口异常 → 不猜，标 pending
        stats["error"] = str(exc)
        return [], stats
    finally:
        _bs_logout()


def assess_gate(series: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    """数据充分度闸门（71号方案 §6.1 步骤2）。

    门槛：PE/PB 各 >=250 条、跨度 >=2年、最近观测 <=30天前、交集 >=250。
    """
    pes = [r["pe"] for r in series]
    pbs = [r["pb"] for r in series]
    both = [r for r in series if r.get("pe") is not None and r.get("pb") is not None]
    last_date = _parse_date(series[-1]["date"]) if series else None
    span = (last_date - _parse_date(series[0]["date"])).days if series and last_date and _parse_date(series[0]["date"]) else 0
    age = (as_of - last_date).days if last_date else None
    checks = {
        "pe_samples": len(pes),
        "pb_samples": len(pbs),
        "intersection": len(both),
        "span_days": span,
        "last_date": series[-1]["date"] if series else None,
        "age_days": age,
    }
    passed = (
        len(pes) >= PE_PB_MIN_SAMPLES
        and len(pbs) >= PE_PB_MIN_SAMPLES
        and span >= PE_PB_MIN_SPAN_DAYS
        and age is not None
        and age <= PE_PB_MAX_AGE_DAYS
        and len(both) >= PE_PB_MIN_SAMPLES
    )
    checks["passed"] = bool(passed)
    return checks


def _valuation_level(pe_rank: float | None, pb_rank: float | None) -> str:
    """分档查表（71号方案 §6.1 步骤3）。

    PE 分位 <=25 且 PB 分位 <=25 → 一眼便宜；任一 >75 → 未达门槛；其余 → 临界。
    任一为 None 不应调用本函数（闸门已保证），但兜底返回 数据不足。
    """
    if pe_rank is None or pb_rank is None:
        return "数据不足"
    if pe_rank <= 25 and pb_rank <= 25:
        return "一眼便宜"
    if pe_rank > 75 or pb_rank > 75:
        return "未达门槛"
    return "临界"


# ---------------------------------------------------------------------------
# 财报（衍生指标，口径 2026-09-01 实测校准）
# ---------------------------------------------------------------------------

_QUARTERS = [(y, q) for y in (2026, 2025, 2024, 2023) for q in (4, 3, 2, 1)]
# 从最新报告期往前（调用处按 as_of 年份动态取，这里仅兜底顺序）

def _quarters_back(as_of: date) -> list[tuple[int, int]]:
    """返回 as_of 往前 MIN_QUARTERS_BACK 个报告期（含当期），最新在前。"""
    y, q = as_of.year, (as_of.month - 1) // 3 + 1
    out: list[tuple[int, int]] = []
    for _ in range(MIN_QUARTERS_BACK):
        out.append((y, q))
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    return out


def _fetch_quarter_fundamentals(symbol: str, year: int, quarter: int) -> dict[str, Any]:
    """拉单个报告期三表衍生指标，合并为 dict；任一接口失败返回 {}。"""
    code = _to_bs_code(symbol)
    try:
        rs_b = bs.query_balance_data(code=code, year=year, quarter=quarter)
        if rs_b.error_code != "0" or not rs_b.next():
            return {}
        b = dict(zip(rs_b.fields, rs_b.get_row_data()))
        rs_p = bs.query_profit_data(code=code, year=year, quarter=quarter)
        if rs_p.error_code != "0" or not rs_p.next():
            return {}
        p = dict(zip(rs_p.fields, rs_p.get_row_data()))
        rs_c = bs.query_cash_flow_data(code=code, year=year, quarter=quarter)
        if rs_c.error_code != "0" or not rs_c.next():
            return {}
        c = dict(zip(rs_c.fields, rs_c.get_row_data()))
        merged = dict(b)
        merged.update(p)
        merged.update(c)
        return merged
    except Exception:
        return {}


def _fnum(row: dict[str, Any], key: str) -> float | None:
    v = row.get(key)
    if v in (None, "", "--"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_latest_fundamentals(symbol: str, as_of: date) -> dict[str, Any]:
    """取 pubDate <= as_of 的最新一期合并财报（point-in-time，71号方案 §6.1 步骤4）。

    返回 {found, stat_date, pub_date, period, source, metrics:{...}}。
    拉不到 → {found: False}（调用方标 pending，不猜）。
    """
    periods = fetch_fundamentals_periods(symbol, as_of, n_periods=1)
    return periods[0] if periods else {"found": False, "error": "近6期无已披露财报"}


def fetch_fundamentals_periods(symbol: str, as_of: date, n_periods: int = 2) -> list[dict[str, Any]]:
    """返回最近 n 个已披露报告期（pubDate<=as_of，最新在前）的合并财报。

    每期 {found, stat_date, pub_date, period, source, metrics:{...}}。
    """
    if bs is None:
        return []
    ok = _bs_login()
    if not ok:
        return []
    try:
        out: list[dict[str, Any]] = []
        for year, quarter in _quarters_back(as_of):
            if len(out) >= n_periods:
                break
            row = _fetch_quarter_fundamentals(symbol, year, quarter)
            if not row:
                continue
            pub = _parse_date(row.get("pubDate"))
            if pub is None or pub > as_of:  # 未披露（未来公告日）→ 往前找
                continue
            stat = row.get("statDate") or f"{year}-{quarter * 3:02d}-01"
            metrics = {
                "liability_to_asset": _fnum(row, "liabilityToAsset"),      # 资产负债率
                "yoy_liability": _fnum(row, "YOYLiability"),               # 负债同比%
                "current_ratio": _fnum(row, "currentRatio"),                # 流动比率
                "cash_ratio": _fnum(row, "cashRatio"),                      # 现金比率
                "np_margin": _fnum(row, "npMargin"),                        # 净利率%
                "gp_margin": _fnum(row, "gpMargin"),                        # 毛利率%
                "net_profit": _fnum(row, "netProfit"),                      # 净利润
                "mb_revenue": _fnum(row, "MBRevenue"),                      # 主营收入
                "cfo_to_np": _fnum(row, "CFOToNP"),                         # 经营CF/净利
                "cfo_to_or": _fnum(row, "CFOToOR"),                         # 经营CF/营收
                "ebit_to_interest": _fnum(row, "ebitToInterest"),           # EBIT/利息
                "nca_to_asset": _fnum(row, "NCAToAsset"),                   # 非流动资产占比
                "tangible_to_asset": _fnum(row, "tangibleAssetToAsset"),    # 有形资产占比
            }
            out.append({
                "found": True,
                "stat_date": stat,
                "pub_date": str(pub),
                "period": f"{year}Q{quarter}",
                "source": "baostock",
                "metrics": metrics,
            })
        return out
    except Exception:
        return []
    finally:
        _bs_logout()


# ---------------------------------------------------------------------------
# 风险分栏
# ---------------------------------------------------------------------------

def _judge_leverage(value: float | None) -> str:
    if value is None:
        return "待补"
    if value > LEVERAGE_HIGH:
        return "高杠杆"
    if value < LEVERAGE_LOW:
        return "低杠杆"
    return "正常"


def _judge_cfo_np(value: float | None) -> str:
    if value is None:
        return "待补"
    if value > CFO_NP_HIGH:
        return "含金量高"
    if value < CFO_NP_LOW:
        return "含金量低"
    return "正常"


def _judge_tangible(value: float | None) -> str:
    if value is None:
        return "待补"
    if value > TANGIBLE_HIGH:
        return "重资产"
    if value < TANGIBLE_LOW:
        return "轻资产"
    return "正常"


def build_risk_columns(fund: dict[str, Any]) -> list[dict[str, Any]]:
    """风险分栏（估值≠安全边际）：杠杆 / 资产结构 / 盈利质量。

    每栏带 period/source/unit 口径；不可得 → value=None, judgement=待补（不猜）。
    """
    if not fund.get("found"):
        return [
            {"name": "杠杆（资产负债率）", "value": None, "judgement": "待补", "period": None, "source": "baostock", "unit": "%"},
            {"name": "资产结构（有形资产占比）", "value": None, "judgement": "待补", "period": None, "source": "baostock", "unit": "%"},
            {"name": "盈利质量（经营CF/净利）", "value": None, "judgement": "待补", "period": None, "source": "baostock", "unit": "倍"},
            {"name": "减值暴露（商誉/应收/存货）", "value": None, "judgement": "待补", "period": None, "source": "baostock 免费接口无减值科目", "unit": "-"},
        ]
    m = fund["metrics"]
    period = fund.get("period")
    src = fund.get("source")
    lev = m.get("liability_to_asset")
    tan = m.get("tangible_to_asset")
    cfo = m.get("cfo_to_np")
    return [
        {
            "name": "杠杆（资产负债率）",
            "value": round(lev * 100, 1) if lev is not None else None,
            "judgement": _judge_leverage(lev),
            "period": period,
            "source": src,
            "unit": "%",
        },
        {
            "name": "资产结构（有形资产占比）",
            "value": round(tan * 100, 1) if tan is not None else None,
            "judgement": _judge_tangible(tan),
            "period": period,
            "source": src,
            "unit": "%",
        },
        {
            "name": "盈利质量（经营CF/净利）",
            "value": round(cfo, 2) if cfo is not None else None,
            "judgement": _judge_cfo_np(cfo),
            "period": period,
            "source": src,
            "unit": "倍",
        },
        {
            "name": "减值暴露（商誉/应收/存货）",
            "value": None,
            "judgement": "待补",
            "period": period,
            "source": "baostock 免费接口无减值科目",
            "unit": "-",
        },
    ]


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def compute_valuation(symbol: str, as_of_date: str | None = None) -> dict[str, Any]:
    """计算估值水位（71号方案 #9 主入口，确定性）。

    返回 dict：
      {symbol, as_of_date, status(ok/insufficient/pending/na), level,
       pe_rank, pb_rank, pe_current, pb_current, samples, gate, risk_columns, note}
    红线：任何缺数 → status!=ok，不产生水位档位。
    """
    as_of = _as_of(as_of_date)
    start = as_of - timedelta(days=365 * 3 + 10)
    series, stats = fetch_pe_pb_series(symbol, start, as_of)
    if stats.get("error"):
        return {
            "symbol": symbol, "as_of_date": as_of.isoformat(), "status": "pending",
            "level": "数据不足", "pe_rank": None, "pb_rank": None, "pe_current": None,
            "pb_current": None, "samples": stats, "gate": None, "risk_columns": [],
            "note": f"估值数据不可得（{stats['error']}），待补。",
        }
    gate = assess_gate(series, as_of)
    result: dict[str, Any] = {
        "symbol": symbol, "as_of_date": as_of.isoformat(), "samples": stats, "gate": gate,
        "risk_columns": [], "note": NOTE_FIXED,
    }
    if not gate["passed"]:
        result.update({
            "status": "insufficient", "level": "数据不足",
            "pe_rank": None, "pb_rank": None, "pe_current": None, "pb_current": None,
            "note": "估值样本不足（PE/PB 有效样本/跨度/时效未达标），不计算水位，不猜数据。",
        })
        fund = fetch_latest_fundamentals(symbol, as_of)
        result["risk_columns"] = build_risk_columns(fund)
        return result
    current = series[-1]
    pes = [r["pe"] for r in series]
    pbs = [r["pb"] for r in series]
    pe_rank = _percentile_rank(pes, current["pe"])
    pb_rank = _percentile_rank(pbs, current["pb"])
    level = _valuation_level(pe_rank, pb_rank)
    fund = fetch_latest_fundamentals(symbol, as_of)
    result.update({
        "status": "ok",
        "level": level,
        "pe_rank": pe_rank,
        "pb_rank": pb_rank,
        "pe_current": round(current["pe"], 2),
        "pb_current": round(current["pb"], 2),
        "pe_date": current["date"],
        "risk_columns": build_risk_columns(fund),
    })
    return result


def render_valuation_block(valuation: dict[str, Any]) -> str:
    """渲染估值区块 Markdown（仅估值配置的卡调用；红线文案不可配置）。"""
    lines = ["### 估值水位（确定性计算 · 近3年分位）"]
    if valuation.get("status") != "ok":
        lines.append(f"**{valuation.get('level') or '数据不足'}**（{valuation.get('note') or ''}）")
        if valuation.get("samples"):
            s = valuation["samples"]
            lines.append(
                f"> 有效样本 {s.get('valid', 0)} / 剔除 {s.get('dropped', 0)}，"
                f"覆盖 {s.get('span_days', 0)} 天"
            )
        lines.append("")
        lines.append(NOTE_FIXED)
        return "\n".join(lines)
    lines.append(
        f"**{valuation['level']}**（PE 分位 p{valuation['pe_rank']} / PB 分位 p{valuation['pb_rank']}，"
        f"当前 PE {valuation['pe_current']} / PB {valuation['pb_current']}，样本 {valuation['samples'].get('valid', 0)} 条）"
    )
    lines.append("")
    lines.append("| 风险分栏（估值≠安全边际） | 数值 | 判读 | 报告期 | 来源 |")
    lines.append("|---|---|---|---|---|")
    for col in valuation.get("risk_columns") or []:
        val = col.get("value")
        val_text = f"{val}{col.get('unit')}" if val is not None else "—"
        lines.append(
            f"| {col['name']} | {val_text} | {col['judgement']} | {col.get('period') or '—'} | {col['source']} |"
        )
    lines.append("")
    lines.append(NOTE_FIXED)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="绝对估值确定性计算（71号方案#9）")
    parser.add_argument("--symbol", required=True, help="A股代码，如 601899.SS")
    parser.add_argument("--as-of-date", help="计算基准日，默认今天")
    args = parser.parse_args()
    result = compute_valuation(args.symbol, as_of_date=args.as_of_date)
    print(render_valuation_block(result))


if __name__ == "__main__":
    main()
