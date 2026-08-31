#!/usr/bin/env python3
"""从结构化 Markdown 笔记抽取财经观点，生成 data/views/structured_views.jsonl。

MVP 目标：不用 LLM，先用规则稳定抽取最近笔记里的“观点对象”：
view_id/source_file/date/analyst/entities/stance/horizon/claim/logic/evidence。
后续可在此基础上加入 LLM 精抽。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import get_obsidian_path, load_config
from entity_normalizer import (
    classify_source_type,
    detect_analyst,
    extract_date_from_text,
    extract_entities,
    is_banned_source,
    load_aliases,
    normalize_text,
)

STANCE_MAP = {
    "看多": "bullish", "偏多": "bullish", "相对看多": "bullish", "中性偏多": "bullish",
    "看空": "bearish", "偏空": "bearish", "中性偏空": "bearish",
    "中性": "neutral", "谨慎": "neutral", "观望": "watch", "关注": "watch",
    "风险": "risk", "不适宜": "risk",
}

HORIZON_MAP = {
    "日内": "intraday", "今天": "intraday", "今日": "intraday",
    "短线": "short", "短期": "short", "过几天": "short", "明日": "short",
    "中长线": "medium", "中线": "medium", "中期": "medium",
    "长期": "long", "长线": "long", "长期持有": "long",
}

SECTION_RE = re.compile(r"^#{2,4}\s+(.+?)\s*$", re.M)
TIMESTAMP_RE = re.compile(r"(?:\(?(?:\d{1,2}:)?\d{1,4}[.:：]\d{1,2}(?:[.:：]\d{1,2})?s?\s*-\s*(?:\d{1,2}:)?\d{1,4}[.:：]\d{1,2}(?:[.:：]\d{1,2})?s?\)?)")


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_views_dir(config: dict[str, Any]) -> Path:
    from config_loader import get_data_dir
    p = get_data_dir(config) / "views"
    p.mkdir(parents=True, exist_ok=True)
    return p


def parse_iso_date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def source_bv(source_file: str) -> str:
    m = re.search(r"(BV[0-9A-Za-z]+)", source_file)
    return m.group(1) if m else ""


def split_sections(text: str) -> list[tuple[str, str]]:
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return [("正文", text)]
    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group(1).strip()
        body = text[start:end].strip()
        if body:
            sections.append((title, body))
    return sections


def clean_line(line: str) -> str:
    line = re.sub(r"^[-*+>]\s*", "", line.strip())
    line = re.sub(r"`{3,}.*", "", line).strip()
    return line


def detect_horizon(text: str) -> str:
    for k, v in HORIZON_MAP.items():
        if k in text:
            return v
    return "unknown"


def detect_stance(text: str) -> str:
    for k, v in STANCE_MAP.items():
        if k in text:
            return v
    if any(x in text for x in ["不要看", "不参与", "离开", "死刑", "下跌", "回调"]):
        return "bearish"
    if any(x in text for x in ["反弹", "修复", "走强", "机会", "量价齐升"]):
        return "bullish"
    return "neutral"


def classify_view_type(section: str, text: str, entities: dict[str, list[str]]) -> str:
    hay = f"{section} {text}"
    if "风险" in hay or "逃顶" in hay or "小心" in hay:
        return "risk"
    if "市场" in section or "大盘" in hay or "指数" in hay:
        return "market"
    if entities.get("stocks") and not entities.get("sectors"):
        return "stock"
    if entities.get("sectors"):
        return "sector"
    if "内容：" in text or "知识" in section or "框架" in hay or "法则" in hay:
        return "framework"
    return "general"


def short_text(s: str, n: int = 260) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:n].rstrip()


def quality_flags(view: dict[str, Any]) -> list[str]:
    flags = []
    for field in ["date", "evidence", "logic"]:
        if view.get(field):
            flags.append(f"has_{field}")
    if view.get("stance") and view.get("stance") != "neutral":
        flags.append("has_stance")
    if view.get("horizon") and view.get("horizon") != "unknown":
        flags.append("has_horizon")
    if view.get("risk"):
        flags.append("has_risk")
    return flags


def make_view_id(source_file: str, section: str, claim: str) -> str:
    raw = f"{source_file}|{section}|{claim}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:16]



def load_existing_views(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    views: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                views.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return views


def view_keys(view: dict[str, Any]) -> tuple[str | None, tuple[str, str] | None]:
    view_id = str(view.get("view_id") or "") or None
    source_file = str(view.get("source_file") or "")
    claim = str(view.get("claim") or "")
    source_claim = (source_file, claim) if source_file and claim else None
    return view_id, source_claim


def merge_views(existing: list[dict[str, Any]], new_views: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen_ids: set[str] = set()
    seen_source_claims: set[tuple[str, str]] = set()
    merged = list(existing)
    for view in existing:
        view_id, source_claim = view_keys(view)
        if view_id:
            seen_ids.add(view_id)
        if source_claim:
            seen_source_claims.add(source_claim)

    added = 0
    for view in new_views:
        view_id, source_claim = view_keys(view)
        if (view_id and view_id in seen_ids) or (source_claim and source_claim in seen_source_claims):
            continue
        merged.append(view)
        added += 1
        if view_id:
            seen_ids.add(view_id)
        if source_claim:
            seen_source_claims.add(source_claim)
    return merged, added

def extract_candidates_from_section(section: str, body: str) -> list[dict[str, str]]:
    """规则抽取候选观点。"""
    lines = [clean_line(x) for x in body.splitlines()]
    lines = [x for x in lines if x]
    cands: list[dict[str, str]] = []

    # 格式 A：短线/中长线：...
    for i, line in enumerate(lines):
        if re.match(r"^(短线|短期|中长线|中线|长期|长线|日内|今日|今天)[：:]", line):
            horizon_line = line
            ctx = [line]
            for j in range(i + 1, min(i + 6, len(lines))):
                if re.match(r"^(短线|短期|中长线|中线|长期|长线|日内|今日|今天)[：:]", lines[j]):
                    break
                ctx.append(lines[j])
            joined = "\n".join(ctx)
            logic = ""
            for x in ctx:
                if x.startswith("逻辑"):
                    logic = re.sub(r"^逻辑[：:]\s*", "", x)
                    break
            cands.append({"kind": "horizon", "claim": horizon_line, "logic": logic, "evidence": joined})

    # 格式 B：观点：...
    for i, line in enumerate(lines):
        if line.startswith("观点：") or line.startswith("观点:"):
            ctx = [line]
            for j in range(i + 1, min(i + 5, len(lines))):
                if lines[j].startswith("观点：") or re.match(r"^#{1,4}\s+", lines[j]):
                    break
                ctx.append(lines[j])
            cands.append({"kind": "观点", "claim": re.sub(r"^观点[：:]\s*", "", line), "logic": "", "evidence": "\n".join(ctx)})

    # 格式 C：预测倾向/条件/时间窗口，取附近内容
    for i, line in enumerate(lines):
        if line.startswith("预测倾向"):
            ctx = []
            for j in range(max(0, i - 2), min(len(lines), i + 5)):
                ctx.append(lines[j])
            claim = "；".join(ctx[:3])
            cands.append({"kind": "预测", "claim": claim, "logic": "", "evidence": "\n".join(ctx)})

    # 格式 D：涉及资产 + 影响结果 + 逻辑
    for i, line in enumerate(lines):
        if line.startswith("涉及资产"):
            ctx = [line]
            for j in range(i + 1, min(i + 6, len(lines))):
                if lines[j].startswith("涉及资产") or lines[j].startswith("内容："):
                    break
                ctx.append(lines[j])
            logic = ""
            for x in ctx:
                if x.startswith("逻辑"):
                    logic = re.sub(r"^逻辑[：:]\s*", "", x)
            cands.append({"kind": "资产", "claim": line, "logic": logic, "evidence": "\n".join(ctx)})

    # 格式 E：内容：市场知识/框架
    for i, line in enumerate(lines):
        if line.startswith("内容："):
            ctx = [line]
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j].startswith("内容：") or lines[j].startswith("涉及资产"):
                    break
                ctx.append(lines[j])
            cands.append({"kind": "内容", "claim": re.sub(r"^内容[：:]\s*", "", line), "logic": "", "evidence": "\n".join(ctx)})

    # 去重
    out = []
    seen = set()
    for c in cands:
        key = short_text(c.get("claim", ""), 120)
        if len(key) < 6 or key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def extract_views_from_file(path: Path, aliases: dict[str, Any], root_hint: Path | None = None) -> list[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    text = normalize_text(raw, aliases)
    source_file = str(path.name)
    if is_banned_source(source_file, aliases) or is_banned_source(text[:1000], aliases):
        return []
    analyst = detect_analyst(source_file, text, aliases)
    if is_banned_source(analyst, aliases) or analyst == "未知":
        # 未知先不收，避免污染 digest。
        return []
    doc_date = extract_date_from_text(source_file, text)
    if not doc_date:
        return []
    # 未来日期防护：笔记日期不得晚于明天（防止主播口播的未来日期被当成观点日期）
    try:
        if datetime.strptime(doc_date, "%Y-%m-%d").date() > date.today():
            return []
    except ValueError:
        return []
    source_type = classify_source_type(source_file, text)
    bv = source_bv(source_file)
    views: list[dict[str, Any]] = []

    for section, body in split_sections(text):
        if any(x in section for x in ["精华总结"]):
            # 精华总结可作为总体观点，但 MVP 先避免和下方观点重复。
            continue
        for cand in extract_candidates_from_section(section, body):
            evidence = short_text(cand.get("evidence", ""), 500)
            claim = short_text(cand.get("claim", ""), 240)
            if len(evidence) < 20 or len(claim) < 6:
                continue
            entities = extract_entities(f"{section}\n{claim}\n{evidence}", aliases)
            if not entities and cand.get("kind") not in ("内容",):
                continue
            horizon = detect_horizon(f"{claim}\n{evidence}")
            stance = detect_stance(f"{claim}\n{evidence}")
            logic = short_text(cand.get("logic") or "", 260)
            if not logic:
                m = re.search(r"逻辑[：:]\s*([^\n]+)", evidence)
                logic = short_text(m.group(1), 260) if m else ""
            risk = ""
            if any(x in evidence for x in ["风险", "小心", "警惕", "不确定", "不要", "不参与", "回调", "下跌"]):
                risk = short_text(evidence, 220)
            timestamp = ""
            tm = TIMESTAMP_RE.search(evidence)
            if tm:
                timestamp = tm.group(0).strip("()")
            view = {
                "version": 1,
                "view_id": make_view_id(source_file, section, claim),
                "source_file": source_file,
                "source_path": str(path),
                "source_bv": bv,
                "source_type": source_type,
                "analyst": analyst,
                "date": doc_date,
                "section": section,
                "timestamp": timestamp,
                "entities": entities,
                "stance": stance,
                "horizon": horizon,
                "view_type": classify_view_type(section, evidence, entities),
                "claim": claim,
                "logic": logic,
                "risk": risk,
                "evidence": evidence,
                "confidence": 0.6,
            }
            qflags = quality_flags(view)
            view["quality_flags"] = qflags
            view["confidence"] = round(min(0.95, 0.35 + 0.08 * len(qflags) + (0.08 if entities else 0)), 2)
            views.append(view)
    return views


def iter_note_files(config: dict[str, Any], include_notes_dir: bool = True) -> list[Path]:
    roots = [get_obsidian_path(config)]
    notes_dir = project_root() / "notes"
    if include_notes_dir and notes_dir.exists():
        roots.append(notes_dir)
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(root.rglob("*.md"))
    # 去重：同名优先 obsidian，然后 notes。
    seen = set()
    out = []
    for p in sorted(files, key=lambda x: str(x)):
        key = p.name
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="抽取结构化财经观点")
    parser.add_argument("--file", help="只抽取单个 Markdown 文件")
    parser.add_argument("--since", help="只抽取该日期及之后，如 2026-07-01")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 个文件，用于小批量测试")
    parser.add_argument("--rebuild", action="store_true", help="重建 structured_views.jsonl")
    parser.add_argument("--output", help="输出 JSONL 路径，默认 data/views/structured_views.jsonl")
    parser.add_argument("--no-notes-dir", action="store_true", help="不扫描项目 notes/ 目录")
    args = parser.parse_args()

    config = load_config()
    aliases = load_aliases(config)
    out_path = Path(args.output) if args.output else data_views_dir(config) / "structured_views.jsonl"
    report_path = data_views_dir(config) / "view_extraction_report.json"
    since_date = parse_iso_date(args.since) if args.since else None

    if args.file:
        files = [Path(args.file)]
    else:
        files = iter_note_files(config, include_notes_dir=not args.no_notes_dir)

    selected = []
    for p in files:
        # 快速按文件名/frontmatter日期过滤。
        d = extract_date_from_text(p.name, p.read_text(encoding="utf-8", errors="ignore")[:1000] if p.exists() else "")
        dd = parse_iso_date(d) if d else None
        if since_date and (not dd or dd < since_date):
            continue
        selected.append(p)
    if args.limit:
        selected = selected[: args.limit]

    all_views: list[dict[str, Any]] = []
    by_file: dict[str, int] = {}
    for p in selected:
        views = extract_views_from_file(p, aliases)
        if views:
            all_views.extend(views)
            by_file[str(p)] = len(views)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    merge_mode = bool(args.file or args.since) and not args.rebuild
    if merge_mode:
        print("--since/--file use merge append mode; only --rebuild overwrites the full view store.")
        existing_views = load_existing_views(out_path)
        views_to_write, views_added = merge_views(existing_views, all_views)
        report_mode = "merge"
        write_mode = "w"
    elif args.rebuild or not out_path.exists():
        views_to_write = all_views
        views_added = len(all_views)
        report_mode = "rebuild" if args.rebuild else "append"
        write_mode = "w"
    else:
        views_to_write = all_views
        views_added = len(all_views)
        report_mode = "append"
        write_mode = "a"

    with out_path.open(write_mode, encoding="utf-8", newline="\n") as f:
        for v in views_to_write:
            f.write(json.dumps(v, ensure_ascii=False, sort_keys=True) + "\n")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output": str(out_path),
        "mode": report_mode,
        "files_scanned": len(selected),
        "files_with_views": len(by_file),
        "views_extracted": len(all_views),
        "views_added": views_added,
        "views_written": len(views_to_write),
        "by_file_sample": dict(list(by_file.items())[:30]),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
