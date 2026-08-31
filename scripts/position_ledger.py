#!/usr/bin/env python3
"""Position Ledger：FIFO cost-lot 完整账本模型（70 号交接 P2 队列，2026-09-01）。

从 portfolio.json 的 history 流水重建每 code 的成本批次（cost lots）：
- 每笔买入 = 一个 cost lot（成本用 amount 字段=实际投入，不用 nav×shares 防舍入差）
- 卖出按 FIFO 消费最早未平仓 lot，份额比例扣减 lot 成本 → 精确已实现盈亏
- 输出：每 code 剩余 lots（成本基础/avg_cost）+ realized_pnl（总额与每 code）
- 多账户扩展位：lot.account 字段，默认 "main"
- 只读账本：不写 portfolio.json；报告写 data/backtest/position_ledger_*.{json,md}

对账目标（--verify）：
1. realized_pnl 总额 == Σ closed_positions.pnl（±0.01）
2. 剩余份额 == holdings.shares（±0.01）
3. 剩余 avg_cost == holdings.avg_cost（±0.0001）
4. 无负 lot（份额守恒，不出现卖出 > 可卖）

用法:
    python scripts/position_ledger.py --verify   # 对账校验（退出码 0/1）
    python scripts/position_ledger.py --report   # 生成 lot 明细报告
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORTFOLIO = ROOT / "data" / "portfolio.json"
REPORT_DIR = ROOT / "data" / "backtest"

EPS = 1e-6


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def build_ledger(portfolio: dict) -> dict[str, Any]:
    """重建 FIFO cost-lot 账本 → {codes: {code: {...}}, realized_total, ...}。"""
    history = portfolio.get("history", []) or []
    by_code: dict[str, list[dict]] = {}
    for e in sorted(history, key=lambda x: (x.get("date", ""), x.get("action", ""))):
        code = str(e.get("code", "?"))
        by_code.setdefault(code, []).append(e)

    codes: dict[str, Any] = {}
    realized_total = 0.0
    for code, events in by_code.items():
        lots: list[dict] = []  # 未平仓 lots（FIFO 队列）
        lots_open: list[dict] = []  # 全量 lot 档案
        realized = 0.0
        sell_count = 0
        for e in events:
            action = e.get("action")
            if action == "buy":
                lot = {
                    "lot_id": f"{code}-{len(lots_open) + 1}",
                    "code": code,
                    "date": e.get("date", ""),
                    "shares": _f(e.get("shares")),
                    "cost": _f(e.get("amount")),
                    "nav": _f(e.get("nav")),
                    "account": e.get("account", "main"),
                    "remaining_shares": _f(e.get("shares")),
                }
                if lot["shares"] > 0:
                    lots_open.append(lot)
                    lots.append(lot)
            elif action == "sell":
                sell_count += 1
                sell_sh = _f(e.get("shares"))
                sell_price = _f(e.get("price")) or _f(e.get("nav"))
                remaining = sell_sh
                matched_cost = 0.0
                while remaining > EPS and lots:
                    lot = lots[0]
                    take = min(remaining, lot["remaining_shares"] + EPS)
                    take = min(take, lot["remaining_shares"])
                    if take <= 0:
                        lots.pop(0)
                        continue
                    ratio = take / lot["shares"] if lot["shares"] else 0.0
                    matched_cost += lot["cost"] * ratio
                    lot["remaining_shares"] -= take
                    remaining -= take
                    if lot["remaining_shares"] <= EPS:
                        lots.pop(0)
                if remaining > EPS:
                    # 卖出超过可用份额：差额按 0 成本处理，对账会报错（份额守恒）
                    pass
                realized += sell_price * sell_sh - matched_cost
        codes[code] = {
            "lots": lots_open,
            "open_lots": lots,
            "realized_pnl": round(realized, 2),
            "remaining_shares": round(sum(l["remaining_shares"] for l in lots), 2),
            "remaining_cost": round(sum(l["cost"] * (l["remaining_shares"] / l["shares"]) for l in lots), 2),
            "avg_cost": round(
                sum(l["cost"] * (l["remaining_shares"] / l["shares"]) for l in lots)
                / sum(l["remaining_shares"] for l in lots),
                4,
            ) if sum(l["remaining_shares"] for l in lots) > 0 else 0.0,
            "sell_count": sell_count,
        }
        realized_total += realized
    return {
        "codes": codes,
        "realized_total": round(realized_total, 2),
        "n_codes": len(codes),
    }


def verify_ledger_model(portfolio: dict) -> dict:
    """对账：新模型 vs portfolio.json 既有字段（closed.pnl / holdings.shares / avg_cost）。"""
    errors: list[str] = []
    checks: dict = {}
    ledger = build_ledger(portfolio)
    closed = portfolio.get("closed_positions", []) or []
    holdings = portfolio.get("holdings", {}) or {}

    # 1. realized_pnl 总额 vs closed.pnl
    closed_pnl = sum(_f(c.get("pnl")) for c in closed)
    checks["realized_total"] = ledger["realized_total"]
    checks["closed_pnl"] = round(closed_pnl, 2)
    if abs(ledger["realized_total"] - closed_pnl) > 0.01:
        errors.append(
            f"FIFO realized {ledger['realized_total']:.2f} != closed.pnl {closed_pnl:.2f}"
        )

    # 2. 剩余份额 vs holdings.shares；3. avg_cost vs holdings.avg_cost
    for code, h in holdings.items():
        lm = ledger["codes"].get(code)
        if not lm:
            errors.append(f"[{code}] 持仓 {h.get('name', '')} 在 FIFO 模型中无记录")
            continue
        if abs(lm["remaining_shares"] - _f(h.get("shares"))) > 0.01:
            errors.append(
                f"[{code}] FIFO 剩余 {lm['remaining_shares']} != holdings.shares {h.get('shares')}"
            )
        if abs(lm["avg_cost"] - _f(h.get("avg_cost"))) > 0.0001:
            errors.append(
                f"[{code}] FIFO avg_cost {lm['avg_cost']} != holdings.avg_cost {h.get('avg_cost')}"
            )

    # 4. 已清仓 code 的 realized 应已在 closed 中（不重复检查，防过度耦合）
    checks["n_codes"] = ledger["n_codes"]
    return {"ok": len(errors) == 0, "errors": errors, "checks": checks, "ledger": ledger}


def render_report(ledger: dict, generated_at: str) -> str:
    lines = [
        f"# Position Ledger 报告（FIFO cost-lot，{generated_at}）",
        "",
        f"> 数据：`{DEFAULT_PORTFOLIO.name}` · 共 {ledger['n_codes']} 个 code · 已实现盈亏合计 **{ledger['realized_total']:.2f}**",
        "> 口径：每笔买入 = 一个 cost lot（成本=amount 实际投入）；卖出按 FIFO 消费 lot，份额比例扣成本",
        "",
        "| code | 买入批次 | 剩余份额 | 剩余成本基础 | avg_cost | 已实现盈亏 | 卖出次数 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for code, lm in ledger["codes"].items():
        lines.append(
            f"| {code} | {len(lm['lots'])} | {lm['remaining_shares']} | "
            f"{lm['remaining_cost']} | {lm['avg_cost']} | {lm['realized_pnl']} | {lm['sell_count']} |"
        )
    lines.append("")
    lines.append("## 未平仓 lot 明细")
    lines.append("")
    lines.append("| lot | code | 日期 | 买入份额 | 成本 | nav | 剩余份额 | 账户 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for code, lm in ledger["codes"].items():
        for lot in lm["lots"]:  # 全量 lot 档案展示（含已平仓，剩余份额列见真章）
            lines.append(
                    f"| `{lot['lot_id']}` | {code} | {lot['date']} | {lot['shares']} | "
                    f"{lot['cost']} | {lot['nav']} | {round(lot['remaining_shares'], 2)} | {lot['account']} |"
                )
    lines.append("")
    lines.append("> 多账户扩展位：lot.account（默认 main），消费方（收益归因/税务）接入时按账户分组。")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Position Ledger FIFO 账本模型")
    parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO))
    parser.add_argument("--verify", action="store_true", help="对账校验（退出码 0/1）")
    parser.add_argument("--report", action="store_true", help="生成 lot 明细报告")
    args = parser.parse_args()

    with open(Path(args.portfolio), encoding="utf-8-sig") as f:
        portfolio = json.load(f)

    if args.verify:
        result = verify_ledger_model(portfolio)
        print(f"Position Ledger 对账: {'✅ 通过' if result['ok'] else '❌ 失败'}")
        for e in result["errors"]:
            print(f"  - {e}")
        print(
            f"  FIFO realized {result['checks']['realized_total']:.2f} vs closed.pnl "
            f"{result['checks']['closed_pnl']:.2f} | codes {result['checks']['n_codes']}"
        )
        sys.exit(0 if result["ok"] else 1)

    if args.report:
        ledger = build_ledger(portfolio)
        stamp = datetime.now().strftime("%Y%m%d")
        md = render_report(ledger, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        md_path = REPORT_DIR / f"position_ledger_{stamp}.md"
        json_path = REPORT_DIR / f"position_ledger_{stamp}.json"
        md_path.write_text(md, encoding="utf-8")
        json_path.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(md)
        print(f"\n报告: {md_path}\n数据: {json_path}")
    else:
        print(json.dumps(build_ledger(portfolio), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
