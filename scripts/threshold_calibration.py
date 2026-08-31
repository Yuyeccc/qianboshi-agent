#!/usr/bin/env python3
"""阈值校准分析（64 号方案，双审融合定稿，2026-09-01）。

用 #14v2 实证命中率校准 claim 置信度映射的消费层字段（prediction_confidence 设计依据）。
核心（gpt 审意见）：
- 证据分数（conf3 的 evidence_confidence）与预测分数**解耦**：不直接改 conf3 映射
- **view 级独立样本**：每 view 取主窗口(window_days=5)只计一次；双口径报告（view 数+组合数）
- C×ok 高命中 = 探索性信号，不作校准依据
- 输出候选区间（非固定值），待独立 OOS 验证后定值

用法:
    python scripts/threshold_calibration.py --report
    python scripts/threshold_calibration.py --report --dry-run   # 只算不写报表（同 --report 只输出 stdout）
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyst_score_builder import wilson_interval  # noqa: E402

DECISION_DB = ROOT / "data" / "qianboshi_decision.db"
AUTHORITY_FILE = ROOT / "data" / "view_authority.json"
STATUS_FILE = ROOT / "data" / "view_tuple_status.json"
REPORT_DIR = ROOT / "data" / "backtest"

AUTHORITIES = ["A", "B", "C", "D"]
MAIN_WINDOW = 5  # 主窗口（view 级独立样本）
MAPPING = {"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3}  # conf3 证据映射（不动）


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


def load_events() -> list[dict]:
    con = sqlite3.connect(DECISION_DB)
    rows = con.execute(
        "SELECT view_id, stance, window_days, return_pct FROM prediction_events "
        "WHERE status='resolved' AND return_pct IS NOT NULL").fetchall()
    con.close()
    return [{"view_id": r[0], "stance": r[1], "window_days": r[2], "return_pct": r[3]} for r in rows]


def cluster_by_view(events: list[dict], main_window: int = MAIN_WINDOW) -> dict[str, dict]:
    """view 级聚类：主窗口(window=5)优先，缺则取该 view 任一 resolved 事件。
    返回 {view_id: {stance, window_days, return_pct}}（每 view 一条独立样本）。"""
    per_view: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        per_view[e["view_id"]].append(e)
    out: dict[str, dict] = {}
    for vid, evs in per_view.items():
        main = [e for e in evs if e["window_days"] == main_window]
        chosen = main[0] if main else evs[0]
        out[vid] = chosen
    return out


def compute_matrix(view_samples: dict[str, dict], auth_map: dict) -> dict:
    """authority 命中率矩阵（view 级独立样本）。"""
    by_auth: dict[str, list[bool]] = defaultdict(list)
    for vid, e in view_samples.items():
        a = auth_map.get(vid, {}).get("authority", "NO_ANNOT")
        by_auth[a].append(is_hit(e["stance"], e["return_pct"], e["window_days"]))

    matrix: dict[str, dict] = {}
    for a in AUTHORITIES + ["NO_ANNOT"]:
        flags = by_auth.get(a, [])
        n = len(flags)
        h = sum(1 for f in flags if f)
        rate = h / n if n else 0.0
        lo, hi = wilson_interval(h, n)
        mapped = MAPPING.get(a)
        matrix[a] = {
            "n_views": n,
            "hits": h,
            "hit_rate": round(rate, 4),
            "wilson": [round(lo, 4), round(hi, 4)],
            "mapped_confidence": mapped,
            "bias": round(rate - mapped, 4) if mapped is not None else None,
            "candidate_interval": _candidate_interval(rate, lo, hi, n),
            "exploratory_only": n < 30,
        }
    return matrix


def _candidate_interval(rate: float, lo: float, hi: float, n: int) -> list | None:
    """预测置信度候选区间（gpt 意见 3：非固定值，收缩向 0.5 基准）。
    规则：n<30 返回 None（不校准）；否则 [max(0.5, lo), min(0.9, hi)] 收缩估计。"""
    if n < 30:
        return None
    # 收缩：rate 向 0.5 收缩 20%（保守），区间取收缩点 ± CI 半宽的一半
    shrunk = 0.5 + (rate - 0.5) * 0.8
    half = (hi - lo) / 4
    return [round(max(0.3, shrunk - half), 2), round(min(0.95, shrunk + half), 2)]


def compute_cross(view_samples: dict[str, dict], auth_map: dict, layer_map: dict) -> dict:
    """authority × tuple_status 交叉（view 级）。"""
    cross: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {"h": 0, "n": 0}))
    for vid, e in view_samples.items():
        a = auth_map.get(vid, {}).get("authority", "NO_ANNOT")
        t = layer_map.get(vid, "no_ru")
        hit = is_hit(e["stance"], e["return_pct"], e["window_days"])
        cross[a][t]["n"] += 1
        if hit:
            cross[a][t]["h"] += 1
    out: dict[str, dict] = {}
    for a in AUTHORITIES:
        out[a] = {}
        for t in ("ok", "partial_anchor", "template_only"):
            e = cross[a].get(t, {"h": 0, "n": 0})
            out[a][t] = {
                "n": e["n"],
                "hit_rate": round(e["h"] / e["n"], 4) if e["n"] else None,
                "exploratory": e["n"] < 30,
            }
    return out


def file_sha256(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def write_report(matrix: dict, cross: dict, sensitivity: dict, meta: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    report = {"meta": meta, "matrix": matrix, "cross": cross, "sensitivity": sensitivity}
    (REPORT_DIR / f"threshold_calibration_{day}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [f"# 阈值校准分析报表（{meta['generated_at']}）", "",
          f"- 样本：view 级独立样本（主窗口 window={MAIN_WINDOW} 优先），组合级仅敏感性",
          f"- 数据：view_authority.json sha={meta['auth_hash']} | prediction_events resolved 事件 {meta['event_count']}",
          f"- 概念：evidence_confidence（conf3 证据语义）与 prediction_confidence（消费层预测语义）解耦，conf3 不动", "",
          "## authority 命中率矩阵（view 级独立样本，主窗口 w5）", "",
          "| authority | 证据映射 | n_view | 命中率 | Wilson 95% CI | 偏差 | 预测置信度候选区间 |",
          "|---|---|---|---|---|---|---|"]
    for a in AUTHORITIES:
        m = matrix[a]
        cand = f"{m['candidate_interval']}" if m["candidate_interval"] else "样本不足，不校准"
        md.append(f"| {a} | {m['mapped_confidence']} | {m['n_views']} | {m['hit_rate']:.1%} | "
                  f"[{m['wilson'][0]:.1%},{m['wilson'][1]:.1%}] | {m['bias']:+.1%} | {cand} |")
    md += ["", "> 候选区间为收缩估计（向 0.5 收缩 20%），**待独立 OOS 验证后定值**；n<30 不校准。", "",
           "## 窗口敏感性（view 级独立样本，主窗口替换）", "",
           "| authority | w3 | w5 | w10 |",
           "|---|---|---|---|"]
    for a in AUTHORITIES:
        cells = []
        for w in (3, 5, 10):
            s = sensitivity[w].get(a)
            cells.append(f"{s['hit_rate']:.0%}(n={s['n_views']})" if s and s["n_views"] else "-")
        md.append(f"| {a} | " + " | ".join(cells) + " |")
    md += ["", "> w5 为主口径；命中率对窗口敏感，校准必须标注窗口口径。", "",
           "## authority × tuple_status 交叉（view 级 w5；n<30 为探索性信号不作校准依据）", "",
           "| authority | ok | partial_anchor | template_only |",
           "|---|---|---|---|"]
    for a in AUTHORITIES:
        cells = []
        for t in ("ok", "partial_anchor", "template_only"):
            e = cross[a][t]
            s = f"{e['hit_rate']:.0%}(n={e['n']})" if e["hit_rate"] is not None else "-"
            if e["exploratory"] and e["n"]:
                s += "⚠探索"
            cells.append(s)
        md.append(f"| {a} | " + " | ".join(cells) + " |")
    (REPORT_DIR / f"threshold_calibration_{day}.md").write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="阈值校准分析（view 级聚类）")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="只算不写报表")
    args = parser.parse_args()

    auth_map = json.loads(AUTHORITY_FILE.read_text(encoding="utf-8"))
    layer_map = {vid: info["layer"] for vid, info in json.loads(STATUS_FILE.read_text(encoding="utf-8")).items()}
    events = load_events()
    view_samples = cluster_by_view(events)
    matrix = compute_matrix(view_samples, auth_map)
    cross = compute_cross(view_samples, auth_map, layer_map)
    # 窗口敏感性：w3/w5/w10 主窗口替换的 view 级矩阵
    sensitivity: dict[int, dict] = {}
    for w in (3, 5, 10):
        samples_w = cluster_by_view(events, main_window=w)
        m_w = compute_matrix(samples_w, auth_map)
        sensitivity[w] = {a: {"n_views": m_w[a]["n_views"], "hit_rate": m_w[a]["hit_rate"]} for a in AUTHORITIES}

    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "auth_hash": file_sha256(AUTHORITY_FILE),
        "status_hash": file_sha256(STATUS_FILE),
        "event_count": len(events),
        "view_count": len(view_samples),
        "main_window": MAIN_WINDOW,
        "note": "候选区间为收缩估计，待独立 OOS 验证后定值；conf3 证据映射不动；命中率对窗口敏感需标注口径",
    }
    if not args.dry_run:
        write_report(matrix, cross, sensitivity, meta)
        mode = "已写报表"
    else:
        mode = "dry-run（未写）"
    print(json.dumps({"mode": mode, "meta": meta, "matrix": matrix, "sensitivity": sensitivity},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
