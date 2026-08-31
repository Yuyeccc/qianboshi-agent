#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ru_pipeline.py — #6 reasoning_unit 第一阶段：建表 + 确定性窗口构造

依据 gpt-5.6-sol 设计（C:/tmp/gpt_reasoning_unit.md）：
  锚点归并不能直接对全量 transcript 做 LLM，先以 annotation 为锚构造窗口。

表：reasoning_unit / reasoning_unit_source / claim_reasoning_unit / reasoning_unit_window

用法：
  env -u PYTHONPATH python scripts/ru_pipeline.py         # 建表
  env -u PYTHONPATH python scripts/ru_pipeline.py --build-windows   # 构造窗口
"""
import os, json, sqlite3, argparse, hashlib, datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
EV = PROJ / "data" / "evidence" / "qianboshi_evidence.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reasoning_unit (
  reasoning_unit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT,
  start_ms INTEGER, end_ms INTEGER,
  source_text TEXT,
  unit_type TEXT,             -- assertion/reason/evidence/qualification/transition
  topic TEXT,
  inference_type TEXT,
  entity_json TEXT,
  normalized_proposition TEXT,
  primary_role TEXT,
  authority_level TEXT,
  grouping_confidence REAL,
  grouping_method TEXT,
  grouping_model TEXT,
  status TEXT DEFAULT 'pending',  -- pending/active/review
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS reasoning_unit_source (
  reasoning_unit_id INTEGER,
  candidate_sentence_id TEXT,
  char_start INTEGER, char_end INTEGER,
  sentence_order INTEGER,
  PRIMARY KEY (reasoning_unit_id, candidate_sentence_id, char_start, char_end)
);
CREATE TABLE IF NOT EXISTS claim_reasoning_unit (
  claim_id TEXT,
  reasoning_unit_id INTEGER,
  relation_role TEXT,          -- core_claim/reason/evidence/qualification/counterpoint/context
  relation_type TEXT,          -- supports/contradicts/qualifies/elaborates
  relation_confidence REAL,
  annotation_id TEXT,
  authority_level TEXT,
  inference_type TEXT,
  PRIMARY KEY (claim_id, reasoning_unit_id, relation_role)
);
CREATE TABLE IF NOT EXISTS reasoning_unit_window (
  window_id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT,
  start_ms INTEGER, end_ms INTEGER,
  input_hash TEXT,
  annotation_ids TEXT,         -- json array
  status TEXT DEFAULT 'pending',  -- pending/running/succeeded/failed/needs_review
  attempt_count INTEGER DEFAULT 0,
  completed_at TEXT,
  error_message TEXT
);
"""


def build_windows(conn_q):
    """给 501 条 annotation 构造归并窗口：quote 时间 ∩ candidate_sentence ±上下文。"""
    cur = conn_q.cursor()
    annos = cur.execute(
        """SELECT a.view_id, a.anchor_start_ms, a.anchor_end_ms, p.bv_id
           FROM view_evidence_annotation a JOIN view_provenance p ON p.view_id=a.view_id
           WHERE a.anchor_start_ms IS NOT NULL AND a.anchor_end_ms IS NOT NULL""").fetchall()
    # 按 bv 分组，读 candidate_sentence
    ev = sqlite3.connect(EV); ec = ev.cursor()
    bv_cs = {}
    for view_id, s, e, bv in annos:
        if bv not in bv_cs:
            bv_cs[bv] = ec.execute(
                "SELECT id,start_ms,end_ms,text FROM candidate_sentence "
                "WHERE raw_asset_id=? ORDER BY start_ms", (bv,)).fetchall()
    ev.close()

    def window_for(segs, s, e):
        # 找与 [s,e] 相交(±10s容差)的句子索引
        lo, hi = s - 10000, e + 10000
        idxs = [i for i, (cid, ss, ee, t) in enumerate(segs)
                if ss <= hi and ee >= lo]
        if not idxs:
            return None
        # 前后扩展 1-3 句
        i0, i1 = max(0, min(idxs) - 2), min(len(segs) - 1, max(idxs) + 2)
        return segs[i0:i1 + 1]

    wins = []
    for view_id, s, e, bv in annos:
        segs = bv_cs.get(bv) or []
        win = window_for(segs, s, e)
        if not win:
            continue
        win_s = win[0][1]; win_e = win[-1][2]
        ann_ids = [view_id]
        wins.append({"asset_id": bv, "start_ms": win_s, "end_ms": win_e,
                     "annotation_ids": ann_ids})
    # 合并同 BV 重叠窗口
    merged = dedupe_merge(wins)
    return merged


def dedupe_merge(wins):
    """合并同一 BV 中时间重叠(容差2s)的窗口，合并 annotation_ids。"""
    by_bv = {}
    for w in wins:
        by_bv.setdefault(w["asset_id"], []).append(w)
    out = []
    for bv, arr in by_bv.items():
        arr.sort(key=lambda x: x["start_ms"])
        cur = None
        for w in arr:
            if cur and w["start_ms"] <= cur["end_ms"] + 2000:
                cur["end_ms"] = max(cur["end_ms"], w["end_ms"])
                cur["annotation_ids"] += w["annotation_ids"]
            else:
                if cur:
                    out.append(cur)
                cur = dict(w)
        if cur:
            out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-windows", action="store_true")
    args = ap.parse_args()
    conn = sqlite3.connect(QB)
    conn.executescript(SCHEMA)
    conn.commit()
    # 建 window 表索引
    conn.execute("CREATE INDEX IF NOT EXISTS idx_window_bv ON reasoning_unit_window(asset_id)")
    conn.commit()
    if args.build_windows:
        wins = build_windows(conn)
        conn.execute("DELETE FROM reasoning_unit_window")  # 幂等
        for w in wins:
            h = hashlib.md5(json.dumps(w, sort_keys=True).encode()).hexdigest()[:16]
            conn.execute(
                """INSERT INTO reasoning_unit_window
                   (asset_id,start_ms,end_ms,input_hash,annotation_ids,status)
                   VALUES (?,?,?,?,?, 'pending')""",
                (w["asset_id"], w["start_ms"], w["end_ms"], h,
                 json.dumps(w["annotation_ids"], ensure_ascii=False)))
        conn.commit()
        print(f"[ru_window] 构造 {len(wins)} 个归并窗口")
    conn.close()


if __name__ == "__main__":
    main()
