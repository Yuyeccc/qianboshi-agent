#!/usr/bin/env python3
"""资产分析卡真实数据烟测。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from asset_card_builder import build_asset_card, render_asset_card
from decision_db import decision_db_path


def assert_card(card: dict) -> None:
    assert isinstance(card, dict)
    assert card.get("asset_id")
    assert card.get("factors")
    assert card.get("logic_chain_summary")
    for factor in card.get("factors") or []:
        assert factor.get("factor_id")
        assert factor.get("current_state")
        assert factor.get("impact_direction")


def main() -> None:
    gold = build_asset_card("GOLD")
    assert_card(gold)
    print(render_asset_card(gold))
    print()

    semi = build_asset_card("SEMI")
    assert_card(semi)
    print(render_asset_card(semi))

    with sqlite3.connect(decision_db_path()) as conn:
        count = conn.execute("SELECT COUNT(*) FROM factor_states").fetchone()[0]
    assert count > 0
    print(f"factor_states rows: {count}")


if __name__ == "__main__":
    main()
