#!/usr/bin/env python3
"""实体标准化与别名匹配。

用于结构化观点抽取、query_views 实体过滤、盘前简报板块归一化。
只依赖 PyYAML 和标准库；配置缺失时有内置最小词典回退。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config


DEFAULT_BANNED_ANALYSTS = ["主力行为学", "汤山老王", "马跑跑", "邻居大爷", "八叔不啰嗦"]
DEFAULT_ALLOWED_ANALYSTS = [
    "钱博士直播", "钱博士短视频", "钱博士", "李一恩", "旗帜鲜明", "笨笨的韭菜",
    "史诗级韭菜", "趋势天哥", "任泽平", "投机大拿", "柏年说", "财联社",
]

DEFAULT_ENTITIES = {
    "创新药": {"aliases": ["医药", "CXO", "CRO", "创新药ETF"], "etfs": ["159992.SZ"]},
    "光模块": {"aliases": ["光通讯", "光通信", "CPO", "光芯片", "通信设备", "新易盛", "中际旭创", "天孚通信"], "stocks": ["300502.SZ", "300308.SZ", "300394.SZ"]},
    "机器人": {"aliases": ["具身智能", "人形机器人", "减速器", "伺服"], "etfs": ["159770.SZ"]},
    "半导体": {"aliases": ["芯片", "半导体设备", "半导体材料", "中芯", "先进制程"], "etfs": ["159813.SZ"]},
    "存储": {"aliases": ["内存", "存储芯片", "DRAM", "NAND", "HBM", "长鑫", "长兴", "美光", "海力士"]},
    "黄金有色": {"aliases": ["黄金", "铜", "有色", "工业金属", "紫金", "紫金矿业"], "stocks": ["601899.SS"]},
    "大盘": {"aliases": ["市场整体", "A股", "指数", "上证", "深成指", "创业板", "大势", "盘面"]},
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_alias_path(config: dict[str, Any] | None = None) -> Path:
    config = config or load_config()
    p = config.get("entities", {}).get("aliases_path") if isinstance(config, dict) else None
    if p:
        path = Path(p)
        if not path.is_absolute():
            path = _project_root() / path
        return path
    return _project_root() / "config" / "entity_aliases.yaml"


def load_aliases(config: dict[str, Any] | None = None, path: str | Path | None = None) -> dict[str, Any]:
    """加载实体别名配置。"""
    alias_path = Path(path) if path else _resolve_alias_path(config)
    if alias_path.exists():
        try:
            import yaml
            data = yaml.safe_load(alias_path.read_text(encoding="utf-8")) or {}
            data.setdefault("entities", DEFAULT_ENTITIES)
            data.setdefault("banned_analysts", DEFAULT_BANNED_ANALYSTS)
            data.setdefault("allowed_analysts", DEFAULT_ALLOWED_ANALYSTS)
            data.setdefault("asr_corrections", {})
            return data
        except Exception as e:
            print(f"[WARN] 读取实体词典失败 {alias_path}: {e}", file=sys.stderr)
    return {
        "version": 0,
        "entities": DEFAULT_ENTITIES,
        "banned_analysts": DEFAULT_BANNED_ANALYSTS,
        "allowed_analysts": DEFAULT_ALLOWED_ANALYSTS,
        "asr_corrections": {},
    }


def normalize_text(text: str, aliases: dict[str, Any] | None = None) -> str:
    """应用 ASR 纠错词典，返回规范化文本。"""
    aliases = aliases or load_aliases()
    out = text or ""
    for wrong, right in (aliases.get("asr_corrections") or {}).items():
        out = out.replace(str(wrong), str(right))
    return out


def is_banned_source(source: str, aliases: dict[str, Any] | None = None) -> bool:
    aliases = aliases or load_aliases()
    return any(b in (source or "") for b in aliases.get("banned_analysts", DEFAULT_BANNED_ANALYSTS))


def detect_analyst(source_file: str, text: str = "", aliases: dict[str, Any] | None = None) -> str:
    """从文件名/frontmatter/text 中识别分析师。"""
    aliases = aliases or load_aliases()
    hay = f"{source_file} {text[:500]}"
    allowed = aliases.get("allowed_analysts", DEFAULT_ALLOWED_ANALYSTS)
    # 长名字先匹配，避免 钱博士 抢在 钱博士直播 前面。
    for name in sorted(allowed, key=len, reverse=True):
        if name and name in hay:
            if name == "钱博士" and "短视频" in hay:
                return "钱博士短视频"
            if name == "钱博士" and ("直播" in hay or "直播总结" in hay):
                return "钱博士直播"
            return name
    m = re.search(r"host:\s*([^\n\r]+)", text)
    if m:
        return m.group(1).strip()
    return "未知"


def extract_date_from_text(source_file: str, text: str = "") -> str:
    """提取 ISO 日期。优先 frontmatter/date，其次文件名。

    注意：正文里常有“预计 2026-08-25”这类未来事件日期，不能当成笔记日期；
    所以这里不再对全文做宽松日期搜索，只看 frontmatter 和文件名。
    """
    candidates = []
    # frontmatter date
    candidates.append(text[:500])
    # 文件名日期
    candidates.append(source_file or "")
    patterns = [
        r"date:\s*(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})",
        r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})",
    ]
    for hay in candidates:
        for pat in patterns:
            m = re.search(pat, hay)
            if not m:
                continue
            y, mo, d = m.groups()
            try:
                return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            except Exception:
                pass
    return ""


def classify_source_type(source_file: str, text: str = "") -> str:
    hay = f"{source_file} {text[:500]}"
    if "短视频" in hay:
        return "short_video"
    if "财联社" in hay:
        return "news"
    if "直播" in hay or "直播总结" in hay:
        return "livestream"
    return "note"


def normalize_symbol(code: str) -> str:
    code = (code or "").strip()
    if not code:
        return code
    if re.match(r"^\d{6}\.(SS|SZ)$", code):
        return code
    if re.match(r"^\d{6}$", code):
        return f"{code}.SS" if code.startswith(("60", "68", "51", "58")) else f"{code}.SZ"
    return code


def normalize_hk_symbol(code: str) -> str:
    code = (code or "").strip().upper()
    if not code:
        return code
    if code.endswith(".HK"):
        code = code[:-3]
    if re.match(r"^\d{4,5}$", code):
        return f"{int(code)}.HK"
    return code


def extract_entities(text: str, aliases: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """从文本提取标准实体。返回 sectors/stocks/etfs/themes/indexes/us_mapping。"""
    aliases = aliases or load_aliases()
    norm = normalize_text(text or "", aliases)
    entities_cfg = aliases.get("entities", DEFAULT_ENTITIES) or {}
    result: dict[str, set[str]] = {
        "sectors": set(), "stocks": set(), "etfs": set(), "themes": set(), "indexes": set(), "us_mapping": set()
    }

    for sector, info in entities_cfg.items():
        terms = [sector] + list(info.get("aliases", []) or [])
        if any(str(term) and str(term).lower() in norm.lower() for term in terms):
            result["sectors"].add(sector)
            for key in ["stocks", "etfs", "themes", "indexes", "us_mapping"]:
                for item in info.get(key, []) or []:
                    result[key].add(normalize_symbol(str(item)) if key in ("stocks", "etfs", "indexes") else str(item))

    for code in re.findall(r"(?<!\d)(\d{6})(?!\d)", norm):
        result["stocks"].add(normalize_symbol(code))
    for code in re.findall(r"\b(\d{6}\.(?:SS|SZ))\b", norm):
        result["stocks"].add(code)
    for ticker in re.findall(r"\b(NVDA|AMD|MRVL|AVGO|MU|TSLA|AAPL|MSFT|GOOGL|AMZN|META|TSM)\b", norm.upper()):
        result["us_mapping"].add(ticker)

    return {k: sorted(v) for k, v in result.items() if v}


def entity_overlap(query: str, view: dict[str, Any], aliases: dict[str, Any] | None = None) -> float:
    """计算 query 与 view.entities 的实体重合度，用于 query_views 排序。"""
    aliases = aliases or load_aliases()
    q = extract_entities(query, aliases)
    v = view.get("entities") or {}
    if not q:
        return 0.0
    best = 0.0
    weights = {"stocks": 1.0, "etfs": 0.9, "sectors": 0.75, "themes": 0.45, "us_mapping": 0.5, "indexes": 0.5}
    for key, w in weights.items():
        qs, vs = set(q.get(key, [])), set(v.get(key, []))
        if qs and vs and qs & vs:
            best = max(best, w)
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description="实体标准化/抽取")
    parser.add_argument("text", nargs="?", help="待分析文本")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()
    text = args.text or sys.stdin.read()
    aliases = load_aliases()
    res = extract_entities(text, aliases)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for k, v in res.items():
            print(f"{k}: {', '.join(v)}")


if __name__ == "__main__":
    main()
