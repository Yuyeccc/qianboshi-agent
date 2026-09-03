#!/usr/bin/env python3
"""记忆健康检查 memory_lint 初版（记忆体系 P0，LLM Wiki lint 纪律的 qianboshi 化）。

P0 检查项（对应 03 融合版 §7.2）：
  [结构] lifecycle 库是否存在/已迁移、jsonl 可解析行、view_id 唯一性
  [过期] horizon 已知且超窗仍未复核的观点（WARN 清单，不自动改状态——lint 发现、人决定）
  [缺来源/缺质量] jsonl 中缺 source/entities 且 authority=D 的活跃观点（WARN）
  [可解释] excluded_view_ids 是否全部落库（应 100% 可解释）
  [一致性] jsonl 的 view_id 与 lifecycle 库行数差（未迁移增量）
退出码：0=干净 / 1=有 WARN / 2=结构级 FAIL（db 缺失等，仅提示不阻断日报）
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import view_lifecycle  # noqa: E402
from view_store import views_path  # noqa: E402

# horizon 建议复核窗口（天）：超过窗口仍未转移的观点 → WARN
HORIZON_REVIEW_DAYS = {"intraday": 3, "short": 14, "medium": 90, "long": 365}


def _load_jsonl_ids(p: Path) -> tuple[list[str], int, int, int]:
    """返回 (唯一 id 列表, 解析失败行数, 唯一 id 数, 重复 id 组数)。"""
    seen: dict[str, int] = {}
    bad = 0
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
            except Exception:
                bad += 1
                continue
            vid = v.get("view_id")
            if vid:
                seen[vid] = seen.get(vid, 0) + 1
    dups = sum(1 for c in seen.values() if c > 1)
    return list(seen.keys()), bad, len(seen), dups


def run(config: dict[str, Any] | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    fails: list[str] = []

    vp = views_path()
    lc_path = view_lifecycle.db_path()

    # [结构] db 与迁移状态
    if not vp.exists():
        fails.append(f"structured_views.jsonl 缺失: {vp}")
        return {"ok": False, "fails": fails, "warnings": warnings}
    ids, bad_lines, total_unique, dup_groups = _load_jsonl_ids(vp)
    if bad_lines:
        warnings.append(f"jsonl 有 {bad_lines} 行解析失败")
    if dup_groups:
        warnings.append(f"jsonl 有 {dup_groups} 组重复 view_id（lifecycle 幂等合并，属数据健康提示）")
    if not lc_path.exists():
        fails.append(f"lifecycle 库未建: {lc_path}（先跑 migrate_view_lifecycle.py）")
        return {"ok": False, "fails": fails, "warnings": warnings}

    sm = view_lifecycle.status_map(db=lc_path)
    db_total = len(sm)
    if db_total == 0:
        fails.append("lifecycle 库为空（未迁移？）")
        return {"ok": False, "fails": fails, "warnings": warnings}
    missing = total_unique - db_total if total_unique > db_total else 0
    if missing > 0:
        warnings.append(f"jsonl 有 {missing} 条观点未入 lifecycle（增量待迁移）")

    # [可解释] excluded 全落库
    ex_path = vp.with_name("excluded_view_ids.json")
    if ex_path.exists():
        ex = set(json.loads(ex_path.read_text(encoding="utf-8")))
        not_in_db = sorted(ex - set(sm.keys()))
        if not_in_db:
            warnings.append(f"excluded {len(not_in_db)} 条不在 lifecycle 库（不可解释，样例 {not_in_db[:3]}）")
        expired_cnt = sum(1 for v in ex if sm.get(v) == "expired")
        if expired_cnt != len(ex):
            warnings.append(f"excluded 仅 {expired_cnt}/{len(ex)} 落为 expired（其余状态需人工核对）")
    else:
        warnings.append("excluded_view_ids.json 缺失（无黑名单文件？）")

    # [过期] horizon 已知且超复核窗口仍 active —— 只对"近 30 天摄入"报警（近期问题需行动）；
    # 存量超窗（历史归档）只进 summary 提示，不刷屏（人工决定是否批量转移，P0.5 出工具）
    today = date.today()
    recent_overdue = 0
    stale_overdue = 0
    with vp.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
            except Exception:
                continue
            vid = v.get("view_id")
            if sm.get(vid) not in ("active", "active_low_quality"):
                continue
            hz = (v.get("horizon") or "unknown").lower()
            win = HORIZON_REVIEW_DAYS.get(hz)
            if not win:
                continue
            d = v.get("date")
            try:
                d0 = datetime.strptime(str(d), "%Y-%m-%d").date()
            except Exception:
                continue
            if (today - d0).days <= win:
                continue
            if (today - d0).days <= 30:
                recent_overdue += 1
            else:
                stale_overdue += 1
    if recent_overdue:
        warnings.append(f"{recent_overdue} 条近 30 天摄入观点已超复核窗口仍 active（需人工转移或复核）")
    if stale_overdue:
        warnings.append(f"{stale_overdue} 条存量超窗观点仍 active（历史归档，批量转移工具见 P0.5，暂不自动处理）")

    # [缺质量] 活跃观点中无实体且 authority=D
    lowq = 0
    with vp.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
            except Exception:
                continue
            vid = v.get("view_id")
            if sm.get(vid) != "active":
                continue
            if not (v.get("entities") or {}) and str(v.get("authority", "")) == "D":
                lowq += 1
    if lowq:
        warnings.append(f"{lowq} 条 active 观点无实体且 authority=D（可考虑转 active_low_quality）")

    # ── P1 检查（信念版本链 + 事件时间轴） ──
    import user_view_versions as uvv
    import event_timeline as et

    uvv_total = 0
    try:
        conn = uvv.connect(db=lc_path)
        # [P1a] current 孤儿：current 指向不存在版本
        orphans = conn.execute(
            """SELECT c.view_key FROM user_view_current c
               LEFT JOIN user_view_versions v ON v.version_id = c.current_version_id
               WHERE v.version_id IS NULL""").fetchall()
        if orphans:
            warnings.append(f"P1a 版本链 {len(orphans)} 个 current 孤儿: "
                            f"{[r['view_key'] for r in orphans][:5]}")
        # [P1a] 投影漂移：my_views.json views[] key 与 current key 集差
        mv = uvv.read_my_views()
        file_keys = {v.get("asset") for v in (mv.get("views") or []) if v.get("asset")}
        cur_keys = {r["view_key"] for r in conn.execute(
            "SELECT view_key FROM user_view_current").fetchall()}
        # 末版 retire 的 key 合法不在投影
        retired = {r["view_key"] for r in conn.execute(
            "SELECT v.view_key FROM user_view_versions v JOIN user_view_current c "
            "ON c.view_key=v.view_key AND v.version_id=c.current_version_id "
            "WHERE v.change_type='retire'").fetchall()}
        drift_extra = sorted(cur_keys - file_keys - retired)  # 链有文件无（未 retire）=新 key 未重建投影
        drift_missing = sorted(file_keys - cur_keys)          # 文件有链无=未迁移
        if drift_extra:
            warnings.append(f"P1a 投影漂移: 版本链 {len(drift_extra)} key 未入投影文件 "
                            f"(样例 {drift_extra[:3]}, 跑 append/rebuild_projection)")
        if drift_missing:
            warnings.append(f"P1a 投影漂移: my_views.json {len(drift_missing)} key 无版本链 "
                            f"(样例 {drift_missing[:3]}, 跑 migrate)")
        uvv_total = conn.execute("SELECT COUNT(*) FROM user_view_versions").fetchone()[0]
        conn.close()
    except Exception as e:
        warnings.append(f"P1a 版本链检查异常: {e}")

    evt_total = 0
    try:
        conn = et.connect(db=lc_path)
        evt_total = et.total(conn)
        if evt_total == 0:
            warnings.append("P1b 事件时间轴为空（跑 build_event_timeline.py 存量重建）")
        conn.close()
    except Exception as e:
        warnings.append(f"P1b 事件时间轴检查异常: {e}")

    # ── P2 检查（记忆冲突 / 规则生命周期 / 报告互链 / 词典覆盖） ──
    conflicts_open = 0
    rules_proposed_stale = 0
    report_total = 0
    report_unlinked = 0
    report_missing = []
    report_bad_links = 0
    try:
        import memory_conflicts as mcx
        conn = mcx.connect(db_path=lc_path)
        mcx.ensure_schema(conn)
        conflicts_open = conn.execute(
            "SELECT COUNT(*) FROM memory_conflicts WHERE status='open'").fetchone()[0]
        conn.close()
        if conflicts_open > 20:
            warnings.append(f"P2 记忆冲突 open {conflicts_open} 条堆积（>20，待人工裁决，"
                            f"跑 memory_conflicts.py list --status open）")
    except Exception as e:
        warnings.append(f"P2 conflicts 检查异常: {e}")

    try:
        import rule_lifecycle as rlx
        conn = rlx.connect(db_path=lc_path)
        rlx.ensure_schema(conn)
        stale = conn.execute(
            "SELECT COUNT(*) FROM rule_lifecycle WHERE state='proposed' "
            "AND proposed_at < datetime('now','-7 days')").fetchone()[0]
        rules_total = conn.execute("SELECT COUNT(*) FROM rule_lifecycle").fetchone()[0]
        conn.close()
        if stale:
            warnings.append(f"P2 规则 proposed {stale} 条超 7 天未审（跑 rule_lifecycle.py list --state proposed）")
    except Exception as e:
        rules_total = 0
        warnings.append(f"P2 rules 检查异常: {e}")

    try:
        import report_docs as rdoc
        conn = rdoc.connect(db_path=lc_path)
        rdoc.ensure_schema(conn)
        rows = conn.execute("SELECT doc_id, linked_view_ids FROM report_docs").fetchall()
        report_total = len(rows)
        # 报告互链断链：linked_view_ids 指向不在 lifecycle 的 view
        known = set(sm.keys())
        for r in rows:
            try:
                vids = json.loads(r["linked_view_ids"] or "[]")
            except Exception:
                vids = []
            if not vids:
                report_unlinked += 1
            bad = [v for v in vids if v not in known]
            if bad:
                report_bad_links += 1
        conn.close()
        # 未登记报告：data/research/*.json 无 report_docs 行（新报告未 scan）；
        # schema_valid=False 无效产物（report_docs scan 本就跳过）不算未登记
        rd_dir = Path(__file__).resolve().parent.parent / "data" / "research"
        if rd_dir.exists():
            doc_ids = {r["doc_id"] for r in rows}
            for jf in sorted(rd_dir.glob("*.json")):
                if jf.stem in doc_ids:
                    continue
                try:
                    jd = json.loads(jf.read_text(encoding="utf-8"))
                except Exception:
                    report_missing.append(jf.stem)
                    continue
                if (jd.get("_meta") or {}).get("schema_valid") is False:
                    continue  # 无效产物，scan 合法跳过
                report_missing.append(jf.stem)
        if report_missing:
            warnings.append(f"P2 报告未登记 {len(report_missing)} 份（跑 report_docs.py scan，"
                            f"样例 {report_missing[:3]}）")
        if report_bad_links:
            warnings.append(f"P2 报告互链断链 {report_bad_links} 条（linked_view_ids 指向非 lifecycle view）")
    except Exception as e:
        warnings.append(f"P2 report_docs 检查异常: {e}")

    coverage = None
    try:
        import entity_coverage_audit as eca
        from entity_normalizer import load_aliases as _la
        am, cm, cs, ck = eca.build_maps(_la())
        jl = Path(vp)
        st, _ = eca.scan(jl, am, cm, cs, ck, min_freq=1, by_entity=False)
        cn = st["cn_total"]
        coverage = round((st["cn_mode1"] + st["cn_mode2"]) / cn * 100, 2) if cn else 0.0
        if coverage < 85.0:
            warnings.append(f"P2 词典主口径覆盖率 {coverage}% < 85%（跑 entity_coverage_audit.py 补词典）")
    except Exception as e:
        warnings.append(f"P2 词典覆盖检查异常: {e}")

    ok = not fails and not warnings
    return {"ok": ok, "fails": fails, "warnings": warnings,
            "summary": {"jsonl_total": total_unique, "lifecycle_total": db_total,
                        "recent_overdue": recent_overdue, "stale_overdue": stale_overdue,
                        "dup_view_ids": dup_groups, "lowq": lowq,
                        "uvv_versions": uvv_total, "event_total": evt_total,
                        "conflicts_open": conflicts_open, "rules_total": rules_total,
                        "report_docs": report_total, "report_unlinked": report_unlinked,
                        "coverage_pct": coverage}}


def main() -> None:
    parser = argparse.ArgumentParser(description="记忆健康检查（memory_lint 初版）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    result = run()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"summary: {result['summary']}")
        for f in result["fails"]:
            print(f"[FAIL] {f}")
        for w in result["warnings"]:
            print(f"[WARN] {w}")
        if result["fails"]:
            print("lint 结论: FAIL(结构级，仅提示；日报不受影响)")
        elif result["warnings"]:
            print("lint 结论: WARN(有建议项)")
        else:
            print("lint 结论: OK")
    sys.exit(2 if result["fails"] else (1 if result["warnings"] else 0))


if __name__ == "__main__":
    main()
