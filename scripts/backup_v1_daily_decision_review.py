"""每日决策复盘任务（cron 用，--no-agent 模式）。

流程：
1. 回填所有到期决策结果（--backfill 逻辑）
2. 找出"今天新回填"的资产（review_date == 今天）
3. 为每个到期资产生成复盘报告 → 写入 data/reviews/{YYYY-MM-DD}_{asset}.md
4. stdout 输出：有复盘 → 打印汇总报告（供飞书投递）；无到期 → 空输出（cron 静默）

用法：
    C:\\Python314\\python.exe scripts/daily_decision_review.py
"""
import json
import sys
import os
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decision_review_generator import (
    backfill_decision_outcomes,
    generate_review_report,
    connect,
)

REVIEWS_DIR = Path(__file__).resolve().parent.parent / "data" / "reviews"


def _pending_review_assets() -> list[str]:
    """所有 review_date<=today 且 data/reviews/ 尚无对应报告的资产（漏跑补跑都能补上）。"""
    today = date.today().isoformat()
    rows = []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.review_date, d.asset_id
            FROM decision_reviews r
            JOIN user_decision_logs d ON d.decision_id = r.decision_id
            WHERE r.review_date <= ?
            """,
            (today,),
        ).fetchall()
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in REVIEWS_DIR.glob("*.md")}  # {review_date}_{asset}
    pending: dict[str, str] = {}  # asset -> review_date
    for rdate, asset in rows:
        if rdate and asset and f"{rdate}_{asset}" not in existing:
            pending[asset] = rdate
    return [(a, pending[a]) for a in sorted(pending)]


def main() -> None:
    # 1. 回填到期决策
    counts = backfill_decision_outcomes()
    print(f"[回填] {json.dumps(counts, ensure_ascii=False)}", file=sys.stderr)

    # 2. 所有已到期但尚未生成报告的资产
    pending = _pending_review_assets()
    if not pending:
        # 无到期决策 → 空输出（cron --no-agent 模式静默）
        return

    # 3. 每个资产生成复盘报告
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    assets = [a for a, _ in pending]
    for asset, rdate in pending:
        md = generate_review_report(asset, use_llm=False)
        path = REVIEWS_DIR / f"{rdate}_{asset}.md"
        path.write_text(md, encoding="utf-8")

    # 4. stdout：飞书可读的复盘汇总
    print(f"# 📊 决策复盘日报（{date.today().isoformat()}）")
    print()
    print(f"今日到期回填资产：{', '.join(assets)}")
    print()
    for asset, _ in pending:
        md = generate_review_report(asset, use_llm=False)
        # 只输出核心部分（判断概览+结果表格），完整报告在文件里
        lines = md.splitlines()
        in_result = False
        for ln in lines:
            if ln.startswith("## 2. 结果"):
                in_result = True
            if in_result:
                print(ln)
            if in_result and ln.startswith("## 3."):
                break
        print()
    print("---")
    print("*收益与结果由数据库确定性生成，非投资建议。完整报告见 data/reviews/。*")


if __name__ == "__main__":
    main()
