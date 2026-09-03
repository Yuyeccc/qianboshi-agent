#!/usr/bin/env python3
"""实体词典覆盖审计（记忆体系 P2 刀0，2026-09-03）。

只读工具：统计 structured_views.jsonl 的 entities 字段对
config/entity_aliases.yaml（回退 entity_normalizer.DEFAULT_ENTITIES）的可归一覆盖率，
输出未覆盖 TOP 清单与挂载建议——"词典成熟度"数据化判定（D1：主口径 ≥85% 视为成熟，
开刀1 冲突检测器）。词典补录仍走人工确认，本脚本不写任何文件。

通道与口径：
- 中文通道（主口径）：sectors + themes，命中方式 mode1=全等（canonical 名/aliases/themes）、
  mode2=canonical 名（≥2 字）为实体词子串。主口径覆盖率 = (mode1+mode2 条数) / 中文总条数。
- 代码通道（辅助口径）：etfs/stocks 反查 canonical.etfs/stocks；indexes/us_mapping 为
  词典未覆盖域（无对应键），单列统计供扩展决策，不计入主口径。

用法：
  C:/Python314/python.exe scripts/entity_coverage_audit.py [--top N] [--min-freq M]
      [--jsonl data/views/structured_views.jsonl] [--aliases-path config/entity_aliases.yaml]
      [--by-entity] [--json]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from entity_normalizer import load_aliases  # noqa: E402

DEFAULT_JSONL = Path(__file__).resolve().parent.parent / "data" / "views" / "structured_views.jsonl"
CODE_CHANNELS = ("etfs", "stocks", "indexes", "us_mapping")
CN_CHANNELS = ("sectors", "themes")


def build_maps(aliases: dict) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """构建 [词→canonical] 全等表、[代码→canonical] 反查表、canonical 名列表(长→短)。

    aliases = load_aliases() 返回的 dict：{"entities": {canonical: {aliases, etfs, themes, stocks}}}
    """
    entities = aliases.get("entities") or {}
    alias_map: dict[str, str] = {}
    code_map: dict[str, str] = {}
    for canonical, spec in entities.items():
        if not isinstance(spec, dict):
            continue
        names = {canonical}
        for k in ("aliases", "themes"):
            for w in spec.get(k) or []:
                if isinstance(w, str):
                    names.add(w)
        for w in names:
            # 已有映射不覆盖：词典内冲突时先注册者胜（yaml 顺序=人工优先级）
            alias_map.setdefault(w, canonical)
        for k in ("etfs", "stocks"):
            for c in spec.get(k) or []:
                if isinstance(c, str):
                    code_map.setdefault(c, canonical)
    canon_sorted = sorted(entities.keys(), key=len, reverse=True)
    return alias_map, code_map, canon_sorted


def classify_word(word: str, alias_map: dict, canon_sorted: list[str]) -> tuple[str, str]:
    """返回 (canonical|None, mode)。mode: 'mode1'|'mode2'|'uncovered'。"""
    if word in alias_map:
        return alias_map[word], "mode1"
    for c in canon_sorted:
        if len(c) >= 2 and c in word:
            return c, "mode2"
    return None, "uncovered"


def scan(jsonl_path: Path, alias_map: dict, code_map: dict, canon_sorted: list[str],
         min_freq: int, by_entity: bool):
    stats = {
        "views_total": 0, "views_with_entities": 0, "views_cover_cn": 0,
        "cn_total": 0, "cn_mode1": 0, "cn_mode2": 0, "cn_uncovered": 0,
        "code_total": 0, "code_hit": 0, "domain_total": {"etfs": 0, "stocks": 0, "indexes": 0, "us_mapping": 0},
        "code_hit_domain": {"etfs": 0, "stocks": 0},
        "canonical_hits": collections.Counter(),
    }
    uncov_words: collections.Counter = collections.Counter()

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            stats["views_total"] += 1
            e = d.get("entities")
            if not e or not isinstance(e, dict):
                continue
            stats["views_with_entities"] += 1
            view_has_cn = False
            for ch in CN_CHANNELS:
                for w in e.get(ch) or []:
                    if not isinstance(w, str) or not w:
                        continue
                    stats["cn_total"] += 1
                    canon, mode = classify_word(w, alias_map, canon_sorted)
                    if mode in ("mode1", "mode2"):
                        view_has_cn = True
                        stats["canonical_hits"][canon] += 1
                        if mode == "mode1":
                            stats["cn_mode1"] += 1
                        else:
                            stats["cn_mode2"] += 1
                    else:
                        stats["cn_uncovered"] += 1
                        uncov_words[(w, ch)] += 1
            for ch in CODE_CHANNELS:
                for c in e.get(ch) or []:
                    if not isinstance(c, str) or not c:
                        continue
                    stats["domain_total"][ch] += 1
                    if ch in ("etfs", "stocks"):
                        stats["code_total"] += 1
                        canon = code_map.get(c)
                        if canon:
                            stats["code_hit"] += 1
                            stats["code_hit_domain"][ch] += 1
                        else:
                            uncov_words[(c, ch)] += 1
                    else:
                        uncov_words[(c, ch)] += 1
            if view_has_cn:
                stats["views_cover_cn"] += 1
    return stats, uncov_words


def render_report(stats: dict, uncov_words: collections.Counter, canon_sorted: list[str],
                  top: int, min_freq: int, by_entity: bool, aliases: dict) -> str:
    cn = stats["cn_total"]
    cn_hit = stats["cn_mode1"] + stats["cn_mode2"]
    cn_rate = cn_hit / cn if cn else 0.0
    code_rate = stats["code_hit"] / stats["code_total"] if stats["code_total"] else 0.0
    vc = stats["views_with_entities"]
    v_rate = stats["views_cover_cn"] / vc if vc else 0.0
    lines = []
    A = lines.append
    A("=" * 64)
    A("实体词典覆盖审计 report（P2 刀0 / 只读）")
    A("=" * 64)
    A(f"数据源：structured_views.jsonl  views_total={stats['views_total']}  "
      f"带entities={vc}  空={stats['views_total'] - vc}")
    A("")
    A(f"[主口径·中文实体] sectors+themes 共 {cn} 条")
    A(f"  mode1 全等命中  {stats['cn_mode1']}  ({stats['cn_mode1'] / cn * 100:.1f}%)" if cn else "  mode1 0")
    A(f"  mode2 子串命中  {stats['cn_mode2']}  ({stats['cn_mode2'] / cn * 100:.1f}%)" if cn else "  mode2 0")
    A(f"  未覆盖         {stats['cn_uncovered']}  ({stats['cn_uncovered'] / cn * 100:.1f}%)" if cn else "  未覆盖 0")
    A(f"  ★ 主口径覆盖率 = {cn_rate * 100:.2f}%  （D1 阈值 ≥85% → 开刀1 检测器）")
    A("")
    A(f"[辅助口径·代码反查] etfs+stocks 共 {stats['code_total']} 条（词典有键域），命中 "
      f"{stats['code_hit']}  ({code_rate * 100:.1f}%)")
    A(f"  domain: etfs={stats['domain_total']['etfs']} (hit {stats['code_hit_domain']['etfs']})  "
      f"stocks={stats['domain_total']['stocks']} (hit {stats['code_hit_domain']['stocks']})")
    A(f"[词典未覆盖域] indexes={stats['domain_total']['indexes']}  us_mapping={stats['domain_total']['us_mapping']} "
      "（词典无此二键，扩展候选；indexes 指数代码可挂 大盘，us_mapping 美股代码待定域）")
    A(f"[view 级] 含≥1 可归一中文实体的 view = {stats['views_cover_cn']}/{vc} ({v_rate * 100:.1f}%)")
    A("[注] 中文 sectors/themes 为词典驱动闭集（抽取时经 entity_normalizer 归一，distinct 词有限），"
      "中文 100% 属预期；真实开放域=代码通道未命中 + claim/logic 自由文本")
    A("")
    A(f"[per-canonical 命中]（前 14，共 {len(stats['canonical_hits'])} canonical 有命中）")
    for canon, n in stats["canonical_hits"].most_common(14):
        A(f"  {canon:<10} {n}")
    A("")
    A(f"[未覆盖 TOP{top}（中文词，含挂载建议）]")
    cn_uncov = [(w, ch, n) for (w, ch), n in uncov_words.items() if ch in CN_CHANNELS and n >= min_freq]
    cn_uncov.sort(key=lambda x: -x[2])
    shown = 0
    for w, ch, n in cn_uncov[:top]:
        sugg = _suggest(w, canon_sorted)
        A(f"  {n:>5}  [{ch}] {w}" + (f"  → 建议挂: {sugg}" if sugg else "  （无 canonical 子串，待人工定）"))
        shown += 1
    if shown == 0:
        A("  （无，全命中）")
    A("")
    A(f"[未覆盖 TOP{min(top, 10)}（代码通道 indexes/us_mapping）]")
    code_uncov = [(w, ch, n) for (w, ch), n in uncov_words.items() if ch in CODE_CHANNELS and n >= min_freq]
    code_uncov.sort(key=lambda x: -x[2])
    for w, ch, n in code_uncov[: min(top, 10)]:
        A(f"  {n:>5}  [{ch}] {w}")
    if not code_uncov:
        A("  （无）")
    return "\n".join(lines)


def _suggest(word: str, canon_sorted: list[str]) -> str:
    for c in canon_sorted:
        if len(c) >= 2 and c in word:
            return c
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="实体词典覆盖审计（只读）")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--min-freq", type=int, default=1)
    ap.add_argument("--jsonl", type=str, default=str(DEFAULT_JSONL))
    ap.add_argument("--aliases-path", type=str, default=None)
    ap.add_argument("--by-entity", action="store_true", help="保留位：per-entity 明细（当前输出 canonical 汇总）")
    ap.add_argument("--json", action="store_true", help="JSON 输出（机器可读，覆盖率判定用）")
    args = ap.parse_args()

    jsonl = Path(args.jsonl)
    if not jsonl.exists():
        print(f"[ERR] 数据源不存在: {jsonl}", file=sys.stderr)
        return 2
    aliases = load_aliases(path=args.aliases_path) if args.aliases_path else load_aliases()
    alias_map, code_map, canon_sorted = build_maps(aliases)
    stats, uncov_words = scan(jsonl, alias_map, code_map, canon_sorted, args.min_freq, args.by_entity)

    if args.json:
        cn = stats["cn_total"]
        out = {
            "views_total": stats["views_total"],
            "views_with_entities": stats["views_with_entities"],
            "cn_total": cn,
            "cn_mode1": stats["cn_mode1"],
            "cn_mode2": stats["cn_mode2"],
            "cn_uncovered": stats["cn_uncovered"],
            "cn_coverage": round((stats["cn_mode1"] + stats["cn_mode2"]) / cn * 100, 2) if cn else 0.0,
            "code_total": stats["code_total"],
            "code_hit": stats["code_hit"],
            "domains": stats["domain_total"],
        }
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    print(render_report(stats, uncov_words, canon_sorted, args.top, args.min_freq, args.by_entity, aliases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
