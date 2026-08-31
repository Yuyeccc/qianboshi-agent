import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brief_renderer import (  # noqa: E402
    _asset_relevance_score,
    _time_bucket,
    _filter_relevant_views,
    _build_top_themes,
    _load_sector_watchlist,
    _evidence_relevance,
    _asr_confidence,
    _render_view_table,
    prediction_badge,
    render_markdown,
)


def view(**kw):
    base = {
        "view_id": "a" * 16,
        "analyst": "钱博士直播",
        "date": "2026-07-20",
        "source_file": "钱博士直播 2026.07.20 BVxxx.md",
        "section": "",
        "entities": {},
        "stance": "watch",
        "horizon": "short",
        "view_type": "general",
        "claim": "",
        "logic": "",
        "risk": "",
        "evidence": "",
    }
    base.update(kw)
    return base


class BriefRendererQualityTests(unittest.TestCase):
    def test_asset_relevance_requires_direct_section_match_for_financial_sector(self):
        weak = view(
            claim="科技股上涨逻辑没有改变，光模块仍需观察",
            logic="光模块和半导体快速下跌后需要换手",
            evidence="科技股、光模块、半导体",
            entities={"sectors": ["光模块", "半导体"]},
        )
        strong = view(
            claim="券商、银行带动大金融修复",
            logic="证券ETF放量，银行保险承接改善",
            evidence="券商 银行 保险 大金融",
            entities={"sectors": ["大金融"], "symbols": ["证券ETF"]},
        )

        self.assertLess(_asset_relevance_score(weak, "大金融"), 0.5)
        self.assertGreaterEqual(_asset_relevance_score(strong, "大金融"), 0.75)
        filtered = _filter_relevant_views([weak, strong], "大金融")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["claim"], strong["claim"])
        self.assertIn("asset_relevance_score", filtered[0])

    def test_time_bucket_splits_recent_and_old_views(self):
        self.assertEqual(_time_bucket("2026-07-21", "2026-07-21"), "今日")
        self.assertEqual(_time_bucket("2026-07-20", "2026-07-21"), "T-1")
        self.assertEqual(_time_bucket("2026-07-18", "2026-07-21"), "3日内")
        self.assertEqual(_time_bucket("2026-07-12", "2026-07-21"), "1月内背景")
        self.assertEqual(_time_bucket("2026-06-01", "2026-07-21"), "过期需复核")

    def test_build_top_themes_prioritizes_fresh_direct_evidence(self):
        sections = [
            {
                "title": "半导体",
                "type": "sector",
                "summary": "半导体短线风险未释放",
                "views": [view(view_id="b" * 16, date="2026-07-20", claim="半导体设备估值高", evidence="半导体 ETF 赎回")],
            },
            {
                "title": "创新药",
                "type": "sector",
                "summary": "创新药长期逻辑改善",
                "views": [view(view_id="c" * 16, date="2026-06-20", claim="创新药长期机会", evidence="创新药 BD")],
            },
            {
                "title": "光模块",
                "type": "sector",
                "summary": "光模块日内修复",
                "views": [view(view_id="d" * 16, date="2026-07-21", claim="光模块修复", evidence="光模块 成交修复")],
            },
        ]

        themes = _build_top_themes(sections, brief_date="2026-07-21", limit=2)
        self.assertEqual([t["title"] for t in themes], ["光模块", "半导体"])
        self.assertEqual(themes[0]["time_bucket"], "今日")
        self.assertEqual(themes[1]["time_bucket"], "T-1")

    def test_build_top_themes_adds_watchlist_validation_objects(self):
        _load_sector_watchlist.cache_clear()
        sections = [
            {
                "title": "光模块",
                "type": "sector",
                "summary": "光模块日内修复",
                "views": [view(view_id="e" * 16, date="2026-07-21", claim="光模块修复", evidence="光模块 成交修复")],
            }
        ]

        themes = _build_top_themes(sections, brief_date="2026-07-21", limit=1)
        watch = "\n".join(themes[0]["watch"])
        self.assertIn("159770.SZ", watch)
        self.assertIn("中际旭创", watch)
        self.assertIn("强验证", watch)
        self.assertIn("高开低走", themes[0]["invalid"])
        self.assertIn("1.2倍", themes[0].get("thresholds", ""))

    def test_build_top_themes_uses_market_score_as_tiebreaker(self):
        sections = [
            {
                "title": "半导体",
                "type": "sector",
                "summary": "半导体观察",
                "views": [view(view_id="f" * 16, date="2026-07-20", section="半导体", claim="半导体观察", evidence="半导体 芯片")],
            },
            {
                "title": "光模块",
                "type": "sector",
                "summary": "光模块观察",
                "views": [view(view_id="g" * 16, date="2026-07-20", section="光模块", claim="光模块观察", evidence="光模块 通信")],
            },
        ]
        market_context = {"sectors": {"半导体": {"score": 0.1}, "光模块": {"score": 0.9}}}

        themes = _build_top_themes(sections, brief_date="2026-07-21", limit=2, market_context=market_context)

        self.assertEqual(themes[0]["title"], "光模块")
        self.assertIn("市场分=0.90", themes[0]["selection_reason"])

    def test_evidence_quality_blocks_mismatch_and_low_asr_from_top_theme(self):
        self.assertEqual(
            _evidence_relevance(view(claim="光通信修复", evidence="光模块 CPO PCB", entities={"sectors": ["光模块"]}), "机器人"),
            "mismatch",
        )
        self.assertEqual(_asr_confidence(view(evidence="00:00:00 脾脂 熟悔 回乱")), "low")
        sections = [
            {
                "title": "机器人",
                "type": "sector",
                "summary": "机器人观察",
                "views": [view(view_id="h" * 16, date="2026-07-21", claim="科技修复", evidence="00:00:00 脾脂 熟悔 光通信 CPO")],
            },
            {
                "title": "创新药",
                "type": "sector",
                "summary": "创新药观察",
                "views": [view(view_id="i" * 16, date="2026-07-20", section="创新药", claim="创新药观察", evidence="创新药 BD 医药")],
            },
        ]

        themes = _build_top_themes(sections, brief_date="2026-07-21", limit=2)

        self.assertEqual(themes[0]["title"], "创新药")
        self.assertNotEqual(themes[0]["title"], "机器人")

    def test_render_markdown_includes_top3_section_when_present(self):
        data = {
            "schema_version": 1,
            "brief_date": "2026-07-21",
            "generated_at": "2026-07-21T09:00:00",
            "session_note": "test",
            "market_snapshot": {"indexes": {}, "tracked_prices": {}, "notes": []},
            "top_themes": [
                {
                    "rank": 1,
                    "title": "光模块",
                    "level": "今日主线",
                    "summary": "日内修复但需验证",
                    "time_bucket": "今日",
                    "latest_date": "2026-07-21",
                    "evidence_refs": ["view_id=dddd; 钱博士直播 2026-07-21"],
                    "watch": ["看光模块ETF成交是否放大"],
                    "invalid": "若冲高回落且量能萎缩，降级观察。",
                }
            ],
            "sections": [
                {
                    "title": "光模块",
                    "type": "sector",
                    "summary": "日内修复但需验证",
                    "views": [view(view_id="d" * 16, date="2026-07-21", claim="光模块修复", evidence="光模块")],
                    "consensus": "",
                    "divergence": "",
                    "action_watch": [],
                }
            ],
            "risk_alerts": [],
            "source_view_ids": ["d" * 16],
            "disclaimer": "仅整理公开内容与行情数据，不构成投资建议。",
        }
        md = render_markdown(data)
        self.assertIn("## 二、今日Top 3主线", md)
        self.assertIn("光模块", md)
        self.assertIn("失效条件", md)

    # ---- 预测力徽标（70 号交接 P2#1，红线#12 与证据·置信解耦） ----

    def test_prediction_badge_shows_value_when_measured(self):
        self.assertEqual(prediction_badge(view(prediction_confidence=0.59)), "预测力0.59")
        self.assertEqual(prediction_badge(view(prediction_confidence=0.65)), "预测力0.65")
        self.assertEqual(prediction_badge(view(prediction_confidence=0.49)), "预测力0.49")

    def test_prediction_badge_baseline_for_conservative_placeholder(self):
        # 0.50 = 保守中性占位（样本不足/未知组合），禁显示成"预测力差"
        self.assertEqual(prediction_badge(view(prediction_confidence=0.50)), "基准")

    def test_prediction_badge_empty_when_missing_or_invalid(self):
        self.assertEqual(prediction_badge(view()), "")
        self.assertEqual(prediction_badge(view(prediction_confidence="bad")), "")

    def test_render_view_table_has_prediction_column(self):
        rows = _render_view_table(
            [
                view(view_id="a" * 16, claim="实测预测力", prediction_confidence=0.59),
                view(view_id="b" * 16, claim="保守基准", prediction_confidence=0.50),
                view(view_id="c" * 16, claim="无预测力字段"),
            ],
            max_rows=8,
        )
        self.assertIn("证据·置信", rows[0])
        self.assertIn("预测力", rows[0])
        self.assertIn("预测力0.59", rows[2])
        self.assertIn("基准", rows[3])
        self.assertIn("|  |", rows[4])  # 无字段 = 空列，不猜测
        # 列数一致：表头 11 列 = 数据行 11 列
        self.assertEqual(rows[0].count("|"), rows[2].count("|"))
        self.assertEqual(rows[0].count("|"), rows[4].count("|"))


if __name__ == "__main__":
    unittest.main()
