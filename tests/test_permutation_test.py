import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from permutation_test import (  # noqa: E402
    build_view_samples,
    permutation_test,
    rate_diff,
    run_window,
)


def ev(view_id, stance, ret, window=5, date="2026-07-10", status="resolved"):
    return {
        "view_id": view_id,
        "entity": "半导体",
        "entity_type": "sector",
        "stance": stance,
        "window_days": window,
        "event_date": date,
        "return_pct": ret,
        "status": status,
        "skip_reason": None,
        "analyst": "钱博士直播",
    }


class PermutationTestTests(unittest.TestCase):
    def test_rate_diff_matches_manual_calc(self):
        layers = ["ok", "ok", "template_only", "template_only"]
        hits = [True, False, True, False]
        self.assertAlmostEqual(rate_diff(layers, hits, "ok"), 0.5 - 0.5)  # 0.0
        layers2 = ["ok", "ok", "ok", "template_only", "template_only"]
        hits2 = [True, True, False, True, False]
        self.assertAlmostEqual(rate_diff(layers2, hits2, "ok"), 2 / 3 - 0.5)

    def test_permutation_p_not_significant_when_no_effect(self):
        # 两层命中率同为 50%，置换下观测差值不显著
        rng = __import__("random").Random(7)
        layers = ["ok"] * 60 + ["template_only"] * 60
        hits = [rng.random() < 0.5 for _ in layers]
        res = permutation_test(layers, hits, n_perm=300, seed=1)
        self.assertGreaterEqual(res["p_one_sided"], 0.05)
        self.assertLess(abs(res["d_obs"]), 0.3)  # 50% vs 50% 差值应小

    def test_permutation_p_significant_when_effect_present(self):
        # ok 层 80% 命中 vs 其余 40% → 置换 p 显著
        layers = ["ok"] * 60 + ["template_only"] * 60
        hits = [True] * 48 + [False] * 12 + [True] * 24 + [False] * 36
        res = permutation_test(layers, hits, n_perm=300, seed=1)
        self.assertLess(res["p_one_sided"], 0.05)
        self.assertGreater(res["d_obs"], 0.2)

    def test_build_view_samples_filters_window_segment_layer(self):
        events = [
            ev("v_ok_1", "bullish", 1.0, window=5, date="2026-07-10"),   # test+roll, ok
            ev("v_ok_1", "bullish", -1.0, window=3, date="2026-07-10"),  # w3 命中=否(另窗)
            ev("v_ok_2", "bearish", -1.5, window=5, date="2026-07-20"),  # test+roll, ok
            ev("v_tm_1", "bullish", -2.0, window=5, date="2026-07-10"),  # template_only, 未命中
            ev("v_no", "bullish", 1.0, window=5, date="2026-07-10"),     # no_ru → 剔除
            ev("v_old", "bullish", 1.0, window=5, date="2026-06-10"),    # train → 剔除
        ]
        layer_map = {
            "v_ok_1": "ok", "v_ok_2": "ok",
            "v_tm_1": "template_only", "v_no": "no_ru", "v_old": "ok",
        }
        layers, hits = build_view_samples(events, layer_map, window_days=5, segment="test")
        # 3 个有效 view：ok×2 + template_only×1
        self.assertEqual(len(layers), 3)
        self.assertEqual(sum(1 for l in layers if l == "ok"), 2)
        self.assertEqual(sum(1 for l in layers if l == "template_only"), 1)
        self.assertNotIn("no_ru", layers)
        self.assertNotIn("v_old", layers)

    def test_permutation_single_layer_returns_error(self):
        layers = ["ok"] * 30
        hits = [True] * 30
        res = permutation_test(layers, hits, n_perm=50)
        self.assertIn("error", res)

    def test_permutation_reproducible_with_seed(self):
        layers = ["ok"] * 40 + ["template_only"] * 40
        hits = [True] * 32 + [False] * 8 + [True] * 20 + [False] * 20
        r1 = permutation_test(layers, hits, n_perm=200, seed=42)
        r2 = permutation_test(layers, hits, n_perm=200, seed=42)
        self.assertEqual(r1["p_one_sided"], r2["p_one_sided"])
        self.assertEqual(r1["d_obs"], r2["d_obs"])

    def test_run_window_end_to_end_synthetic(self):
        events = [ev(f"v{i}", "bullish", 1.0, window=5, date="2026-07-10") for i in range(20)]
        layer_map = {f"v{i}": "ok" if i < 12 else "template_only" for i in range(20)}
        res = run_window(events, layer_map, window_days=5, n_perm=100, seed=3)
        self.assertEqual(res["window_days"], 5)
        self.assertEqual(res["segment"], "test")
        self.assertEqual(res["n_a"], 12)
        self.assertEqual(res["n_b"], 8)


if __name__ == "__main__":
    unittest.main()
