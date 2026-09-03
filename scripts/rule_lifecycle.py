#!/usr/bin/env python3
"""规则生命周期（记忆体系 P2 刀2，2026-09-03）。

03 融合终版 §7.1 纪律 + 风险 5：自动生成只进 proposed，用户确认才 active；
划界铁律：rule_lifecycle 是权威规则库，rule_engine.rules(my_views.json) 是用户文件
——active 同步=CLI 打印待人工落盘，绝不程序改写（HANDOFF 铁律 7 敏感文件）。

状态机：proposed →(confirm 人工)→ active →(suspend/retire 人工)→ suspended/retired
（trial 保留枚举待触发源，蓝图非目标不自动化）。

数据源现状（2026-09-03 实查）：
- decision_reviews.new_rule_learned 5 行全空 → extract 现 0 样本属预期，机制就位，
  复盘器未来填充后自动生效（复盘器改造登记 HANDOFF，非本刀）。
- rule_engine.rules 3 条（rule-001 黄金加投/002 创新药建仓/003 神火 watch）人工确认过
  = 天然 active → migrate 导入 legacy active（与 P1a user_view v1 迁移同构，幂等）。

用法：
  C:/Python314/python.exe scripts/rule_lifecycle.py migrate [--dry-run]       # 存量 rules → active
  C:/Python314/python.exe scripts/rule_lifecycle.py extract [--dry-run|--apply]  # review 教训 → proposed
  C:/Python314/python.exe scripts/rule_lifecycle.py add --text "..." [--scope X] [--source manual]  # 人工录 proposed
  C:/Python314/python.exe scripts/rule_lifecycle.py confirm <rule_id> --reason "..." [--by xxx]     # → active
  C:/Python314/python.exe scripts/rule_lifecycle.py suspend|retire <rule_id> --reason "..."
  C:/Python314/python.exe scripts/rule_lifecycle.py list [--state active]
  C:/Python314/python.exe scripts/rule_lifecycle.py stats
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

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "views" / "view_lifecycle.db"
DECISION_DB = ROOT / "data" / "qianboshi_decision.db"
MY_VIEWS = ROOT / "data" / "my_views.json"

STATES = ("proposed", "trial", "active", "suspended", "retired")
SOURCES = ("decision_review", "manual_legacy", "manual")
ACTIONS = ("propose", "confirm", "suspend", "retire", "reactivate")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """db_path 缺省=模块 DB_PATH（运行时读，便于测试 monkeypatch）。"""
    con = sqlite3.connect(str(db_path or DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS rule_lifecycle (
        rule_id TEXT PRIMARY KEY,
        rule_text TEXT NOT NULL,
        rule_source TEXT NOT NULL CHECK(rule_source IN ('decision_review','manual_legacy','manual')),
        source_review_id TEXT,
        source_decision_id TEXT,
        scope TEXT,
        action TEXT,
        state TEXT NOT NULL CHECK(state IN ('proposed','trial','active','suspended','retired')),
        rule_fingerprint TEXT NOT NULL UNIQUE,
        proposed_at TEXT,
        activated_at TEXT,
        state_changed_at TEXT,
        state_reason TEXT,
        activated_by TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rule_state_history (
        history_id TEXT PRIMARY KEY,
        rule_id TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('propose','confirm','suspend','retire','reactivate')),
        reason TEXT NOT NULL,
        by TEXT,
        at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_rule_state ON rule_lifecycle(state);
    """)


# ---------- 工具 ----------

def fingerprint(rule_text: str, scope: str = "") -> str:
    norm = re.sub(r"\s+", "", f"{scope}|{rule_text}")
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:20]


def load_my_views_rules() -> list[dict]:
    """读 rule_engine.rules（只读，敏感文件不改）。"""
    mv = json.load(open(MY_VIEWS, encoding="utf-8-sig"))
    return mv.get("rule_engine", {}).get("rules") or []


def load_review_lessons() -> list[dict]:
    """decision_reviews.new_rule_learned 非空行。"""
    if not os.path.exists(DECISION_DB):
        return []
    con = sqlite3.connect(str(DECISION_DB))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT review_id, decision_id, new_rule_learned FROM decision_reviews "
            "WHERE new_rule_learned IS NOT NULL AND TRIM(new_rule_learned) != ''").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def rule_text_from_legacy(r: dict) -> str:
    cond = r.get("condition") or {}
    scenario = str(cond.get("scenario") or "")
    scope = str(r.get("scope") or "")
    action = str(r.get("action") or "")
    if scenario:
        text = f"[{scope}] {scenario}"
    else:
        text = f"[{scope}] watch 关注（{action}）"
    return text + (f"（action={action}）" if scenario else "")


def insert_rule(con: sqlite3.Connection, rule_text: str, source: str, state: str,
                scope: str = "", action: str = "", source_review_id: str = "",
                source_decision_id: str = "", reason: str = "", by: str = "cli",
                rule_id: str | None = None) -> str | None:
    """INSERT 幂等（fingerprint 冲突返回 None）。"""
    fp = fingerprint(rule_text, scope)
    if con.execute("SELECT 1 FROM rule_lifecycle WHERE rule_fingerprint=?", (fp,)).fetchone():
        return None
    now = _utcnow()
    rid = rule_id or f"rl_{uuid.uuid4().hex[:16]}"
    con.execute(
        "INSERT INTO rule_lifecycle(rule_id,rule_text,rule_source,source_review_id,source_decision_id,"
        "scope,action,state,rule_fingerprint,proposed_at,activated_at,state_changed_at,state_reason,"
        "activated_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, rule_text, source, source_review_id or None, source_decision_id or None,
         scope or None, action or None, state, fp,
         now if state == "proposed" else None,
         now if state == "active" else None,
         now, reason or None, by if state == "active" else None, now))
    con.execute("INSERT INTO rule_state_history(history_id,rule_id,action,reason,by,at) "
                "VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex[:20], rid,
                 "propose" if state == "proposed" else "confirm",
                 reason or ("legacy 导入" if state == "active" else "manual 提案"), by, now))
    return rid


def transition(con: sqlite3.Connection, rule_id: str, to_state: str, reason: str,
               by: str = "cli") -> tuple[bool, str]:
    """状态转移（只追加）。返回 (ok, 信息)。"""
    row = con.execute("SELECT * FROM rule_lifecycle WHERE rule_id=?", (rule_id,)).fetchone()
    if not row:
        return False, f"rule 不存在: {rule_id}"
    cur = row["state"]
    allowed = {
        "proposed": ("active",),                    # 蓝图：自动只进 proposed，confirm 人工
        "active": ("suspended", "retired"),
        "suspended": ("active", "retired"),         # reactivate
        "retired": (),
        "trial": ("active",),
    }
    if to_state not in allowed.get(cur, ()):
        return False, f"非法流转 {cur}→{to_state}（允许: {allowed.get(cur) or '无'}）"
    if not reason:
        return False, "reason 必填（留痕纪律）"
    now = _utcnow()
    action_map = {"active": "confirm" if cur == "proposed" else "reactivate",
                  "suspended": "suspend", "retired": "retire"}
    con.execute("UPDATE rule_lifecycle SET state=?, state_changed_at=?, state_reason=?, "
                "activated_by=CASE WHEN ?='active' THEN ? ELSE activated_by END, "
                "activated_at=CASE WHEN ?='active' THEN ? ELSE activated_at END "
                "WHERE rule_id=?",
                (to_state, now, reason, to_state, by, to_state, now, rule_id))
    con.execute("INSERT INTO rule_state_history(history_id,rule_id,action,reason,by,at) "
                "VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex[:20], rule_id, action_map[to_state], reason, by, now))
    return True, f"{rule_id} {cur}→{to_state}"


def print_rule_engine_sync_hint(rule_ids: list[str], con: sqlite3.Connection) -> None:
    """confirm→active 后打印待同步 rule_engine.rules 的落盘 diff 提示（不写文件）。"""
    if not rule_ids:
        return
    rows = []
    for rid in rule_ids:
        r = con.execute("SELECT * FROM rule_lifecycle WHERE rule_id=?", (rid,)).fetchone()
        if r:
            rows.append(r)
    print("=" * 60)
    print("[同步提示] 以下规则已 active，但 my_views.json.rule_engine.rules 是敏感用户文件")
    print("（HANDOFF 铁律 7），CLI 不自动改写。请人工落盘（备份后）或确认由规则消费方读取")
    print("rule_lifecycle 权威库。待落盘条目：")
    for r in rows:
        print(f"  - {r['rule_id']} [{r['scope'] or ''}] {r['rule_text'][:80]}")
    print("=" * 60)


# ---------- CLI ----------

def cmd_migrate(args) -> int:
    con = connect()
    ensure_schema(con)
    rules = load_my_views_rules()
    print(f"[migrate] rule_engine.rules 共 {len(rules)} 条 → 导入 active（manual_legacy）")
    if args.dry_run:
        for r in rules:
            t = rule_text_from_legacy(r)
            print(f"  [dry] {r.get('id')} {t[:70]}")
        con.close()
        return 0
    n = 0
    for r in rules:
        rid = insert_rule(con, rule_text_from_legacy(r), "manual_legacy", "active",
                          scope=str(r.get("scope") or ""), action=str(r.get("action") or ""),
                          rule_id=str(r.get("id") or None), reason="legacy rule_engine 导入")
        if rid:
            n += 1
            print(f"  + {rid} active（{str(r.get('scope'))[:20]}）")
    con.commit()
    print(f"[migrate] 导入 {n} 条（幂等，fingerprint 重复跳过）")
    con.close()
    return 0


def cmd_extract(args) -> int:
    con = connect()
    ensure_schema(con)
    lessons = load_review_lessons()
    print(f"[extract] decision_reviews.new_rule_learned 非空 {len(lessons)} 条"
          "（当前 0 属预期：复盘器未填充，机制就位）")
    cands = []
    for r in lessons:
        text = str(r["new_rule_learned"]).strip()
        cands.append({"text": text, "review_id": r["review_id"], "decision_id": r["decision_id"]})
    print(f"[by_state] 候选 proposed {len(cands)}")
    for c in cands:
        print(f"  [proposed 候选] {c['text'][:80]}  (rev {c['review_id'][:20]})")
    if args.apply:
        n = 0
        for c in cands:
            rid = insert_rule(con, c["text"], "decision_review", "proposed",
                              source_review_id=c["review_id"], source_decision_id=c["decision_id"],
                              reason="复盘教训自动提取（只进 proposed，确认才 active）")
            if rid:
                n += 1
        con.commit()
        print(f"[apply] 落库 {n} 条 proposed")
    con.close()
    return 0


def cmd_add(args) -> int:
    con = connect()
    ensure_schema(con)
    rid = insert_rule(con, args.text, args.source, "proposed",
                      scope=args.scope or "", action=args.action or "",
                      reason="manual 录入", by=args.by)
    con.commit()
    if rid:
        print(f"[add] {rid} proposed（指纹唯一）")
    else:
        print("[add] 跳过：同文本规则已存在（fingerprint 去重）")
    con.close()
    return 0


def cmd_confirm(args) -> int:
    con = connect()
    ensure_schema(con)
    ok, msg = transition(con, args.rule_id, "active", args.reason, by=args.by)
    if not ok:
        print(f"[ERR] {msg}", file=sys.stderr)
        con.close()
        return 2
    con.commit()
    print(f"[confirm] {msg}")
    print_rule_engine_sync_hint([args.rule_id], con)
    con.close()
    return 0


def cmd_suspend_retire(args) -> int:
    con = connect()
    ensure_schema(con)
    ok, msg = transition(con, args.rule_id, args.cmd, args.reason, by=args.by)
    if not ok:
        print(f"[ERR] {msg}", file=sys.stderr)
        con.close()
        return 2
    con.commit()
    print(f"[{args.cmd}] {msg}")
    con.close()
    return 0


def cmd_list(args) -> int:
    con = connect()
    ensure_schema(con)
    q = "SELECT * FROM rule_lifecycle WHERE 1=1"
    params: list = []
    if args.state:
        q += " AND state=?"; params.append(args.state)
    q += " ORDER BY created_at DESC LIMIT ?"; params.append(args.limit)
    rows = con.execute(q, params).fetchall()
    print(f"[list] {len(rows)} 条")
    for r in rows:
        print(f"  {r['rule_id']:<24} {r['state']:<9} [{str(r['scope'] or ''):<8}] "
              f"{r['rule_text'][:60]}")
    con.close()
    return 0


def cmd_stats(args) -> int:
    con = connect()
    ensure_schema(con)
    for r in con.execute("SELECT state, COUNT(*) n FROM rule_lifecycle GROUP BY state"):
        print(f"  {r['state']:<10} {r['n']}")
    total = con.execute("SELECT COUNT(*) FROM rule_lifecycle").fetchone()[0]
    print(f"  total={total}")
    con.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="规则生命周期 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("migrate"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_migrate)

    p = sub.add_parser("extract"); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("add"); p.add_argument("--text", required=True)
    p.add_argument("--scope", default=""); p.add_argument("--action", default="")
    p.add_argument("--source", default="manual", choices=SOURCES)
    p.add_argument("--by", default="cli")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("confirm"); p.add_argument("rule_id")
    p.add_argument("--reason", required=True); p.add_argument("--by", default="cli")
    p.set_defaults(fn=cmd_confirm)

    for name in ("suspend", "retire"):
        p = sub.add_parser(name); p.add_argument("rule_id")
        p.add_argument("--reason", required=True); p.add_argument("--by", default="cli")
        p.set_defaults(fn=cmd_suspend_retire, cmd=name)

    p = sub.add_parser("list"); p.add_argument("--state", default=None, choices=STATES)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("stats"); p.set_defaults(fn=cmd_stats)

    args = ap.parse_args()
    if args.cmd == "extract" and args.dry_run and args.apply:
        print("[ERR] --dry-run 与 --apply 互斥", file=sys.stderr)
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
