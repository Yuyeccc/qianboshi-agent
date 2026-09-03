#!/usr/bin/env python3
"""事件时间轴每日补偿 reconcile（记忆体系 P1b，03 融合终版 §6.2 主路径）。

设计：源量级小（决策类 ~18 / view 痕迹 ~251 / resolved ~12.4K），reconcile = 全量扫描 +
source_fingerprint 幂等补缺——不用水位，天然不漏补录/迟到源；每轮成本 <2s。

    C:/Python314/python.exe scripts/reconcile_event_timeline.py            # 补缺（幂等）
    C:/Python314/python.exe scripts/reconcile_event_timeline.py --dry-run  # 预演统计
    C:/Python314/python.exe scripts/reconcile_event_timeline.py --json     # 机器可读

挂点（D5 已批）：先 CLI --once 手动/复盘后触发，观察 2-3 轮后接 orchestrator periodic。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import event_timeline as evt  # noqa: E402
import view_lifecycle  # noqa: E402
import build_event_timeline as build  # noqa: E402
from decision_db import decision_db_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="事件时间轴补偿 reconcile（幂等补缺）")
    parser.add_argument("--dry-run", action="store_true", help="预演：只统计不落库")
    parser.add_argument("--json", action="store_true", help="机器可读 JSON 输出")
    parser.add_argument("--db", help="覆盖 lifecycle 库路径（事件落点）")
    parser.add_argument("--decision-db", help="覆盖决策源库路径")
    parser.add_argument("--jsonl", help="覆盖 structured_views.jsonl 路径")
    parser.add_argument("--research-dir", help="覆盖研究报告中目录（默认 data/research）")
    parser.add_argument("--no-scan-reports", action="store_true",
                        help="跳过 P2 刀3 报告前置登记（默认 scan 幂等登记后事件化）")
    args = parser.parse_args()

    ev_db = args.db or view_lifecycle.db_path()
    dec_db = args.decision_db or decision_db_path()

    # P2 刀3：报告登记前置（幂等，report_docs 是 report_generated 事件源）
    if not args.no_scan_reports:
        from types import SimpleNamespace
        import report_docs as rdoc
        rd_args = SimpleNamespace(
            dry_run=args.dry_run,
            dir=args.research_dir or str(Path(__file__).resolve().parent.parent / "data" / "research"),
            views=args.jsonl or str(Path(__file__).resolve().parent.parent / "data" / "views" / "structured_views.jsonl"),
            db=ev_db)
        rdoc.cmd_scan(rd_args)

    conn = evt.connect(db=ev_db)
    before = evt.count_by_type(conn)
    before_total = sum(before.values())
    conn.close()

    result = build.build_all(ev_db, dec_db, args.jsonl, dry_run=args.dry_run)

    conn = evt.connect(db=ev_db)
    after_total = evt.total(conn)
    after = evt.count_by_type(conn)
    conn.close()

    delta = {k: after.get(k, 0) - before.get(k, 0)
             for k in set(before) | set(after) if after.get(k, 0) != before.get(k, 0)}
    out = {
        "before_total": before_total,
        "after_total": after_total,
        "delta_total": after_total - before_total,
        "delta_by_type": delta,
        "dry_run": args.dry_run,
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        flag = "（预演，未落库）" if args.dry_run else ""
        print(f"事件时间轴 reconcile{flag}: {before_total} -> {after_total} "
              f"(新增 {out['delta_total']})")
        for k, v in sorted(delta.items()):
            print(f"  +{k}: {v}")
        if not args.dry_run and out["delta_total"] == 0:
            print("  无缺漏，事件层与源一致。")
    if not args.dry_run and out["delta_total"] == 0:
        sys.exit(0)


if __name__ == "__main__":
    main()
