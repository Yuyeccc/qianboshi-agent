#!/usr/bin/env python3
"""EvidencePack 快速功能测试。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evidence_pack_builder import PACK_FIELDS, build_evidence_pack


def _assert_top_fields(pack: dict) -> None:
    assert isinstance(pack, dict)
    for field in PACK_FIELDS:
        assert field in pack, field


def main() -> None:
    gold = build_evidence_pack("GOLD")
    _assert_top_fields(gold)
    assert isinstance(gold.get("asset_card"), dict)
    assert gold.get("asset_card") or gold.get("asset_card") == {}
    assert gold.get("summary")

    semi = build_evidence_pack("SEMI")
    _assert_top_fields(semi)
    assert isinstance(semi.get("analyst_scores"), list)

    debate = gold.get("debate_card") or {}
    print("GOLD summary:", gold.get("summary"))
    print("GOLD factors:", len(gold.get("factor_states") or []))
    print("GOLD debate bullish:", len(debate.get("bullish") or []))
    print("GOLD debate bearish:", len(debate.get("bearish") or []))
    print("SEMI analyst_scores:", len(semi.get("analyst_scores") or []))

    unknown = build_evidence_pack("UNKNOWN_ASSET")
    _assert_top_fields(unknown)
    assert unknown.get("asset_id") == "UNKNOWN_ASSET"
    assert unknown.get("asset_name") == "UNKNOWN_ASSET"
    assert isinstance(unknown.get("asset_card"), dict)
    assert isinstance(unknown.get("summary"), str)


if __name__ == "__main__":
    main()
