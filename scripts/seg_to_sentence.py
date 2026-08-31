#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seg_to_sentence.py — #6 reasoning_unit 前置：把 ASR 细段聚合为句子级候选

transcript_segment 平均段长仅 1.9s/9字（faster-whisper 极致细颗粒），
不适合直接当语义单元。本脚本做**确定性预聚合**：按标点（。！？）和长停顿
（段间 gap > 阈值）把连续细段拼成句子级候选句，作为 reasoning_unit 的地基。

粒度设计（可调）：
  - 硬切：句子碰到中文句末标点 或 段间 gap > 停顿阈值(默认1.0s)
  - 软限：候选句目标 20-80 字（超长句内部再按逗号/停顿二次切分）

输出：candidate_sentence 表（BV/start_ms/end_ms/text/seg_ids）

用法:
  env -u PYTHONPATH python scripts/seg_to_sentence.py --bv BVxxxx --limit 200000
"""
import os, re, sqlite3, argparse
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
EV = PROJ / "data" / "evidence" / "qianboshi_evidence.db"
SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate_sentence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  raw_asset_id TEXT,
  start_ms INTEGER, end_ms INTEGER,
  text TEXT, seg_ids TEXT,
  sentence_idx INTEGER
);
CREATE INDEX IF NOT EXISTS idx_cs_bv ON candidate_sentence(raw_asset_id);
"""

# 句末标点 + 句内软断点
END_PUNC = set("。！？!?.…")
HARD_PUNC = set("。！？!?…")


def seg_to_sentences(segs, gap_ms=1000, min_len=8, max_len=60):
    """segs: list[(start_ms,end_ms,text)] 按 start 排序 → list[dict]。
    切分：句末标点硬切、段间gap硬切、逗号软断(>30字)、超max_len软切。"""
    sents = []
    cur = {"start": None, "end": None, "parts": [], "segs": []}

    def cur_len():
        return sum(len(p) for p in cur["parts"])

    def maybe_soft_flush():
        # 逗号软断：当前句已 >30 字且最后字符是逗号/顿号 → 切出
        if cur["parts"] and cur_len() >= 30:
            last_text = cur["parts"][-1].strip()
            if last_text and last_text[-1] in "，、；；,":
                sents.append(_flush(cur, min_len))
                return True
        return False

    for s, e, t in segs:
        t = (t or "").strip()
        if not t:
            continue
        if cur["start"] is None:
            cur["start"] = s
        if cur["end"] is not None and (s - cur["end"]) > gap_ms and cur["parts"]:
            sents.append(_flush(cur, min_len))
            cur = {"start": s, "end": e, "parts": [t], "segs": [f"{s}-{e}"]}
            continue
        if maybe_soft_flush():
            cur = {"start": s, "end": e, "parts": [t], "segs": [f"{s}-{e}"]}
            continue
        cur["parts"].append(t)
        cur["segs"].append(f"{s}-{e}")
        cur["end"] = e
        if t and t[-1] in END_PUNC:
            sents.append(_flush(cur, min_len))
            cur = {"start": None, "end": None, "parts": [], "segs": []}
        elif cur_len() > max_len:
            sents.append(_flush(cur, min_len))
            cur = {"start": None, "end": None, "parts": [], "segs": []}
    if cur["parts"]:
        sents.append(_flush(cur, min_len))
    return sents


def _flush(cur, min_len):
    if not cur["parts"]:
        return None
    text = "".join(cur["parts"])
    if len(text) < min_len:
        return None
    return {"start_ms": cur["start"], "end_ms": cur["end"],
            "text": text, "seg_ids": ",".join(cur["segs"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bv", default=None, help="只处理单个 BV（调试）")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    conn = sqlite3.connect(EV)
    cur = conn.cursor()
    cur.executescript(SCHEMA)
    if args.bv:
        sql = "SELECT start_ms,end_ms,text FROM transcript_segment WHERE raw_asset_id=? AND start_ms IS NOT NULL ORDER BY start_ms"
        rows = cur.execute(sql, (args.bv,)).fetchall()
        total = 1
    else:
        sql = "SELECT raw_asset_id,start_ms,end_ms,text FROM transcript_segment WHERE start_ms IS NOT NULL ORDER BY raw_asset_id,start_ms"
        rows = cur.execute(sql).fetchall()
        if args.limit:
            rows = rows[:args.limit]
        total = None
    # 归并到句子
    n_sent = 0
    if args.bv:
        cur.execute("DELETE FROM candidate_sentence WHERE raw_asset_id=?", (args.bv,))  # 幂等清该BV
        sents = [s for s in seg_to_sentences(rows) if s]
        insert_sentences(cur, args.bv, sents)
        n_sent = len(sents)
        conn.commit()
    else:
        # 按 BV 分组，跑前清该 BV（幂等）
        bv = None; buf = []
        def flush_bv():
            nonlocal n_sent
            if buf:
                cur.execute("DELETE FROM candidate_sentence WHERE raw_asset_id=?", (bv,))
                sents = [s for s in seg_to_sentences(buf) if s]
                insert_sentences(cur, bv, sents)
                n_sent += len(sents)
        for row in rows:
            if bv is None:
                bv = row[0]
            elif row[0] != bv:
                flush_bv()
                buf = []; bv = row[0]
            buf.append((row[1], row[2], row[3]))
        flush_bv()
        conn.commit()
    print(f"[seg_to_sentence] 生成句子候选 {n_sent} 条 (BV={args.bv or 'all'})")
    conn.close()


def insert_sentences(cur, bv, sents):
    for i, s in enumerate(sents):
        cur.execute(
            "INSERT OR IGNORE INTO candidate_sentence "
            "(raw_asset_id,start_ms,end_ms,text,seg_ids,sentence_idx) VALUES (?,?,?,?,?,?)",
            (bv, s["start_ms"], s["end_ms"], s["text"], s["seg_ids"], i))


if __name__ == "__main__":
    main()
