"""每日决策复盘任务 v2（cron 用，--no-agent 模式）。2026-08-27 升级

v2 流程：
1. registry/rules 自检（坏配置 → 告警文本退出，推飞书可见）
2. 行情新鲜度预检 + 定向补价（registry 所有 active 标的；缺价错误进日报告警段）
3. 回填到期决策结果（含映射变更 reopen；v2 判定：基准对比/噪声带/细分等级）
4. 为今日新复盘资产生成报告文件 {rdate}_{asset}_v2.md
5. stdout 输出日报（结论表+教训摘要+异常清单）；无到期决策静默

用法：
    C:\\Python314\\python.exe scripts/daily_decision_review.py
"""
import json
import sys
import os
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decision_review_generator import (
    backfill_decision_outcomes,
    generate_review_report,
)

REVIEWS_DIR = Path(__file__).resolve().parent.parent / "data" / "reviews"

# LLM 教训每日最大调用数（防超时与费用失控）
MAX_LESSON_CALLS = 3


def _alert_and_exit(msg: str) -> None:
    """配置级失败：stdout 输出告警（飞书可见）+ exit 1。"""
    print("# ⚠️ 决策复盘系统告警")
    print()
    print(msg)
    print()
    print(f"*时间：{datetime.now().isoformat(timespec='seconds')}*")
    sys.exit(1)


def _today_reviewed_assets() -> list[tuple[str, str]]:
    """今天新回填的 (review_date, asset_id) 列表——查库而非看文件。"""
    today = date.today().isoformat()
    from decision_db import connect
    out: list[tuple[str, str]] = []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.review_date, d.asset_id, MAX(r.created_at) AS latest
            FROM decision_reviews r
            JOIN user_decision_logs d ON d.decision_id = r.decision_id
            WHERE r.created_at >= ?
            GROUP BY d.asset_id
            ORDER BY latest DESC
            """,
            (today,),
        ).fetchall()
        for rdate, asset, _ in rows:
            if rdate and asset:
                out.append((rdate, asset))
    return out


def _check_price_freshness() -> list[str]:
    """行情新鲜度预检 + 定向补价。返回未能解决的错误清单。"""
    from asset_registry import load_registry, resolve_asset
    from price_backfill import ensure_price_window, is_fresh, load_trends

    registry = load_registry()
    trends = load_trends()
    errors: list[str] = []
    checked: set[str] = set()

    for asset_id, rec in registry.get("assets", {}).items():
        if rec.get("status") != "active":
            continue
        try:
            spec = resolve_asset(asset_id)
        except Exception as e:
            errors.append(f"{asset_id}: registry解析失败 {e}")
            continue
        primary = spec["primary_symbol"]
        benchmark = spec["benchmark_symbol"]
        pair = f"{primary}|{benchmark}"
        if pair in checked:
            continue
        checked.add(pair)

        need = []
        for sym in (primary, benchmark):
            if not is_fresh(trends, sym):
                need.append(sym)
        if not need:
            continue
        # 定向补价：t0 取 40 天前足够覆盖 medium 窗口
        t0 = (date.today() - timedelta(days=40)).isoformat()
        t1 = date.today().isoformat()
        result = ensure_price_window(spec, t0, t1, trends=trends)
        for e in result.get("errors", []):
            errors.append(f"{asset_id}: 补价失败 {e}")

    return errors


def main() -> None:
    # 1. 配置自检
    try:
        from asset_registry import load_registry, load_rules
        reg = load_registry()
        rules = load_rules()
    except Exception as e:
        _alert_and_exit(f"配置加载失败：{e}\n复盘系统未执行任何回填，请检查 asset_registry.json / review_rules.json")

    # 2. 行情新鲜度预检（不阻断——错误进日报异常段）
    price_errors: list[str] = []
    try:
        price_errors = _check_price_freshness()
    except Exception as e:
        price_errors.append(f"新鲜度预检整体异常：{e}")

    # 3. 回填（含 reopen / v2 判定）
    counts = backfill_decision_outcomes()
    print(f"[回填] {json.dumps({k: v for k, v in counts.items() if k != 'filled_rows'}, ensure_ascii=False)}",
          file=sys.stderr)
    if counts.get("reopened"):
        print(f"[reopen] 因映射变更重开并重算 {counts['reopened']} 条决策", file=sys.stderr)

    filled_rows = counts.get("filled_rows") or []
    reviewed_assets = _today_reviewed_assets()
    if not reviewed_assets and not counts.get("reopened"):
        # 无到期决策 → 静默（但预检异常仍要报告！）
        if price_errors:
            print("# ⚠️ 决策复盘系统告警")
            print()
            print("今日无到期决策，但行情巡检发现异常：")
            print()
            for e in price_errors:
                print(f"- {e}")
            sys.exit(0)
        return

    # 4. 生成 v2 报告文件（按资产去重）
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    assets = sorted({a for _, a in reviewed_assets})
    for asset in assets:
        try:
            md = generate_review_report(asset, use_llm=False)
            rdate = next(r for r, a in reviewed_assets if a == asset)
            path = REVIEWS_DIR / f"{rdate}_{asset}_v2.md"
            path.write_text(md, encoding="utf-8")
        except Exception as e:
            print(f"[report_fail] {asset}: {e}", file=sys.stderr)

    # 5. 日报 stdout
    label_emoji = {"right": "✅", "wrong": "❌", "mixed": "➖", "too_early": "⏳"}
    print(f"# 决策复盘日报（{date.today().isoformat()}）")
    print()
    if counts.get("reopened"):
        print(f"⚠️ 映射变更触发重算：{counts['reopened']} 条历史决策已重开重算（详见报告）")
        print()
    print("## 今日结论")
    print()
    for row in filled_rows:
        emoji = label_emoji.get(row.get("result_label"), "·")
        bench = f"{row['benchmark_return']:+.2f}%" if row.get("benchmark_return") is not None else "-"
        excess = f"{row['excess_return']:+.2f}%" if row.get("excess_return") is not None else "-"
        grade = f"（细分{row['result_grade']}）" if row.get("result_grade") else ""
        name = {"GOLD": "黄金", "INNOV_DRUG": "创新药", "TECH": "科技", "BAIJIU": "白酒",
                "ALUMINUM": "铝", "SEMI": "半导体", "BATTERY": "电池"}.get(row.get("asset_id"),
                                                                          row.get("asset_id"))
        print(f"- {name}({row.get('asset_id')}) {row.get('result_label') and ''}"
              f"{emoji} 标的{row['outcome_return']:+.2f}% | 基准{bench} | 超额{excess}{grade}")
    print()

    # 6. 教训摘要（LLM 有预算上限；wrong 的优先）
    def _lesson_priority(item):
        _, r = item
        return 0 if r.get("result_label") == "wrong" else 1

    lesson_budget = max(0, min(MAX_LESSON_CALLS, len(reviewed_assets)))
    pairs = sorted(zip([a for a, _ in reviewed_assets], filled_rows), key=_lesson_priority)[:lesson_budget] \
        if len(filled_rows) == len(reviewed_assets) \
        else [(a, None) for a, _ in reviewed_assets[:lesson_budget]]

    if pairs:
        print("## 教训摘要")
        print()
        try:
            from config_loader import get_llm_config, load_config
            from review_llm import generate_lessons
            llm_cfg = get_llm_config(load_config())
            for asset, row in pairs:
                try:
                    dec_row = None
                    rev_row = None
                    from decision_db import connect
                    with connect() as conn:
                        dr = conn.execute(
                            "SELECT * FROM user_decision_logs WHERE asset_id=? ORDER BY decision_date DESC LIMIT 1",
                            (asset,)).fetchone()
                        if dr:
                            dec_row = dict(dr)
                        if row is None and dec_row:
                            rr = conn.execute(
                                "SELECT * FROM decision_reviews WHERE decision_id=? ORDER BY created_at DESC LIMIT 1",
                                (dec_row["decision_id"],)).fetchone()
                            if rr:
                                rev_row = dict(rr)
                        elif row is not None:
                            rev_row = row
                    if not dec_row or not rev_row:
                        continue
                    result = generate_lessons(dec_row, rev_row, llm_cfg)
                    name = {"GOLD": "黄金", "INNOV_DRUG": "创新药", "TECH": "科技", "BAIJIU": "白酒",
                            "ALUMINUM": "铝", "SEMI": "半导体", "BATTERY": "电池"}.get(asset, asset)
                    if result.get("status") == "ok" and result.get("lessons"):
                        ls = result["lessons"]
                        rule = ls.get("new_rule_learned", "")
                        wrongs = ls.get("what_went_wrong") or []
                        line = f"- {name}："
                        if wrongs:
                            line += f"问题——{'；'.join(wrongs[:1])}。"
                        line += f"规则：{rule}" if rule else "无新规则。"
                        print(line)
                    else:
                        print(f"- {name}：（教训待补跑）")
                except Exception as e:
                    print(f"- {{}}：（教训生成异常：{{}}）".format(asset, e))
        except Exception as e:
            print(f"(教训模块异常：{e})")
        print()

    # 7. 异常段
    print("## 异常与待办")
    print()
    has_issue = False
    if price_errors:
        for e in price_errors:
            print(f"- 缺价/补价失败：{e}")
            has_issue = True
    if counts.get("no_data"):
        print(f"- {counts['no_data']} 条决策因行情缺失未回填（明晚自动重试）")
        has_issue = True
    if counts.get("skipped"):
        print(f"- {counts['skipped']} 条决策被跳过（未到期或未注册，详见 stderr 日志）")
        has_issue = True
    if not has_issue:
        print("- 无")
    print()
    print("---")
    print("*数值由数据库确定性计算；教训由deepseek-v4-flash基于证据包生成，非投资建议。*")


if __name__ == "__main__":
    main()
