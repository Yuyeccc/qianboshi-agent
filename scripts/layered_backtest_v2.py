#!/usr/bin/env python3
"""#14v2 分层前瞻回测（2026-08-31，方案 54 号融合定稿）。

把 prediction_events 命中率按观点推理链完整度（tuple_status）分层统计，禁止混合：
  ok / partial_anchor / template_only / no_ru + 总参考行（禁止引用）。

- 五层 × 三方向（all/bullish/bearish/risk）× 5 窗口 × 4 段（all/train/test/roll）
- 事件级 + view 级计权命中率（分母=COUNT(DISTINCT view_id)）
- Wilson 95% CI + binomial 双侧 5% vs 50% 随机基准 + min_sample=30 标注
- OOS：主切分 train<=2026-06-30 / test>=2026-07-01 + expanding 滚动 2026-07-15
- 四分母（resolved/error/skipped/eligible）+ 可评估覆盖率 = resolved/(resolved+error)
- 结果写 decision.db 新表 prediction_backtest_layers（run_id 唯一键，事务写入，可回滚）
- 只读：不写任何数据文件，不改现有表

用法:
    python scripts/layered_backtest_v2.py --report           # 分层报表 + 写库
    python scripts/layered_backtest_v2.py --report --dry-run # 只算不写库
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyst_score_builder import wilson_interval  # noqa: E402

DECISION_DB = ROOT / "data" / "qianboshi_decision.db"
STATUS_FILE = ROOT / "data" / "view_tuple_status.json"
REPORT_DIR = ROOT / "data" / "backtest"

LAYERS = ["ok", "partial_anchor", "template_only", "no_ru"]
DIRECTIONS = ["all", "bullish", "bearish", "risk"]
WINDOWS = [1, 3, 5, 10, 20]
SEGMENTS = ["all", "train", "test", "roll"]
MIN_SAMPLE = 30
TRAIN_CUTOFF = "2026-06-30"   # train <= cutoff
TEST_CUTOFF = "2026-07-01"    # test >= cutoff
ROLL_CUTOFF = "2026-07-15"    # expanding 滚动对照段 >= cutoff

# 命中规则（与 analyst_score_builder 内联 SQL 一致，勿改）
def is_hit(stance: str, return_pct: float, window_days: int) -> bool:
    if stance == "bullish":
        return return_pct > 0
    if stance == "bearish":
        return return_pct < 0
    if stance == "risk":
        if window_days <= 3:
            return return_pct < -0.5
        if window_days <= 10:
            return return_pct < -1.0
        return return_pct < -2.0
    return False


def binomial_two_sided_p(hits: int, total: int, p0: float = 0.5) -> float:
    """正态近似双侧 p 值。"""
    if total <= 0:
        return 1.0
    mean = total * p0
    std = math.sqrt(total * p0 * (1 - p0))
    if std == 0:
        return 1.0
    z = abs(hits - mean) / std
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))


def load_status_map(path: Path) -> dict[str, str]:
    """view_id → layer（any_ok 聚合已由 Mac 导出时完成）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {vid: info["layer"] for vid, info in data.items()}


def load_events() -> list[dict[str, Any]]:
    """全量 prediction_events（含状态，用于四分母 + resolved 明细）。"""
    con = sqlite3.connect(DECISION_DB)
    rows = con.execute(
        "SELECT view_id, entity, entity_type, stance, window_days, event_date, "
        "return_pct, status, skip_reason, analyst FROM prediction_events"
    ).fetchall()
    con.close()
    cols = ["view_id", "entity", "entity_type", "stance", "window_days", "event_date",
            "return_pct", "status", "skip_reason", "analyst"]
    return [dict(zip(cols, r)) for r in rows]


def segment_of(event_date: str) -> list[str]:
    """事件所属段（可属多段：all 恒在，train/test/roll 按日期）。"""
    segs = ["all"]
    if event_date <= TRAIN_CUTOFF:
        segs.append("train")
    if event_date >= TEST_CUTOFF:
        segs.append("test")
    if event_date >= ROLL_CUTOFF:
        segs.append("roll")
    return segs


def compute_layer_stats(events: list[dict[str, Any]], layer_map: dict[str, str]) -> dict:
    """分层统计 → {layer: {direction: {window: {segment: {event, view}}}}}."""
    # 事件级：key = (layer, direction, window, segment) -> [hit_flags]
    ev_groups: dict[tuple, list[bool]] = defaultdict(list)
    # view 级：key = (layer, direction, window, segment, view_id) -> max(hit)
    vw_groups: dict[tuple, dict[str, bool]] = defaultdict(dict)
    # 四分母
    denom: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # skipped 原因
    skip_reasons: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for ev in events:
        layer = layer_map.get(ev["view_id"], "no_ru")
        if layer not in LAYERS:
            layer = "no_ru"
        status = ev["status"]
        denom[layer][status] += 1
        if status == "skipped" and ev["skip_reason"]:
            skip_reasons[layer][ev["skip_reason"]] += 1
        if status != "resolved" or ev["return_pct"] is None:
            continue
        ret = float(ev["return_pct"])
        stance = ev["stance"] or ""
        window = int(ev["window_days"])
        hit = is_hit(stance, ret, window)
        dirs = ["all", stance] if stance in ("bullish", "bearish", "risk") else ["all"]
        for d in dirs:
            for seg in segment_of(ev["event_date"]):
                key = (layer, d, window, seg)
                ev_groups[key].append(hit)
                vw_groups[key].setdefault(ev["view_id"], False)
                vw_groups[key][ev["view_id"]] = vw_groups[key][ev["view_id"]] or hit

    stats: dict[str, Any] = {"layers": {}, "denominators": {}, "skip_reasons": {}}
    for (layer, d, window, seg), flags in ev_groups.items():
        ev_total = len(flags)
        ev_hits = sum(1 for f in flags if f)
        vw = vw_groups[(layer, d, window, seg)]
        vw_total = len(vw)
        vw_hits = sum(1 for v in vw.values() if v)
        entry = {
            "event_total": ev_total, "event_hits": ev_hits,
            "event_rate": round(ev_hits / ev_total, 4) if ev_total else 0.0,
            "view_total": vw_total, "view_hits": vw_hits,
            "view_rate": round(vw_hits / vw_total, 4) if vw_total else 0.0,
            "min_sample_ok": vw_total >= MIN_SAMPLE,
        }
        ev_lo, ev_hi = wilson_interval(ev_hits, ev_total)
        vw_lo, vw_hi = wilson_interval(vw_hits, vw_total)
        entry["event_wilson"] = [round(ev_lo, 4), round(ev_hi, 4)]
        entry["view_wilson"] = [round(vw_lo, 4), round(vw_hi, 4)]
        entry["binomial_p"] = round(binomial_two_sided_p(ev_hits, ev_total), 4)
        stats["layers"].setdefault(layer, {}).setdefault(d, {}).setdefault(str(window), {})[seg] = entry

    for layer, cnts in denom.items():
        r, e, s = cnts.get("resolved", 0), cnts.get("error", 0), cnts.get("skipped", 0)
        stats["denominators"][layer] = {
            "resolved": r, "error": e, "skipped": s,
            "eligible": r + e,
            "coverage": round(r / (r + e), 4) if (r + e) else 0.0,
        }
    stats["skip_reasons"] = {k: dict(v) for k, v in skip_reasons.items()}
    return stats


def file_sha256(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def diff_ci(p1: float, n1: int, p2: float, n2: int, z: float = 1.96) -> tuple[float, float]:
    """两比例差值 Wald CI（ok vs 对照层的效应量）。"""
    if n1 <= 0 or n2 <= 0:
        return 0.0, 0.0
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    d = p1 - p2
    return d - z * se, d + z * se


def write_report(stats: dict, meta: dict) -> dict:
    """JSON + Markdown 报表（共享同一结构），返回报表 dict。"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    report = {"meta": meta, **stats}
    json_path = REPORT_DIR / f"layered_report_{day}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [f"# #14v2 分层前瞻回测报表（{meta['generated_at']}）", "",
          f"- run_id: `{meta['run_id']}` | git: {meta['git_sha']} | 规则: {meta['rule_version']}",
          f"- 数据: view_tuple_status.json sha256={meta['status_hash']} | prediction_events={meta['event_count']}",
          f"- OOS: train≤{TRAIN_CUTOFF} / test≥{TEST_CUTOFF} / roll≥{ROLL_CUTOFF}（expanding）",
          f"- 命中规则: bull ret>0 / bear ret<0 / risk 0.5(≤3d)·1.0(≤10d)·2.0(>10d)", "",
          "## 四分母与覆盖率", "",
          "| layer | resolved | error | skipped | eligible | 可评估覆盖率 |",
          "|---|---|---|---|---|---|"]
    for layer in LAYERS:
        d = stats["denominators"].get(layer, {})
        md.append(f"| {layer} | {d.get('resolved',0)} | {d.get('error',0)} | {d.get('skipped',0)} | {d.get('eligible',0)} | {d.get('coverage',0):.1%} |")
    md += ["", "## 分层命中率（view 级计权，Wilson 95% CI；min_sample=30；binomial_p=事件级双侧检验）", "",
           "| layer | direction | window | segment | n_view | hit_rate | CI | binomial_p | 样本不足 |",
           "|---|---|---|---|---|---|---|---|---|"]
    for layer in LAYERS:
        for d in DIRECTIONS:
            for w in WINDOWS:
                for seg in SEGMENTS:
                    e = stats["layers"].get(layer, {}).get(d, {}).get(str(w), {}).get(seg)
                    if not e or not e["view_total"]:
                        continue
                    ci = f"[{e['view_wilson'][0]:.1%},{e['view_wilson'][1]:.1%}]"
                    flag = "" if e["min_sample_ok"] else "⚠不足"
                    md.append(f"| {layer} | {d} | {w} | {seg} | {e['view_total']} | {e['view_rate']:.1%} | {ci} | {e['binomial_p']:.3f} | {flag} |")
    md += ["", "> 总参考行未列（混合值禁止引用）。template_only 为弱语义/污染对照层，显著偏离 50% 不构成预测证据。", "",
           "## ok vs template_only 差值（效应量，view 级，all 方向）", "",
           "| segment | window | ok_rate | tmpl_rate | 差值 | 差值 95% CI | 含 0? |",
           "|---|---|---|---|---|---|---|"]
    for seg in ["all", "test", "train"]:
        for w in WINDOWS:
            ok_e = stats["layers"].get("ok", {}).get("all", {}).get(str(w), {}).get(seg)
            t_e = stats["layers"].get("template_only", {}).get("all", {}).get(str(w), {}).get(seg)
            if not ok_e or not t_e or not ok_e["view_total"] or not t_e["view_total"]:
                continue
            d_lo, d_hi = diff_ci(ok_e["view_rate"], ok_e["view_total"], t_e["view_rate"], t_e["view_total"])
            contains_zero = "是" if d_lo <= 0 <= d_hi else "否"
            md.append(f"| {seg} | {w} | {ok_e['view_rate']:.1%}(n={ok_e['view_total']}) | {t_e['view_rate']:.1%}(n={t_e['view_total']}) | "
                      f"{ok_e['view_rate']-t_e['view_rate']:+.1%} | [{d_lo:+.1%},{d_hi:+.1%}] | {contains_zero} |")
    md_path = REPORT_DIR / f"layered_report_{day}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    return report


def write_db(report: dict, run_id: str, dry_run: bool = False) -> int:
    """事务写入 prediction_backtest_layers（唯一键 run_id, layer, direction, window, segment, sample_type）。"""
    con = sqlite3.connect(DECISION_DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS prediction_backtest_layers (
            run_id TEXT NOT NULL,
            layer TEXT NOT NULL,
            direction TEXT NOT NULL,
            window_days INT NOT NULL,
            segment TEXT NOT NULL,
            sample_type TEXT NOT NULL,
            total INT NOT NULL,
            hits INT NOT NULL,
            hit_rate REAL,
            wilson_low REAL,
            wilson_high REAL,
            binomial_p REAL,
            min_sample_ok INT,
            PRIMARY KEY (run_id, layer, direction, window_days, segment, sample_type)
        )"""
    )
    rows = []
    for layer in LAYERS:
        for d in DIRECTIONS:
            for w in WINDOWS:
                for seg in SEGMENTS:
                    e = report["layers"].get(layer, {}).get(d, {}).get(str(w), {}).get(seg)
                    if not e:
                        continue
                    for st, total, hits, rate, ci, p in (
                        ("event", e["event_total"], e["event_hits"], e["event_rate"], e["event_wilson"], e["binomial_p"]),
                        ("view", e["view_total"], e["view_hits"], e["view_rate"], e["view_wilson"], e["binomial_p"]),
                    ):
                        if total == 0:
                            continue
                        rows.append((run_id, layer, d, w, seg, st, total, hits, rate,
                                     ci[0], ci[1], p, 1 if e["min_sample_ok"] else 0))
    if dry_run:
        return len(rows)
    try:
        with con:
            con.executemany(
                "INSERT OR REPLACE INTO prediction_backtest_layers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            # 记录 run 元数据（与主数据同事务提交）
            con.execute(
                "CREATE TABLE IF NOT EXISTS prediction_backtest_runs (run_id TEXT PRIMARY KEY, meta TEXT, created_at TEXT)")
            con.execute("INSERT OR REPLACE INTO prediction_backtest_runs VALUES (?,?,?)",
                        (run_id, json.dumps(report["meta"], ensure_ascii=False), report["meta"]["generated_at"]))
    finally:
        con.close()
    return len(rows)


def git_sha() -> str:
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, cwd=ROOT, timeout=5).stdout.strip() or "n/a"
    except Exception:
        return "n/a"


def main() -> None:
    parser = argparse.ArgumentParser(description="#14v2 分层前瞻回测")
    parser.add_argument("--report", action="store_true", help="生成分层报表")
    parser.add_argument("--dry-run", action="store_true", help="只算不写库")
    parser.add_argument("--layers-json", action="store_true", help="仅输出分层映射统计（自检用）")
    args = parser.parse_args()

    layer_map = load_status_map(STATUS_FILE)
    if args.layers_json:
        from collections import Counter
        print(json.dumps(dict(Counter(layer_map.values())), ensure_ascii=False))
        return

    events = load_events()
    stats = compute_layer_stats(events, layer_map)
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    meta = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "rule_version": "tuple_status_any_ok_v1",
        "status_hash": file_sha256(STATUS_FILE),
        "event_count": len(events),
        "resolved_views": len({e["view_id"] for e in events if e["status"] == "resolved"}),
        "oos": {"train_cutoff": TRAIN_CUTOFF, "test_cutoff": TEST_CUTOFF, "roll_cutoff": ROLL_CUTOFF},
    }
    report = write_report(stats, meta)
    n = write_db(report, run_id, dry_run=args.dry_run)
    mode = "dry-run(未写库)" if args.dry_run else f"已写库 {n} 行"
    print(json.dumps({"run_id": run_id, "mode": mode,
                      "report_json": str(REPORT_DIR / f"layered_report_{datetime.now().strftime('%Y%m%d')}.json"),
                      "denominators": report["denominators"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
