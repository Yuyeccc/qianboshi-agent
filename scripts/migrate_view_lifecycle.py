#!/usr/bin/env python3
"""存量迁移入口（记忆体系 P0，架构文档 v6 §5.1）。

用法：
    C:/Python314/python.exe scripts/migrate_view_lifecycle.py --dry-run   # 只统计
    C:/Python314/python.exe scripts/migrate_view_lifecycle.py             # 落库（幂等）

迁移规则：structured_views.jsonl 全量 view_id → data/views/view_lifecycle.db
    - excluded_view_ids（坏时间戳/幻觉质量排除）→ expired + data_quality=suspect
    - 其余 → active
    - 已存在行不覆盖（幂等可重跑）
jsonl 原文件永不改动。落库前自动备份旧 db（若存在）。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import view_lifecycle  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="观点生命周期存量迁移（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只统计不落库")
    parser.add_argument("--db", help="覆盖 lifecycle 库路径")
    args = parser.parse_args()

    target = Path(args.db) if args.db else view_lifecycle.db_path()
    if not args.dry_run and target.exists():
        bak = str(target) + f".bak_{datetime.now():%Y%m%d_%H%M%S}_pre_migrate"
        shutil.copy2(target, bak)
        print(f"[备份] {target} -> {bak}")

    conn = view_lifecycle.connect(db=target)
    result = view_lifecycle.migrate_from_jsonl(conn, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    conn.close()

    if not args.dry_run:
        c2 = view_lifecycle.connect(db=target)
        print(json.dumps(view_lifecycle.stats(c2), ensure_ascii=False, indent=2))
        c2.close()


if __name__ == "__main__":
    main()
