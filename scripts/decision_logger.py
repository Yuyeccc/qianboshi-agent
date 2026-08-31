#!/usr/bin/env python3
"""决策日志录入器：把用户的口头/群聊决策结构化存入 user_decision_logs。

用法:
    python scripts/decision_logger.py --asset GOLD --direction bullish --date 2026-08-06 --thesis "..." 
    python scripts/decision_logger.py --list            # 列出全部决策
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from decision_db import fetch_decisions, upsert_decision_log

ASSET_ALIASES = {
    "gold": ("GOLD", "黄金", "commodity"),
    "黄金": ("GOLD", "黄金", "commodity"),
    "semi": ("SEMI", "半导体", "sector"),
    "半导体": ("SEMI", "半导体", "sector"),
    "a": ("GOLD", "黄金", "commodity"),
}


def resolve_asset(asset_key: str) -> tuple[str, str, str]:
    return ASSET_ALIASES.get(asset_key.lower(), (asset_key.upper(), asset_key, "other"))


def build_decision(args: argparse.Namespace) -> dict[str, Any]:
    asset_id, asset_name, asset_type = resolve_asset(args.asset)
    decision = {
        "decision_id": args.decision_id or f"dec_{args.date}_{asset_id}_{args.seq or '001'}",
        "asset_id": asset_id,
        "asset_name": asset_name,
        "asset_type": asset_type,
        "decision_date": args.date,
        "horizon": args.horizon,
        "direction": args.direction,
        "conviction": args.conviction,
        "thesis": args.thesis,
        "key_reasons": json.loads(args.key_reasons) if args.key_reasons else [],
        "premise": json.loads(args.premise) if args.premise else [],
        "invalidation_conditions": json.loads(args.invalidation) if args.invalidation else [],
        "action_note": args.action,
        "status": args.status or "open",
    }
    if args.evidence:
        evs = json.loads(args.evidence)
        if isinstance(evs, list):
            decision["evidence"] = evs
    return decision


def render_decision(d: dict[str, Any]) -> str:
    return (
        f"[{d.get('status', 'open')}] {d.get('decision_date')} | {d.get('asset_name')} "
        f"({d.get('asset_id')}) | {d.get('direction')}@{d.get('horizon')} "
        f"信心{d.get('conviction') or '?'}\n"
        f"  判断: {d.get('thesis', '')[:120]}\n"
        f"  理由: {d.get('key_reasons', '[]')[:160]}\n"
        f"  前提: {d.get('premise', '[]')[:160]}\n"
        f"  证伪: {d.get('invalidation_conditions', '[]')[:160]}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="用户决策日志")
    parser.add_argument("--list", action="store_true", help="列出全部决策")
    parser.add_argument("--status", default=None, help="按状态过滤: open/reviewed/archived")
    parser.add_argument("--asset", default="GOLD", help="资产: gold/semi/黄金/半导体")
    parser.add_argument("--direction", default="bullish", choices=["bullish", "bearish", "neutral", "watch"])
    parser.add_argument("--horizon", default="medium", choices=["short", "medium", "long"])
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--conviction", type=float, default=None)
    parser.add_argument("--thesis", required=not "--list" in sys.argv, default="")
    parser.add_argument("--key-reasons", default=None, help="JSON数组")
    parser.add_argument("--premise", default=None, help="JSON数组: 前提条件(成立才继续持有判断)")
    parser.add_argument("--invalidation", default=None, help="JSON数组: 什么情况说明错了")
    parser.add_argument("--action", default=None, help="行动备注(非交易指令)")
    parser.add_argument("--evidence", default=None, help="JSON数组: 证据快照")
    parser.add_argument("--decision-id", default=None)
    parser.add_argument("--seq", default=None, help="决策序号(同资产同日多条时)")
    args = parser.parse_args()

    if args.list or not args.thesis:
        decisions = fetch_decisions(status=args.status)
        print(f"共 {len(decisions)} 条决策:")
        for d in decisions:
            print()
            print(render_decision(d))
        return

    decision = build_decision(args)
    did = upsert_decision_log(decision)
    print(f"✅ 已录入: {did}")
    print(render_decision(decision))


if __name__ == "__main__":
    main()
