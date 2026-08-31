#!/usr/bin/env python3
"""多空对照卡真实数据烟测。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from debate_card_builder import build_debate_card


def summarize(card: dict) -> dict:
    return {
        "entity": card.get("entity_name"),
        "card_id": card.get("card_id"),
        "window": card.get("window"),
        "highlights": card.get("highlights"),
        "counts": card.get("counts"),
        "metrics": card.get("metrics"),
        "bullish_sample": [x.get("claim") for x in card.get("bullish", [])[:2]],
        "bearish_sample": [x.get("claim") for x in card.get("bearish", [])[:2]],
    }


def main() -> None:
    cards = [
        build_debate_card("半导体", lookback_days=60),
        build_debate_card("光模块", lookback_days=60),
    ]
    for card in cards:
        assert isinstance(card, dict)
        assert "highlights" in card
        assert "bullish" in card
        assert "bearish" in card
    print(json.dumps([summarize(card) for card in cards], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
