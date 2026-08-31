#!/usr/bin/env python3
"""#14v2 分层回测显著性补强：置换检验（70 号交接 P2 队列，2026-09-01）。

把「ok 层 OOS 优于 template_only」从 Wilson CI 推断升级为置换检验 p 值：
- H0：层标签（ok/template_only）与命中结果独立
- 观测统计量：ok 层 view 级命中率 − template_only 层 view 级命中率（test 段）
- 置换：保持各层 view 数不变，随机重分配 view 的层标签（按 view 打乱，
  事件级不独立；与 compute_layer_stats 的 view 级聚合口径一致）
- p 单侧（H1: ok > template_only，方向由 #14v2 结论预设）+ 双侧参考
- 只读：不写 decision.db，不碰 Mac 库；报告写 data/backtest/permutation_*.{json,md}

用法:
    python scripts/permutation_test.py --report            # w3/w5 双窗口 + 写报告
    python scripts/permutation_test.py --window 5 --n-perm 500 --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from layered_backtest_v2 import (  # noqa: E402
    DECISION_DB,
    STATUS_FILE,
    TEST_CUTOFF,
    is_hit,
    load_events,
    load_status_map,
    segment_of,
)

REPORT_DIR = ROOT / "data" / "backtest"


def build_view_samples(
    events: list[dict[str, Any]],
    layer_map: dict[str, str],
    window_days: int,
    segment: str = "test",
    layer_a: str = "ok",
    layer_b: str = "template_only",
) -> tuple[list[str], list[bool]]:
    """取 segment 段 resolved 事件 → view 级 (layer, hit) 样本。

    口径与 compute_layer_stats 一致：view 在 (window, direction=all, segment)
    下任意事件命中即该 view 命中（max 聚合）；层不在 a/b 的 view 剔除。
    返回 (layers, hits) 两个对齐列表。
    """
    view_hit: dict[str, bool] = {}
    view_layer: dict[str, str] = {}
    for ev in events:
        layer = layer_map.get(ev["view_id"], "no_ru")
        if layer not in (layer_a, layer_b):
            continue
        if ev["status"] != "resolved" or ev["return_pct"] is None:
            continue
        if int(ev["window_days"]) != window_days:
            continue
        if segment not in segment_of(ev["event_date"]):
            continue
        stance = ev["stance"] or ""
        if stance not in ("bullish", "bearish", "risk"):
            continue  # 方向 all 的有效子集：只有有立场的事件参与命中判定
        hit = is_hit(stance, float(ev["return_pct"]), window_days)
        vid = ev["view_id"]
        view_layer[vid] = layer
        view_hit[vid] = view_hit.get(vid, False) or hit
    layers, hits = [], []
    for vid in view_hit:
        layers.append(view_layer[vid])
        hits.append(view_hit[vid])
    return layers, hits


def rate_diff(layers: list[str], hits: list[bool], layer_a: str) -> float:
    """ok 层命中率 − b 层命中率（view 级）。"""
    hits_a = [h for l, h in zip(layers, hits) if l == layer_a]
    hits_b = [h for l, h in zip(layers, hits) if l != layer_a]
    if not hits_a or not hits_b:
        return 0.0
    return sum(hits_a) / len(hits_a) - sum(hits_b) / len(hits_b)


def permutation_test(
    layers: list[str],
    hits: list[bool],
    layer_a: str = "ok",
    layer_b: str = "template_only",
    n_perm: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """置换检验：固定层大小重分配层标签，返回观测差值 + p 值。"""
    rng = random.Random(seed)
    n_a = sum(1 for l in layers if l == layer_a)
    n_total = len(layers)
    if n_a == 0 or n_a == n_total:
        return {"error": "单层无样本，无法置换"}
    d_obs = rate_diff(layers, hits, layer_a)
    idx_all = list(range(n_total))
    # 零分布：随机抽 n_a 个当 a 层（其余为 b 层），重算差值
    count_ge = 0  # 单侧：|d_perm| >= |d_obs| 用单侧方向 d_perm >= d_obs
    count_abs_ge = 0  # 双侧：|d_perm| >= |d_obs|
    d_abs = abs(d_obs)
    for _ in range(n_perm):
        chosen = set(rng.sample(idx_all, n_a))
        perm_layers = [layer_a if i in chosen else layer_b for i in idx_all]
        d = rate_diff(perm_layers, hits, layer_a)
        if d >= d_obs:
            count_ge += 1
        if abs(d) >= d_abs:
            count_abs_ge += 1
    return {
        "layer_a": layer_a,
        "layer_b": "其余",
        "n_a": n_a,
        "n_b": n_total - n_a,
        "rate_a": round(sum(h for l, h in zip(layers, hits) if l == layer_a) / n_a, 4),
        "rate_b": round(
            sum(h for l, h in zip(layers, hits) if l != layer_a) / (n_total - n_a), 4
        ),
        "d_obs": round(d_obs, 4),
        "p_one_sided": round((count_ge + 1) / (n_perm + 1), 4),
        "p_two_sided": round((count_abs_ge + 1) / (n_perm + 1), 4),
        "n_perm": n_perm,
        "seed": seed,
    }


def run_window(
    events: list[dict[str, Any]],
    layer_map: dict[str, str],
    window_days: int,
    n_perm: int,
    seed: int,
) -> dict[str, Any]:
    layers, hits = build_view_samples(
        events, layer_map, window_days=window_days, segment="test"
    )
    result = permutation_test(layers, hits, n_perm=n_perm, seed=seed)
    result["window_days"] = window_days
    result["segment"] = "test"
    return result


def render_report(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    lines = [
        f"# 置换检验报告（#14v2 显著性补强，{meta['generated_at']}）",
        "",
        f"> 数据：`{DECISION_DB.name}` prediction_events（resolved {meta['n_resolved']}）· 层映射 `{STATUS_FILE.name}`",
        f"> 样本：test 段（>= {TEST_CUTOFF}）resolved 事件，view 级 max 聚合，方向 all",
        f"> 方法：固定层大小置换（n_perm={meta['n_perm']}，seed={meta['seed']}），H0=层标签与命中独立",
        f"> 解读：**p_one_sided < 0.05 = ok 层显著优于对比层**；p 是随机置换下出现≥观测差值的概率",
        "",
        "| 窗口 | n_ok | n_其余 | ok命中率 | 其余命中率 | 差值 | p(单侧) | p(双侧) | 判定 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        if "error" in r:
            lines.append(
                f"| {r.get('window_days', '?')} | — | — | — | — | — | — | — | {r['error']} |"
            )
            continue
        sig = "显著" if r["p_one_sided"] < 0.05 else "不显著"
        lines.append(
            f"| w{r['window_days']} | {r['n_a']} | {r['n_b']} | {r['rate_a']:.1%} | "
            f"{r['rate_b']:.1%} | {r['d_obs']:+.1%} | {r['p_one_sided']} | "
            f"{r['p_two_sided']} | {sig} |"
        )
    lines.append("")
    lines.append("> 约束：置换只在 ok/template_only 两层间进行（#14v2 对比结论的当事人）；")
    lines.append("> 层数固定=条件置换，保持原样本规模结构；结论不改变 #14v2 分层解读边界（红线#10）。")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="分层回测置换检验")
    ap.add_argument("--report", action="store_true", help="跑 w3/w5 双窗口并写报告文件")
    ap.add_argument("--window", type=int, default=None, help="单窗口（3 或 5）")
    ap.add_argument("--n-perm", type=int, default=1000, help="置换次数（默认 1000）")
    ap.add_argument("--seed", type=int, default=42, help="随机种子（默认 42）")
    args = ap.parse_args()

    events = load_events()
    layer_map = load_status_map(STATUS_FILE)
    n_resolved = sum(1 for e in events if e["status"] == "resolved")

    windows = [args.window] if args.window else ([3, 5] if args.report else [5])
    results = [
        run_window(events, layer_map, w, args.n_perm, args.seed) for w in windows
    ]
    for r in results:
        print(json.dumps(r, ensure_ascii=False))

    if args.report:
        meta = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "n_resolved": n_resolved,
            "n_perm": args.n_perm,
            "seed": args.seed,
        }
        md = render_report(results, meta)
        stamp = datetime.now().strftime("%Y%m%d")
        md_path = REPORT_DIR / f"permutation_{stamp}.md"
        json_path = REPORT_DIR / f"permutation_{stamp}.json"
        md_path.write_text(md, encoding="utf-8")
        json_path.write_text(
            json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n报告: {md_path}\n数据: {json_path}")


if __name__ == "__main__":
    main()
