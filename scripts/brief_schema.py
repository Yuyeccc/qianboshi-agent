#!/usr/bin/env python3
"""盘前简报 JSON schema 与校验器。

目标：把 LLM 输出从自由 Markdown 约束为可校验 JSON，再由 brief_renderer.py 稳定渲染。
不依赖 jsonschema 第三方库，避免部署额外依赖。
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

BANNED_ANALYSTS = ["主力行为学", "汤山老王", "马跑跑", "邻居大爷", "八叔不啰嗦"]
REQUIRED_VIEW_FIELDS = ["view_id", "analyst", "date", "source_file", "claim"]
VALID_STANCES = {"bullish", "bearish", "neutral", "watch", "risk", "mixed"}
VALID_HORIZONS = {"intraday", "short", "medium", "long", "unknown"}
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
VIEW_ID_RE = re.compile(r"^[0-9a-f]{8,40}$", re.I)


def empty_brief(date_str: str | None = None) -> dict[str, Any]:
    """返回最小合法简报 JSON 骨架。"""
    d = date_str or datetime.now().strftime("%Y-%m-%d")
    return {
        "schema_version": 1,
        "brief_date": d,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "session_note": "",
        "market_snapshot": {
            "indexes": {},
            "tracked_prices": {},
            "notes": [],
        },
        "market_context": {
            "trade_date": d,
            "session_type": "cached",
            "indexes": {},
            "sectors": {},
            "symbols": {},
            "overnight": {},
            "notes": [],
        },
        "sections": [],
        "risk_alerts": [],
        "source_view_ids": [],
        "disclaimer": "仅整理公开内容与行情数据，不构成投资建议。",
    }


def compact_view(v: dict[str, Any]) -> dict[str, Any]:
    """将 view_store 观点压缩成 brief schema 可用的 evidence view。"""
    return {
        "view_id": v.get("view_id", ""),
        "analyst": v.get("analyst", ""),
        "date": v.get("date", ""),
        "source_file": v.get("source_file", ""),
        "section": v.get("section", ""),
        "entities": v.get("entities", {}),
        "stance": v.get("stance", "neutral"),
        "horizon": v.get("horizon", "unknown"),
        "view_type": v.get("view_type", "general"),
        "claim": v.get("claim", ""),
        "logic": v.get("logic", ""),
        "risk": v.get("risk", ""),
        "evidence": v.get("evidence", ""),
        "rank_score": v.get("rank_score"),
        "bucket": v.get("bucket"),
        "time_bucket": v.get("time_bucket"),
        "asset_relevance_score": v.get("asset_relevance_score"),
        "evidence_relevance": v.get("evidence_relevance"),
        "asr_confidence": v.get("asr_confidence"),
        "prediction_confidence": v.get("prediction_confidence"),  # #70：预测力徽标消费字段
    }


def make_section(title: str, summary: str = "", views: list[dict[str, Any]] | None = None, section_type: str = "analysis") -> dict[str, Any]:
    return {
        "title": title,
        "type": section_type,
        "summary": summary,
        "views": [compact_view(v) for v in (views or [])],
        "consensus": "",
        "divergence": "",
        "action_watch": [],
    }


def _check_view(v: dict[str, Any], path: str, errors: list[dict[str, str]], warnings: list[dict[str, str]]) -> None:
    for f in REQUIRED_VIEW_FIELDS:
        if not v.get(f):
            errors.append({"path": f"{path}.{f}", "type": "missing_required_view_field", "message": f"观点缺字段 {f}"})
    if v.get("view_id") and not VIEW_ID_RE.match(str(v.get("view_id"))):
        warnings.append({"path": f"{path}.view_id", "type": "weak_view_id", "message": "view_id 格式不像结构化观点ID"})
    if v.get("date") and not DATE_RE.match(str(v.get("date"))):
        errors.append({"path": f"{path}.date", "type": "bad_date", "message": "观点日期必须是 YYYY-MM-DD"})
    if v.get("stance") and v.get("stance") not in VALID_STANCES:
        warnings.append({"path": f"{path}.stance", "type": "unknown_stance", "message": f"未知立场 {v.get('stance')}"})
    if v.get("horizon") and v.get("horizon") not in VALID_HORIZONS:
        warnings.append({"path": f"{path}.horizon", "type": "unknown_horizon", "message": f"未知周期 {v.get('horizon')}"})
    hay = json.dumps(v, ensure_ascii=False)
    for banned in BANNED_ANALYSTS:
        if banned in hay:
            errors.append({"path": path, "type": "banned_analyst", "message": f"禁用分析师残留: {banned}"})
    if not v.get("evidence") and not v.get("logic"):
        warnings.append({"path": path, "type": "weak_evidence", "message": "观点缺 evidence/logic，证据弱"})


def validate_brief(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not isinstance(data, dict):
        return {"valid": False, "errors": [{"path": "$", "type": "not_object", "message": "brief 必须是 object"}], "warnings": []}
    if data.get("schema_version") != 1:
        errors.append({"path": "schema_version", "type": "bad_schema_version", "message": "schema_version 必须是 1"})
    if not DATE_RE.match(str(data.get("brief_date", ""))):
        errors.append({"path": "brief_date", "type": "bad_date", "message": "brief_date 必须是 YYYY-MM-DD"})
    for banned in BANNED_ANALYSTS:
        if banned in json.dumps(data, ensure_ascii=False):
            errors.append({"path": "$", "type": "banned_analyst", "message": f"禁用分析师残留: {banned}"})

    market_context = data.get("market_context")
    if market_context is not None:
        if not isinstance(market_context, dict):
            warnings.append({"path": "market_context", "type": "bad_market_context", "message": "market_context 应为 object"})
        elif "sectors" in market_context and not isinstance(market_context.get("sectors"), dict):
            warnings.append({"path": "market_context.sectors", "type": "bad_market_context_sectors", "message": "market_context.sectors 应为 object"})

    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append({"path": "sections", "type": "empty_sections", "message": "sections 不能为空"})
    else:
        for si, sec in enumerate(sections):
            p = f"sections[{si}]"
            if not sec.get("title"):
                errors.append({"path": f"{p}.title", "type": "missing_title", "message": "section 缺 title"})
            views = sec.get("views", [])
            if not isinstance(views, list):
                errors.append({"path": f"{p}.views", "type": "bad_views", "message": "views 必须是数组"})
                continue
            if sec.get("type") in ("analysis", "sector", "market") and not views:
                warnings.append({"path": f"{p}.views", "type": "no_views", "message": "分析类 section 没有结构化观点引用"})
            for vi, v in enumerate(views):
                _check_view(v, f"{p}.views[{vi}]", errors, warnings)

    source_ids = set(data.get("source_view_ids", []) or [])
    actual_ids = {v.get("view_id") for sec in data.get("sections", []) if isinstance(sec, dict) for v in sec.get("views", []) if isinstance(v, dict) and v.get("view_id")}
    if actual_ids and not source_ids:
        warnings.append({"path": "source_view_ids", "type": "missing_source_index", "message": "建议汇总 source_view_ids"})
    missing = actual_ids - source_ids if source_ids else set()
    if missing:
        warnings.append({"path": "source_view_ids", "type": "incomplete_source_index", "message": f"source_view_ids 漏 {len(missing)} 个 view_id"})

    return {
        "valid": not errors,
        "has_errors": bool(errors),
        "has_warnings": bool(warnings),
        "errors": errors,
        "warnings": warnings,
        "summary": f"errors={len(errors)}, warnings={len(warnings)}",
    }


def format_validation(report: dict[str, Any], max_items: int = 40) -> str:
    out = [f"[brief_schema] {report.get('summary')}"]
    for bucket in ["errors", "warnings"]:
        for item in report.get(bucket, [])[:max_items]:
            out.append(f"{bucket[:-1].upper()} {item.get('path')}: {item.get('type')} | {item.get('message')}")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="校验盘前简报 JSON")
    ap.add_argument("path", nargs="?", help="brief JSON path；为空则输出空 schema 样例")
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()
    if args.sample or not args.path:
        print(json.dumps(empty_brief(), ensure_ascii=False, indent=2))
        return
    path = Path(args.path)
    data = json.loads(path.read_text(encoding="utf-8"))
    report = validate_brief(data)
    print(format_validation(report))
    raise SystemExit(0 if report["valid"] else 2)


if __name__ == "__main__":
    main()
