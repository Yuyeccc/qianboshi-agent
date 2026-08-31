#!/usr/bin/env python3
"""结构化观点库查询工具。

读写 data/views/structured_views.jsonl，提供 stats/query/latest 三个 CLI，供 Agent 工具层调用。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import get_data_dir, load_config
from entity_normalizer import entity_overlap, extract_entities, is_banned_source, load_aliases


SOURCE_QUALITY = {
    "钱博士直播": 1.00,
    "钱博士短视频": 0.90,
    "钱博士": 0.90,
    "李一恩": 0.75,
    "旗帜鲜明": 0.75,
    "笨笨的韭菜": 0.65,
    "任泽平": 0.65,
    "史诗级韭菜": 0.60,
    "趋势天哥": 0.60,
    "投机大拿": 0.60,
    "柏年说": 0.60,
    "财联社": 0.55,
}


def views_path(config: dict[str, Any] | None = None) -> Path:
    config = config or load_config()
    p = config.get("views", {}).get("structured_views_path") if isinstance(config, dict) else None
    if p:
        path = Path(p)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        return path
    return get_data_dir(config) / "views" / "structured_views.jsonl"


def parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


def parse_date_range(value: str | None) -> tuple[date | None, date | None]:
    if not value:
        return None, None
    value = str(value).strip()
    today = date.today()
    m = re.match(r"^(\d+)d$", value)
    if m:
        return today - timedelta(days=int(m.group(1))), today + timedelta(days=1)
    if ":" in value:
        a, b = value.split(":", 1)
        return parse_date(a), parse_date(b)
    d = parse_date(value)
    if d:
        return d, d
    return None, None


def load_views(path: str | Path | None = None, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    path = Path(path) if path else views_path(config)
    if not path.exists():
        return []
    views = []
    # 预加载别名一次，避免每条观点重复 load_aliases（7800条时从171s降到1s级）
    aliases = load_aliases()
    # 坏时间戳排除清单（2026-08-30：DB quality_issue TS_OUT_OF_DURATION/TS_REVERSED 609 条，
    # 日期/时间戳为 LLM 幻觉，禁入日报/简报检索）。文件缺失或损坏时静默跳过（不阻断查询）。
    excluded = set()
    try:
        ex_path = views_path(config).with_name("excluded_view_ids.json")
        if ex_path.exists():
            excluded = set(json.loads(ex_path.read_text(encoding="utf-8")))
    except Exception:
        excluded = set()
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
            except Exception:
                continue
            if v.get("view_id") in excluded:
                continue
            if is_banned_source(v.get("source_file", ""), aliases) or is_banned_source(v.get("analyst", ""), aliases):
                continue
            views.append(v)
    views = dedupe_views(views)
    return _inject_prediction_confidence(views)


_PC_MAPS: dict | None = None


def _inject_prediction_confidence(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """#66：按 view_id 注入 prediction_confidence（实证预测力，66 号方案）。

    映射文件缺失时静默跳过（排序回退原 confidence，版本兼容）。
    """
    global _PC_MAPS
    if _PC_MAPS is None:
        maps: dict = {}
        try:
            root = Path(__file__).resolve().parents[1] / "data"
            auth = json.loads((root / "view_authority.json").read_text(encoding="utf-8"))
            layer = json.loads((root / "view_tuple_status.json").read_text(encoding="utf-8"))
            maps = {"auth": {vid: i.get("authority", "") for vid, i in auth.items()},
                    "layer": {vid: i.get("layer", "") for vid, i in layer.items()}}
        except Exception:
            maps = {}
        _PC_MAPS = maps
    if not _PC_MAPS:
        return views
    try:
        from prediction_confidence import prediction_confidence
    except Exception:
        return views
    auth, layer = _PC_MAPS["auth"], _PC_MAPS["layer"]
    out = []
    for v in views:
        vid = v.get("view_id")
        if vid and vid in auth and vid in layer:
            pc = prediction_confidence(auth.get(vid, ""), layer.get(vid, ""))
            if pc is not None:
                v = dict(v)
                v["prediction_confidence"] = pc
        out.append(v)
    return out


def dedupe_views(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for v in views:
        vid = v.get("view_id") or f"{v.get('source_file')}|{v.get('claim')}"
        if vid in seen:
            continue
        seen.add(vid)
        out.append(v)
    return out


def claim_quality(v: dict[str, Any]) -> float:
    checks = [
        bool(v.get("stance") and v.get("stance") != "neutral"),
        bool(v.get("horizon") and v.get("horizon") != "unknown"),
        bool(v.get("logic")),
        bool(v.get("risk")),
        bool(v.get("evidence")),
    ]
    return sum(checks) / len(checks)


def evidence_score(v: dict[str, Any]) -> float:
    score = 0.0
    if v.get("evidence"):
        score += 0.5
    if v.get("timestamp"):
        score += 0.25
    if v.get("source_file") and v.get("date"):
        score += 0.25
    return min(score, 1.0)


def source_quality(v: dict[str, Any]) -> float:
    return SOURCE_QUALITY.get(v.get("analyst", ""), 0.5)


def bucket_view(v: dict[str, Any], ent_score: float = 0.0, today: date | None = None) -> str:
    today = today or date.today()
    d = parse_date(v.get("date"))
    age = (today - d).days if d else 9999
    vt = v.get("view_type")
    if age <= 1 and ent_score >= 0.8:
        return "A"
    if age <= 3 and ent_score >= 0.7:
        return "B"
    if age <= 7 and (ent_score >= 0.5 or not ent_score):
        return "C"
    if age <= 30 and vt in ("framework", "sector", "risk", "market"):
        return "D"
    return "E"


def score_view(v: dict[str, Any], ent_score: float = 0.0) -> float:
    if not ent_score and v.get("entities"):
        ent_score = 0.55
    # #66：排序置信权重用 prediction_confidence（实证预测力），缺失回退原 confidence（版本兼容）
    conf_w = float(v.get("prediction_confidence") or v.get("confidence", 0.5))
    return round(
        ent_score * 0.35
        + claim_quality(v) * 0.25
        + source_quality(v) * 0.15
        + evidence_score(v) * 0.15
        + conf_w * 0.10,
        4,
    )


def filter_views(
    views: list[dict[str, Any]],
    entity: str | None = None,
    analyst: str | None = None,
    date_range: str | None = "7d",
    view_type: str | None = None,
    stance: str | None = None,
) -> list[dict[str, Any]]:
    aliases = load_aliases()
    start, end = parse_date_range(date_range)
    out = []
    for v in views:
        d = parse_date(v.get("date"))
        if start and (not d or d < start):
            continue
        if end and d and d > end:
            continue
        if analyst and analyst not in v.get("analyst", ""):
            continue
        if view_type and v.get("view_type") != view_type:
            continue
        if stance and v.get("stance") != stance:
            continue
        ent_score = entity_overlap(entity, v, aliases) if entity else 0.0
        if entity and ent_score <= 0:
            # 兜底：文本包含实体名也算弱匹配。
            hay = f"{v.get('section','')} {v.get('claim','')} {v.get('evidence','')}"
            if entity not in hay:
                continue
            ent_score = 0.45
        vv = dict(v)
        vv["entity_score"] = round(ent_score, 3)
        vv["bucket"] = bucket_view(vv, ent_score)
        vv["rank_score"] = score_view(vv, ent_score)
        out.append(vv)
    out.sort(key=lambda x: (x.get("bucket", "Z"), -x.get("rank_score", 0), x.get("date", "")), reverse=False)
    return out


def query_views(
    entity: str | None = None,
    analyst: str | None = None,
    date_range: str | None = "7d",
    view_type: str | None = None,
    stance: str | None = None,
    limit: int = 20,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    views = load_views(path=path)
    return filter_views(views, entity=entity, analyst=analyst, date_range=date_range, view_type=view_type, stance=stance)[:limit]


def query_views_by_entity(
    entity: str,
    horizon: str | None = None,
    stance: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    view_type: str | None = None,
    views: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """按实体、日期、周期查询结构化观点。"""
    date_range = None
    if date_start or date_end:
        date_range = f"{date_start or ''}:{date_end or ''}"
    items = filter_views(
        views if views is not None else load_views(),
        entity=entity,
        date_range=date_range,
        view_type=view_type,
        stance=stance,
    )
    if horizon:
        items = [v for v in items if v.get("horizon") == horizon]
    return items


def get_latest_views(days: int = 3, limit: int = 50, sectors: list[str] | None = None) -> list[dict[str, Any]]:
    dr = f"{days}d"
    views = load_views()
    items = filter_views(views, date_range=dr)
    if sectors:
        allowed = set(sectors)
        items = [v for v in items if allowed & set((v.get("entities") or {}).get("sectors", []))]
    # 最新优先；同 source/section 不刷屏。
    items.sort(key=lambda x: (x.get("date", ""), x.get("rank_score", 0)), reverse=True)
    seen = set()
    out = []
    for v in items:
        key = (v.get("source_file"), v.get("section"), tuple((v.get("entities") or {}).get("sectors", [])))
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
        if len(out) >= limit:
            break
    return out


def stats(views: list[dict[str, Any]]) -> dict[str, Any]:
    by_date = Counter(v.get("date", "") for v in views)
    by_analyst = Counter(v.get("analyst", "") for v in views)
    by_sector = Counter()
    by_type = Counter(v.get("view_type", "") for v in views)
    for v in views:
        for s in (v.get("entities") or {}).get("sectors", []):
            by_sector[s] += 1
    return {
        "total_views": len(views),
        "date_min": min((d for d in by_date if d), default=""),
        "date_max": max((d for d in by_date if d), default=""),
        "by_date_top": by_date.most_common(20),
        "by_analyst": by_analyst.most_common(),
        "by_sector_top": by_sector.most_common(30),
        "by_type": by_type.most_common(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="结构化观点库查询")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("stats")
    q = sub.add_parser("query")
    q.add_argument("--entity")
    q.add_argument("--analyst")
    q.add_argument("--date-range", default="7d")
    q.add_argument("--view-type")
    q.add_argument("--stance")
    q.add_argument("--limit", type=int, default=10)
    q.add_argument("--json", action="store_true")
    l = sub.add_parser("latest")
    l.add_argument("--days", type=int, default=3)
    l.add_argument("--limit", type=int, default=20)
    l.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.cmd == "stats":
        print(json.dumps(stats(load_views()), ensure_ascii=False, indent=2))
        return
    if args.cmd == "query":
        res = query_views(entity=args.entity, analyst=args.analyst, date_range=args.date_range, view_type=args.view_type, stance=args.stance, limit=args.limit)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            for i, v in enumerate(res, 1):
                secs = ",".join((v.get("entities") or {}).get("sectors", []))
                print(f"[{i}] {v.get('date')} {v.get('analyst')} {secs} {v.get('stance')}/{v.get('horizon')} score={v.get('rank_score')} bucket={v.get('bucket')}")
                print(f"    {v.get('claim')}")
                print(f"    来源: {v.get('source_file')}")
        return
    if args.cmd == "latest":
        res = get_latest_views(days=args.days, limit=args.limit)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            for i, v in enumerate(res, 1):
                secs = ",".join((v.get("entities") or {}).get("sectors", []))
                print(f"[{i}] {v.get('date')} {v.get('analyst')} {secs} {v.get('claim')[:90]}")
        return
    parser.print_help()


if __name__ == "__main__":
    main()
