#!/usr/bin/env python3
"""记忆冲突治理（记忆体系 P2 刀1，2026-09-03）。

memory_conflicts 显式化 + open→人工裁决闭环（03 融合终版 §7.1：方向/时域/事实/规则/
用户信念五类冲突；本刀先落 direction/temporal/user_belief 三类自动检测，factual/rule 随
刀2 与 claim 分级就位）。检测默认 --dry-run 出候选清单，--apply 才落库；裁决永远人工。

数据契约（2026-09-03 实查）：
- structured_views.jsonl 每行含 stance(bullish/neutral/bearish/watch/risk)/horizon(intraday/
  short/medium/long/unknown)/analyst/date/entities{sectors,themes,stocks,etfs,indexes,us_mapping}
- view_lifecycle.db: view_lifecycle 表 status(active/confirmed/falsified/...)
- user_view_versions.content_json: {asset,date,view,strategy,status}（无结构化 stance，
  user_belief 类用保守词表从 view/strategy 文本提取，检出率低属预期）

三类冲突：
1. direction：同 (canonical_entity, horizon) 组内 active/confirmed 多头簇 vs 空头簇对峙
   （各取 confidence 最高者为代表对，evidence 记簇规模）。幂等指纹 sha256(type|entity|horizon|a|b)。
2. temporal：同 (canonical, analyst, horizon) 按 date 序列 stance 翻转（bullish↔bearish），
   翻转前旧观点仍 active（应 supersede 而未）→ 冲突对。
3. user_belief：user 信念文本词表 stance × 现役观点对立，实体经 user key→canonical 对齐。

用法：
  C:/Python314/python.exe scripts/memory_conflicts.py detect [--dry-run|--apply] [--views jsonl] [--limit N]
  C:/Python314/python.exe scripts/memory_conflicts.py list [--status open] [--type direction] [--limit 50]
  C:/Python314/python.exe scripts/memory_conflicts.py resolve <conflict_id> --verdict a_wins|b_wins|neither|dismiss --reason "..." [--by xxx]
  C:/Python314/python.exe scripts/memory_conflicts.py stats
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from entity_coverage_audit import build_maps  # noqa: E402
from entity_normalizer import load_aliases  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "views" / "view_lifecycle.db"
DEFAULT_VIEWS = ROOT / "data" / "views" / "structured_views.jsonl"

STANCE_OPPOSITE = {"bullish": "bearish", "bearish": "bullish"}
CONFLICT_TYPES = ("direction", "temporal", "factual", "rule", "user_belief")
STATUSES = ("open", "resolved", "dismissed")
VERDICTS = ("a_wins", "b_wins", "neither", "dismiss")

# user 信念文本 stance 词表（保守：明确动作/态度词，避免假设句误报）
USER_BULLISH = ("看多", "看好", "做多", "可买", "买入", "持有", "加仓", "上涨", "看涨", "目标价上")
USER_BEARISH = ("看空", "不看好", "回避", "不碰", "清仓", "减仓", "卖出", "下跌", "看跌", "不买", "离场")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS memory_conflicts (
        conflict_id TEXT PRIMARY KEY,
        conflict_type TEXT NOT NULL CHECK(conflict_type IN ('direction','temporal','factual','rule','user_belief')),
        entity_key TEXT NOT NULL,
        horizon TEXT,
        analyst TEXT,
        view_id_a TEXT,
        view_id_b TEXT,
        stance_a TEXT,
        stance_b TEXT,
        evidence_summary TEXT,
        source_card_id TEXT,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','dismissed')),
        verdict TEXT,
        resolution_reason TEXT,
        resolved_at TEXT,
        resolved_by TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS conflict_history (
        history_id TEXT PRIMARY KEY,
        conflict_id TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('resolve','dismiss','reopen')),
        verdict TEXT,
        reason TEXT NOT NULL,
        by TEXT,
        at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_conflicts_status ON memory_conflicts(status);
    CREATE INDEX IF NOT EXISTS idx_conflicts_entity ON memory_conflicts(entity_key, conflict_type);
    """)


# ---------- 数据加载 ----------

def load_views(jsonl_path: Path) -> list[dict]:
    out = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append(d)
    return out


def load_lifecycle(con: sqlite3.Connection) -> dict[str, str]:
    try:
        return {r["view_id"]: r["status"] for r in con.execute("SELECT view_id, status FROM view_lifecycle")}
    except sqlite3.Error:
        return {}


def view_canonicals(view: dict, alias_map: dict, code_map: dict) -> list[str]:
    """view 的实体 → canonical 集（中文词全等 + 代码反查）。"""
    out: set[str] = set()
    e = view.get("entities") or {}
    for w in (e.get("sectors") or []) + (e.get("themes") or []):
        if isinstance(w, str) and w in alias_map:
            out.add(alias_map[w])
    for ch in ("etfs", "stocks", "indexes", "us_mapping"):
        for c in e.get(ch) or []:
            if isinstance(c, str) and c in code_map:
                out.add(code_map[c])
    return sorted(out)


def _conflict_id(ctype: str, entity: str, a: str, b: str, extra: str = "") -> str:
    raw = f"{ctype}|{entity}|{a}|{b}|{extra}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


# ---------- 检测器（纯函数，可单测） ----------

def _active(status_map: dict, view_id: str) -> bool:
    return status_map.get(view_id, "active") in ("active", "confirmed")


STRONG_BEAR = ("看空", "不看好", "清仓", "减仓", "离场", "回避", "别碰", "不碰", "卖出")
STRONG_BULL = ("看多", "看好", "加仓", "布局", "买入", "做多", "可买", "抄底")


def _text_ok(view: dict) -> bool:
    """claim 文本与 stance 标签一致性粗校验（强词表，双向都含/都不含=不判）。

    背景（2026-09-03 实查）：全库 bullish/bearish 4824 条中 86 条 claim-stance 矛盾
    （1.78%），脏 view 会误导方向冲突代表与换向序列——检测器内过滤，
    簇计数保留（只影响代表资格）。弱词（涨/跌/风险）不用防"中性偏多+规避风险"误伤。
    """
    s = view.get("stance")
    if s not in ("bullish", "bearish"):
        return True
    claim = str(view.get("claim") or "")
    has_bear = any(w in claim for w in STRONG_BEAR)
    has_bull = any(w in claim for w in STRONG_BULL)
    if has_bear and not has_bull:
        return s == "bearish"
    if has_bull and not has_bear:
        return s == "bullish"
    return True


def _pick_rep(cluster: list[dict]) -> dict:
    """簇代表：confidence 最高且 claim-stance 一致的 view（全脏则兜底取最高）。"""
    ordered = sorted(cluster, key=lambda x: -float(x.get("confidence") or 0.0))
    for v in ordered:
        if _text_ok(v):
            return v
    return ordered[0]


def detect_direction(views: list[dict], status_map: dict, alias_map: dict, code_map: dict) -> list[dict]:
    """同 (canonical, horizon) 组内 bullish 簇 vs bearish 簇（簇代表=confidence 最高）。"""
    groups: dict[tuple, dict[str, list]] = {}
    for v in views:
        if v.get("stance") not in ("bullish", "bearish"):
            continue
        if not _active(status_map, v.get("view_id", "")):
            continue
        for canon in view_canonicals(v, alias_map, code_map):
            key = (canon, v.get("horizon") or "unknown")
            groups.setdefault(key, {"bullish": [], "bearish": []})
            groups[key][v["stance"]].append(v)
    cands = []
    for (canon, horizon), clusters in groups.items():
        bulls, bears = clusters["bullish"], clusters["bearish"]
        if not bulls or not bears:
            continue
        ba = _pick_rep(bulls)
        bb = _pick_rep(bears)
        if ba["view_id"] == bb["view_id"]:
            continue
        cands.append({
            "conflict_type": "direction",
            "entity_key": canon,
            "horizon": horizon,
            "analyst": None,
            "view_id_a": ba["view_id"], "stance_a": "bullish",
            "view_id_b": bb["view_id"], "stance_b": "bearish",
            "evidence_summary": (f"多头簇 {len(bulls)} 条 vs 空头簇 {len(bears)} 条 "
                                 f"(同 {canon} {horizon})"),
        })
    return cands


def detect_temporal(views: list[dict], status_map: dict, alias_map: dict, code_map: dict,
                    max_flips: int = 8) -> list[dict]:
    """同 (canonical, analyst, horizon) 按 date 序列 stance 翻转，旧观点未 supersede。

    收敛口径（2026-09-03 实跑定）：组内翻转总数 ≤ max_flips（过滤直播类高频振荡源，
    如 钱博士直播 单组 51 次逐场翻多翻空=正常节奏非挂账），只报**最近一次**翻转
    （当下状态冲突点，人工裁决动作=旧观点 supersede 或 dismiss）。
    """
    groups: dict[tuple, list[dict]] = {}
    for v in views:
        if v.get("stance") not in ("bullish", "bearish"):
            continue
        if not v.get("date"):
            continue
        if not _text_ok(v):
            continue  # claim-stance 矛盾脏 view 不参与换向序列
        for canon in view_canonicals(v, alias_map, code_map):
            key = (canon, v.get("analyst") or "未知", v.get("horizon") or "unknown")
            groups.setdefault(key, []).append(v)
    cands = []
    for (canon, analyst, horizon), seq in groups.items():
        seq_sorted = sorted(seq, key=lambda x: (str(x.get("date")), str(x.get("timestamp") or "")))
        flips = []
        prev = None
        for v in seq_sorted:
            if prev is not None and prev["stance"] == STANCE_OPPOSITE.get(v["stance"]) \
                    and prev["date"] != v["date"]:
                flips.append((prev, v))
            prev = v
        if not flips or len(flips) > max_flips:
            continue
        old, new = flips[-1]
        if not _active(status_map, old["view_id"]):
            continue
        cands.append({
            "conflict_type": "temporal",
            "entity_key": canon,
            "horizon": horizon,
            "analyst": analyst,
            "view_id_a": old["view_id"], "stance_a": old["stance"],
            "view_id_b": new["view_id"], "stance_b": new["stance"],
            "evidence_summary": (f"{analyst} 同 {canon} {horizon} 观点 "
                                 f"{old['date']} {old['stance']} → {new['date']} {new['stance']} "
                                 f"(组内共翻转 {len(flips)} 次)，旧观点仍现役未 supersede"),
        })
    return cands


def user_key_to_canonicals(user_key: str, alias_map: dict, canon_names: list[str]) -> list[str]:
    """user 信念 key（如 科技股/半导体、黄金）→ canonical 集：key 各段与 canonical/alias 匹配。"""
    hits: set[str] = set()
    for seg in re.split(r"[/／、,，\s]+", user_key):
        seg = seg.strip()
        if not seg:
            continue
        if seg in alias_map:
            hits.add(alias_map[seg])
            continue
        for canon in canon_names:
            if len(canon) >= 2 and canon in seg:
                hits.add(canon)
    return sorted(hits)


def _user_stance(text: str) -> str | None:
    if any(w in text for w in USER_BEARISH):
        return "bearish"
    if any(w in text for w in USER_BULLISH):
        return "bullish"
    return None


def detect_user_belief(views: list[dict], status_map: dict, user_views: dict,
                       alias_map: dict, code_map: dict, canon_names: list[str]) -> list[dict]:
    """user 信念文本 stance × 现役观点对立，实体经 user key→canonical 对齐。

    收敛口径（2026-09-03 实跑定）：529 逐条对呛不可裁决 → 按 (user_key→canonical×对立向)
    簇级收敛，报现役簇代表（confidence 最高）+ 簇计数 1 条。
    """
    # 收集 (canonical, u_stance) → 对立现役观点列表
    buckets: dict[tuple, list[dict]] = {}
    meta: dict[tuple, dict] = {}
    for ukey, uinfo in user_views.items():
        text = " ".join(str(uinfo.get(k) or "") for k in ("view", "strategy"))
        u_stance = _user_stance(text)
        if u_stance is None:
            continue
        for canon in user_key_to_canonicals(ukey, alias_map, canon_names):
            gk = (canon, u_stance)
            meta.setdefault(gk, {"user_key": ukey, "user_text": text[:120]})
            for v in views:
                if v.get("stance") != STANCE_OPPOSITE.get(u_stance):
                    continue
                if not _active(status_map, v.get("view_id", "")):
                    continue
                if canon not in view_canonicals(v, alias_map, code_map):
                    continue
                buckets.setdefault(gk, []).append(v)
    cands = []
    for (canon, u_stance), opp_views in buckets.items():
        rep = _pick_rep(opp_views)
        m = meta[(canon, u_stance)]
        cands.append({
            "conflict_type": "user_belief",
            "entity_key": canon,
            "horizon": rep.get("horizon"),
            "analyst": rep.get("analyst"),
            "view_id_a": f"user:{m['user_key']}", "stance_a": u_stance,
            "view_id_b": rep["view_id"], "stance_b": rep["stance"],
            "evidence_summary": (f"用户信念[{m['user_key']}] 文本判 {u_stance} vs 现役 "
                                 f"{STANCE_OPPOSITE[u_stance]} 观点簇 {len(opp_views)} 条"
                                 f"(代表 {rep.get('analyst')} {rep['date']})"),
        })
    return cands


def dedupe(cands: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for c in cands:
        cid = _conflict_id(c["conflict_type"], c["entity_key"], c["view_id_a"], c["view_id_b"],
                           str(c.get("horizon") or "") + str(c.get("analyst") or ""))
        if cid in seen:
            continue
        seen.add(cid)
        out.append(c)
    return out


# ---------- CLI ----------

def cmd_detect(args) -> int:
    con = connect()
    ensure_schema(con)
    aliases = load_aliases()
    alias_map, code_map, canon_names, _ = build_maps(aliases)
    views = load_views(Path(args.views))
    status_map = load_lifecycle(con)

    cands = dedupe(
        detect_direction(views, status_map, alias_map, code_map)
        + detect_temporal(views, status_map, alias_map, code_map)
    )
    if args.with_user_belief:
        user_views = load_user_views(con)
        cands = dedupe(cands + detect_user_belief(views, status_map, user_views,
                                                  alias_map, code_map, canon_names))

    print(f"[detect] 扫描 {len(views)} views / {len(status_map)} lifecycle / 候选 "
          f"{len(cands)}（--dry-run 默认只列不落库）")
    by_type: dict[str, int] = {}
    for c in cands:
        by_type[c["conflict_type"]] = by_type.get(c["conflict_type"], 0) + 1
    print("[by_type]", by_type)
    for i, c in enumerate(cands[: args.limit], 1):
        cid = _conflict_id(c["conflict_type"], c["entity_key"], c["view_id_a"], c["view_id_b"],
                           str(c.get("horizon") or "") + str(c.get("analyst") or ""))
        print(f"  {i:>3} [{c['conflict_type']:<11}] {c['entity_key']:<6} {c.get('horizon'):<8} "
              f"{c['stance_a']:<8} {c['view_id_a'][:16]} vs {c['stance_b']:<8} {c['view_id_b'][:16]}  {c['evidence_summary'][:52]}")

    if args.apply:
        now = _utcnow()
        inserted = 0
        for c in cands:
            cid = _conflict_id(c["conflict_type"], c["entity_key"], c["view_id_a"], c["view_id_b"],
                               str(c.get("horizon") or "") + str(c.get("analyst") or ""))
            if con.execute("SELECT 1 FROM memory_conflicts WHERE conflict_id=?", (cid,)).fetchone():
                continue
            con.execute(
                "INSERT INTO memory_conflicts(conflict_id,conflict_type,entity_key,horizon,analyst,"
                "view_id_a,view_id_b,stance_a,stance_b,evidence_summary,status,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?, 'open', ?)",
                (cid, c["conflict_type"], c["entity_key"], c.get("horizon"), c.get("analyst"),
                 c["view_id_a"], c["view_id_b"], c["stance_a"], c["stance_b"], c["evidence_summary"], now))
            inserted += 1
        con.commit()
        print(f"[apply] 落库 {inserted} 条（幂等，重复跳过）")
    con.close()
    return 0


def load_user_views(con: sqlite3.Connection) -> dict:
    out = {}
    try:
        rows = con.execute(
            "SELECT uvv.view_key, uvv.content_json FROM user_view_current uvc "
            "JOIN user_view_versions uvv ON uvv.view_key=uvc.view_key "
            "AND uvv.version_no=uvc.current_version_no").fetchall()
    except sqlite3.Error:
        return out
    for r in rows:
        try:
            d = json.loads(r["content_json"]) if isinstance(r["content_json"], str) else r["content_json"]
        except (json.JSONDecodeError, TypeError):
            d = {}
        out[r["view_key"]] = d
    return out


def cmd_list(args) -> int:
    con = connect()
    ensure_schema(con)
    q = "SELECT * FROM memory_conflicts WHERE 1=1"
    params: list = []
    if args.status:
        q += " AND status=?"; params.append(args.status)
    if args.type:
        q += " AND conflict_type=?"; params.append(args.type)
    q += " ORDER BY created_at DESC LIMIT ?"; params.append(args.limit)
    rows = con.execute(q, params).fetchall()
    print(f"[list] {len(rows)} 条")
    for r in rows:
        print(f"  {r['conflict_id']} [{r['conflict_type']:<11}] {r['entity_key']:<6} {r['status']:<9} "
              f"{r['stance_a'] or '-':<8} {str(r['view_id_a'])[:14]} vs {r['stance_b'] or '-':<8} "
              f"{str(r['view_id_b'])[:14]}  {str(r['evidence_summary'])[:44]}")
    con.close()
    return 0


def cmd_resolve(args) -> int:
    con = connect()
    ensure_schema(con)
    row = con.execute("SELECT * FROM memory_conflicts WHERE conflict_id=?", (args.conflict_id,)).fetchone()
    if not row:
        print(f"[ERR] conflict 不存在: {args.conflict_id}", file=sys.stderr)
        return 2
    if row["status"] != "open":
        print(f"[ERR] conflict 已 {row['status']}（只允许 open→resolved/dismissed）", file=sys.stderr)
        return 2
    if not args.reason:
        print("[ERR] --reason 必填（裁决留痕纪律）", file=sys.stderr)
        return 2
    now = _utcnow()
    if args.verdict == "dismiss":
        new_status = "dismissed"
    else:
        new_status = "resolved"
    con.execute("UPDATE memory_conflicts SET status=?, verdict=?, resolution_reason=?, "
                "resolved_at=?, resolved_by=? WHERE conflict_id=?",
                (new_status, args.verdict, args.reason, now, args.by, args.conflict_id))
    con.execute("INSERT INTO conflict_history(history_id,conflict_id,action,verdict,reason,by,at) "
                "VALUES(?,?,?,?,?,?,?)",
                (uuid.uuid4().hex[:20], args.conflict_id,
                 "dismiss" if new_status == "dismissed" else "resolve",
                 args.verdict, args.reason, args.by, now))
    con.commit()
    print(f"[resolve] {args.conflict_id} → {new_status} (verdict={args.verdict})")
    con.close()
    return 0


def cmd_stats(args) -> int:
    con = connect()
    ensure_schema(con)
    print("[stats] memory_conflicts")
    for r in con.execute("SELECT conflict_type, status, COUNT(*) n FROM memory_conflicts "
                         "GROUP BY conflict_type, status ORDER BY conflict_type, status"):
        print(f"  {r['conflict_type']:<12} {r['status']:<9} {r['n']}")
    total = con.execute("SELECT COUNT(*) FROM memory_conflicts").fetchone()[0]
    open_n = con.execute("SELECT COUNT(*) FROM memory_conflicts WHERE status='open'").fetchone()[0]
    print(f"  total={total}  open={open_n}")
    con.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="记忆冲突治理 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_d = sub.add_parser("detect", help="检测冲突候选（默认 dry-run）")
    p_d.add_argument("--dry-run", dest="dry", action="store_true", help="只列候选（默认）")
    p_d.add_argument("--apply", action="store_true", help="落库（幂等）")
    p_d.add_argument("--views", type=str, default=str(DEFAULT_VIEWS))
    p_d.add_argument("--limit", type=int, default=50)
    p_d.add_argument("--with-user-belief", action="store_true",
                     help="启用第3类 user_belief（词表保守，检出率低属预期）")
    p_d.set_defaults(fn=cmd_detect)

    p_l = sub.add_parser("list", help="列出 conflicts")
    p_l.add_argument("--status", type=str, default="open", choices=STATUSES)
    p_l.add_argument("--type", dest="type", type=str, default=None, choices=CONFLICT_TYPES)
    p_l.add_argument("--limit", type=int, default=50)
    p_l.set_defaults(fn=cmd_list)

    p_r = sub.add_parser("resolve", help="裁决（open→resolved/dismissed，人工）")
    p_r.add_argument("conflict_id", type=str)
    p_r.add_argument("--verdict", required=True, choices=VERDICTS)
    p_r.add_argument("--reason", required=True)
    p_r.add_argument("--by", type=str, default="cli")
    p_r.set_defaults(fn=cmd_resolve)

    p_s = sub.add_parser("stats", help="统计")
    p_s.set_defaults(fn=cmd_stats)

    args = ap.parse_args()
    if args.cmd == "detect" and args.dry and args.apply:
        print("[ERR] --dry-run 与 --apply 互斥", file=sys.stderr)
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
