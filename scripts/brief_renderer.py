#!/usr/bin/env python3
"""稳定盘前简报渲染器。

输入 brief_schema JSON，输出 Markdown。renderer 负责格式和证据链，LLM 只负责 JSON 内容。
也提供 --build-from-views 的 MVP：直接从 structured_views/latest_digest 构造一份可用简报。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from brief_schema import compact_view, empty_brief, format_validation, make_section, validate_brief
from config_loader import get_data_dir, load_config
from latest_digest import get_latest_digest
from market_context import build_market_context
from view_store import filter_views, load_views
from claim_dimensions import (
    attach_dimensions,
    claim_level_badge,
    source_evidence_badge,
    evidence_badge,
    evidence_detail,
    conflict_badge,
    reasoning_chain,
    confidence_badge,
    uncertainty_badge,
    crowding_for_entity,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

FOCUS_ENTITIES = ["大盘", "半导体", "光模块", "创新药", "机器人", "存储", "大金融", "大消费", "黄金有色"]
PRIMARY_ANALYSTS = ["钱博士直播", "钱博士短视频", "钱博士", "李一恩", "旗帜鲜明", "投机大拿"]
STANCE_ICON = {
    "bullish": "🐂 看多",
    "bearish": "🐻 看空",
    "neutral": "🦀 中性",
    "watch": "👀 关注",
    "risk": "⚠️ 风险",
    "mixed": "🔀 分歧",
}
HORIZON_LABEL = {
    "intraday": "日内",
    "short": "短线",
    "medium": "中期",
    "long": "长期",
    "unknown": "未标注",
}

ENTITY_KEYWORDS = {
    "大盘": ["大盘", "指数", "上证", "沪指", "创业板", "科创", "港股", "A股", "市场"],
    "半导体": ["半导体", "芯片", "晶圆", "设备", "材料", "中芯", "寒武纪", "海光", "688981", "159813"],
    "光模块": ["光模块", "光通信", "光芯片", "CPO", "PCB", "算力", "通信", "159770"],
    "创新药": ["创新药", "医药", "药", "BD", "医保", "CXO", "159992"],
    "机器人": ["机器人", "人形", "减速器", "伺服", "传感器", "特斯拉", "159770"],
    "存储": ["存储", "DRAM", "NAND", "HBM", "内存", "闪存", "存储芯片"],
    "大金融": ["大金融", "金融", "券商", "证券", "银行", "保险", "地产", "互金"],
    "大消费": ["大消费", "消费", "白酒", "食品", "旅游", "零售", "免税", "家电"],
    "黄金有色": ["黄金", "有色", "铜", "铝", "锂", "紫金", "贵金属", "商品", "601899"],
}

TIME_BUCKET_RANK = {
    "今日": 0,
    "T-1": 1,
    "3日内": 2,
    "1周内": 3,
    "1月内背景": 4,
    "过期需复核": 9,
    "日期缺失": 10,
}


def _parse_date(s: Any) -> datetime | None:
    try:
        return datetime.strptime(str(s or "")[:10], "%Y-%m-%d")
    except Exception:
        return None


def _time_bucket(view_date: Any, brief_date: Any | None = None) -> str:
    """把观点日期分层，避免旧观点被当成今日主判断。"""
    vd = _parse_date(view_date)
    bd = _parse_date(brief_date) or datetime.now()
    if not vd:
        return "日期缺失"
    delta = (bd.date() - vd.date()).days
    if delta <= 0:
        return "今日"
    if delta == 1:
        return "T-1"
    if delta <= 3:
        return "3日内"
    if delta <= 7:
        return "1周内"
    if delta <= 30:
        return "1月内背景"
    return "过期需复核"


def _view_text(v: dict[str, Any]) -> str:
    entities = v.get("entities") if isinstance(v.get("entities"), dict) else {}
    parts = [v.get("section"), v.get("claim"), v.get("logic"), v.get("risk"), v.get("evidence"), v.get("source_file")]
    for val in entities.values():
        if isinstance(val, list):
            parts.extend(map(str, val))
        else:
            parts.append(str(val))
    return " ".join(str(p or "") for p in parts)


def _asset_relevance_score(v: dict[str, Any], entity: str) -> float:
    """粗粒度实体相关度：先硬过滤明显错配，再让排序使用。"""
    text = _view_text(v)
    keywords = ENTITY_KEYWORDS.get(entity, [entity])
    score = 0.0
    if entity and entity in text:
        score += 0.6
    hits = sum(1 for kw in keywords if kw and kw in text)
    if hits:
        score += min(0.4, 0.16 * hits)
    entities = v.get("entities") if isinstance(v.get("entities"), dict) else {}
    entity_blob = json.dumps(entities, ensure_ascii=False)
    if entity in entity_blob:
        score += 0.25
    if str(v.get("section") or "") == entity:
        score += 0.2
    return min(score, 1.0)


def _filter_relevant_views(views: list[dict[str, Any]], entity: str, threshold: float = 0.5) -> list[dict[str, Any]]:
    filtered = []
    for v in views:
        score = _asset_relevance_score(v, entity)
        if score >= threshold:
            vv = dict(v)
            vv["asset_relevance_score"] = round(score, 3)
            filtered.append(vv)
    return filtered


def _evidence_relevance(v: dict[str, Any], entity: str) -> str:
    score = _asset_relevance_score(v, entity)
    if score >= 0.75:
        return "direct"
    if score >= 0.5:
        return "related"
    if score >= 0.3:
        return "weak"
    return "mismatch"


def _asr_confidence(v: dict[str, Any]) -> str:
    text = _view_text(v)
    bad_signals = ["00:00:00", "脾脂", "熟悔", "回乱", "掌服", "長幅"]
    hits = sum(1 for item in bad_signals if item in text)
    if hits >= 2:
        return "low"
    if hits == 1:
        return "medium"
    return "high"


@lru_cache(maxsize=1)
def _load_sector_watchlist() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "config" / "sector_watchlist.yaml"
    if not path.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        print(f"[WARN] 读取 sector_watchlist.yaml 失败: {exc}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def _sector_watchlist(entity: str) -> dict[str, Any]:
    cfg = _load_sector_watchlist().get(entity) or {}
    return cfg if isinstance(cfg, dict) else {}


def _join_watch_items(items: Any, limit: int = 3) -> str:
    if not isinstance(items, list):
        return ""
    return "、".join(esc(x) for x in items[:limit] if esc(x))


def _default_theme_watch(title: str) -> list[str]:
    cfg = _sector_watchlist(title)
    if not cfg:
        return [f"观察{title}板块指数/ETF、核心标的量能和相对强弱。"]
    watches = []
    objects = []
    if cfg.get("etfs"):
        objects.append(f"ETF：{_join_watch_items(cfg.get('etfs'))}")
    if cfg.get("indexes"):
        objects.append(f"指数：{_join_watch_items(cfg.get('indexes'))}")
    if cfg.get("core_symbols"):
        objects.append(f"核心标的：{_join_watch_items(cfg.get('core_symbols'))}")
    if objects:
        watches.append("观察对象：" + "；".join(objects))
    if cfg.get("strong_validation"):
        watches.append("强验证：" + "；".join(esc(x) for x in cfg.get("strong_validation", [])[:3]))
    if cfg.get("weak_validation"):
        watches.append("弱验证：" + "；".join(esc(x) for x in cfg.get("weak_validation", [])[:3]))
    return watches or [f"观察{title}板块指数/ETF、核心标的量能和相对强弱。"]


def _theme_watch(title: str, sec: dict[str, Any]) -> list[str]:
    if _sector_watchlist(title):
        return _default_theme_watch(title)
    return sec.get("action_watch") or _default_theme_watch(title)


def _default_theme_invalid(title: str) -> str:
    cfg = _sector_watchlist(title)
    invalid = cfg.get("invalid") if cfg else None
    if isinstance(invalid, list) and invalid:
        return "；".join(esc(x) for x in invalid[:3])
    return "若核心标的弱于板块、板块弱于大盘，或放量冲高回落，则降级观察。"


def _theme_thresholds(title: str) -> str:
    """从 watchlist 的 validation_thresholds 渲染可执行量化阈值。"""
    cfg = _sector_watchlist(title)
    th = cfg.get("validation_thresholds") if cfg else None
    if not isinstance(th, dict) or not th:
        return ""
    parts = []
    minutes = th.get("open_window_minutes")
    rs = th.get("relative_strength_pct")
    tv = th.get("turnover_vs_5d")
    ncore = th.get("min_core_symbols_confirming")
    bench = cfg.get("benchmark")
    if minutes and rs and bench:
        parts.append(f"开盘{int(minutes)}分钟内板块强于{bench} ≥ {float(rs):.1f}pct")
    if tv:
        parts.append(f"成交额 ≥ 5日均值 {float(tv):.1f}倍")
    if ncore:
        parts.append(f"核心标的至少 {int(ncore)} 只确认")
    return "；".join(parts) if parts else ""


def esc(s: Any) -> str:
    return str(s or "").replace("|", "｜").replace("\n", " ").strip()


def fmt_price(v: Any) -> str:
    if v is None or v == "":
        return "N/A"
    try:
        return f"{float(v):.2f}"
    except Exception:
        return str(v)


def fmt_change(info: dict[str, Any], symbol: str = "") -> str:
    if not isinstance(info, dict):
        return "N/A"
    cp = info.get("change_pct")
    if cp is None:
        return "N/A（昨收/缓存价）" if symbol.endswith((".SS", ".SZ")) else "N/A"
    try:
        val = float(cp)
        return f"{val:+.2f}%"
    except Exception:
        return str(cp)


def _source_line(v: dict[str, Any]) -> str:
    return (
        f"证据链：view_id={v.get('view_id')}；{v.get('analyst')}；{v.get('date')}；"
        f"source_file={v.get('source_file')}"
    )


def _inline_refs(views: list[dict[str, Any]], max_items: int = 2) -> str:
    refs = []
    for v in views[:max_items]:
        if not v.get("view_id"):
            continue
        refs.append(
            f"view_id={v.get('view_id')}；{v.get('analyst')} {v.get('date')}；source_file={v.get('source_file')}"
        )
    return "；".join(refs)


def _with_refs(text: Any, views: list[dict[str, Any]]) -> str:
    body = esc(text)
    if not body:
        return ""
    refs = _inline_refs(views)
    if not refs or "view_id=" in body or "source_file=" in body:
        return body
    return f"{body}（证据链：{refs}）"


def prediction_badge(v: dict[str, Any]) -> str:
    """预测力徽标（红线#12：与证据·置信解耦，独立列展示，禁混用）。

    prediction_confidence = 实证预测力（view 级 w5 命中率查表，66 号方案消费层）；
    - pc=0.50 → 「基准」：保守中性占位（样本不足/未知组合），防误读为"预测力差"
    - pc≠0.50 → 「预测力0.59」：如实显示（含 0.49 实测≈随机值，不美化）
    - 无字段 → 空串：不猜测（红线#1 unknown 不猜测）
    """
    pc = v.get("prediction_confidence")
    if pc is None:
        return ""
    try:
        pc = float(pc)
    except (TypeError, ValueError):
        return ""
    if pc == 0.50:
        return "基准"
    return f"预测力{pc:.2f}"


def _render_view_table(views: list[dict[str, Any]], max_rows: int = 8) -> list[str]:
    if not views:
        return ["> 待验证：本节缺结构化观点引用。"]
    # #4 红线：表达类型(claim_level)与证据层级(source_layer/verification)并列展示，
    # 无维度数据 = ❔ 未标，禁止猜测；forecast 不做任何"降权隐身"处理。
    # #5：证据列并入最低维置信徽标 + 疑点标签列（确定性、可复现）。
    # #13：新增「原文」列（🔍原文指针/❔缺失/⚠️存疑）；冲突徽标并入疑点列尾部；
    #   stale 标签不再逐行刷（行内只留短标签，详情页展开）。
    # #66/#70：新增「预测力」列（prediction_confidence 实证值，红线#12 与证据·置信分列）。
    views = [attach_dimensions(v) for v in views]
    out = [
        "| 分析师 | 日期 | 立场 | 类型 | 证据·置信 | 预测力 | 疑点·冲突 | 周期 | 核心观点 | 原文 | view_id |",
        "|---|---:|---|---|---|---|---|---|---|---|---|",
    ]
    for v in views[:max_rows]:
        utags = uncertainty_badge(v)
        cf = conflict_badge(v)
        ut_col = " ".join(x for x in (utags, cf) if x) or "—"
        out.append(
            "| {analyst} | {date} | {stance} | {clv} | {ev}·{conf} | {pc} | {utags} | {horizon} | {claim} | {orig} | `{vid}` |".format(
                analyst=esc(v.get("analyst")),
                date=esc(v.get("date")),
                stance=STANCE_ICON.get(v.get("stance"), esc(v.get("stance"))),
                clv=claim_level_badge(v),
                ev=source_evidence_badge(v),
                conf=confidence_badge(v),
                pc=prediction_badge(v),
                utags=esc(ut_col),
                horizon=HORIZON_LABEL.get(v.get("horizon"), esc(v.get("horizon"))),
                claim=esc(v.get("claim"))[:120],
                orig=evidence_badge(v),
                vid=esc(v.get("view_id")),
            )
        )
    return out


def _render_evidence_details(views: list[dict[str, Any]], max_items: int = 4) -> list[str]:
    """#13: 原文详情锚点区（两次点击到原文）。
    第一击：观点表 🔍原文 → 本区锚点；第二击：BV 深链（可点 HTTPS）。
    同时展示该 view 所属冲突组的多空对照（不合并结论，红线#3/#4）。"""
    out = []
    views = [attach_dimensions(v) for v in views]
    for v in views[:max_items]:
        vid = v.get("view_id", "")
        if not vid:
            continue
        ev = evidence_detail(v)
        head = f"<a name=\"evidence-{vid}\"></a>**🔍 原文详情** `{vid}`"
        if not ev:
            out.append(f"{head}\n\n> ❔ 原文缺失（锚定失败，不猜测时间戳）\n")
            continue
        lines = [f"{head}\n"]
        src = _source_line(v)
        if src:
            lines.append(f"- 来源：{src}")
        if ev.get("quote_text"):
            lines.append(f"- 引用原文：> {esc(ev['quote_text'])[:200]}")
        if ev.get("segment_text"):
            lines.append(f"- 原文片段：> {esc(ev['segment_text'])[:300]}")
        if ev.get("ts_display"):
            lines.append(f"- 时间戳：{esc(ev['ts_display'])}")
        if ev.get("url"):
            lines.append(f"- 原视频（点击直达）：[{esc(ev['url'])}]({ev['url']})")
        if ev.get("extraction_status") == "hash_mismatch":
            lines.append("- ⚠️ 原文存疑：引用文本与转写片段数字级不一致（ASR 差异，标记不阻断）")
        # #6: 论证链（前提→机制→结论 + 触发/失效条件）
        chain = reasoning_chain(v)
        if chain:
            lines.append(f"- 论证链：{chain}")
        # 冲突对照：该 view 所属冲突组的对立面实质成员
        groups = v.get("conflict_groups") or []
        if groups:
            cg = _conflict_opposite(v, groups[0]["group_id"])
            if cg:
                lines.append(f"- 🔀 冲突对照（组 `{groups[0]['group_id']}`）：")
                lines.append(f"  - 多：{cg['bull'][:140]}")
                lines.append(f"  - 空：{cg['bear'][:140]}")
        out.append("\n".join(lines) + "\n")
    return out


def _conflict_opposite(v: dict[str, Any], group_id: str) -> dict[str, str] | None:
    """从冲突导出取同组对立面代表 claim（实质成员优先，模板折叠）。"""
    try:
        import claim_dimensions as cd
        raw = cd._load_conflicts()
        for c in raw.get("conflicts", []):
            if c["conflict_group_id"] != group_id:
                continue
            bull = "；".join(
                f"{m['date']} {m['claim']}" for m in c["bull_members"][:2] if not m.get("template_claim"))
            bear = "；".join(
                f"{m['date']} {m['claim']}" for m in c["bear_members"][:2] if not m.get("template_claim"))
            if not bull:
                bull = f"（{c['n_bull']} 条看多，均为模板结论，可查原文）"
            if not bear:
                bear = f"（{c['n_bear']} 条看空，均为模板结论，可查原文）"
            return {"bull": bull, "bear": bear}
    except Exception:
        return None
    return None


def render_debate_card(card: dict[str, Any]) -> str:
    """渲染多空对照卡 Markdown 区块。"""
    entity = card.get("entity_name") or card.get("entity") or ""
    badges = " ".join(f"`{tag}`" for tag in (card.get("highlights") or []))
    lines = [f"## {esc(entity)}｜多空对照卡 {badges}".rstrip()]
    # #7 拥挤度警示：只报告观点集中度，不暗示反向交易（蓝图红线）
    crowd = crowding_for_entity(entity)
    if crowd:
        lines.append(f"> {crowd}")

    def _score_text(item: dict[str, Any]) -> str:
        score = item.get("analyst_score")
        if not isinstance(score, dict):
            return ""
        try:
            hit_rate = float(score.get("hit_rate"))
        except Exception:
            return ""
        sample = score.get("sample_count")
        pct = hit_rate * 100 if hit_rate <= 1 else hit_rate
        if sample is None:
            return f"｜历史命中率{pct:.0f}%"
        return f"｜历史命中率{pct:.0f}%(样本{sample})"

    def _render_side(title: str, items: list[dict[str, Any]], limit: int = 5) -> None:
        lines.append(f"### {title}")
        if not items:
            lines.append("- 暂无")
            return
        for idx, item in enumerate(items[:limit], 1):
            try:
                conf = f"{float(item.get('confidence') or 0):.2f}"
            except Exception:
                conf = esc(item.get("confidence"))
            lines.append(f"{idx}. {esc(item.get('analyst'))}：{esc(item.get('claim'))}（置信{conf}）{_score_text(item)}")
            lines.append(f"   - 逻辑：{esc(item.get('logic'))}")
            lines.append(f"   - 证据：{esc(item.get('evidence'))[:80]}")
        if len(items) > limit:
            lines.append(f"- …另有 {len(items) - limit} 条同类观点（共 {len(items)} 条）")

    _render_side("多头论据", card.get("bullish") or [])
    _render_side("空头论据", card.get("bearish") or [])
    if card.get("risk"):
        _render_side("风险论据", card.get("risk") or [], limit=3)

    lines.append("### 分歧点")
    disagreements = card.get("disagreements") or []
    if disagreements:
        for item in disagreements:
            bull = "；".join(esc(x) for x in item.get("bullish_side", []) if esc(x))
            bear = "；".join(esc(x) for x in item.get("bearish_side", []) if esc(x))
            lines.append(f"- {esc(item.get('topic'))}：多头侧 {bull or '暂无'}；空头侧 {bear or '暂无'}")
    else:
        lines.append("- 暂无")

    lines.append("### 共识点")
    consensus = card.get("consensus") or []
    if consensus:
        for item in consensus:
            if isinstance(item, dict):
                lines.append(f"- {esc(item.get('topic') or item.get('claim') or item)}")
            else:
                lines.append(f"- {esc(item)}")
    else:
        lines.append("- 暂无")

    lines.append("### 新变化")
    changes = card.get("new_changes") or []
    if changes:
        for item in changes:
            if isinstance(item, dict):
                lines.append(f"- {esc(item.get('topic'))}：前值 {item.get('previous_net_stance_score')}，当前 {item.get('current_net_stance_score')}")
            else:
                lines.append(f"- {esc(item)}")
    else:
        lines.append("- 暂无")
    return "\n".join(lines)


def render_evidence_pack(pack: dict[str, Any]) -> str:
    """渲染 EvidencePack 摘要和关键字段简表。"""
    asset_name = pack.get("asset_name") or pack.get("asset_id") or ""
    debate = pack.get("debate_card") if isinstance(pack.get("debate_card"), dict) else {}
    counts = debate.get("counts") if isinstance(debate, dict) else {}
    bull = int((counts or {}).get("bullish") or len(debate.get("bullish") or []))
    bear = int((counts or {}).get("bearish") or len(debate.get("bearish") or []))
    market = pack.get("market_snapshot") if isinstance(pack.get("market_snapshot"), dict) else {}
    lines = [f"### {esc(asset_name)} EvidencePack"]
    if pack.get("summary"):
        lines.append(f"> {esc(pack.get('summary'))}")
    lines.append("")
    lines.append("| 字段 | 数量/状态 |")
    lines.append("|---|---:|")
    lines.append(f"| factor_states | {len(pack.get('factor_states') or [])} |")
    lines.append(f"| debate_card | {bull}多 / {bear}空 |")
    lines.append(f"| latest_views | {len(pack.get('latest_views') or [])} |")
    lines.append(f"| analyst_scores | {len(pack.get('analyst_scores') or [])} |")
    lines.append(f"| market_snapshot | {len(market)} |")
    lines.append(f"| user_decision_history | {len(pack.get('user_decision_history') or [])} |")
    lines.append(f"| rag_evidence | {len(pack.get('rag_evidence') or [])} |")
    return "\n".join(lines)


def render_markdown(data: dict[str, Any]) -> str:
    report = validate_brief(data)
    lines: list[str] = []
    lines.append(f"# 📋 盘前简报 | {data.get('brief_date', '')}")
    lines.append("")
    lines.append(f"> 生成时间：{data.get('generated_at', '')} | {data.get('session_note', '')}")
    lines.append(f"> 质检：{report.get('summary')} | schema_valid={report.get('valid')}")
    lines.append(f"> 免责声明：{data.get('disclaimer', '仅整理公开内容与行情数据，不构成投资建议。')}")
    lines.append("")

    market = data.get("market_snapshot") or {}
    indexes = market.get("indexes") or {}
    tracked = market.get("tracked_prices") or {}
    notes = market.get("notes") or []

    lines.append("## 一、市场快照")
    lines.append("")
    if indexes:
        lines.append("### 指数/海外核心标的")
        lines.append("| 标的 | 价格 | 涨跌 | 备注 |")
        lines.append("|---|---:|---:|---|")
        for sym, info in indexes.items():
            if isinstance(info, dict):
                lines.append(f"| {esc(sym)} | {fmt_price(info.get('price'))} | {fmt_change(info, sym)} | {esc(info.get('note') or info.get('name'))} |")
        lines.append("")
    if tracked:
        lines.append("### 重点跟踪标的")
        lines.append("| 标的 | 价格 | 涨跌 | 说明 |")
        lines.append("|---|---:|---:|---|")
        for sym, info in tracked.items():
            if isinstance(info, dict):
                lines.append(f"| {esc(sym)} | {fmt_price(info.get('price'))} | {fmt_change(info, sym)} | {esc(info.get('change_str') or info.get('note') or info.get('name'))} |")
        lines.append("> A股非交易时段仅显示昨收/缓存价，不把单点缓存写成今日涨跌。")
        lines.append("")
    for n in notes:
        lines.append(f"> {esc(n)}")
    if notes:
        lines.append("")

    market_context = data.get("market_context") or {}
    sectors = market_context.get("sectors") if isinstance(market_context, dict) else {}
    if isinstance(sectors, dict) and sectors:
        ranked_sectors = sorted(sectors.items(), key=lambda x: ((x[1] or {}).get("rank") or 999, -float((x[1] or {}).get("score") or 0), x[0]))
        lines.append("### 板块市场强弱参考")
        lines.append("| 方向 | 代理标的 | 涨跌 | 相对基准 | 市场分 | 数据状态 |")
        lines.append("|---|---|---:|---:|---:|---|")
        for name, info in ranked_sectors[:8]:
            if not isinstance(info, dict):
                continue
            ret = info.get("return_pct")
            rel = info.get("relative_strength")
            ret_s = "N/A" if ret is None else f"{float(ret):+.2f}%"
            rel_s = "N/A" if rel is None else f"{float(rel):+.2f}pct"
            lines.append(
                f"| {esc(name)} | {esc(info.get('market_proxy') or '待核验')} | {ret_s} | {rel_s} | "
                f"{float(info.get('score') or 0):.2f} | {esc(info.get('source'))} |"
            )
        if market_context.get("notes"):
            lines.append(f"> 市场上下文：{esc('；'.join(market_context.get('notes', [])[:4]))}")
        lines.append("")

    top_themes = data.get("top_themes") or []
    if top_themes:
        lines.append("## 二、今日Top 3主线")
        lines.append("")
        lines.append("| 优先级 | 方向 | 级别 | 最新观点 | 时效 | 核心判断 |")
        lines.append("|---:|---|---|---:|---|---|")
        for t in top_themes[:3]:
            refs = t.get("evidence_refs") or []
            ref_suffix = f"（证据链：{esc(refs[0])}）" if refs else ""
            lines.append(
                f"| {esc(t.get('rank'))} | {esc(t.get('title'))} | {esc(t.get('level'))} | "
                f"{esc(t.get('latest_date'))} | {esc(t.get('time_bucket'))} | {esc(t.get('summary'))[:120]}{ref_suffix} |"
            )
        lines.append("")
        for t in top_themes[:3]:
            lines.append(f"### {esc(t.get('rank'))}. {esc(t.get('title'))}｜{esc(t.get('level'))}")
            if t.get("summary"):
                lines.append(f"- 今日判断：{esc(t.get('summary'))}")
            if t.get("selection_reason"):
                lines.append(f"- 入选理由：{esc('；'.join(t.get('selection_reason') or []))}")
            refs = t.get("evidence_refs") or []
            if refs:
                lines.append(f"- 直接证据：{esc('；'.join(refs[:2]))}")
            watch = t.get("watch") or []
            if watch:
                lines.append(f"- 盘中验证：{esc('；'.join(watch[:3]))}")
            thresholds = t.get("thresholds") or _theme_thresholds(str(t.get("title") or ""))
            if thresholds:
                lines.append(f"- 量化阈值：{esc(thresholds)}")
            if t.get("invalid"):
                invalid_refs = f"（证据链：{esc(refs[0])}）" if refs and "view_id=" not in esc(t.get("invalid")) else ""
                lines.append(f"- 失效条件：{esc(t.get('invalid'))}{invalid_refs}")
            lines.append("")

    section_offset = 2 if top_themes else 1
    for idx, sec in enumerate(data.get("sections", []), 1):
        lines.append(f"## {idx + section_offset}、{esc(sec.get('title'))}")
        lines.append("")
        views = sec.get("views") or []
        if sec.get("summary"):
            lines.append(f"**本节结论：** {_with_refs(sec.get('summary'), views)}")
            lines.append("")
        if sec.get("consensus"):
            lines.append(f"**共识：** {_with_refs(sec.get('consensus'), views)}")
        if sec.get("divergence"):
            lines.append(f"**分歧：** {_with_refs(sec.get('divergence'), views)}")
        if sec.get("consensus") or sec.get("divergence"):
            lines.append("")
        lines.extend(_render_view_table(views))
        lines.append("")
        lines.extend(_render_evidence_details(views))
        lines.append("")
        actions = sec.get("action_watch") or []
        if actions:
            lines.append("**今日观察点：**")
            for a in actions:
                lines.append(f"- {_with_refs(a, views)}")
            lines.append("")

    risks = data.get("risk_alerts") or []

    # 多空对照卡区块（决策台阶段一：data 里带 debate_cards 时渲染）
    debate_cards = data.get("debate_cards") or []
    if debate_cards:
        lines.append("## 今日重点资产多空对照")
        lines.append("")
        for card in debate_cards:
            lines.append(render_debate_card(card))
            lines.append("")

    # 资产分析卡区块（决策台阶段三：data 里带 asset_cards 时渲染）
    asset_cards = data.get("asset_cards") or []
    if asset_cards:
        try:
            from asset_card_builder import render_asset_card
            lines.append("## 今日重点资产分析卡")
            lines.append("")
            for card in asset_cards:
                lines.append(render_asset_card(card))
                lines.append("")
        except Exception as e:
            print(f"  ⚠️ 资产分析卡渲染失败，不影响简报: {e}", file=sys.stderr)

    evidence_packs = data.get("evidence_packs") or []
    if evidence_packs:
        lines.append("## EvidencePack ?????")
        lines.append("")
        for pack in evidence_packs:
            lines.append(render_evidence_pack(pack))
            lines.append("")

    lines.append("## 风险提醒")
    if risks:
        for r in risks:
            if isinstance(r, dict):
                lines.append(f"- {esc(r.get('title'))}: {esc(r.get('detail'))}")
            else:
                lines.append(f"- {esc(r)}")
    else:
        lines.append("- 待验证：本期未提供额外风险列表。")
    lines.append("")

    source_ids = data.get("source_view_ids") or []
    if source_ids:
        lines.append("## 结构化观点索引")
        lines.append(", ".join(f"`{esc(x)}`" for x in source_ids[:80]))
        lines.append("")

    if report.get("errors") or report.get("warnings"):
        lines.append("## 质检摘要")
        for bucket in ["errors", "warnings"]:
            for item in report.get(bucket, [])[:20]:
                lines.append(f"- {bucket[:-1].upper()} {esc(item.get('path'))}: {esc(item.get('message'))}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _market_snapshot_from_cache(config: dict[str, Any]) -> dict[str, Any]:
    snapshot_path = DATA_DIR / "market_snapshot_10d.json"
    source_note = "行情来自本地 market_cache；非交易时段优先显示缓存价。"
    if snapshot_path.exists():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            cache = snapshot.get("symbols") if isinstance(snapshot, dict) else {}
            source_note = f"行情来自 {snapshot_path.name}，含近{snapshot.get('days', 10)}个交易日历史。"
        except Exception:
            cache = {}
    else:
        try:
            import market_cache
            cache = market_cache.get_cached_prices() or {}
        except Exception:
            cache = {}
    indexes = {}
    tracked = {}
    for sym in ["^DJI", "^IXIC", "^GSPC", "NVDA", "AMD", "MRVL", "AAPL", "TSLA"]:
        if sym in cache:
            indexes[sym] = cache[sym]
    for sym in ["159813.SZ", "159770.SZ", "159992.SZ", "300502.SZ", "688981.SS", "601899.SS", "600745.SS"]:
        if sym in cache:
            info = dict(cache[sym])
            if sym.endswith((".SS", ".SZ")) and len(info.get("prices", [])) < 2:
                info["change_pct"] = None
                info["change_str"] = "N/A（昨收/缓存价，未计算今日涨跌）"
            tracked[sym] = info
    return {"indexes": indexes, "tracked_prices": tracked, "notes": [source_note]}


def _view_dedupe_key(v: dict[str, Any]) -> tuple[Any, ...]:
    """避免同一文件/同一小节拆出来的重复短句刷屏。"""
    claim = str(v.get("claim") or "").strip()
    stance_only = {
        "短线：看多 🐂📈", "短线：看空 🐻📉", "短线：中性 🦀➡️",
        "中长线：看多 🐂📈", "中长线：看空 🐻📉", "中长线：中性🦀➡️",
    }
    if claim in stance_only:
        claim = "stance_only"
    return (v.get("source_file"), v.get("section"), v.get("analyst"), claim[:24])


def _balanced_views_for_entity(all_views: list[dict[str, Any]], entity: str, days: int, per_entity: int) -> list[dict[str, Any]]:
    """按分析师均衡抽样，防止单一最新来源刷屏。"""
    candidates = filter_views(all_views, entity=entity, date_range=f"{days}d")
    if not candidates:
        return []
    candidates = _filter_relevant_views(candidates, entity)
    if not candidates:
        return []

    deduped = []
    seen = set()
    for v in candidates:
        key = _view_dedupe_key(v)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(v)

    by_analyst: dict[str, list[dict[str, Any]]] = {}
    for v in deduped:
        by_analyst.setdefault(v.get("analyst") or "未知", []).append(v)

    def analyst_priority(name: str) -> tuple[int, str]:
        try:
            return (PRIMARY_ANALYSTS.index(name), name)
        except ValueError:
            return (len(PRIMARY_ANALYSTS), name)

    analysts = sorted(
        by_analyst,
        key=lambda a: (
            analyst_priority(a),
            by_analyst[a][0].get("bucket", "Z"),
            -float(by_analyst[a][0].get("rank_score", 0)),
            by_analyst[a][0].get("date", ""),
        ),
    )

    selected = []
    selected_ids = set()
    # 第一轮：每位分析师最多先取 1 条。
    for analyst in analysts:
        if len(selected) >= per_entity:
            break
        for v in by_analyst[analyst]:
            vid = v.get("view_id")
            if vid not in selected_ids:
                selected.append(v)
                selected_ids.add(vid)
                break

    # 第二轮：不够再补高分，但单一分析师最多占一半左右。
    max_per_analyst = max(1, (per_entity + 1) // 2)
    counts: dict[str, int] = {}
    for v in selected:
        a = v.get("analyst") or "未知"
        counts[a] = counts.get(a, 0) + 1
    for v in deduped:
        if len(selected) >= per_entity:
            break
        vid = v.get("view_id")
        a = v.get("analyst") or "未知"
        if vid in selected_ids:
            continue
        if counts.get(a, 0) >= max_per_analyst and len(by_analyst) > 1:
            continue
        selected.append(v)
        selected_ids.add(vid)
        counts[a] = counts.get(a, 0) + 1

    # 第三轮：极端情况下放开比例补满。
    for v in deduped:
        if len(selected) >= per_entity:
            break
        vid = v.get("view_id")
        if vid not in selected_ids:
            selected.append(v)
            selected_ids.add(vid)

    return selected[:per_entity]


def _best_view_for_section(sec: dict[str, Any], brief_date: str) -> dict[str, Any] | None:
    views = sec.get("views") or []
    if not views:
        return None
    title = str(sec.get("title") or "")

    def key(v: dict[str, Any]) -> tuple[Any, ...]:
        evidence_grade = v.get("evidence_relevance") or _evidence_relevance(v, title)
        asr_grade = v.get("asr_confidence") or _asr_confidence(v)
        quality_penalty = 0 if evidence_grade in {"direct", "related"} and asr_grade != "low" else 1
        return (
            quality_penalty,
            TIME_BUCKET_RANK.get(_time_bucket(v.get("date"), brief_date), 99),
            -float(v.get("asset_relevance_score") or _asset_relevance_score(v, title)),
            -float(v.get("rank_score") or 0),
        )

    best = sorted(views, key=key)[0]
    out = dict(best)
    out["evidence_relevance"] = out.get("evidence_relevance") or _evidence_relevance(out, title)
    out["asr_confidence"] = out.get("asr_confidence") or _asr_confidence(out)
    return out


def _theme_level(bucket: str, score: float) -> str:
    if bucket in {"今日", "T-1", "3日内"} and score >= 0.65:
        return "今日主线"
    if bucket in {"1周内", "1月内背景"}:
        return "背景跟踪"
    return "次级观察"


def _build_top_themes(
    sections: list[dict[str, Any]],
    brief_date: str,
    limit: int = 3,
    market_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    themes = []
    market_sectors = (market_context or {}).get("sectors") if isinstance(market_context, dict) else {}
    market_sectors = market_sectors if isinstance(market_sectors, dict) else {}
    for sec in sections:
        if sec.get("type") not in {"sector", "market", "analysis"}:
            continue
        best = _best_view_for_section(sec, brief_date)
        if not best:
            continue
        title = str(sec.get("title") or "")
        bucket = _time_bucket(best.get("date"), brief_date)
        relevance = float(best.get("asset_relevance_score") or _asset_relevance_score(best, title))
        evidence_grade = best.get("evidence_relevance") or _evidence_relevance(best, title)
        asr_grade = best.get("asr_confidence") or _asr_confidence(best)
        quality_ok = evidence_grade in {"direct", "related"} and asr_grade != "low"
        market_info = market_sectors.get(title) if isinstance(market_sectors.get(title), dict) else {}
        market_score = float((market_info or {}).get("score") or 0)
        rank_score = (
            100
            - TIME_BUCKET_RANK.get(bucket, 99) * 12
            + relevance * 20
            + min(float(best.get("rank_score") or 0), 10)
            + market_score * 25
            - (60 if not quality_ok else 0)
        )
        refs = [
            f"view_id={best.get('view_id')}；{best.get('analyst')} {best.get('date')}；source_file={best.get('source_file')}"
        ]
        selection_reason = [
            f"观点时效={bucket}",
            f"证据相关度={relevance:.2f}",
            f"证据质量={evidence_grade}/{asr_grade}",
        ]
        if market_info:
            selection_reason.append(f"市场分={market_score:.2f}")
        else:
            selection_reason.append("市场数据缺失")
        level = _theme_level(bucket, relevance) if quality_ok else "次级观察"
        themes.append({
            "rank_score": round(rank_score, 3),
            "title": title,
            "level": level,
            "summary": sec.get("summary") or best.get("claim") or "待验证",
            "time_bucket": bucket,
            "latest_date": best.get("date"),
            "evidence_refs": refs,
            "watch": _theme_watch(title, sec),
            "invalid": _default_theme_invalid(title),
            "selection_reason": selection_reason,
            "market_score": round(market_score, 3),
            "evidence_relevance": evidence_grade,
            "asr_confidence": asr_grade,
            "thresholds": _theme_thresholds(title),
        })
    themes.sort(key=lambda x: (-float(x.get("rank_score", 0)), str(x.get("title"))))
    out = []
    for i, t in enumerate(themes[:limit], 1):
        tt = dict(t)
        tt["rank"] = i
        tt.pop("rank_score", None)
        out.append(tt)
    return out


def build_from_views(days: int = 30, per_entity: int = 4) -> dict[str, Any]:
    config = load_config()
    all_views = load_views(config=config)
    data = empty_brief(datetime.now().strftime("%Y-%m-%d"))
    data["session_note"] = "结构化观点库渲染版"
    data["market_snapshot"] = _market_snapshot_from_cache(config)

    sections = []
    all_ids = []
    brief_date = data.get("brief_date") or datetime.now().strftime("%Y-%m-%d")
    for entity in FOCUS_ENTITIES:
        views = _balanced_views_for_entity(all_views, entity=entity, days=days, per_entity=per_entity)
        cviews = [compact_view(v) for v in views]
        for cv in cviews:
            cv["time_bucket"] = _time_bucket(cv.get("date"), brief_date)
            cv["asset_relevance_score"] = round(_asset_relevance_score(cv, entity), 3)
            cv["evidence_relevance"] = _evidence_relevance(cv, entity)
            cv["asr_confidence"] = _asr_confidence(cv)
        if not cviews:
            continue
        stances = {v.get("stance") for v in cviews}
        summary = f"{entity}：近{days}天找到{len(cviews)}条结构化观点。"
        consensus = ""
        divergence = ""
        if len(stances) == 1:
            consensus = f"观点立场较集中：{STANCE_ICON.get(next(iter(stances)), next(iter(stances)))}。"
        elif len(stances) > 1:
            divergence = "存在多空/周期分歧，需看今日盘面验证。"
        sec = make_section(entity, summary=summary, views=cviews, section_type="sector" if entity != "大盘" else "market")
        sec["consensus"] = consensus
        sec["divergence"] = divergence
        sec["action_watch"] = _default_theme_watch(entity) + [
            "若行情与结构化观点冲突，以盘中量价和后续验证为准。",
        ]
        sections.append(sec)
        all_ids.extend(v.get("view_id") for v in cviews if v.get("view_id"))

    data["sections"] = sections
    data["market_context"] = build_market_context(watchlist=_load_sector_watchlist(), trade_date=brief_date)
    data["top_themes"] = _build_top_themes(sections, brief_date=brief_date, limit=3, market_context=data.get("market_context"))
    data["risk_alerts"] = [
        {"title": "观点时效", "detail": "观点库按日期窗口抽取，旧观点必须结合今日盘面验证。"},
        {"title": "行情缓存", "detail": "A股非交易时段价格为昨收/缓存价，不代表今日实时涨跌。"},
        {"title": "非投资建议", "detail": "本文只整理公开观点和数据，不构成买卖建议。"},
    ]
    data["source_view_ids"] = sorted(set(all_ids))

    # 多空对照卡（决策台阶段一）：对每个重点实体生成卡片，无观点则跳过
    try:
        from debate_card_builder import build_debate_card
        from decision_db import upsert_debate_cards
        cards = []
        for entity in FOCUS_ENTITIES:
            card = build_debate_card(entity, lookback_days=days, views=all_views, write_db=False)
            if card and (card.get("bullish") or card.get("bearish") or card.get("risk")):
                cards.append(card)
        if cards:
            upsert_debate_cards(cards)
            data["debate_cards"] = cards
    except Exception as e:
        print(f"  ⚠️ 多空卡生成失败(不影响简报): {e}", file=sys.stderr)

    # 资产分析卡（决策台阶段三）：扫描配置生成，单卡失败不影响简报。
    try:
        from asset_card_builder import build_asset_card
        from factor_config_loader import load_all_asset_configs
        asset_cards = []
        for cfg in load_all_asset_configs():
            try:
                asset_cards.append(build_asset_card(str(cfg.get("asset_id")), as_of_date=brief_date))
            except Exception as e:
                print(f"  ⚠️ 资产分析卡生成失败 {cfg.get('asset_id')}: {e}", file=sys.stderr)
        if asset_cards:
            data["asset_cards"] = asset_cards
    except Exception as e:
        print(f"  ⚠️ 资产分析卡扫描失败，不影响简报: {e}", file=sys.stderr)

    try:
        from evidence_pack_builder import build_evidence_pack
        evidence_packs = []
        for asset_id in ["GOLD", "SEMI", "AI", "ROBOT", "BAIJIU"]:
            try:
                evidence_packs.append(build_evidence_pack(asset_id, as_of_date=brief_date))
            except Exception as e:
                print(f"  ?? EvidencePack ???? {asset_id}: {e}", file=sys.stderr)
        if evidence_packs:
            data["evidence_packs"] = evidence_packs
    except Exception as e:
        print(f"  ?? EvidencePack ??????????: {e}", file=sys.stderr)

    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="渲染盘前简报 Markdown")
    ap.add_argument("json_path", nargs="?", help="brief JSON path")
    ap.add_argument("--build-from-views", action="store_true", help="直接从 structured_views 构建 brief JSON")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--per-entity", type=int, default=4)
    ap.add_argument("--json-out", help="保存构建出的 JSON")
    ap.add_argument("--output", help="保存 Markdown")
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()

    if args.build_from_views:
        data = build_from_views(days=args.days, per_entity=args.per_entity)
    elif args.json_path:
        data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    else:
        raise SystemExit("需要 json_path 或 --build-from-views")

    report = validate_brief(data)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.validate_only:
        print(format_validation(report))
        raise SystemExit(0 if report["valid"] else 2)
    md = render_markdown(data)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(md, encoding="utf-8")
        print(args.output)
    else:
        print(md)
    if not report["valid"]:
        print(format_validation(report), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
