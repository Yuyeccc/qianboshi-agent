#!/usr/bin/env python3
"""观点结果评估（记忆体系 P0.5 + P0.5b，架构文档 v6 §5.1）。

数据源：prediction_events（prediction_event_builder + outcome_updater 已产出
status=resolved 事件：view_id + entity + window_days(1/3/5/10/20) + return_pct）。
本脚本把 resolved 结果**聚合回写**到 view_lifecycle 状态机。

判定规则（保守、可解释，与 outcome_updater.is_hit 符号语义一致）：
  P0.5b horizon↔窗口匹配（2026-09-03 加）：先按观点 horizon 过滤事件——intraday ≥1d /
      short ≥5d / medium ≥10d / long ≥20d / unknown ≥10d；短窗口结果不参与长周期观点判定
      （无匹配窗口事件 → hold 不强行结论）
  实体级：每实体的多窗口 return 取平均 avg_r
          stance 与 avg_r 方向一致 且 |avg_r| >= CONFIRM_BAND → confirm 票
          stance 与 avg_r 方向相反 且 |avg_r| >= FALSIFY_BAND → falsify 票
  view 级：confirm 票>0 且 falsify 票==0 → confirmed 候选
          falsify 票>0 且 confirm 票==0 → falsified 候选
          冲突(两票都有)或无票 → 保持原状态（结果不充分不强行结论，03 融合版原则）
  已非 active 的 view 跳过（expired/falsified 等不动）。

安全设计：默认 --dry-run 只出候选清单给人核对；--apply 才 transition
（每笔留痕：reason 含实体/平均收益/窗口数/匹配窗口，linked_outcome_id=首票 event_id）。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import view_lifecycle  # noqa: E402

# 阈值（%）：|平均收益| 达到才给票；对称默认，可 --band 覆盖
CONFIRM_BAND = 5.0
FALSIFY_BAND = 5.0
# horizon↔窗口匹配（P0.5b）：观点按 horizon 只认达到匹配窗口的结果——
# intraday 1d 即验证；short 需 ≥5d；medium 需 ≥10d；long 需 ≥20d；unknown 保守 ≥10d。
# 短窗口结果不参与长周期观点判定（防"5d 小涨验证 medium 观点"式误判）。
HORIZON_MIN_WINDOW = {"intraday": 1, "short": 5, "medium": 10, "long": 20, "unknown": 10}
# prediction_events 库路径
DECISION_DB = Path(__file__).resolve().parent.parent / "data" / "qianboshi_decision.db"
JSONL_PATH = Path(__file__).resolve().parent.parent / "data" / "views" / "structured_views.jsonl"


def view_horizon_map(path: str | Path | None = None) -> dict[str, str]:
    """jsonl 全量 vid → horizon 映射（一次全扫 ~0.5s，evaluate 每轮调用幂等）。"""
    p = Path(path) if path else JSONL_PATH
    out: dict[str, str] = {}
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
            except Exception:
                continue
            vid = v.get("view_id")
            if vid:
                out[vid] = v.get("horizon") or "unknown"
    return out


def _match_horizon_window(events: list[dict[str, Any]], horizon: str | None) -> list[dict[str, Any]]:
    """horizon↔窗口过滤：只留 window_days >= 匹配值的事件（horizon=None 不过滤=旧行为）。"""
    if horizon is None:
        return events
    need = HORIZON_MIN_WINDOW.get(horizon, HORIZON_MIN_WINDOW["unknown"])
    return [e for e in events if (e.get("window_days") or 0) >= need]


# ---------- 纯聚合（可单测） ----------

def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def aggregate_view_events(events: list[dict[str, Any]], confirm_band: float = CONFIRM_BAND,
                          falsify_band: float = FALSIFY_BAND,
                          horizon: str | None = None) -> dict[str, Any]:
    """把一条 view 的全部 resolved 事件聚合成判定建议。

    events: [{entity, stance, return_pct, event_id}, ...]
    horizon: P0.5b 窗口匹配——None=不过滤（旧行为）；否则只统计达到匹配窗口的事件。
    返回 {"suggestion": confirmed|falsified|hold, "reason": str, "evidence": [...]}
    """
    if not events:
        return {"suggestion": "hold", "reason": "无 resolved 事件", "evidence": []}
    matched = _match_horizon_window(events, horizon)
    if horizon is not None and not matched:
        need = HORIZON_MIN_WINDOW.get(horizon, HORIZON_MIN_WINDOW["unknown"])
        return {"suggestion": "hold",
                "reason": f"无匹配窗口事件({horizon} 需 ≥{need}d 结果)", "evidence": []}
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for e in matched:
        by_entity.setdefault(e["entity"], []).append(e)

    confirm_tickets: list[dict[str, Any]] = []
    falsify_tickets: list[dict[str, Any]] = []
    for ent, evs in by_entity.items():
        stance = (evs[0].get("stance") or "").lower()
        if stance not in ("bullish", "bearish"):
            continue
        avg_r = _avg([e.get("return_pct") or 0.0 for e in evs])
        direction_ok = (stance == "bullish" and avg_r > 0) or (stance == "bearish" and avg_r < 0)
        if direction_ok and abs(avg_r) >= confirm_band:
            confirm_tickets.append({"entity": ent, "avg_return_pct": round(avg_r, 2),
                                    "windows": len(evs), "event_id": evs[0]["event_id"]})
        elif not direction_ok and abs(avg_r) >= falsify_band:
            falsify_tickets.append({"entity": ent, "avg_return_pct": round(avg_r, 2),
                                    "windows": len(evs), "event_id": evs[0]["event_id"]})

    if confirm_tickets and not falsify_tickets:
        return {"suggestion": "confirmed",
                "reason": f"{len(confirm_tickets)} 实体方向验证(超 +{confirm_band}%)",
                "evidence": confirm_tickets}
    if falsify_tickets and not confirm_tickets:
        return {"suggestion": "falsified",
                "reason": f"{len(falsify_tickets)} 实体方向证伪(超 -{falsify_band}%)",
                "evidence": falsify_tickets}
    if confirm_tickets and falsify_tickets:
        return {"suggestion": "hold",
                "reason": f"冲突：{len(confirm_tickets)} 验证 vs {len(falsify_tickets)} 证伪（人工裁决）",
                "evidence": confirm_tickets + falsify_tickets}
    return {"suggestion": "hold", "reason": "无实体达阈值", "evidence": []}


# ---------- 真实库接入 ----------

def fetch_resolved_events(conn: sqlite3.Connection, view_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT event_id, entity, stance, window_days, return_pct
           FROM prediction_events
           WHERE view_id=? AND status='resolved' AND return_pct IS NOT NULL""",
        (view_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def evaluate(dry_run: bool = True, limit: int | None = None, apply: bool = False,
             confirm_band: float = CONFIRM_BAND, falsify_band: float = FALSIFY_BAND,
             only: str | None = None) -> dict[str, Any]:
    """全量评估：lifecycle 中 active/active_low_quality 且有 resolved 结果的 view。

    only='falsified'/'confirmed' 时只落指定建议（另一个仅统计不转移）。
    """
    lc_conn = view_lifecycle.connect()
    rows = lc_conn.execute(
        "SELECT view_id FROM view_lifecycle WHERE status IN ('active','active_low_quality')"
    ).fetchall()
    active_ids = [r["view_id"] for r in rows]
    if limit:
        active_ids = active_ids[:limit]

    db = sqlite3.connect(str(DECISION_DB))
    db.row_factory = sqlite3.Row
    hz_map = view_horizon_map()  # P0.5b：vid → horizon（jsonl 全扫一次）
    suggestions = {"confirmed": [], "falsified": [], "hold": []}
    for vid in active_ids:
        events = fetch_resolved_events(db, vid)
        horizon = hz_map.get(vid) or "unknown"
        agg = aggregate_view_events(events, confirm_band=confirm_band,
                                    falsify_band=falsify_band, horizon=horizon)
        if agg["suggestion"] == "hold":
            continue
        suggestions[agg["suggestion"]].append({"view_id": vid, "horizon": horizon, **agg})
        if apply and agg["suggestion"] in ("confirmed", "falsified") and (only is None or agg["suggestion"] == only):
            ev = agg["evidence"][0]
            need = HORIZON_MIN_WINDOW.get(horizon, HORIZON_MIN_WINDOW["unknown"])
            try:
                view_lifecycle.transition(
                    lc_conn, vid, agg["suggestion"],
                    reason=f"auto-eval: {agg['reason']} [hz={horizon} 匹配窗口≥{need}d] (实体 {ev['entity']} avg {ev['avg_return_pct']}% / {ev['windows']}窗口)",
                    changed_by="evaluate_view_outcomes",
                    linked_outcome_id=ev["event_id"],
                    skip_outcome_check=True,
                )
            except (ValueError, KeyError) as e:
                suggestions[agg["suggestion"]][-1]["apply_error"] = str(e)
    db.close()
    return {"dry_run": not apply, "confirm_band": confirm_band, "falsify_band": falsify_band,
            "only": only, "horizon_window_match": True, "scanned": len(active_ids),
            "confirmed": suggestions["confirmed"], "falsified": suggestions["falsified"],
            "hold_count": len(suggestions["hold"])}


def main() -> None:
    parser = argparse.ArgumentParser(description="观点结果评估（P0.5）——把 resolved 结果回写状态机")
    parser.add_argument("--apply", action="store_true", help="实际转移（默认 dry-run 只出候选清单）")
    parser.add_argument("--limit", type=int, default=None, help="只评估前 N 条 active 观点（调试）")
    parser.add_argument("--band", type=float, default=None, help="覆盖判定阈值 %%（默认对称 5）")
    parser.add_argument("--confirm-band", type=float, default=CONFIRM_BAND, help="验证票阈值 %%")
    parser.add_argument("--falsify-band", type=float, default=FALSIFY_BAND, help="证伪票阈值 %%")
    parser.add_argument("--only", choices=["falsified", "confirmed"], default=None,
                        help="只落指定建议（另一个仅统计不转移）")
    args = parser.parse_args()

    if args.band:
        args.confirm_band = args.falsify_band = args.band
    result = evaluate(dry_run=not args.apply, limit=args.limit, apply=args.apply,
                      confirm_band=args.confirm_band, falsify_band=args.falsify_band,
                      only=args.only)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
