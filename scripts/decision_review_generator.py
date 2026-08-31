#!/usr/bin/env python3
"""决策复盘生成器 v2（2026-08-27 全量升级）：

v2 变更：
- 标的解析接入 asset_registry 注册表（防静默跳过：未注册/未生效显式 stderr 告警）
- 判定引擎切换 review_judge.review_decision（绝对/相对收益分离、噪声带分档、细分等级）
- 映射变更自动 reopen：registry.previous.json 检测到 symbol 变更时重开对应决策并删除失效复盘
- decision_reviews 新增 result_grade / rule_version 列（自动迁移）
- 报告表格升级（含基准收益/超额/细分列）；--llm 接 review_llm.generate_lessons 教训闭环

公开接口向后兼容：
- backfill_decision_outcomes(days_offset=0) -> counts dict
- generate_review_report(asset_id, use_llm=False) -> markdown str

用法:
    python scripts/decision_review_generator.py --backfill          # 回填到期决策结果
    python scripts/decision_review_generator.py --report GOLD       # 生成黄金复盘报告
    python scripts/decision_review_generator.py --report GOLD --llm # LLM教训总结
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
from decision_db import connect, fetch_decisions

# v2 助手函数（LLM 生成，老手审批修正后整合）
from _review_v2_helpers import (
    ensure_review_columns,
    reopen_on_mapping_changes,
    compute_review_row,
    render_result_table,
)

HORIZON_DAYS = {"short": 5, "medium": 20, "long": 60}


def _load_trends() -> dict[str, Any]:
    p = Path(__file__).parent.parent / "data" / "price_trends.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _load_rules() -> dict[str, Any]:
    from asset_registry import load_rules
    try:
        return load_rules()
    except Exception as e:  # 规则文件损坏时降级默认
        print(f"[warn] review_rules 加载失败用内置默认: {e}", file=sys.stderr)
        return {"rule_version": "v1-fallback", "noise_band_pct": {"short": 2.0, "medium": 1.5, "long": 1.0},
                "neutral_abs_band_pct": {"short": 3.0, "medium": 2.0, "long": 1.5},
                "benchmark_max_offset_days": 5, "price_nearest_window_days": 5,
                "conviction_grades": {"strong_wrong_min_conviction": 0.7, "weak_wrong_max_conviction": 0.4}}


def _resolve_symbol(decision: dict[str, Any]) -> dict[str, Any] | None:
    """v2: 决策 → registry 解析。失败打印明确原因（防静默跳过）。"""
    from asset_registry import RegistryError, resolve_asset
    asset_id = (decision.get("asset_id") or "").upper()
    try:
        return resolve_asset(asset_id, as_of=decision.get("decision_date"))
    except RegistryError as e:
        print(f"[skip] {asset_id}: {e}", file=sys.stderr)
        return None


def _inject_spec(decision: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """把 registry 解析出的标的代码塞进 decision 副本供 review_judge 使用。"""
    d = dict(decision)
    d["primary_symbol"] = spec["primary_symbol"]
    d["benchmark_symbol"] = spec["benchmark_symbol"]
    d["_asset_name"] = spec.get("name")
    return d


def backfill_decision_outcomes(days_offset: int = 0) -> dict[str, int | list]:
    """回填到期决策的结果（写入 decision_reviews 表）。v2 编排。"""
    trends = _load_trends()
    rules = _load_rules()
    decisions = fetch_decisions(status="open")
    now = date.today()
    counts: dict[str, Any] = {
        "checked": 0, "filled": 0, "no_data": 0, "skipped": 0,
        "reopened": 0, "filled_rows": [],
    }

    with connect() as conn:
        # v2: 映射变更驱动的 reopen（registry.previous.json 存在且 primary_symbol 有变化时触发）
        ensure_review_columns(conn)
        reopened = reopen_on_mapping_changes(conn)
        counts["reopened"] = reopened
        if reopened:
            conn.commit()
            decisions = fetch_decisions(status="open")  # reopen 后重新拉取 open 列表

        for d in decisions:
            counts["checked"] += 1
            decision_date = datetime.strptime(d["decision_date"], "%Y-%m-%d").date()
            horizon = d.get("horizon") or "medium"
            window = HORIZON_DAYS.get(horizon, 20)
            review_date_calc = decision_date + timedelta(days=window)
            if review_date_calc > now + timedelta(days=days_offset):
                counts["skipped"] += 1
                continue

            spec = _resolve_symbol(d)
            if not spec:
                counts["skipped"] += 1  # stderr 已由 _resolve_symbol 打印原因
                continue

            row = compute_review_row(_inject_spec(d, spec), trends, rules)
            if row is None:
                counts["no_data"] += 1
                print(f"[no_price] {d['asset_id']} {d['decision_date']}: 行情缺失", file=sys.stderr)
                continue

            conn.execute(
                """
                INSERT INTO decision_reviews (
                    review_id, decision_id, review_date, horizon_days,
                    outcome_return, benchmark_return, excess_return,
                    result_label, result_grade, rule_version, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                    outcome_return=excluded.outcome_return,
                    benchmark_return=excluded.benchmark_return,
                    excess_return=excluded.excess_return,
                    result_label=excluded.result_label,
                    result_grade=excluded.result_grade,
                    rule_version=excluded.rule_version
                """,
                (
                    row["review_id"], row["decision_id"], row["review_date"],
                    row["horizon_days"], row["outcome_return"],
                    row["benchmark_return"], row["excess_return"],
                    row["result_label"], row["result_grade"],
                    row["rule_version"], datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.execute(
                "UPDATE user_decision_logs SET status='reviewed', updated_at=? WHERE decision_id=?",
                (datetime.now().isoformat(timespec="seconds"), d["decision_id"]),
            )
            row["asset_id"] = d["asset_id"]
            counts["filled"] += 1
            counts["filled_rows"].append(row)
        conn.commit()

    counts["filled_rows"] = counts["filled_rows"]
    return counts


def generate_review_report(asset_id: str, use_llm: bool = False) -> str:
    """生成某资产的复盘报告 Markdown。v2: 含基准对比表与可选LLM认知修正。"""
    with connect() as conn:
        asset_row = conn.execute(
            "SELECT asset_name FROM user_decision_logs WHERE asset_id=? LIMIT 1",
            (asset_id,),
        ).fetchone()
        asset_name = asset_row[0] if asset_row else asset_id
        decisions = [dict(r) for r in conn.execute(
            "SELECT * FROM user_decision_logs WHERE asset_id=? ORDER BY decision_date",
            (asset_id,),
        ).fetchall()]
        reviews = {r["decision_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM decision_reviews ORDER BY review_date"
        ).fetchall()}

    if not decisions:
        return f"# {asset_id} 决策复盘\n\n暂无决策记录。"

    label_map = {"right": "✅正确", "wrong": "❌错误", "mixed": "➖混合", "too_early": "⏳过早"}

    lines = [f"# {asset_name}({asset_id}) 决策复盘", ""]
    lines.append("## 1. 判断概览")
    bullish = sum(1 for d in decisions if d.get("direction") == "bullish")
    bearish = sum(1 for d in decisions if d.get("direction") == "bearish")
    neutral = sum(1 for d in decisions if d.get("direction") == "neutral")
    reviewed = sum(1 for d in decisions if d["decision_id"] in reviews)
    lines.append(f"- 决策次数：{len(decisions)}")
    lines.append(f"- 看多：{bullish}次 / 看空：{bearish}次 / 中性：{neutral}次")
    lines.append(f"- 已完成复盘：{reviewed}次")

    grade_stats: dict[str, int] = {}
    for rv in reviews.values():
        g = rv.get("result_grade")
        if g:
            grade_stats[g] = grade_stats.get(g, 0) + 1
    if grade_stats:
        stat_str = " / ".join(f"{k} {v}" for k, v in sorted(grade_stats.items()))
        lines.append(f"- 细分等级统计：{stat_str}")
    lines.append("")

    # 结果表：优先 v2 表格渲染（有数值列），fallback 兼容
    table_rows = []
    for d in decisions:
        rv = reviews.get(d["decision_id"])
        if rv is None:
            table_rows.append({
                "decision_date": d["decision_date"][5:], "direction": d.get("direction"),
                "horizon": d.get("horizon"), "outcome_return": None,
                "benchmark_return": None, "excess_return": None,
                "result_label": None, "result_grade": None,
            })
        else:
            out_ret = rv.get("outcome_return")
            table_rows.append({
                "decision_date": d["decision_date"][5:], "direction": d.get("direction"),
                "horizon": d.get("horizon"),
                "outcome_return": float(out_ret) if out_ret is not None else None,
                "benchmark_return": rv.get("benchmark_return"),
                "excess_return": rv.get("excess_return"),
                "result_label": rv.get("result_label"), "result_grade": rv.get("result_grade"),
            })
    lines.append("## 2. 结果")
    lines.append(render_result_table(table_rows))
    lines.append("")

    lines.append("## 3. 主要依据")
    for d in decisions:
        reasons = json.loads(d.get("key_reasons") or "[]")
        if reasons:
            lines.append(f"- **{d['decision_date'][5:]} {d.get('asset_name')}**："
                         + "；".join(reasons))
    lines.append("")

    if use_llm:
        latest_numeric = None
        for d in reversed(decisions):  # 最近日期优先
            rv = reviews.get(d["decision_id"])
            if rv and rv.get("outcome_return") is not None:
                latest_numeric = (d, rv)
                break
        if latest_numeric is None:
            lines.append("## 4. 认知修正")
            lines.append("")
            lines.append("（无可复盘的数值记录）")
        else:
            dd, rv = latest_numeric
            try:
                from config_loader import get_llm_config, load_config
                from review_llm import generate_lessons
                llm_cfg = get_llm_config(load_config())
                result = generate_lessons(dd, rv, llm_cfg)
                lines.append("## 4. 认知修正")
                lines.append("")
                if result.get("status") == "ok" and result.get("lessons"):
                    ls = result["lessons"]
                    lines.append(f"**做对了**：{'；'.join(ls.get('what_went_right') or ['无'])}")
                    lines.append("")
                    lines.append(f"**做错了**：{'；'.join(ls.get('what_went_wrong') or ['无'])}")
                    lines.append("")
                    lines.append(f"**遗漏因素**：{'；'.join(ls.get('missed_factors') or ['无'])}")
                    lines.append("")
                    lines.append(f"**规则更新**：{ls.get('new_rule_learned', '无')}")
                    lines.append("")
                    lines.append(f"*（分析模型：{result.get('model')}）*")
                else:
                    lines.append(f"(教训生成失败：{result.get('error', '未知原因')})")
            except Exception as e:
                lines.append("## 4. 认知修正")
                lines.append("")
                lines.append(f"（教训闭环异常：{e}）")

    lines.append("")
    lines.append("---")
    lines.append("*本报告收益与结果由数据库确定性生成（规则版本见各列），非投资建议。*")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="决策复盘生成器 v2")
    parser.add_argument("--backfill", action="store_true", help="回填到期决策结果")
    parser.add_argument("--report", help="生成某资产复盘报告（如 GOLD）")
    parser.add_argument("--llm", action="store_true", help="复盘总结用LLM提炼教训")
    parser.add_argument("--days-offset", type=int, default=0, help="允许提前N天回填（测试用）")
    args = parser.parse_args()

    if args.backfill:
        r = backfill_decision_outcomes(days_offset=args.days_offset)
        print(json.dumps({k: v for k, v in r.items() if k != "filled_rows"},
                         ensure_ascii=False, indent=2))
    if args.report:
        print(generate_review_report(args.report, use_llm=args.llm))
    if not args.backfill and not args.report:
        parser.print_help()


if __name__ == "__main__":
    main()
