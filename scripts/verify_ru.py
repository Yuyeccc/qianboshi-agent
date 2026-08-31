#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ru.py — #6 reasoning_unit 全量归并完成后的质量验收。

统计：unit 总数/active、source_text 非空率、unit_type/topic/inference_type 分布、
claim_reasoning_unit M:N 反链健康度、window 状态分布、与 claim 的联动率。

用法: env -u PYTHONPATH python scripts/verify_ru.py
"""
import sqlite3, sys
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
q = sqlite3.connect(QB); c = q.cursor()

print("=" * 60)
print("#6 reasoning_unit 质量验收")
print("=" * 60)

# window 状态
print("\n[window 状态分布]")
for r in c.execute("SELECT status, COUNT(*) FROM reasoning_unit_window GROUP BY status ORDER BY 2 DESC"):
    print(f"  {r[0]:<12} {r[1]}")

# ru 总览
tot_ru = c.execute("SELECT COUNT(*) FROM reasoning_unit").fetchone()[0]
act_ru = c.execute("SELECT COUNT(*) FROM reasoning_unit WHERE status='active'").fetchone()[0]
src_null = c.execute("SELECT COUNT(*) FROM reasoning_unit WHERE status='active' AND (source_text IS NULL OR source_text='')").fetchone()[0]
print(f"\n[reasoning_unit] 总 {tot_ru} | active {act_ru} | source_text 空 {src_null} "
      f"({src_null/act_ru*100:.1f}% 为空)" if act_ru else "\n[reasoning_unit] 无 active")

if act_ru:
    print("\n[unit_type 分布]")
    for r in c.execute("SELECT unit_type, COUNT(*) FROM reasoning_unit WHERE status='active' GROUP BY unit_type ORDER BY 2 DESC"):
        print(f"  {r[0]:<14} {r[1]} ({r[1]/act_ru*100:.0f}%)")

    print("\n[inference_type 分布]")
    for r in c.execute("SELECT inference_type, COUNT(*) FROM reasoning_unit WHERE status='active' GROUP BY inference_type ORDER BY 2 DESC"):
        print(f"  {r[0]:<16} {r[1]}")

    print("\n[topic 分布 top15]")
    for r in c.execute("SELECT topic, COUNT(*) FROM reasoning_unit WHERE status='active' GROUP BY topic ORDER BY 2 DESC LIMIT 15"):
        print(f"  {r[0]:<24} {r[1]}")

    print("\n[source_text 平均长度]")
    avg_len = c.execute("SELECT AVG(LENGTH(source_text)) FROM reasoning_unit WHERE status='active'").fetchone()[0]
    print(f"  {avg_len:.0f} 字符/单元")

# claim_reasoning_unit 反链
print("\n[claim_reasoning_unit 反链]")
cru = c.execute("SELECT COUNT(*) FROM claim_reasoning_unit").fetchone()[0]
seen_claims = c.execute("SELECT COUNT(DISTINCT claim_id) FROM claim_reasoning_unit").fetchone()[0]
tot_claims = c.execute("SELECT COUNT(*) FROM claim").fetchone()[0]
print(f"  关联记录 {cru} | 覆盖 claim {seen_claims}/{tot_claims} ({seen_claims/tot_claims*100:.0f}%)")
avg_ru_per_claim = c.execute("SELECT AVG(n) FROM (SELECT claim_id, COUNT(*) n FROM claim_reasoning_unit GROUP BY claim_id)").fetchone()[0]
print(f"  平均每 claim 关联 {avg_ru_per_claim:.2f} 个 ru")

# 冷启动检测：多窗归并但 0 claim 联动
print("\n[联动率检查]")
c2 = c.execute("SELECT COUNT(DISTINCT c.claim_id) FROM claim c WHERE c.claim_id NOT IN (SELECT DISTINCT claim_id FROM claim_reasoning_unit)").fetchone()[0]
print(f"  无关联 ru 的 claim：{c2}（若 >0 说明窗口覆盖未达，需补）")
q.close()
