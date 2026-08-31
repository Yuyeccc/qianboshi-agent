#!/usr/bin/env python3
"""Hybrid 盘前简报生成器。

目标：
1. 先由 brief_renderer.build_from_views() 确定性构建 brief JSON，锁死 views/source_view_ids/market_snapshot。
2. LLM 只润色每个 section 的 summary/consensus/divergence/action_watch。
3. 合并时只接受上述白名单字段，不允许 LLM 新增/删除/修改证据链。
4. 最终仍交给 brief_schema 校验、brief_renderer 稳定渲染 Markdown。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from brief_renderer import _build_top_themes, _default_theme_watch, build_from_views, render_markdown
from brief_schema import format_validation, validate_brief
from config_loader import get_llm_config, load_config

ALLOWED_SECTION_FIELDS = {"summary", "consensus", "divergence", "action_watch"}
MAX_FIELD_CHARS = 360
MAX_ACTION_ITEMS = 5
MAX_ACTION_CHARS = 120


SYSTEM_PROMPT = """你是财经盘前简报编辑，不是投顾。
你的任务不是重新分析，也不是增删观点，而是把已有结构化观点润色成更像人写的盘前简报。

硬性规则：
1. 只能根据输入 JSON 里的 views 写 summary/consensus/divergence/action_watch。
2. 不得新增分析师、日期、股票代码、行情、view_id、source_file。
3. 不得删除或改写证据链；证据链由程序保留，你只返回可读文字字段。
4. 没有足够证据就写“待验证”，不要编。
5. 每个 section 的文字必须简短、务实、盘前可执行。
6. 不给买卖建议，只写观察点和风险。
7. 输出必须是纯 JSON，不要 Markdown，不要代码块。
"""


USER_TEMPLATE = """请润色下面这份结构化盘前简报的每个 section。

只输出如下 JSON 结构：
{{
  "sections": [
    {{
      "section_index": 0,
      "summary": "...",
      "consensus": "...",
      "divergence": "...",
      "action_watch": ["...", "..."]
    }}
  ]
}}

输入 brief JSON（证据链字段只供你理解，不能改）：
{brief_json}
"""

SECTION_TEMPLATE = """请只润色下面这一个 section。

只输出如下 JSON 结构：
{{
  "section_index": {section_index},
  "summary": "...",
  "consensus": "...",
  "divergence": "...",
  "action_watch": ["...", "..."]
}}

输入 section JSON（views 只供理解，不能改证据链）：
{section_json}
"""


def _section_for_llm(sec: dict[str, Any], index: int) -> dict[str, Any]:
    """压缩 section，避免把长字段全部塞给 LLM。"""
    views = []
    for v in sec.get("views", [])[:6]:
        views.append({
            "view_id": v.get("view_id"),
            "analyst": v.get("analyst"),
            "date": v.get("date"),
            "source_file": v.get("source_file"),
            "stance": v.get("stance"),
            "horizon": v.get("horizon"),
            "claim": v.get("claim"),
            "logic": v.get("logic"),
            "risk": v.get("risk"),
            "evidence": v.get("evidence"),
        })
    return {
        "section_index": index,
        "title": sec.get("title"),
        "type": sec.get("type"),
        "current_summary": sec.get("summary"),
        "current_consensus": sec.get("consensus"),
        "current_divergence": sec.get("divergence"),
        "current_action_watch": sec.get("action_watch"),
        "views": views,
    }


def make_llm_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "brief_date": data.get("brief_date"),
        "session_note": data.get("session_note"),
        "sections": [_section_for_llm(sec, i) for i, sec in enumerate(data.get("sections", []))],
        "risk_alerts": data.get("risk_alerts", []),
    }


def _extract_json(text: str) -> dict[str, Any]:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        end = s.rfind("}")
        if start >= 0 and end > start:
            return json.loads(s[start:end + 1])
        raise


def _clip_text(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def _sanitize_actions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:MAX_ACTION_ITEMS]:
        text = _clip_text(item, MAX_ACTION_CHARS)
        if text:
            out.append(text)
    return out


def _llm_json_request(messages: list[dict[str, str]], config_path: str | None = None, max_tokens: int = 1200) -> dict[str, Any]:
    config = load_config(config_path)
    llm = get_llm_config(config)
    if not llm.get("api_key"):
        raise RuntimeError("API key 未配置：无法执行 hybrid LLM 润色")

    # 贵模型优先（2026-08-22）：premium gpt-5.6 → fallback pro
    from llm_fallback import call_analysis_llm

    content, _used_model = call_analysis_llm(
        llm,
        messages,
        temperature=min(float(llm.get("temperature_analysis", 0.7)), 0.4),
        max_tokens=max_tokens,
        json_mode=True,
        timeout=180,
    )
    return _extract_json(content)


def call_llm_for_polish(payload: dict[str, Any], config_path: str | None = None) -> dict[str, Any]:
    """整份简报一次性润色。保留作兼容；实际默认用逐 section。"""
    brief_json = json.dumps(payload, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(brief_json=brief_json)},
    ]
    return _llm_json_request(messages, config_path=config_path, max_tokens=4096)


def call_llm_for_section(section_payload: dict[str, Any], config_path: str | None = None) -> dict[str, Any]:
    section_index = int(section_payload.get("section_index", 0))
    section_json = json.dumps(section_payload, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": SECTION_TEMPLATE.format(section_index=section_index, section_json=section_json)},
    ]
    return _llm_json_request(messages, config_path=config_path, max_tokens=1000)


def call_llm_for_sections(payload: dict[str, Any], config_path: str | None = None) -> dict[str, Any]:
    """逐 section 润色，单节失败则跳过，避免坏 JSON 拖垮整份简报。"""
    patches = []
    for sec in payload.get("sections", []):
        try:
            patch = call_llm_for_section(sec, config_path=config_path)
            if isinstance(patch, dict):
                patch.setdefault("section_index", sec.get("section_index"))
                patches.append(patch)
        except Exception as e:
            print(f"[WARN] section {sec.get('section_index')} LLM润色失败，保留确定性文本: {e}", file=sys.stderr)
            continue
    return {"sections": patches}


def merge_polish(base: dict[str, Any], polish: dict[str, Any]) -> dict[str, Any]:
    """只合并白名单文字字段，证据链字段完全来自 base。"""
    data = deepcopy(base)
    sections_patch = polish.get("sections", []) if isinstance(polish, dict) else []
    if not isinstance(sections_patch, list):
        return data

    for patch_sec in sections_patch:
        if not isinstance(patch_sec, dict):
            continue
        try:
            idx = int(patch_sec.get("section_index"))
        except Exception:
            continue
        if idx < 0 or idx >= len(data.get("sections", [])):
            continue
        target = data["sections"][idx]
        for field in ALLOWED_SECTION_FIELDS:
            if field not in patch_sec:
                continue
            if field == "action_watch":
                actions = _sanitize_actions(patch_sec.get(field))
                deterministic = _default_theme_watch(str(target.get("title") or ""))
                if actions:
                    target[field] = deterministic + [a for a in actions if a not in deterministic]
            else:
                text = _clip_text(patch_sec.get(field))
                if text:
                    target[field] = text

    data["session_note"] = (data.get("session_note") or "") + " + LLM白名单润色"
    data["generated_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        data["top_themes"] = _build_top_themes(
            data.get("sections", []),
            brief_date=data.get("brief_date") or datetime.now().strftime("%Y-%m-%d"),
            limit=3,
            market_context=data.get("market_context"),
        )
    except Exception:
        pass
    return data


def build_hybrid(days: int = 30, per_entity: int = 4, config_path: str | None = None, no_llm: bool = False) -> dict[str, Any]:
    base = build_from_views(days=days, per_entity=per_entity)
    if no_llm:
        return base
    payload = make_llm_payload(base)
    polish = call_llm_for_sections(payload, config_path=config_path)
    return merge_polish(base, polish)


def main() -> None:
    ap = argparse.ArgumentParser(description="生成 hybrid 盘前简报：结构化证据链 + LLM白名单润色")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--per-entity", type=int, default=4)
    ap.add_argument("--config", help="指定 config.yaml")
    ap.add_argument("--json-out", help="保存 hybrid JSON")
    ap.add_argument("--output", help="保存 Markdown")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="跳过 LLM，仅用于调试确定性构建")
    args = ap.parse_args()

    data = build_hybrid(days=args.days, per_entity=args.per_entity, config_path=args.config, no_llm=args.no_llm)
    report = validate_brief(data)

    if args.json_out:
        p = Path(args.json_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.validate_only:
        print(format_validation(report))
        raise SystemExit(0 if report["valid"] else 2)

    md = render_markdown(data)
    if args.output:
        p = Path(args.output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md, encoding="utf-8")
        print(str(p))
    else:
        print(md)

    if not report["valid"]:
        print(format_validation(report), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
