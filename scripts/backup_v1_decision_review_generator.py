#!/usr/bin/env python3
"""决策复盘生成器（阶段四后半）：决策到期回填结果 + 复盘报告。

确定性部分（收益/方向/引用）全部从数据库生成，LLM 只做可选润色。

用法:
    python scripts/decision_review_generator.py --backfill          # 回填到期决策结果
    python scripts/decision_review_generator.py --report GOLD       # 生成黄金复盘报告
    python scripts/decision_review_generator.py --report GOLD --llm # LLM润色总结
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from decision_db import connect, decision_db_path, fetch_decisions

# 复盘周期（决策后 N 日回填）
REVIEW_WINDOWS = {"short": 5, "medium": 20, "long": 60}


def _load_trends() -> dict[str, Any]:
    p = Path(__file__).parent.parent / "data" / "price_trends.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _price_on(trends: dict[str, Any], symbol: str, day: date) -> float | None:
    sym = trends.get(symbol) or {}
    row = sym.get(day.isoformat())
    if row:
        return float(row.get("price") or 0) or None
    return None


def _nearest_price(trends: dict[str, Any], symbol: str, day: date, window: int = 5) -> float | None:
    """找 day 前后 window 天内最近的价格（交易日缺口兼容）。"""
    for offset in range(window + 1):
        for d in (day + timedelta(days=offset), day - timedelta(days=offset)):
            p = _price_on(trends, symbol, d)
            if p:
                return p
    return None


def _asset_symbol(decision: dict[str, Any]) -> str | None:
    """决策 → 行情 symbol 映射。"""
    asset = (decision.get("asset_id") or "").upper()
    mapping = {
        "GOLD": "518880.SS",  # 华安黄金ETF（场内，对应场外000217）
        "INNOV_DRUG": "159992.SZ",  # 创新药ETF
        "TECH": "512480.SS",
        "BAIJIU": "512690.SS",
        "ALUMINUM": "601899.SS",  # 紫金矿业代理
        "SEMI": "159813.SZ",
    }
    return mapping.get(asset)


def backfill_decision_outcomes(days_offset: int = 0) -> dict[str, int]:
    """回填到期决策的结果（写入 decision_reviews 表）。"""
    trends = _load_trends()
    decisions = fetch_decisions(status="open")
    now = date.today()
    counts = {"checked": 0, "filled": 0, "no_data": 0, "skipped": 0}

    with connect() as conn:
        for d in decisions:
            counts["checked"] += 1
            decision_date = datetime.strptime(d["decision_date"], "%Y-%m-%d").date()
            horizon = d.get("horizon") or "medium"
            window = REVIEW_WINDOWS.get(horizon, 20)
            review_date = decision_date + timedelta(days=window)
            # 到期才回填
            if review_date > now + timedelta(days=days_offset):
                counts["skipped"] += 1
                continue

            symbol = _asset_symbol(d)
            if not symbol:
                counts["skipped"] += 1
                continue
            p0 = _nearest_price(trends, symbol, decision_date)
            p1 = _nearest_price(trends, symbol, review_date)
            if not p0 or not p1:
                counts["no_data"] += 1
                continue

            ret = (p1 - p0) / p0 * 100
            direction = d.get("direction")
            if direction == "bullish":
                label = "right" if ret > 0 else "wrong"
            elif direction == "bearish":
                label = "right" if ret < 0 else "wrong"
            else:
                label = "mixed" if abs(ret) < 1 else "too_early"

            review_id = f"rev_{d['decision_id']}_{review_date.isoformat()}"
            conn.execute(
                """
                INSERT INTO decision_reviews (
                    review_id, decision_id, review_date, horizon_days,
                    outcome_return, result_label, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                    outcome_return=excluded.outcome_return,
                    result_label=excluded.result_label
                """,
                (
                    review_id, d["decision_id"], review_date.isoformat(), window,
                    round(ret, 4), label, datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.execute(
                "UPDATE user_decision_logs SET status='reviewed', updated_at=? WHERE decision_id=?",
                (datetime.now().isoformat(timespec="seconds"), d["decision_id"]),
            )
            counts["filled"] += 1
        conn.commit()
    return counts


def generate_review_report(asset_id: str, use_llm: bool = False) -> str:
    """生成某资产的复盘报告 Markdown。"""
    with connect() as conn:
        decisions = [dict(r) for r in conn.execute(
            "SELECT * FROM user_decision_logs WHERE asset_id=? ORDER BY decision_date",
            (asset_id,),
        ).fetchall()]
        reviews = {r["decision_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM decision_reviews ORDER BY review_date"
        ).fetchall()}

    if not decisions:
        return f"# {asset_id} 决策复盘\n\n暂无决策记录。"

    lines = [f"# {asset_id} 决策复盘", ""]
    lines.append("## 1. 判断概览")
    lines.append(f"- 决策次数：{len(decisions)}")
    bullish = sum(1 for d in decisions if d.get("direction") == "bullish")
    bearish = sum(1 for d in decisions if d.get("direction") == "bearish")
    neutral = sum(1 for d in decisions if d.get("direction") == "neutral")
    reviewed = sum(1 for d in decisions if d["decision_id"] in reviews)
    lines.append(f"- 看多：{bullish}次 / 看空：{bearish}次 / 中性：{neutral}次")
    lines.append(f"- 已完成复盘：{reviewed}次")
    lines.append("")

    lines.append("## 2. 结果")
    lines.append("| 日期 | 判断 | 周期 | 结果 | 收益 |")
    lines.append("|---|---|---|---|---|")
    for d in decisions:
        rv = reviews.get(d["decision_id"])
        label_map = {"right": "✅正确", "wrong": "❌错误", "mixed": "⚠️混合", "too_early": "⏳过早"}
        ret = f"{rv['outcome_return']:+.2f}%" if rv else "-"
        label = label_map.get(rv["result_label"], "-") if rv else "待回填"
        lines.append(f"| {d['decision_date'][5:]} | {d.get('direction')} | {d.get('horizon')} | {label} | {ret} |")
    lines.append("")

    lines.append("## 3. 主要依据")
    for d in decisions:
        reasons = json.loads(d.get("key_reasons") or "[]")
        if reasons:
            lines.append(f"- **{d['decision_date'][5:]} {d.get('asset_name')}**：" + "；".join(reasons))
    lines.append("")

    # 认知修正区（LLM 可选）
    if use_llm:
        try:
            from config_loader import get_llm_config, load_config
            llm = get_llm_config(load_config())
            import requests
            prompt = (
                "你是投研复盘助手。以下是用户对一个资产的判断记录，请总结：1)哪些判断被市场验证；"
                "2)哪些认知需要修正；3)给出可执行的规则更新建议。用中文，300字内。\n\n"
                + json.dumps(decisions, ensure_ascii=False, indent=1)
            )
            # 贵模型优先（2026-08-22）：premium gpt-5.6 → fallback pro
            from llm_fallback import call_analysis_llm

            summary, _used_model = call_analysis_llm(
                llm,
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500,
                timeout=120,
            )
            lines.append("## 4. 认知修正（LLM总结）")
            lines.append(summary)
        except Exception as e:
            lines.append("")
            lines.append(f"## 4. 认知修正\n\n（LLM总结失败：{e}）")

    lines.append("")
    lines.append("---")
    lines.append("*本报告收益与结果由数据库确定性生成，非投资建议。*")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="决策复盘生成器")
    parser.add_argument("--backfill", action="store_true", help="回填到期决策结果")
    parser.add_argument("--report", help="生成某资产复盘报告（如 GOLD）")
    parser.add_argument("--llm", action="store_true", help="复盘总结用LLM润色")
    parser.add_argument("--days-offset", type=int, default=0, help="允许提前N天回填（测试用）")
    args = parser.parse_args()

    if args.backfill:
        r = backfill_decision_outcomes(days_offset=args.days_offset)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    if args.report:
        print(generate_review_report(args.report, use_llm=args.llm))
    if not args.backfill and not args.report:
        parser.print_help()


if __name__ == "__main__":
    main()
