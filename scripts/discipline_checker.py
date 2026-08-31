#!/usr/bin/env python3
"""组合纪律检查器（830报告 #17 → #17v2，2026-08-31 P0 口径修正）。

三层纪律：主题仓位上限 + 单标的上限 + 组合成本回撤开关。
只做规则比对 → 输出违反清单，不输出任何调仓/买卖指令。

#17v2 P0 修正（gpt-5.6-sol 审核 2026-08-31 定稿口径）：
- 第 3 层回撤由「history 累计买入基准」改为「成本口径 cost_drawdown」：
  单一成本账本 = closed_positions（已平仓权威）+ holdings（当前持仓）；
  history 仅校验不重复计入。
- 命名 cost_drawdown（成本口径，非市值峰值回撤），输出 schema 固定。
- 净投入 <= 0 → status=unknown + data_quality，不触发违规（防除零/负基准）。
- 缺 proceeds / 部分卖出无法可靠计算 → data_quality 标记，不硬判。

遗留登记（不在本刀范围）：portfolio_max_cost 规则未实现（配置已存在）；
账本治理 P1：history 缺 159992 买入记录 → 后续补流水/position ledger。

用法:
    python scripts/discipline_checker.py                 # 检查当前持仓
    python scripts/discipline_checker.py --portfolio <path>  # 指定持仓文件
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORTFOLIO = ROOT / "data" / "portfolio.json"
DEFAULT_RULES = ROOT / "config" / "discipline_rules.json"


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _to_float(v, dq: list[str], tag: str, default: float = 0.0) -> float | None:
    """金额转 float；非法值（负数/字符串）→ data_quality 标记返回 None。"""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        dq.append(f"invalid_amount:{tag}")
        return None
    if f < 0:
        dq.append(f"negative_amount:{tag}")
        return None
    return f


def _compute_cost_drawdown(portfolio: dict, current_open_cost: float) -> dict:
    """成本口径回撤（#17v2 P0）。

    gross_invested = Σ closed_positions.cost + Σ holdings.buy_amount（当前持仓成本）
    recovered      = Σ closed_positions.proceeds
    net_invested   = gross_invested - recovered
    cost_drawdown  = (net_invested - current_open_cost) / net_invested
    负值 = 盈利，不触发；net_invested <= 0 → unknown（防除零/负基准）；
    缺 proceeds / 部分卖出 → data_quality 标记，不硬判。
    """
    dq: list[str] = []
    closed = portfolio.get("closed_positions", []) or []
    gross_invested = 0.0
    recovered = 0.0
    missing_proceeds = False

    for cp in closed:
        cost = _to_float(cp.get("cost"), dq, f"closed_cost:{cp.get('code', '?')}")
        if cost is None:
            continue
        gross_invested += cost
        proceeds = _to_float(cp.get("proceeds"), dq, f"closed_proceeds:{cp.get('code', '?')}")
        if proceeds is None:
            missing_proceeds = True
            dq.append(f"closed_missing_proceeds:{cp.get('code', '?')}")
            continue
        recovered += proceeds

    gross_invested += current_open_cost
    net_invested = gross_invested - recovered

    if missing_proceeds:
        # 部分卖出无法可靠计算 → 不硬判（gpt 意见 4）
        dq.append("partial_sell_unverifiable")
        return {
            "gross_invested": round(gross_invested, 2),
            "recovered": round(recovered, 2),
            "net_invested": round(net_invested, 2),
            "cost_drawdown": None,
            "drawdown_status": "unverifiable",
            "data_quality": dq,
        }
    if net_invested <= 0:
        dq.append("net_invested_non_positive")
        return {
            "gross_invested": round(gross_invested, 2),
            "recovered": round(recovered, 2),
            "net_invested": round(net_invested, 2),
            "cost_drawdown": None,
            "drawdown_status": "unknown",
            "data_quality": dq,
        }

    cost_drawdown = (net_invested - current_open_cost) / net_invested
    if cost_drawdown < 0:
        status = "profit"
    else:
        status = "ok"  # 阈值判定由调用方决定是否 breach
    return {
        "gross_invested": round(gross_invested, 2),
        "recovered": round(recovered, 2),
        "net_invested": round(net_invested, 2),
        "cost_drawdown": round(cost_drawdown, 4),
        "drawdown_status": status,
        "data_quality": dq,
    }


def check_discipline(portfolio: dict, rules: dict) -> dict:
    """执行三层纪律检查，返回违规清单。

    输出 schema（gpt 审 2026-08-31 定稿，无动作字段）：
    {checked_at, portfolio_updated_at, current_open_cost, gross_invested, recovered,
     net_invested, cost_drawdown, drawdown_status, theme_ratios, violations, ok, data_quality}
    """
    holdings = portfolio.get("holdings", {}) or {}
    # 当前持仓成本 = Σ holdings.buy_amount（单一成本账本；total_cost 字段仅兜底）
    current_open_cost = 0.0
    dq: list[str] = []
    for code, h in holdings.items():
        amt = _to_float(h.get("buy_amount"), dq, f"holding_amount:{code}")
        if amt is None:
            continue
        current_open_cost += amt
    if current_open_cost <= 0:
        total_cost_f = _to_float(portfolio.get("total_cost"), dq, "total_cost")
        if total_cost_f and total_cost_f > 0:
            current_open_cost = total_cost_f
        else:
            dq.append("no_open_cost")

    # 主题聚合（按 sector 字段）
    theme_cost: dict[str, float] = {}
    for code, h in holdings.items():
        sector = h.get("sector") or "default"
        amt = _to_float(h.get("buy_amount"), dq, f"holding_amount:{code}")
        theme_cost[sector] = theme_cost.get(sector, 0) + (amt or 0)

    violations: list[dict] = []
    theme_caps = rules.get("theme_caps", {})
    single_cap = float(rules.get("single_position_cap", 0.30))
    total = current_open_cost

    # 1. 主题仓位上限
    for theme, cost in theme_cost.items():
        ratio = cost / total if total else 0
        cap = float(theme_caps.get(theme, theme_caps.get("default", 0.25)))
        if ratio > cap:
            violations.append({
                "type": "theme_cap",
                "theme": theme,
                "ratio": round(ratio, 4),
                "cap": cap,
                "message": f"主题[{theme}]仓位 {ratio:.1%} 超上限 {cap:.1%}，需人工确认",
            })

    # 2. 单标的上限
    for code, h in holdings.items():
        cost = _to_float(h.get("buy_amount"), dq, f"holding_amount:{code}") or 0
        ratio = cost / total if total else 0
        if ratio > single_cap:
            violations.append({
                "type": "single_cap",
                "code": code,
                "name": h.get("name", ""),
                "ratio": round(ratio, 4),
                "cap": single_cap,
                "message": f"标的[{h.get('name', code)}]仓位 {ratio:.1%} 超单标的上限 {single_cap:.1%}，需人工确认",
            })

    # 3. 组合成本回撤开关（#17v2 成本口径，只比对不输出调仓）
    dd_switch = rules.get("drawdown_switch", {})
    dd = _compute_cost_drawdown(portfolio, current_open_cost)
    dq.extend(d for d in dd["data_quality"] if d not in dq)
    if dd_switch.get("enabled") and dd["drawdown_status"] not in ("unknown", "unverifiable"):
        max_dd = float(dd_switch.get("max_drawdown_pct", 0.15))
        if dd["cost_drawdown"] is not None and dd["cost_drawdown"] > max_dd:
            dd["drawdown_status"] = "breach"
            violations.append({
                "type": "drawdown_switch",
                "drawdown": dd["cost_drawdown"],
                "max_drawdown": max_dd,
                "message": f"组合成本回撤 {dd['cost_drawdown']:.1%} 超开关阈值 {max_dd:.1%}，需人工确认",
            })

    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "portfolio_updated_at": portfolio.get("updated"),
        "current_open_cost": round(current_open_cost, 2),
        "gross_invested": dd["gross_invested"],
        "recovered": dd["recovered"],
        "net_invested": dd["net_invested"],
        "cost_drawdown": dd["cost_drawdown"],
        "drawdown_status": dd["drawdown_status"],
        "theme_ratios": {t: round(c / total, 4) for t, c in theme_cost.items()} if total else {},
        "violations": violations,
        "ok": len(violations) == 0,
        "data_quality": dq,
    }


def render_report(result: dict) -> str:
    lines = [f"# 组合纪律检查（{result.get('checked_at', '?')}）", ""]
    lines.append(f"当前持仓成本: {result.get('current_open_cost', 0):.2f}")
    if result.get("net_invested") is not None:
        lines.append(
            f"成本账本: 累计投入 {result.get('gross_invested', 0):.2f} / 已回收 {result.get('recovered', 0):.2f}"
            f" / 净投入 {result.get('net_invested', 0):.2f}"
        )
        if result.get("cost_drawdown") is not None:
            lines.append(f"成本回撤: {result['cost_drawdown']:.1%}（{result.get('drawdown_status', '?')}）")
    ratios = result.get("theme_ratios", {})
    if ratios:
        lines.append("主题占比: " + " | ".join(f"{t} {r:.1%}" for t, r in ratios.items()))
    lines.append("")
    if result.get("ok"):
        lines.append("✅ 全部纪律通过")
    else:
        lines.append("⚠️ 违规清单（仅提醒，非交易指令）:")
        for v in result["violations"]:
            lines.append(f"- [{v['type']}] {v['message']}")
    dq = result.get("data_quality") or []
    if dq:
        lines.append("")
        lines.append(f"⚠️ 数据质量标记: {', '.join(dq)}（部分数据不可判定，不触发违规）")
    lines.append("")
    lines.append("> 本检查只做规则比对，不构成任何买卖/调仓建议。")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="组合纪律检查器")
    parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO))
    parser.add_argument("--rules", default=str(DEFAULT_RULES))
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    portfolio = load_json(Path(args.portfolio))
    rules = load_json(Path(args.rules))
    result = check_discipline(portfolio, rules)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_report(result))


if __name__ == "__main__":
    main()
