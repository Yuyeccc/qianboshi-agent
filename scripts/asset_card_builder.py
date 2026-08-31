#!/usr/bin/env python3
"""资产分析卡生成与 Markdown 渲染。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from factor_config_loader import load_all_asset_configs
from factor_state_refresher import refresh_asset_card


def esc(value: Any) -> str:
    return str(value or "").replace("|", "｜").replace("\n", " ").strip()


def build_asset_card(asset_id: str, as_of_date: str | None = None) -> dict[str, Any]:
    """生成单个资产分析卡。"""
    return refresh_asset_card(asset_id, as_of_date=as_of_date)


def render_asset_card(card: dict[str, Any]) -> str:
    """渲染资产分析卡 Markdown 表格。"""
    asset_name = card.get("asset_name") or card.get("asset_id") or ""
    lines = [f"## {esc(asset_name)}分析卡 v{esc(card.get('version'))}"]
    lines.append("")
    lines.append(f"> {esc(card.get('logic_chain_summary'))}")
    lines.append("")
    lines.append(f"| 因素 | 当前状态 | 变化 | 对{esc(asset_name)}影响 | 证据 |")
    lines.append("|---|---|---|---|---|")
    for factor in card.get("factors") or []:
        evidence = factor.get("evidence_refs") or []
        evidence_text = "、".join(esc(x) for x in evidence[:3]) if isinstance(evidence, list) else esc(evidence)
        lines.append(
            "| {factor_name} | {current_state} | {change_direction} | {impact_direction}({impact_strength}) | {evidence} |".format(
                factor_name=esc(factor.get("factor_name")),
                current_state=esc(factor.get("current_state")),
                change_direction=esc(factor.get("change_direction")),
                impact_direction=esc(factor.get("impact_direction")),
                impact_strength=esc(factor.get("impact_strength")),
                evidence=esc(evidence_text),
            )
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成资产分析卡")
    parser.add_argument("--asset", help="资产ID，例如 GOLD；不指定则扫描全部配置")
    parser.add_argument("--as-of-date", help="刷新日期，默认今天")
    args = parser.parse_args()

    cards = []
    if args.asset:
        cards.append(build_asset_card(args.asset, as_of_date=args.as_of_date))
    else:
        for cfg in load_all_asset_configs():
            cards.append(build_asset_card(str(cfg.get("asset_id")), as_of_date=args.as_of_date))
    print("\n\n".join(render_asset_card(card) for card in cards))


if __name__ == "__main__":
    main()
