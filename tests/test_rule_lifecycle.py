# -*- coding: utf-8 -*-
"""rule_lifecycle 单测（P2 刀2）。"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import rule_lifecycle as rl  # noqa: E402


@pytest.fixture()
def tmpdb(tmp_path):
    p = tmp_path / "lifecycle.db"
    con = rl.connect(p)
    rl.ensure_schema(con)
    yield con
    con.close()


class TestFingerprint:
    def test_stable_and_scope_sensitive(self):
        assert rl.fingerprint("看多黄金") == rl.fingerprint(" 看多 黄金 ")
        assert rl.fingerprint("看多黄金", "黄金") != rl.fingerprint("看多黄金", "白银")


class TestInsertRule:
    def test_insert_proposed_with_history(self, tmpdb):
        rid = rl.insert_rule(tmpdb, "测试规则：回调至 X 加仓", "manual", "proposed", scope="黄金")
        assert rid
        row = tmpdb.execute("SELECT * FROM rule_lifecycle WHERE rule_id=?", (rid,)).fetchone()
        assert row["state"] == "proposed"
        assert row["rule_fingerprint"]
        h = tmpdb.execute("SELECT * FROM rule_state_history WHERE rule_id=?", (rid,)).fetchall()
        assert len(h) == 1 and h[0]["action"] == "propose"

    def test_duplicate_fingerprint_skipped(self, tmpdb):
        r1 = rl.insert_rule(tmpdb, "重复规则文本", "manual", "proposed")
        r2 = rl.insert_rule(tmpdb, "重复规则文本", "manual", "proposed")
        assert r1 and r2 is None

    def test_manual_legacy_active(self, tmpdb):
        rid = rl.insert_rule(tmpdb, "[黄金] 当日黄金涨→加投100", "manual_legacy", "active",
                             scope="黄金", rule_id="rule-001")
        assert rid == "rule-001"
        row = tmpdb.execute("SELECT * FROM rule_lifecycle WHERE rule_id='rule-001'").fetchone()
        assert row["activated_at"] and row["state"] == "active"


class TestTransition:
    def _mk(self, tmpdb, state="proposed"):
        return rl.insert_rule(tmpdb, f"规则 {state}", "manual", state, scope="X")

    def test_confirm_proposed_to_active(self, tmpdb):
        rid = self._mk(tmpdb, "proposed")
        ok, msg = rl.transition(tmpdb, rid, "active", "用户确认", by="user")
        assert ok and "proposed→active" in msg
        assert tmpdb.execute("SELECT state FROM rule_lifecycle WHERE rule_id=?", (rid,)).fetchone()[0] == "active"
        h = tmpdb.execute("SELECT action FROM rule_state_history WHERE rule_id=?", (rid,)).fetchall()
        assert [x["action"] for x in h] == ["propose", "confirm"]

    def test_illegal_from_active(self, tmpdb):
        rid = self._mk(tmpdb, "active")
        ok, msg = rl.transition(tmpdb, rid, "proposed", "回退")
        assert not ok and "非法流转" in msg

    def test_suspend_and_reactivate(self, tmpdb):
        rid = self._mk(tmpdb, "active")
        ok, _ = rl.transition(tmpdb, rid, "suspended", "暂缓观察")
        assert ok
        ok, _ = rl.transition(tmpdb, rid, "active", "重新激活")
        assert ok
        ok, _ = rl.transition(tmpdb, rid, "retired", "废弃")
        assert ok
        # retired 终态
        ok, _ = rl.transition(tmpdb, rid, "active", "复活")
        assert not ok

    def test_retired_terminal(self, tmpdb):
        rid = self._mk(tmpdb, "active")
        ok, _ = rl.transition(tmpdb, rid, "retired", "废弃")
        assert ok
        row = tmpdb.execute("SELECT state FROM rule_lifecycle WHERE rule_id=?", (rid,)).fetchone()
        assert row["state"] == "retired"

    def test_reason_required(self, tmpdb):
        rid = self._mk(tmpdb, "proposed")
        ok, msg = rl.transition(tmpdb, rid, "active", "")
        assert not ok and "reason" in msg

    def test_unknown_rule(self, tmpdb):
        ok, msg = rl.transition(tmpdb, "nope", "active", "x")
        assert not ok and "不存在" in msg


class TestRuleTextFromLegacy:
    def test_full_rule(self):
        r = {"scope": "黄金", "condition": {"scenario": "当日涨→加投100"}, "action": "notify_user"}
        t = rl.rule_text_from_legacy(r)
        assert "[黄金]" in t and "当日涨→加投100" in t and "notify_user" in t

    def test_no_scenario(self):
        r = {"scope": "铝", "condition": {"scenario": ""}, "action": "watch"}
        t = rl.rule_text_from_legacy(r)
        assert "watch" in t


class TestLoadReviewLessons:
    def test_filters_empty(self, tmp_path):
        db = tmp_path / "decision.db"
        con = __import__("sqlite3").connect(str(db))
        con.executescript("""
        CREATE TABLE decision_reviews(review_id TEXT PRIMARY KEY, decision_id TEXT,
            review_date TEXT, new_rule_learned TEXT, suggest_asset_card_update INTEGER DEFAULT 0);
        INSERT INTO decision_reviews VALUES('rev1','dec1','2026-08-01','不追高、回调再看',0);
        INSERT INTO decision_reviews VALUES('rev2','dec2','2026-08-01','',0);
        INSERT INTO decision_reviews VALUES('rev3','dec3','2026-08-01',NULL,0);
        """)
        con.commit()
        con.close()
        monkeypatch_ok = False
        orig = rl.DECISION_DB
        rl.DECISION_DB = db
        try:
            out = rl.load_review_lessons()
            assert len(out) == 1 and out[0]["new_rule_learned"] == "不追高、回调再看"
        finally:
            rl.DECISION_DB = orig


class TestMigrateFlow:
    def test_cmd_migrate_to_tmp(self, tmp_path, monkeypatch):
        # 造 tmp my_views.json（3 rules）→ migrate 全流程
        mv = {"rule_engine": {"rules": [
            {"id": "rule-001", "scope": "黄金", "condition": {"scenario": "当日黄金涨→加投100"},
             "action": "notify_user"},
            {"id": "rule-002", "scope": "创新药", "condition": {"scenario": "回调至1.15试仓"},
             "action": "notify_user"},
            {"id": "rule-003", "scope": "铝", "condition": {"scenario": ""}, "action": "watch"},
        ]}}
        mv_path = tmp_path / "my_views.json"
        mv_path.write_text(json.dumps(mv, ensure_ascii=False), encoding="utf-8")
        db_path = tmp_path / "lifecycle.db"
        monkeypatch.setattr(rl, "MY_VIEWS", mv_path)
        monkeypatch.setattr(rl, "DB_PATH", db_path)

        args = SimpleNamespace(dry_run=True)
        assert rl.cmd_migrate(args) == 0  # dry-run 不落库
        args = SimpleNamespace(dry_run=False)
        assert rl.cmd_migrate(args) == 0

        con = rl.connect(db_path)
        rows = con.execute("SELECT rule_id,state,rule_source FROM rule_lifecycle").fetchall()
        con.close()
        ids = {r["rule_id"] for r in rows}
        assert ids == {"rule-001", "rule-002", "rule-003"}
        assert all(r["state"] == "active" for r in rows)
        assert all(r["rule_source"] == "manual_legacy" for r in rows)
        # 幂等：重跑 0 新增
        assert rl.cmd_migrate(SimpleNamespace(dry_run=False)) == 0
        con = rl.connect(db_path)
        assert con.execute("SELECT COUNT(*) FROM rule_lifecycle").fetchone()[0] == 3
        con.close()


class TestSyncHint:
    def test_hint_no_write(self, tmpdb, capsys):
        rid = rl.insert_rule(tmpdb, "待确认规则", "manual", "proposed", scope="X")
        rl.transition(tmpdb, rid, "active", "确认", by="u")
        rl.print_rule_engine_sync_hint([rid], tmpdb)
        out = capsys.readouterr().out
        assert "同步提示" in out and "人工落盘" in out
