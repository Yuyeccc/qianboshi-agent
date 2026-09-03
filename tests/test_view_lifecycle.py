#!/usr/bin/env python3
"""观点生命周期单测（记忆体系 P0）：状态机/迁移幂等/excluded 可解释/日报过滤。

跑：cd E:\\qianboshi-agent && C:/Python314/python.exe -m pytest tests/test_view_lifecycle.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import view_lifecycle as lc  # noqa: E402


# ---------- fixtures ----------

def _jsonl(tmp: Path, excluded: list[str] | None = None) -> Path:
    rows = []
    excluded = set(excluded or [])
    n = 1
    for vid, ok in [(f"vid{n}", True), (f"vid{n+1}", True), (f"vid{n+2}", False)]:
        if vid in excluded:
            n += 1
            continue
        rows.append({
            "view_id": vid, "analyst": f"分析师{n}", "claim": f"看多 {n}",
            "confidence": 0.7, "date": "2026-06-27", "authority": "B",
            "entities": {"sectors": ["半导体"]}, "evidence": f"(00:{n:02d}:00) 原文",
            "horizon": "medium", "source_file": f"src{n}.txt",
        })
        n += 1
    # 补 excluded 行（黑名单行仍在 jsonl 中）
    for vid in excluded:
        rows.append({"view_id": vid, "analyst": "排除源", "claim": "坏时间戳",
                     "date": "2026-06-27", "authority": "D", "entities": {},
                     "evidence": "(00:99:99) 幻觉", "source_file": "bad.txt"})
    p = tmp / "structured_views.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


@pytest.fixture()
def db_env(tmp_path):
    views = _jsonl(tmp_path, excluded=["vid3"])
    ex = tmp_path / "excluded_view_ids.json"
    ex.write_text(json.dumps(["vid3"]), encoding="utf-8")
    db = tmp_path / "view_lifecycle.db"
    conn = lc.connect(db=db)
    yield {"conn": conn, "views": views, "excluded": ex, "db": db}
    conn.close()


# ---------- 迁移 ----------

def test_migrate_active_and_excluded(db_env):
    r = lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    assert r["total"] == 3
    assert r["active"] == 2
    assert r["expired"] == 1
    sm = lc.status_map(db=db_env["db"])
    assert sm == {"vid1": "active", "vid2": "active", "vid3": "expired"}
    row = db_env["conn"].execute(
        "SELECT data_quality, transition_reason FROM view_lifecycle WHERE view_id='vid3'").fetchone()
    assert row["data_quality"] == "suspect"
    assert "legacy_excluded" in row["transition_reason"]


def test_migrate_idempotent(db_env):
    r1 = lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    r2 = lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    assert r2["skipped"] == 3  # 全部已存在，零新插入
    assert lc.stats(db_env["conn"])["total"] == r1["total"] == 3


def test_migrate_dry_run_no_write(db_env):
    r = lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"],
                              excluded_path=db_env["excluded"], dry_run=True)
    assert r["dry_run"] and r["total"] == 3
    assert lc.stats(db_env["conn"])["total"] == 0


def test_migrate_preserves_transitioned_state(db_env):
    """已转移的观点重跑迁移不得被重置回 active（幂等=尊重现状态）。"""
    lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    lc.transition(db_env["conn"], "vid1", "confirmed", "行情验证通过", changed_by="test",
                  linked_outcome_id="out_1")
    lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    assert lc.status_map(db=db_env["db"])["vid1"] == "confirmed"


# ---------- 状态机 ----------

def test_transition_ok_and_history(db_env):
    lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    r = lc.transition(db_env["conn"], "vid1", "confirmed", "行情验证通过", changed_by="test",
                      linked_outcome_id="out_1")
    assert r["old_status"] == "active" and r["new_status"] == "confirmed"
    h = lc.history(db_env["conn"], "vid1")
    assert len(h) == 1 and h[0]["reason"] == "行情验证通过"


def test_transition_invalid_status_rejected(db_env):
    lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    with pytest.raises(ValueError):
        lc.transition(db_env["conn"], "vid1", "zzz", "非法")


def test_transition_requires_reason(db_env):
    lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    with pytest.raises(ValueError):
        lc.transition(db_env["conn"], "vid1", "confirmed", "   ")


def test_falsified_requires_outcome(db_env):
    lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    with pytest.raises(ValueError):
        lc.transition(db_env["conn"], "vid1", "falsified", "看错了")
    # 逃生门放行
    lc.transition(db_env["conn"], "vid1", "falsified", "看错了", skip_outcome_check=True)
    assert lc.status_map(db=db_env["db"])["vid1"] == "falsified"


def test_superseded_requires_target(db_env):
    lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    with pytest.raises(ValueError):
        lc.transition(db_env["conn"], "vid1", "superseded", "被新观点替代")
    lc.transition(db_env["conn"], "vid1", "superseded", "被新观点替代", superseded_by_view_id="vid2")
    assert lc.status_map(db=db_env["db"])["vid1"] == "superseded"


def test_same_status_rejected(db_env):
    lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    with pytest.raises(ValueError):
        lc.transition(db_env["conn"], "vid1", "active", "原地踏步")


def test_transition_unknown_view_rejected(db_env):
    lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    with pytest.raises(KeyError):
        lc.transition(db_env["conn"], "ghost_id", "confirmed", "不存在")


# ---------- 日报过滤（view_store facade 集成） ----------

def test_filter_views_excludes_inactive_when_flag_on(monkeypatch):
    import view_store
    views = [
        {"view_id": "v_ok", "date": "2026-09-01", "claim": "a"},
        {"view_id": "v_dead", "date": "2026-09-01", "claim": "b"},
        {"view_id": "v_unmigrated", "date": "2026-09-01", "claim": "c"},
    ]
    # flag 开：falsified/expired/superseded 剔除；未迁移保留（向后兼容）
    monkeypatch.setattr(view_store, "_lifecycle_status_map",
                        lambda config=None: {"v_ok": "active", "v_dead": "expired"})
    out = view_store.filter_views(views, date_range=None)
    ids = {v["view_id"] for v in out}
    assert ids == {"v_ok", "v_unmigrated"}


def test_filter_views_unchanged_when_flag_off(monkeypatch):
    import view_store
    views = [
        {"view_id": "v_ok", "date": "2026-09-01", "claim": "a"},
        {"view_id": "v_dead", "date": "2026-09-01", "claim": "b"},
    ]
    monkeypatch.setattr(view_store, "_lifecycle_status_map", lambda config=None: None)
    out = view_store.filter_views(views, date_range=None)
    assert {v["view_id"] for v in out} == {"v_ok", "v_dead"}


# ---------- lint 可解释性 ----------

def test_lint_reports_unexplained_excluded(tmp_path, monkeypatch, db_env):
    import memory_lint
    monkeypatch.setattr(memory_lint, "views_path", lambda: db_env["views"])
    monkeypatch.setattr(lc, "db_path", lambda: db_env["db"])  # memory_lint 内部调 view_lifecycle.db_path
    # 迁移后 excluded 全可解释 → 无 "不可解释" WARN
    lc.migrate_from_jsonl(db_env["conn"], views_path=db_env["views"], excluded_path=db_env["excluded"])
    result = memory_lint.run()
    assert not any("不可解释" in w for w in result["warnings"])
    assert not any("不在 lifecycle" in w for w in result["warnings"])
