#!/usr/bin/env python3
"""组合账本一致性校验（57 号方案，2026-09-01）。

校验 portfolio.json 成本账本与流水（history）的闭合性：
1. history 买入总额 == gross_invested（Σ closed_positions.cost + Σ holdings.buy_amount）
2. history 卖出总额 == Σ closed_positions.proceeds
3. 每个 closed_position 的卖出流水完整（sell 条数匹配 sell_dates/sell_date）
4. 每个 holdings 的买入流水存在
5. 每股 code 买卖对账：卖出金额 <= 买入金额（不出现负数仓位）

用法:
    python scripts/ledger_verify.py          # 校验，通过退出码 0
    python scripts/ledger_verify.py --json   # JSON 输出
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORTFOLIO = ROOT / "data" / "portfolio.json"


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def verify_ledger(portfolio: dict) -> dict:
    """校验账本一致性，返回 {ok, errors[], checks{...}}。"""
    errors: list[str] = []
    checks: dict = {}

    holdings = portfolio.get("holdings", {}) or {}
    closed = portfolio.get("closed_positions", []) or []
    history = portfolio.get("history", []) or []

    # 1. 买入总额 vs gross_invested
    buy_total = sum(_f(e.get("amount")) for e in history if e.get("action") == "buy")
    gross_invested = sum(_f(c.get("cost")) for c in closed) + sum(_f(h.get("buy_amount")) for h in holdings.values())
    checks["buy_total"] = buy_total
    checks["gross_invested"] = gross_invested
    if abs(buy_total - gross_invested) > 0.01:
        errors.append(f"买入总额 {buy_total:.2f} != gross_invested {gross_invested:.2f}")

    # 2. 卖出总额 vs recovered
    sell_total = sum(_f(e.get("amount")) for e in history if e.get("action") == "sell")
    recovered = sum(_f(c.get("proceeds")) for c in closed)
    checks["sell_total"] = sell_total
    checks["recovered"] = recovered
    if abs(sell_total - recovered) > 0.01:
        errors.append(f"卖出总额 {sell_total:.2f} != recovered {recovered:.2f}")

    # 3. closed_position 卖出流水完整
    for cp in closed:
        code = cp.get("code", "?")
        sell_dates = cp.get("sell_dates") or ([cp.get("sell_date")] if cp.get("sell_date") else [])
        n_sell = sum(1 for e in history if e.get("action") == "sell" and e.get("code") == code)
        if n_sell != len(sell_dates):
            errors.append(f"[{code}] 卖出流水 {n_sell} 条 != closed.sell_dates {len(sell_dates)} 条")

    # 4. holdings 买入流水存在
    for code, h in holdings.items():
        n_buy = sum(1 for e in history if e.get("action") == "buy" and e.get("code") == code)
        if n_buy == 0:
            errors.append(f"[{code}] 持仓 {h.get('name', '')} 无买入流水")

    # 5. 每股买卖对账（按份额：卖出份额 <= 买入份额，不出现负数仓位）
    #    金额卖出 > 买入 = 盈利卖出（正常），份额才是仓位本体的度量
    by_code: dict[str, dict] = {}
    for e in history:
        c = by_code.setdefault(e.get("code", "?"), {"buy_amt": 0.0, "sell_amt": 0.0, "buy_sh": 0.0, "sell_sh": 0.0})
        if e.get("action") == "buy":
            c["buy_amt"] += _f(e.get("amount"))
            c["buy_sh"] += _f(e.get("shares"))
        elif e.get("action") == "sell":
            c["sell_amt"] += _f(e.get("amount"))
            c["sell_sh"] += _f(e.get("shares"))
    for code, v in by_code.items():
        if v["sell_sh"] > v["buy_sh"] + 1e-6:
            errors.append(f"[{code}] 卖出份额 {v['sell_sh']:.2f} > 买入份额 {v['buy_sh']:.2f}（负数仓位）")

    return {"ok": len(errors) == 0, "errors": errors, "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description="组合账本一致性校验")
    parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with open(Path(args.portfolio), encoding="utf-8-sig") as f:
        portfolio = json.load(f)
    result = verify_ledger(portfolio)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"账本校验: {'✅ 通过' if result['ok'] else '❌ 失败'}")
        for e in result["errors"]:
            print(f"  - {e}")
        print(f"  买入总额 {result['checks']['buy_total']:.2f} / gross {result['checks']['gross_invested']:.2f}"
              f" | 卖出 {result['checks']['sell_total']:.2f} / recovered {result['checks']['recovered']:.2f}")
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
