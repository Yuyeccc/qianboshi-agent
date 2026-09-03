#!/usr/bin/env python3
"""报告互链登记（记忆体系 P2 刀3，2026-09-03）。

03 融合终版 §7.3 好答案回填：研究报告按 doc 元数据登记互链（report_docs 权威表，
报告 JSON 原样只读，禁 _meta 扩展双写）。report_generated 事件由刀3 事件源接入
（build_event_timeline._build_report_docs），本脚本只负责登记。

数据源现状（2026-09-03 实查）：data/research/ 12 份 = research 型 10 份
（coreIssue/facts/opinions[]/evidence，schema_valid 判定） + portfolio_risk 型 2 份
（goal/holdingsExposure）；1 份 schema_valid=False 无效跳过。

登记字段：
- doc_id = 文件名 stem（20260903_185657_130b9112 唯一）
- report_type = research | portfolio_risk（顶层键判定）
- entity_key = coreIssue/goal/entity 文本词典扫描（restricted 词表=canonical 名+aliases，
  防 themes 泛词误伤如\"政策\"→创新药）+ holdingsExposure 代码反查，逗号 join
- linked_view_ids = opinions[{analyst,date,side}] 强匹配 structured_views
  （analyst+date 精确 + side→stance 映射），无引用留空
- status = valid | superseded | retracted（治理动作 set-status）

用法：
  C:/Python314/python.exe scripts/report_docs.py scan [--dry-run]      # 存量+增量登记（sha256 幂等）
  C:/Python314/python.exe scripts/report_docs.py list [--limit 20] [--status valid]
  C:/Python314/python.exe scripts/report_docs.py set-status <doc_id> --status superseded --reason "..."
  C:/Python314/python.exe scripts/report_docs.py stats
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from entity_coverage_audit import build_maps  # noqa: E402
from entity_normalizer import load_aliases  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "views" / "view_lifecycle.db"
RESEARCH_DIR = ROOT / "data" / "research"
VIEWS_JSONL = ROOT / "data" / "views" / "structured_views.jsonl"

SIDE_MAP = {"bull": "bullish", "bear": "bearish", "neutral": "neutral"}
STATUSES = ("valid", "superseded", "retracted")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path or DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS report_docs (
        doc_id TEXT PRIMARY KEY,
        report_type TEXT NOT NULL,
        entity_key TEXT,
        entity_raw TEXT,
        file_path TEXT NOT NULL,
        file_sha256 TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'valid' CHECK(status IN ('valid','superseded','retracted')),
        linked_view_ids TEXT,
        linked_decision_id TEXT,
        linked_review_id TEXT,
        linked_asset_ids TEXT,
        generated_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_report_status ON report_docs(status);
    """)


# ---------- 词典/实体 ----------

def build_scan_maps():
    """restricted 词表：canonical 名 + aliases（不含 themes 泛词）+ 代码反查表。"""
    aliases = load_aliases()
    entities = aliases.get("entities") or {}
    cn_map: dict[str, str] = {}
    code_map: dict[str, str] = {}
    canon_list: list[str] = []
    for canon, spec in entities.items():
        if not isinstance(spec, dict):
            continue
        canon_list.append(canon)
        cn_map[canon] = canon
        for w in spec.get("aliases") or []:
            if isinstance(w, str) and w:
                cn_map.setdefault(w, canon)
        for k in ("etfs", "stocks", "indexes"):
            for c in spec.get(k) or []:
                if isinstance(c, str) and c:
                    code_map.setdefault(c, canon)
    canon_sorted = sorted(canon_list, key=len, reverse=True)
    return cn_map, code_map, canon_sorted


def extract_entities(text: str, cn_map: dict, canon_sorted: list[str]) -> list[str]:
    """文本词典扫描（canonical/alias 全等子串，长词优先）。返回命中 canonical 有序去重。"""
    if not text:
        return []
    hits: list[str] = []
    seen: set[str] = set()
    for c in canon_sorted:
        if c in text and c not in seen:
            seen.add(c)
            hits.append(c)
    # aliases 层（canonical 名已扫过；alias 命中补 canonical）
    for w, canon in cn_map.items():
        if canon in seen or w in seen:
            continue
        if len(w) >= 2 and w in text:
            seen.add(canon)
            hits.append(canon)
    return hits


def report_type_of(d: dict) -> str:
    if "coreIssue" in d or "opinions" in d:
        return "research"
    if "goal" in d or "holdingsExposure" in d:
        return "portfolio_risk"
    return "unknown"


def _entity_from_report(d: dict, cn_map: dict, code_map: dict, canon_sorted: list[str]) -> tuple[str, str]:
    hits: list[str] = []
    raw_parts: list[str] = []
    if report_type_of(d) == "portfolio_risk":
        text = " ".join(str(d.get(k) or "") for k in ("goal", "entity"))
        raw_parts.append(text[:200])
        hits += extract_entities(text, cn_map, canon_sorted)
        exp = d.get("holdingsExposure") or {}
        for e in exp.get("exposed") or []:
            code = str(e.get("marketCode") or e.get("code") or "")
            if code and code in code_map:
                hits.append(code_map[code])
    else:
        text = " ".join(str(d.get(k) or "") for k in ("coreIssue", "summary"))
        raw_parts.append(text[:200])
        hits += extract_entities(text, cn_map, canon_sorted)
    # 去重保序
    seen: set[str] = set()
    out = [h for h in hits if not (h in seen or seen.add(h))]
    return ",".join(out), " ".join(x for x in raw_parts if x)[:300]


# ---------- opinion→view 强匹配 ----------

def build_view_index(jsonl_path: Path | str) -> dict:
    """(analyst, date) → {stance: [view_ids]}。"""
    jp = Path(jsonl_path)
    idx: dict[tuple, dict[str, list]] = {}
    if not jp.exists():
        return idx
    with open(jp, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
            except Exception:
                continue
            a = v.get("analyst")
            dt = v.get("date")
            st = v.get("stance")
            if not a or not dt or st not in SIDE_MAP.values():
                continue
            idx.setdefault((a, dt), {}).setdefault(st, []).append(v.get("view_id"))
    return idx


def match_opinions(d: dict, view_index: dict) -> list[str]:
    """opinions[{analyst,date,side}] → linked view_ids（精确匹配，无引用留空）。"""
    out: list[str] = []
    for op in d.get("opinions") or []:
        if not isinstance(op, dict):
            continue
        a = op.get("analyst")
        dt = op.get("date")
        side = SIDE_MAP.get(str(op.get("side") or ""))
        if not a or not dt or not side:
            continue
        vids = (view_index.get((a, dt)) or {}).get(side) or []
        for vid in vids:
            if vid not in out:
                out.append(vid)
    return out


# ---------- 登记 ----------

def scan_file(path: Path, con: sqlite3.Connection, cn_map: dict, code_map: dict,
              canon_sorted: list[str], view_index: dict, dry_run: bool) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"doc_id": path.stem, "skipped": "json 解析失败"}
    m = d.get("_meta") or {}
    if m.get("schema_valid") is False:
        return {"doc_id": path.stem, "skipped": "schema_valid=False 无效产物"}
    rtype = report_type_of(d)
    if rtype == "unknown":
        return {"doc_id": path.stem, "skipped": "未知报告结构"}
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    entity_key, entity_raw = _entity_from_report(d, cn_map, code_map, canon_sorted)
    linked_vids = match_opinions(d, view_index)
    gen_at = str(d.get("generatedAt") or m.get("generated_at") or "")[:19]
    now = _utcnow()
    existing = con.execute("SELECT file_sha256, status FROM report_docs WHERE doc_id=?",
                           (path.stem,)).fetchone() if not dry_run else None
    if existing and existing["file_sha256"] == sha:
        return {"doc_id": path.stem, "action": "unchanged"}
    try:
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        rel = path.name  # 测试/外部目录兜底
    row = {
        "doc_id": path.stem, "report_type": rtype, "entity_key": entity_key,
        "entity_raw": entity_raw, "file_path": rel,
        "file_sha256": sha, "status": "valid", "linked_view_ids": json.dumps(linked_vids, ensure_ascii=False),
        "linked_decision_id": None, "linked_review_id": None, "linked_asset_ids": None,
        "generated_at": gen_at, "created_at": now, "updated_at": now,
    }
    if dry_run:
        action = "new" if not existing else "changed"
        return {"doc_id": path.stem, "action": action, "entity_key": entity_key,
                "linked_views": len(linked_vids)}
    if existing:
        con.execute(
            "UPDATE report_docs SET report_type=?, entity_key=?, entity_raw=?, file_sha256=?, "
            "linked_view_ids=?, generated_at=?, updated_at=? WHERE doc_id=?",
            (rtype, entity_key, entity_raw, sha, row["linked_view_ids"], gen_at, now, path.stem))
        return {"doc_id": path.stem, "action": "updated", "entity_key": entity_key}
    con.execute(
        "INSERT INTO report_docs(doc_id,report_type,entity_key,entity_raw,file_path,file_sha256,"
        "status,linked_view_ids,linked_decision_id,linked_review_id,linked_asset_ids,generated_at,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row["doc_id"], row["report_type"], row["entity_key"], row["entity_raw"], row["file_path"],
         row["file_sha256"], row["status"], row["linked_view_ids"], None, None, None,
         row["generated_at"], now, now))
    return {"doc_id": path.stem, "action": "inserted", "entity_key": entity_key,
            "linked_views": len(linked_vids)}


def cmd_scan(args) -> int:
    con = connect(args.db)
    ensure_schema(con)
    cn_map, code_map, canon_sorted = build_scan_maps()
    view_index = build_view_index(Path(args.views))
    files = sorted(Path(args.dir).glob("*.json"))
    results = []
    for f in files:
        results.append(scan_file(f, con, cn_map, code_map, canon_sorted, view_index, args.dry_run))
    if not args.dry_run:
        con.commit()
    n_ok = sum(1 for r in results if r.get("action") in ("inserted", "updated", "new", "changed"))
    n_unch = sum(1 for r in results if r.get("action") == "unchanged")
    n_skip = sum(1 for r in results if "skipped" in r)
    print(f"[scan] {len(files)} 报告（{args.dir}）: 登记/更新 {n_ok}  未变 {n_unch}  跳过 {n_skip}"
          + ("（dry-run 未落库）" if args.dry_run else ""))
    for r in results:
        if r.get("action") in ("inserted", "updated", "new", "changed"):
            print(f"  {r['action']:<9} {r['doc_id']}  entity={r.get('entity_key') or '(空,待人工)'}"
                  + (f"  linked_views={r.get('linked_views')}" if "linked_views" in r else ""))
        elif "skipped" in r:
            print(f"  跳过      {r['doc_id']}  {r['skipped']}")
    con.close()
    return 0


def cmd_list(args) -> int:
    con = connect()
    ensure_schema(con)
    q = "SELECT * FROM report_docs WHERE 1=1"
    params: list = []
    if args.status:
        q += " AND status=?"; params.append(args.status)
    q += " ORDER BY created_at DESC LIMIT ?"; params.append(args.limit)
    rows = con.execute(q, params).fetchall()
    print(f"[list] {len(rows)} 条")
    for r in rows:
        lv = r["linked_view_ids"] or "[]"
        print(f"  {r['doc_id']:<24} {r['report_type']:<14} {r['status']:<10} "
              f"entity={r['entity_key'] or '空'}")
        print(f"    linked_views={lv[:80]}  sha={r['file_sha256'][:10]}  gen={r['generated_at']}")
    con.close()
    return 0


def cmd_set_status(args) -> int:
    con = connect()
    ensure_schema(con)
    row = con.execute("SELECT * FROM report_docs WHERE doc_id=?", (args.doc_id,)).fetchone()
    if not row:
        print(f"[ERR] doc 不存在: {args.doc_id}", file=sys.stderr)
        con.close()
        return 2
    if row["status"] == args.status:
        print(f"[set-status] {args.doc_id} 已是 {args.status}")
        con.close()
        return 0
    if not args.reason:
        print("[ERR] --reason 必填（状态变更留痕）", file=sys.stderr)
        con.close()
        return 2
    con.execute("UPDATE report_docs SET status=?, updated_at=? WHERE doc_id=?",
                (args.status, _utcnow(), args.doc_id))
    con.commit()
    print(f"[set-status] {args.doc_id}: {row['status']} → {args.status}（{args.reason}）")
    con.close()
    return 0


def cmd_stats(args) -> int:
    con = connect()
    ensure_schema(con)
    for r in con.execute("SELECT report_type, status, COUNT(*) n FROM report_docs "
                         "GROUP BY report_type, status"):
        print(f"  {r['report_type']:<16} {r['status']:<10} {r['n']}")
    total = con.execute("SELECT COUNT(*) FROM report_docs").fetchone()[0]
    with_ent = con.execute("SELECT COUNT(*) FROM report_docs WHERE entity_key IS NOT NULL "
                           "AND entity_key != ''").fetchone()[0]
    with_link = con.execute("SELECT COUNT(*) FROM report_docs WHERE linked_view_ids IS NOT NULL "
                            "AND linked_view_ids != '[]'").fetchone()[0]
    print(f"  total={total}  entity_key 命中 {with_ent}  含 view 互链 {with_link}")
    con.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="报告互链登记 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--dir", default=str(RESEARCH_DIR))
    p.add_argument("--views", default=str(VIEWS_JSONL))
    p.add_argument("--db", default=None)
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("list")
    p.add_argument("--status", default=None, choices=STATUSES)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("set-status")
    p.add_argument("doc_id")
    p.add_argument("--status", required=True, choices=STATUSES)
    p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_set_status)

    p = sub.add_parser("stats"); p.set_defaults(fn=cmd_stats)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
