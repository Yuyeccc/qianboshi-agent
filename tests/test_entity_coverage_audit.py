# -*- coding: utf-8 -*-
"""entity_coverage_audit 单测（P2 刀0）。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from entity_coverage_audit import (  # noqa: E402
    build_maps,
    classify_word,
    scan,
)

TEST_ALIASES = {
    "entities": {
        "半导体": {"aliases": ["芯片", "先进制程"], "etfs": ["159813.SZ"], "stocks": ["688981.SS"],
                 "themes": ["国产替代"], "us_mapping": ["NVDA"]},
        "大盘": {"aliases": ["上证", "指数"], "etfs": ["510300.SS"], "themes": ["护盘"],
                "indexes": ["000001.SS"]},
    }
}


def maps():
    return build_maps(TEST_ALIASES)


class TestBuildMaps:
    def test_alias_map_full(self):
        alias_map, _, _, _ = maps()
        assert alias_map["半导体"] == "半导体"
        assert alias_map["芯片"] == "半导体"
        assert alias_map["先进制程"] == "半导体"
        assert alias_map["国产替代"] == "半导体"  # themes 也进表
        assert alias_map["上证"] == "大盘"

    def test_code_map(self):
        _, code_map, _, _ = maps()
        assert code_map["159813.SZ"] == "半导体"
        assert code_map["688981.SS"] == "半导体"
        assert code_map["510300.SS"] == "大盘"
        assert code_map["000001.SS"] == "大盘"   # indexes 键也反查
        assert code_map["NVDA"] == "半导体"       # us_mapping 键也反查

    def test_coverage_keys_dynamic(self):
        _, _, _, ck = maps()
        assert ck == {"etfs", "stocks", "indexes", "us_mapping"}

    def test_canon_sorted_longest_first(self):
        _, _, canon, _ = maps()
        assert canon == sorted(canon, key=len, reverse=True)

    def test_first_registered_wins_on_collision(self):
        aliases = {"entities": {"甲": {"aliases": ["x"]}, "乙": {"aliases": ["x"]}}}
        am, _, _, _ = build_maps(aliases)
        assert am["x"] == "甲"


class TestClassify:
    def test_mode1_exact(self):
        am, _, cs, _ = maps()
        assert classify_word("半导体", am, cs) == ("半导体", "mode1")
        assert classify_word("国产替代", am, cs) == ("半导体", "mode1")

    def test_mode2_substring(self):
        am, _, cs, _ = maps()
        # canonical 名是词子串
        assert classify_word("半导体设备行情", am, cs) == ("半导体", "mode2")

    def test_uncovered(self):
        am, _, cs, _ = maps()
        assert classify_word("黄金", am, cs) == (None, "uncovered")
        # alias 子串不触发 mode2（mode2 只认 canonical 名）
        assert classify_word("先进制程设备", am, cs) == (None, "uncovered")


class TestScan:
    @pytest.fixture()
    def jl(self, tmp_path):
        rows = [
            {"view_id": "v1", "entities": {
                "sectors": ["半导体", "黄金"],
                "themes": ["国产替代", "轮动"],
                "etfs": ["159813.SZ", "999999.XX"],
                "stocks": ["688981.SS"],
                "indexes": ["000001.SS"],
                "us_mapping": ["NVDA"],
            }},
            {"view_id": "v2"},  # 无 entities
            {"view_id": "v3", "entities": {"us_mapping": ["AMD"]}},  # AMD 不在词典 → 覆盖域内未命中
            None,  # 坏行
            {"view_id": "v4", "entities": {"sectors": ["半导体"]}},
        ]
        p = tmp_path / "views.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                if r is None:
                    f.write("{bad json\n")
                else:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return p

    def test_scan_counts(self, jl):
        am, cm, cs, ck = maps()
        st, _ = scan(jl, am, cm, cs, ck, min_freq=1, by_entity=False)
        assert st["views_total"] == 4  # 坏行不计
        assert st["views_with_entities"] == 3
        # 中文：半导体 m1 / 黄金 uncov / 国产替代 m1 / 轮动 uncov / (v4) 半导体 m1
        assert st["cn_total"] == 5
        assert st["cn_mode1"] == 3
        assert st["cn_uncovered"] == 2
        # 代码全域（四域词典都有键）：v1 etfs2+stocks1+indexes1+us1 + v3 us1 = 6
        assert st["code_total"] == 6
        assert st["code_hit"] == 4  # 159813 / 688981 / 000001.SS / NVDA
        assert st["domain_total"]["etfs"] == 2
        assert st["domain_total"]["stocks"] == 1
        assert st["domain_total"]["indexes"] == 1
        assert st["domain_total"]["us_mapping"] == 2
        assert st["code_hit_domain"]["indexes"] == 1
        assert st["code_hit_domain"]["us_mapping"] == 1
        # view 级：v1/v4 有中文命中
        assert st["views_cover_cn"] == 2

    def test_uncovered_words_recorded(self, jl):
        am, cm, cs, ck = maps()
        st, uncov = scan(jl, am, cm, cs, ck, min_freq=1, by_entity=False)
        keys = {k for k, _ in uncov.items()}
        assert ("黄金", "sectors") in keys
        assert ("轮动", "themes") in keys
        assert ("999999.XX", "etfs") in keys  # 覆盖域内未命中代码也记录
        assert ("AMD", "us_mapping") in keys
        assert ("000001.SS", "indexes") not in keys  # 词典覆盖后不再算未覆盖

    def test_empty_entities_not_views_cover(self, jl):
        am, cm, cs, ck = maps()
        st, _ = scan(jl, am, cm, cs, ck, min_freq=1, by_entity=False)
        assert st["views_total"] - st["views_with_entities"] == 1

    def test_uncovered_domain_when_key_absent(self, tmp_path):
        """词典某域无键时（如 us_mapping 键删掉），该域代码全部落 uncov 且不计 code_total。"""
        aliases = {"entities": {"大盘": {"aliases": ["上证"], "indexes": ["000001.SS"]}}}
        am, cm, cs, ck = build_maps(aliases)
        assert "us_mapping" not in ck
        rows = [{"view_id": "v9", "entities": {"us_mapping": ["NVDA", "AMD"], "indexes": ["000001.SS"]}}]
        p = tmp_path / "v.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(rows[0], ensure_ascii=False) + "\n")
        st, uncov = scan(p, am, cm, cs, ck, min_freq=1, by_entity=False)
        assert st["code_total"] == 1  # 只计 indexes
        assert st["code_hit"] == 1
        assert {k for k, _ in uncov.items()} == {("NVDA", "us_mapping"), ("AMD", "us_mapping")}
