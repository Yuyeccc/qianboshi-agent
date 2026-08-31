#!/usr/bin/env python3
"""Create professional and plain-language versions from one validated brief JSON."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from brief_hybrid import build_hybrid
from brief_renderer import render_markdown
from brief_schema import format_validation, validate_brief

ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = ROOT / "data" / "tmp"


def _strip_evidence_noise(text: str) -> str:
    text = re.sub(r"（证据链：[^）]+）", "", text)
    text = re.sub(r"view_id=[^；\n|]+；[^\n|]+", "证据已留存", text)
    text = text.replace("结构化观点", "公开观点")
    text = text.replace("市场分", "盘面强弱分")
    return text


def render_plain_markdown(data: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# 盘前简报（普通人版） | {data.get('brief_date', '')}")
    lines.append("")
    lines.append("> 这版说人话：先看市场环境，再看三条主线、谁在什么时候说过、盘中怎么验证、什么情况说明看错。不是买卖建议。")
    lines.append("")

    market = data.get("market_snapshot") or {}
    indexes = market.get("indexes") or {}
    tracked = market.get("tracked_prices") or {}
    if indexes or tracked:
        lines.append("## 1. 先看市场环境")
        if indexes:
            for sym, info in list(indexes.items())[:10]:
                if not isinstance(info, dict):
                    continue
                name = info.get("name") or sym
                price = info.get("price")
                change = info.get("change_pct")
                change_s = "涨跌待确认" if change is None else f"{float(change):+.2f}%"
                ten = info.get("change_10d_pct")
                ten_s = "" if ten is None else f"，近10日{float(ten):+.2f}%"
                lines.append(f"- {name}（{sym}）：{price}，今天{change_s}{ten_s}")
        if tracked:
            hot = []
            for sym, info in tracked.items():
                if not isinstance(info, dict):
                    continue
                try:
                    hot.append((abs(float(info.get("change_pct") or 0)), sym, info))
                except Exception:
                    pass
            hot.sort(reverse=True)
            if hot:
                lines.append("- 国内重点票：" + "；".join(
                    f"{sym} {float(info.get('change_pct') or 0):+.2f}%"
                    for _, sym, info in hot[:8]
                ))
        lines.append("")

    market_context = data.get("market_context") or {}
    sectors = market_context.get("sectors") if isinstance(market_context, dict) else {}
    if isinstance(sectors, dict) and sectors:
        ranked = sorted(sectors.items(), key=lambda x: ((x[1] or {}).get("rank") or 999, -float((x[1] or {}).get("score") or 0), x[0]))
        lines.append("## 2. 板块强弱")
        for name, info in ranked[:8]:
            if not isinstance(info, dict):
                continue
            ret = info.get("return_pct")
            rel = info.get("relative_strength")
            ret_s = "涨跌待确认" if ret is None else f"{float(ret):+.2f}%"
            rel_s = "相对强弱待确认" if rel is None else f"相对基准{float(rel):+.2f}pct"
            proxy = info.get("market_proxy") or "代理标的待核验"
            lines.append(f"- {name}：{proxy} 今天{ret_s}，{rel_s}，市场分{float(info.get('score') or 0):.2f}")
        lines.append("")

    top = data.get("top_themes") or []
    lines.append("## 3. 今天重点看这三条")
    if not top:
        lines.append("- 暂时没有足够证据排出Top3，先看大盘和成交量。")
    for item in top[:3]:
        lines.append(f"### {item.get('rank')}. {item.get('title')}：{item.get('level')}")
        summary = _strip_evidence_noise(str(item.get("summary") or "待验证"))
        lines.append(f"- 简单说：{summary}")
        refs = item.get("evidence_refs") or []
        plain_refs = []
        for ref in refs[:2]:
            m = re.search(r"；([^；]+?) (\d{4}-\d{2}-\d{2})；", str(ref))
            if m:
                plain_refs.append(f"{m.group(1)} {m.group(2)}")
        if plain_refs:
            lines.append(f"- 这个判断来自：{'；'.join(plain_refs)}")
        watch = item.get("watch") or []
        if watch:
            lines.append(f"- 怎么确认：{'；'.join(str(x) for x in watch[:3])}")
        invalid = item.get("invalid")
        if invalid:
            lines.append(f"- 什么情况要小心：{invalid}")
        reason = item.get("selection_reason") or []
        if reason:
            cleaned = []
            for x in reason:
                s = str(x)
                if s.startswith("观点时效="):
                    cleaned.append("观点够新：" + s.split("=", 1)[1])
                elif s.startswith("市场分="):
                    cleaned.append("盘面强弱分：" + s.split("=", 1)[1])
                elif s.startswith("证据相关度="):
                    cleaned.append("和这个方向直接相关")
            if cleaned:
                lines.append(f"- 为什么放进重点：{'；'.join(cleaned[:4])}")
        lines.append("")

    lines.append("## 4. 普通人看盘清单")
    lines.append("- 先看指数：大盘弱的时候，题材再热也容易冲高回落。")
    lines.append("- 再看龙头：板块涨但龙头不涨，通常不是强主线。")
    lines.append("- 再看成交：放量承接比单纯拉高更重要。")
    lines.append("- 最后看失效：一旦触发失效条件，就先降级观察，别硬扛观点。")
    lines.append("")

    risks = data.get("risk_alerts") or []
    lines.append("## 5. 风险提醒")
    if risks:
        for r in risks[:5]:
            if isinstance(r, dict):
                lines.append(f"- {r.get('title')}：{r.get('detail')}")
            else:
                lines.append(f"- {r}")
    else:
        lines.append("- 数据和观点都可能过期，盘中要重新验证。")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="生成专业版+普通人版盘前简报")
    ap.add_argument("--days", type=int, default=10, help="观点窗口；默认和行情窗口对齐为10天")
    ap.add_argument("--per-entity", type=int, default=4)
    ap.add_argument("--no-llm", action="store_true", help="跳过LLM润色，用确定性文本验证")
    ap.add_argument("--prefix", default=str(TMP_DIR / "brief_dual"))
    args = ap.parse_args()

    data = build_hybrid(days=args.days, per_entity=args.per_entity, no_llm=args.no_llm)
    report = validate_brief(data)
    if not report.get("valid"):
        print(format_validation(report), file=sys.stderr)
        raise SystemExit(2)

    prefix = Path(args.prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = prefix.with_suffix(".json")
    pro_path = Path(str(prefix) + "_professional.md")
    plain_path = Path(str(prefix) + "_plain.md")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pro_path.write_text(render_markdown(data), encoding="utf-8")
    plain_path.write_text(render_plain_markdown(data), encoding="utf-8")
    print(f"json={json_path}")
    print(f"professional={pro_path}")
    print(f"plain={plain_path}")


if __name__ == "__main__":
    main()
