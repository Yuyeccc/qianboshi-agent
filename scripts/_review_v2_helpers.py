def ensure_review_columns(conn) -> None:
    """确保 decision_reviews 表包含复盘细分与规则版本字段。"""
    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(decision_reviews)")
    }

    if "result_grade" not in existing_columns:
        conn.execute(
            "ALTER TABLE decision_reviews ADD COLUMN result_grade TEXT"
        )

    if "rule_version" not in existing_columns:
        conn.execute(
            "ALTER TABLE decision_reviews ADD COLUMN rule_version TEXT"
        )


def reopen_on_mapping_changes(conn) -> int:
    """资产映射变更后重开关联判断，并删除已失效的复盘结果。"""
    import sys
    from asset_registry import detect_mapping_changes

    changes = detect_mapping_changes()
    if not changes:
        return 0

    asset_ids = [
        change["asset_id"]
        for change in changes
        if change.get("asset_id") is not None
    ]
    if not asset_ids:
        return 0

    for change in changes:
        print(
            f"[reopen] {change.get('asset_id')}: "
            f"{change.get('old_symbol')} -> {change.get('new_symbol')}",
            file=sys.stderr,
        )

    placeholders = ", ".join("?" for _ in asset_ids)
    where_clause = f"asset_id IN ({placeholders})"

    cursor = conn.execute(
        f"""
        UPDATE user_decision_logs
        SET status = 'open', updated_at = datetime('now')
        WHERE {where_clause}
        """,
        asset_ids,
    )
    conn.execute(
        f"""
        DELETE FROM decision_reviews
        WHERE decision_id IN (
            SELECT decision_id
            FROM user_decision_logs
            WHERE {where_clause}
        )
        """,
        asset_ids,
    )
    return cursor.rowcount


def compute_review_row(
    decision: dict, trends: dict, rules: dict
) -> dict | None:
    """调用复盘裁判并标准化为可写入 decision_reviews 的记录。"""
    from review_judge import review_decision

    review = review_decision(decision, trends, rules)
    if review.get("status") == "no_price":
        return None

    horizon_days_map = {
        "short": 5,
        "medium": 20,
        "long": 60,
    }
    review_date = review["review_date"]
    benchmark_return = review.get("benchmark_return")
    excess_return = review.get("excess_return")

    return {
        "review_id": f"rev_{decision['decision_id']}_{review_date}",
        "decision_id": decision["decision_id"],
        "review_date": review_date,
        "horizon_days": horizon_days_map.get(decision.get("horizon"), 20),
        "outcome_return": round(review["outcome_return"], 4),
        "benchmark_return": (
            round(benchmark_return, 4)
            if benchmark_return is not None
            else None
        ),
        "excess_return": (
            round(excess_return, 4)
            if excess_return is not None
            else None
        ),
        "result_label": review["result_label"],
        "result_grade": review.get("result_grade"),
        "rule_version": review.get("rule_version"),
    }


def render_result_table(rows: list[dict]) -> str:
    """将复盘结果渲染为 Markdown 表格。"""
    label_map = {
        "right": "✅正确",
        "wrong": "❌错误",
        "mixed": "➖混合",
        "too_early": "⏳过早",
    }

    def format_return(value) -> str:
        if value is None:
            return "-"
        return f"{value:+.2f}%"

    lines = [
        "| 日期 | 判断 | 周期 | 标的收益 | 基准收益 | 超额 | 主标签 | 细分 |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]

    for row in rows:
        result_label = row.get("result_label")
        main_label = label_map.get(result_label, "待回填")
        if result_label is None:
            main_label = "待回填"

        lines.append(
            "| {date} | {direction} | {horizon} | {outcome} | {benchmark} | "
            "{excess} | {label} | {grade} |".format(
                date=row.get("decision_date") or "-",
                direction=row.get("direction") or "-",
                horizon=row.get("horizon") or "-",
                outcome=format_return(row.get("outcome_return")),
                benchmark=format_return(row.get("benchmark_return")),
                excess=format_return(row.get("excess_return")),
                label=main_label,
                grade=row.get("result_grade") or "-",
            )
        )

    return "\n".join(lines)
