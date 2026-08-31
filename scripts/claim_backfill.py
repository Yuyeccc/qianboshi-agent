#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
claim_backfill.py — 维度落库（#3#4#5）：view_evidence_annotation → claim 表

把 task2 标注的维度（证据权威/推理类型/因果主线/支撑判定）回填进结构化 claim 表，
并把单一 confidence 拆成三维（evidence/reasoning/forecast）。task2 全量跑完后执行。

claim 表 schema 对齐 25_架构 + gpt 维度评审（31_）。

用法:
  env -u PYTHONPATH python scripts/claim_backfill.py [--limit N]
"""
import os, re, json, sqlite3, argparse
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS claim (
  claim_id TEXT PRIMARY KEY,
  view_id TEXT,
  claim_text TEXT,
  subject_entity TEXT,
  stance TEXT,
  horizon TEXT,
  inference_type TEXT,
  topic TEXT,
  evidence_authority TEXT,
  evidence_confidence REAL,
  reasoning_confidence REAL,
  forecast_confidence REAL,
  support_level TEXT,
  match_quality REAL,
  materiality TEXT,
  lifecycle_status TEXT,
  calc_id TEXT,
  updated_at TEXT DEFAULT (datetime('now'))
);
"""

# 三维 confidence 推导（确定性规则，不用 LLM）
# gpt审0902修正：authority/mq 缺失 → 三维全 NULL（下游 unrated + missing_data），
# 禁止默认 0.5 伪装成中置信
def conf3(authority, match_quality):
    if authority not in ("A", "B", "C", "D") or match_quality is None:
        return None, None, None
    ev = {"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3}[authority]
    rea = round(match_quality, 2)
    fore = round(min(1.0, rea * 0.9 + (0.1 if authority in ('A', 'B') else 0)), 2)
    return ev, rea, fore


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    conn = sqlite3.connect(QB)
    cur = conn.cursor()
    cur.executescript(SCHEMA)
    conn.commit()

    q = """SELECT a.view_id, v.claim, v.stance, v.horizon,
             a.evidence_authority, a.inference_type, a.topic, a.match_quality, a.supported,
             v.raw_json
          FROM view_evidence_annotation a
          JOIN view_raw v ON v.view_id=a.view_id"""
    rows = cur.execute(q).fetchall()
    if args.limit:
        rows = rows[:args.limit]

    n = 0
    for (view_id, claim, stance, horizon, auth, inference, topic,
         mq, supported, raw_json) in rows:
        try:
            d = json.loads(raw_json)
        except Exception:
            d = {}
        ent = d.get("entities") or {}
        subject = ",".join(filter(None, [x for k in ("stocks", "sectors", "themes")
                                         for x in (ent.get(k) or [])]))[:200]
        ev_c, rea_c, fore_c = conf3(auth, mq)
        support = "supported" if supported else "contradicted"
        # materiality 简化：match_quality 阈值
        mat = "high" if (mq or 0) >= 0.8 else ("medium" if (mq or 0) >= 0.5 else "low")
        life = "published" if supported else "monitoring"
        cur.execute(
            """INSERT OR REPLACE INTO claim
               (claim_id, view_id, claim_text, subject_entity, stance, horizon,
                inference_type, topic, evidence_authority,
                evidence_confidence, reasoning_confidence, forecast_confidence,
                support_level, match_quality, materiality, lifecycle_status, calc_id,
                updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
            (view_id, view_id, claim, subject, stance, horizon,
             inference, topic, auth, ev_c, rea_c, fore_c,
             support, mq, mat, life, None))
        n += 1
    conn.commit()
    tot = cur.execute("SELECT COUNT(*) FROM claim").fetchone()[0]
    conn.close()
    print(f"[claim] 回填 {n} 条 (库内共 {tot})")


if __name__ == "__main__":
    main()
