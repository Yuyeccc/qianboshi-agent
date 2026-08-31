#!/usr/bin/env python3
"""生成最近观点 digest，供盘前简报绕开 embedding 使用。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import get_data_dir, load_config
from view_store import get_latest_views, load_views, query_views


def digest_path(config: dict[str, Any] | None = None) -> Path:
    config = config or load_config()
    p = config.get("views", {}).get("latest_digest_path") if isinstance(config, dict) else None
    if p:
        path = Path(p)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        return path
    return get_data_dir(config) / "views" / "latest_digest.json"


def compact_view(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "view_id": v.get("view_id"),
        "date": v.get("date"),
        "analyst": v.get("analyst"),
        "source_file": v.get("source_file"),
        "section": v.get("section"),
        "entities": v.get("entities", {}),
        "stance": v.get("stance"),
        "horizon": v.get("horizon"),
        "view_type": v.get("view_type"),
        "claim": v.get("claim"),
        "logic": v.get("logic"),
        "risk": v.get("risk"),
        "rank_score": v.get("rank_score"),
        "bucket": v.get("bucket"),
        "evidence": v.get("evidence", "")[:260],
    }


def build_digest(days: int = 7, max_per_sector: int = 5, top_limit: int = 80) -> dict[str, Any]:
    views = get_latest_views(days=days, limit=top_limit)
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    market_overview = []
    risk_signals = []

    for v in views:
        cv = compact_view(v)
        by_date[v.get("date", "")].append(cv)
        sectors = (v.get("entities") or {}).get("sectors", [])
        if not sectors:
            sectors = ["未分类"]
        for s in sectors:
            if len(by_sector[s]) < max_per_sector:
                by_sector[s].append(cv)
        if v.get("view_type") == "market" and len(market_overview) < 10:
            market_overview.append(cv)
        if v.get("view_type") == "risk" or v.get("risk"):
            if len(risk_signals) < 20:
                risk_signals.append(cv)

    digest = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window_days": days,
        "source_view_count": len(views),
        "by_date": dict(sorted(by_date.items(), reverse=True)),
        "by_sector": dict(sorted(by_sector.items(), key=lambda kv: (-len(kv[1]), kv[0]))),
        "market_overview": market_overview,
        "risk_signals": risk_signals,
        "top_views": [compact_view(v) for v in views[: min(30, len(views))]],
    }
    return digest


def get_latest_digest(days: int = 3, sectors: list[str] | None = None, limit: int = 30) -> dict[str, Any]:
    """供 tool_registry 调用。优先读现成 digest；没有或窗口不匹配则现场构建。"""
    path = digest_path()
    digest = None
    if path.exists():
        try:
            digest = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            digest = None
    if not digest or int(digest.get("window_days", 0)) < days:
        digest = build_digest(days=days)
    if sectors:
        allowed = set(sectors)
        filtered = {}
        for s, items in digest.get("by_sector", {}).items():
            if s in allowed:
                filtered[s] = items[:limit]
        digest = dict(digest)
        digest["by_sector"] = filtered
    digest = dict(digest)
    digest["top_views"] = digest.get("top_views", [])[:limit]
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 latest_digest.json")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-per-sector", type=int, default=5)
    parser.add_argument("--top-limit", type=int, default=80)
    parser.add_argument("--print", dest="do_print", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()

    config = load_config()
    digest = build_digest(days=args.days, max_per_sector=args.max_per_sector, top_limit=args.top_limit)
    out = Path(args.output) if args.output else digest_path(config)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.do_print:
        print(json.dumps(digest, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"output": str(out), "window_days": args.days, "source_view_count": digest["source_view_count"], "sectors": list(digest.get("by_sector", {}).keys())[:20]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
