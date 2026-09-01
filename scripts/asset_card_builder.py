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
from valuation_calc import render_valuation_block


def esc(value: Any) -> str:
    return str(value or "").replace("|", "｜").replace("\n", " ").strip()


_STATUS_BADGE = {
    "available": "✅已拿到",
    "pending": "⏳待补",
    "insufficient": "⚠️不足",
    "na": "⛔不适用",
}

_STATUS_CN = {"available": "已拿到", "pending": "待补", "insufficient": "不足", "na": "不适用"}

_DIMENSION_CN = {"现金流": "💰现金流", "债务": "🏦债务", "减值": "🧨减值", "质量": "⚖️质量"}


def build_asset_card(asset_id: str, as_of_date: str | None = None) -> dict[str, Any]:
    """生成单个资产分析卡。"""
    return refresh_asset_card(asset_id, as_of_date=as_of_date)


def _render_data_status_badge(data_status: dict[str, Any]) -> str:
    """资料充分度徽标行（71号方案 #10）。"""
    if not data_status:
        return ""
    labels = {
        "market": "行情",
        "views": "观点",
        "fundamentals": "财报",
        "valuation": "估值",
    }
    parts = []
    for key, label in labels.items():
        status = data_status.get(key)
        badge = _STATUS_BADGE.get(status, "⏳待补")
        parts.append(f"{label}{badge}")
    return f"> 📦 资料充分度：" + "　".join(parts)


def _render_quality_factors(quality_factors: list[dict[str, Any]]) -> str:
    """质量因子卡（71号方案 #10）。"""
    if not quality_factors:
        return ""
    lines = ["### 质量因子卡（估值≠安全边际）", "", "| 因子 | 数值 | 判读 | 报告期 | 来源 |", "|---|---|---|---|---|"]
    for qf in quality_factors:
        val = qf.get("value")
        val_text = f"{val}{qf.get('unit')}" if val is not None else "—"
        lines.append(
            f"| {esc(qf.get('factor_name'))} | {val_text} | {esc(qf.get('judgement'))} | {esc(qf.get('period') or '—')} | {esc(qf.get('source'))} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_analysis_framework(framework: list[dict[str, Any]]) -> str:
    """8问框架（71号方案 #8）。ETF/商品卡空列表 → 一行不适用说明。"""
    lines = ["### 8问框架（质量判断）"]
    if not framework:
        lines.append("> 本资产类型无财报（ETF/商品），8问框架不适用。")
        lines.append("")
        return "\n".join(lines)
    lines.append("")
    lines.append("| # | 问题 | 当前判断 | 状态 |")
    lines.append("|---|---|---|---|")
    for q in framework:
        dim = _DIMENSION_CN.get(q.get("dimension"), esc(q.get("dimension")))
        status = _STATUS_CN.get(q.get("status"), q.get("status") or "待补")
        lines.append(
            f"| {esc(q.get('question_id'))} {dim} | {esc(q.get('question'))} | {esc(q.get('answer'))} | {status} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_asset_card(card: dict[str, Any]) -> str:
    """渲染资产分析卡 Markdown（三维：资料充分度/质量/估值）。"""
    asset_name = card.get("asset_name") or card.get("asset_id") or ""
    lines = [f"## {esc(asset_name)}分析卡 v{esc(card.get('version'))}"]
    lines.append("")
    lines.append(f"> {esc(card.get('logic_chain_summary'))}")
    lines.append("")
    badge = _render_data_status_badge(card.get("data_status") or {})
    if badge:
        lines.append(badge)
        lines.append("")
    lines.append(f"| 因素 | 当前状态 | 变化 | 对{esc(asset_name)}影响 | 证据 |")
    lines.append("|---|---|---|---|---|")
    for factor in card.get("factors") or []:
        evidence = factor.get("evidence_refs") or []
        evidence_text = "、".join(esc(x) for x in evidence[:3]) if isinstance(evidence, list) else esc(evidence)
        impact = factor.get("impact_direction") or ""
        if impact == "unknown":
            impact_text = "待定（数据待补）"
        elif impact == "neutral":
            impact_text = "中性"
        else:
            impact_text = f"{impact}({esc(factor.get('impact_strength'))})"
        lines.append(
            "| {factor_name} | {current_state} | {change_direction} | {impact} | {evidence} |".format(
                factor_name=esc(factor.get("factor_name")),
                current_state=esc(factor.get("current_state")),
                change_direction=esc(factor.get("change_direction")),
                impact=impact_text,
                evidence=esc(evidence_text),
            )
        )
    lines.append("")
    qf_block = _render_quality_factors(card.get("quality_factors") or [])
    if qf_block:
        lines.append(qf_block)
    lines.append(_render_analysis_framework(card.get("analysis_framework") or []))
    valuation = card.get("valuation")
    if valuation:
        lines.append(render_valuation_block(valuation))
    return "\n".join(lines).rstrip() + "\n"


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
