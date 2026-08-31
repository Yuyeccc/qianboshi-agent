#!/usr/bin/env python3
"""
transcript_segment_indexer.py — Phase 0 数据底座第一刀

把 transcripts/ 下按行内嵌时间戳的 ASR 文本（[12.80s -> 14.60s] 文本）
重建为结构化 transcript_segment，落 SQLite 真相源 + JSONL 归档。

设计要点（对齐 25_工作台架构v3_融合终版.md 保真核心）：
  transcript_segment: raw_asset_id/version/speaker/start_ms/end_ms/text/
                       asr_confidence/correction_status
  - 原始文本永不删除（校正生成新版本，这里 txt 是 source of truth）
  - source 权威源: bv_source_map.json（900条）优先，缺的用观点库 analyst 回填
  - 脏行（箭头-->、嵌套[、行首截断）尽量提取时间戳，否则归 orphan 保留原文

用法:
  env -u PYTHONPATH python scripts/transcript_segment_indexer.py \
      [--db data/evidence/qianboshi_evidence.db] [--overwrite]
"""
import os
import re
import sys
import json
import glob
import time
import sqlite3
import argparse
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
TRANS_DIR = PROJ / "transcripts"
EVID_DIR = PROJ / "data" / "evidence"
VIEWS_FILE = PROJ / "data" / "views" / "structured_views.jsonl"
SRC_MAP_FILE = PROJ / "data" / "bv_source_map.json"
ANALYST_OUT = EVID_DIR / "bv_analyst.json"

# ── 时间戳解析（覆盖 -> / --> 两种箭头，数字后单位 s 可选） ──
# 标准: [12.80s -> 14.60s] 文本 ; [0.00 --> 3.28] 文本
TS_RE = re.compile(
    r'^\s*\[\s*(\d+\.?\d*)\s*s?\s*-{1,2}>\s*(\d+\.?\d*)\s*s?\s*\]\s*(.*)$'
)
# 兜底: 从整行任意位置抓 "NNs -> NNs]"（处理行首截断/嵌套）
TS_FALLBACK = re.compile(
    r'\[\s*(\d+\.?\d*)\s*s?\s*-{1,2}>\s*(\d+\.?\d*)\s*s?\s*\]'
)


def load_bv_analyst():
    """合并 bv_source_map + 观点库 analyst，输出 BV→source 权威映射。"""
    mapping = {}
    # 1) 权威源
    if SRC_MAP_FILE.exists():
        m = json.loads(SRC_MAP_FILE.read_text(encoding="utf-8"))
        mapping.update(m)
    # 2) 观点库回填（对缺失 BV）
    if VIEWS_FILE.exists():
        from collections import defaultdict, Counter
        bv_analysts = defaultdict(Counter)
        with open(VIEWS_FILE, encoding="utf-8") as f:
            for ln in f:
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                bv = d.get("source_bv", "")
                ana = d.get("analyst", "")
                if bv and ana:
                    bv_analysts[bv][ana] += 1
        filled = 0
        for bv, cnt in bv_analysts.items():
            if bv not in mapping:
                mapping[bv] = cnt.most_common(1)[0][0]
                filled += 1
        print(f"[source] 观点库回填 {filled} 个 BV 的分析师")
    return mapping


def parse_line(line):
    """解析一行 → (start_s, end_s, text) 或 None。
    优先标准格式；失败则兜底抓行内时间戳，剩余部分为文本。"""
    line = line.strip()
    if not line:
        return None
    m = TS_RE.match(line)
    if m:
        return float(m.group(1)), float(m.group(2)), m.group(3).strip()
    # 兜底：从行内任意位置提取时间戳
    m = TS_FALLBACK.search(line)
    if m:
        s = float(m.group(1))
        e = float(m.group(2))
        # 文本 = 去除时间戳部分后剩余
        text = TS_FALLBACK.sub("", line)
        text = re.sub(r'\s+', ' ', text).strip()
        # 若剩余只有符号（如 ']' 's -> ...s]'），视为无文本
        if not text or set(text) <= set(']s- >'):
            text = ""
        return s, e, text
    return None


def index_file(bv, fp, src_map):
    """解析单个转录文件 → 段列表。"""
    bv_id = _norm_bv(bv)
    source = src_map.get(bv, src_map.get(bv_id, "未知"))
    segments = []
    raw_file = fp.name
    try:
        lines = open(fp, encoding="utf-8").read().splitlines()
    except Exception as e:
        print(f"  ERR 读文件 {fp.name}: {e}")
        return segments, source
    corrected = "_corrected" in fp.name
    orphan = 0
    for i, ln in enumerate(lines):
        parsed = parse_line(ln)
        if parsed is None:
            orphan += 1
            seg = {
                "id": f"{bv_id}:{i}", "raw_asset_id": bv_id, "source": source,
                "order_idx": i, "speaker": None, "start_ms": None, "end_ms": None,
                "text": ln.strip(), "asr_confidence": None,
                "correction_status": "orphan", "raw_file": raw_file,
            }
            segments.append(seg)
            continue
        s, e, text = parsed
        seg = {
            "id": f"{bv_id}:{i}", "raw_asset_id": bv_id, "source": source,
            "order_idx": i, "speaker": None,
            "start_ms": int(round(s * 1000)), "end_ms": int(round(e * 1000)),
            "text": text, "asr_confidence": None,
            "correction_status": "corrected" if corrected else "raw",
            "raw_file": raw_file,
        }
        segments.append(seg)
    if orphan:
        print(f"  {bv}: {len(segments)} 段 / {orphan} 孤儿")
    return segments, source


def _norm_bv(bv):
    """规范化 BV：去掉 _pN 分P后缀，只留 BV 主 id。"""
    m = re.match(r'(BV[0-9A-Za-z]+)', bv)
    return m.group(1) if m else bv


SCHEMA = """
CREATE TABLE IF NOT EXISTS transcript_segment (
    id TEXT PRIMARY KEY,
    raw_asset_id TEXT NOT NULL,
    source TEXT,
    version INTEGER,
    speaker TEXT,
    start_ms INTEGER,
    end_ms INTEGER,
    text TEXT,
    asr_confidence REAL,
    correction_status TEXT,
    order_idx INTEGER,
    raw_file TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_seg_bv ON transcript_segment(raw_asset_id);
CREATE INDEX IF NOT EXISTS idx_seg_source ON transcript_segment(source);
CREATE INDEX IF NOT EXISTS idx_seg_start ON transcript_segment(start_ms);
"""


def build_db(db_path, overwrite):
    if db_path.exists() and not overwrite:
        print(f"[db] 已存在 {db_path}，--overwrite 覆盖")
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(EVID_DIR / "qianboshi_evidence.db"))
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只处理前N个文件(调试)")
    args = ap.parse_args()

    EVID_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    src_map = load_bv_analyst()
    # 落 BV→source 权威映射（含回填），供后续复用
    ANALYST_OUT.write_text(json.dumps(src_map, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print(f"[source] BV→分析师映射共 {len(src_map)} 条 → {ANALYST_OUT.name}")

    db_path = Path(args.db)
    conn = build_db(db_path, args.overwrite)
    cur = conn.cursor()

    # 优先 corrected，缺则 raw
    files = sorted(glob.glob(str(TRANS_DIR / "*_transcript_corrected.txt")))
    have = {Path(f).name.replace("_transcript_corrected.txt", "") for f in files}
    for rf in glob.glob(str(TRANS_DIR / "*_transcript.txt")):
        if "_corrected" in rf:
            continue
        bv = Path(rf).name.replace("_transcript.txt", "")
        if bv not in have:
            files.append(rf)
    files = sorted(files)
    if args.limit:
        files = files[: args.limit]
    print(f"[scan] 待索引转录文件 {len(files)} 个\n")

    total = orphan_all = sources_seen = 0
    sources = set()
    bv_indexed = 0
    BATCH = 5000
    buf = []
    for fi, fp in enumerate(files, 1):
        bv = Path(fp).stem
        segments, source = index_file(bv, Path(fp), src_map)
        if source not in ("未知", None):
            sources.add(source)
        if not segments:
            print(f"  [skip] {bv}: 0 行")
            continue
        bv_indexed += 1
        for seg in segments:
            buf.append(tuple([seg[k] for k in (
                "id", "raw_asset_id", "source", "order_idx", "speaker",
                "start_ms", "end_ms", "text", "asr_confidence",
                "correction_status", "raw_file")]))
        total += len(segments)
        orphan_all += sum(1 for s in segments if s["correction_status"] == "orphan")
        if len(buf) >= BATCH:
            cur.executemany(
                """INSERT OR IGNORE INTO transcript_segment
                   (id, raw_asset_id, source, order_idx, speaker, start_ms,
                    end_ms, text, asr_confidence, correction_status, raw_file)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""", buf)
            conn.commit()
            buf = []
        if fi % 50 == 0:
            print(f"  [{fi}/{len(files)}] 累计 {total} 段, {time.time()-t0:.0f}s")
    if buf:
        cur.executemany(
            """INSERT OR IGNORE INTO transcript_segment
               (id, raw_asset_id, source, order_idx, speaker, start_ms,
                end_ms, text, asr_confidence, correction_status, raw_file)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""", buf)
        conn.commit()

    # 汇总统计
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT raw_asset_id), COUNT(DISTINCT source) FROM transcript_segment")
    n_seg, n_bv, n_src = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM transcript_segment WHERE start_ms IS NULL")
    n_orphan = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT source) FROM transcript_segment WHERE source != '未知'")
    n_src_ok = cur.fetchone()[0]
    conn.close()

    manifest = {
        "script": "transcript_segment_indexer.py",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files_indexed": len(files),
        "files_with_segments": bv_indexed,
        "segments_total": n_seg,
        "segments_orphan": n_orphan,
        "bv_distinct": n_bv,
        "sources_distinct": n_src,
        "sources_known": n_src_ok,
        "db": str(db_path),
    }
    (EVID_DIR / "manifest_index.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "=" * 50)
    print("✅ 索引完成")
    print(f"   文件: {len(files)} (有段 {bv_indexed})")
    print(f"   segment: {n_seg}   orphan: {n_orphan} ({n_orphan/n_seg*100:.2f}%)")
    print(f"   独立 BV: {n_bv}   已知分析师: {n_src_ok}")
    print(f"   耗时: {time.time()-t0:.0f}s")
    print(f"   DB: {db_path}")
    print(f"   manifest: {EVID_DIR/'manifest_index.json'}")


if __name__ == "__main__":
    main()
