#!/usr/bin/env python3
"""
钱博士Agent MCP Server — 让 Hermes Studio / Hermes Agent 直接查看流水线调试信息

暴露工具（在 Studio 聊天里自然调用）:
  pipeline_status  流水线全环节实时状态（监控/队列/转写/笔记/RAG/日报/磁盘）
  queue_list       待处理队列（最新优先）
  logs_tail        查看运行日志尾部
  rag_stats        RAG向量库统计

启动: python qianboshi_mcp.py  (stdio 模式, 由 Hermes MCP 客户端拉起)
"""
import json
import sys
from pathlib import Path
from datetime import datetime

from mcp.server.fastmcp import FastMCP

PROJ = Path(r"E:\qianboshi-agent")
OBSIDIAN = Path(r"E:\obsidian-vault\学习\钱博士")

mcp = FastMCP("qianboshi")


def _read_json(rel):
    p = PROJ / rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pipeline_status_dict():
    state = _read_json("data/monitor_state.json") or {}
    queue = _read_json("data/pipeline_queue.json") or []
    transcripts = len(list((PROJ / "transcripts").glob("*_transcript*.txt")))
    notes = len(list(OBSIDIAN.glob("*.md"))) if OBSIDIAN.exists() else 0
    idx = _read_json("data/vector_db/index.json") or {}
    chunks = sum(len(v.get("chunk_ids", [])) for v in idx.values() if isinstance(v, dict))
    briefs = len(list((PROJ / "data/briefs").glob("*.md"))) if (PROJ / "data/briefs").exists() else 0
    audio_gb = sum(f.stat().st_size for f in (PROJ / "audio").glob("*.wav")) / 1024**3 if (PROJ / "audio").exists() else 0
    channels = state.get("channels", {})
    ch_summary = {uid: {"last_check": c.get("last_check", ""), "last_bvid": c.get("last_bvid", "")}
                  for uid, c in channels.items()}
    return {
        "monitor": {"checked_at": state.get("checked_at", "从未"), "channels": ch_summary},
        "queue": {"pending": len(queue)},
        "transcripts": {"files": transcripts},
        "notes": {"count": notes},
        "rag": {"chunks": chunks},
        "briefs": {"count": briefs},
        "audio_gb": round(audio_gb, 1),
    }


@mcp.tool()
def pipeline_status() -> str:
    """钱博士Agent 流水线全环节实时状态：监控最后检查时间与各频道、队列待处理数、转写稿数、笔记数、RAG chunks数、日报数、audio占用GB。返回JSON。"""
    return json.dumps(_pipeline_status_dict(), ensure_ascii=False, indent=1)


@mcp.tool()
def queue_list(limit: int = 10) -> str:
    """钱博士Agent 待处理任务队列（按发布日期最新优先）。limit: 返回条数，默认10。"""
    queue = _read_json("data/pipeline_queue.json") or []
    rows = [{"bvid": q.get("bvid"), "channel": q.get("channel"), "analyst": q.get("analyst"),
             "pubdate": q.get("pubdate"), "title": (q.get("title") or "")[:40]}
            for q in queue[:limit]]
    return json.dumps({"total": len(queue), "items": rows}, ensure_ascii=False, indent=1)


@mcp.tool()
def logs_tail(file: str = "", lines: int = 50) -> str:
    """查看钱博士Agent运行日志尾部。file: 日志文件名（留空=最新的.log），lines: 行数，默认50。"""
    log_dir = PROJ / "logs"
    if not log_dir.exists():
        return "logs/ 目录不存在"
    files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return "logs/ 目录无日志"
    target = None
    if file:
        target = log_dir / file
        if not target.exists():
            return f"找不到日志 {file}，可用: {', '.join(p.name for p in files[:10])}"
    else:
        target = files[0]
    content = target.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = "\n".join(content[-lines:])
    return f"=== {target.name} ({len(content)}行, 显示最后{lines}行) ===\n{tail}"


@mcp.tool()
def rag_stats() -> str:
    """RAG向量库统计：总chunks数、笔记条目数、向量库文件大小。"""
    idx = _read_json("data/vector_db/index.json") or {}
    chunks = sum(len(v.get("chunk_ids", [])) for v in idx.values() if isinstance(v, dict))
    db = PROJ / "data" / "vector_db"
    size_mb = sum(f.stat().st_size for f in db.rglob("*") if f.is_file()) / 1024**2 if db.exists() else 0
    return json.dumps({"notes_indexed": len(idx), "chunks": chunks,
                       "vector_db_size_mb": round(size_mb, 1)}, ensure_ascii=False, indent=1)


# ─── 决策台分析工具（阶段六：飞书/聊天可调用） ───────────────────


def _import_decision_modules():
    """按需导入项目脚本（避免 MCP 启动时加载慢依赖）。"""
    sys.path.insert(0, str(PROJ / "scripts"))
    import asset_card_builder
    import debate_card_builder
    import decision_review_generator
    import evidence_pack_builder
    from decision_db import fetch_decisions
    return asset_card_builder, debate_card_builder, decision_review_generator, evidence_pack_builder, fetch_decisions


def _gated(text: str, tool: str, field: str = "") -> str:
    """#11v2：输出侧合规门（annotate 加横幅 / block 拦截 / clean 直通）。"""
    try:
        from compliance_gate import output_gate
        r = output_gate(text, source="mcp", tool=tool, field=field)
        return r["output"]
    except Exception:
        return text  # fail-safe：import 失败不阻断 MCP（compliance_gate 内部已 fail-closed）


@mcp.tool()
def get_asset_analysis_card(asset_id: str) -> str:
    """获取某资产的资产分析卡（因素→状态→影响→证据）。asset_id 如 GOLD/SEMI/AI/ROBOT/BAIJIU。"""
    try:
        asset_card_builder, _, _, _, _ = _import_decision_modules()
        card = asset_card_builder.build_asset_card(asset_id)
        return _gated(asset_card_builder.render_asset_card(card), tool="get_asset_analysis_card")
    except Exception as e:
        return _gated(f"获取资产分析卡失败: {e}", tool="get_asset_analysis_card")


@mcp.tool()
def get_debate_card(entity: str, lookback_days: int = 60) -> str:
    """获取某实体的多空对照卡（多头/空头/分歧/共识/新变化）。entity 如 黄金/半导体/光模块。"""
    try:
        _, debate_card_builder, _, _, _ = _import_decision_modules()
        card = debate_card_builder.build_debate_card(entity, lookback_days=lookback_days)
        from brief_renderer import render_debate_card
        return _gated(render_debate_card(card), tool="get_debate_card")
    except Exception as e:
        return _gated(f"获取多空对照卡失败: {e}", tool="get_debate_card")


@mcp.tool()
def get_evidence_pack(asset_id: str, horizon: str = "medium") -> str:
    """Return EvidencePack JSON for one asset."""
    try:
        _, _, _, evidence_pack_builder, _ = _import_decision_modules()
        pack = evidence_pack_builder.build_evidence_pack(asset_id, horizon=horizon)
        return _gated(json.dumps(pack, ensure_ascii=False, indent=1), tool="get_evidence_pack")
    except Exception as e:
        return _gated(f"get_evidence_pack failed: {e}", tool="get_evidence_pack")


@mcp.tool()
def get_decision_review(asset_id: str, use_llm: bool = False) -> str:
    """获取某资产的用户决策复盘报告（判断概览/结果/依据/认知修正）。asset_id 如 GOLD。"""
    try:
        _, _, decision_review_generator, _, _ = _import_decision_modules()
        return _gated(decision_review_generator.generate_review_report(asset_id, use_llm=use_llm),
                      tool="get_decision_review")
    except Exception as e:
        return _gated(f"获取复盘报告失败: {e}", tool="get_decision_review")


@mcp.tool()
def list_user_decisions(status: str = "") -> str:
    """列出用户决策日志（含判断/理由/证伪/信心度）。status 可选 open/reviewed。"""
    try:
        _, _, _, _, fetch_decisions = _import_decision_modules()
        decisions = fetch_decisions(status=status or None)
        out = []
        for d in decisions:
            out.append({
                "id": d.get("decision_id"),
                "date": d.get("decision_date"),
                "asset": d.get("asset_name"),
                "direction": d.get("direction"),
                "horizon": d.get("horizon"),
                "conviction": d.get("conviction"),
                "status": d.get("status"),
                "thesis": (d.get("thesis") or "")[:100],
            })
        return _gated(json.dumps(out, ensure_ascii=False, indent=1), tool="list_user_decisions")
    except Exception as e:
        return _gated(f"列出决策失败: {e}", tool="list_user_decisions")


# ─── 记忆体系时间轴工具（P1b） ───────────────────────


def _timeline_conn():
    """事件时间轴库只读连接（lifecycle 库，P1b schema 内建）。"""
    sys.path.insert(0, str(PROJ / "scripts"))
    import event_timeline as et
    from view_lifecycle import db_path
    conn = et.connect(db=db_path())
    return conn, et


@mcp.tool()
def timeline_get(event_type: str = "", actor: str = "", since: str = "", limit: int = 20) -> str:
    """记忆体系事件时间轴查询（观点状态变化/决策/复盘/资产卡版本/行情结果/信念变更）。
    event_type 可选: decision_created/review_created/asset_card_versioned/outcome_observed/
    view_created/view_status_changed/user_view_changed；actor 如 user/market/分析师名；
    since 起始时间(ISO 或日期)；limit 条数默认20。返回事件 JSON。"""
    try:
        conn, et = _timeline_conn()
        try:
            rows = et.query_timeline(conn, event_type=event_type, actor=actor,
                                     since=since, limit=limit)
        finally:
            conn.close()
        return _gated(json.dumps({"count": len(rows), "items": rows},
                                 ensure_ascii=False, indent=1), tool="timeline_get")
    except Exception as e:
        return _gated(f"时间轴查询失败: {e}", tool="timeline_get")


@mcp.tool()
def timeline_trace_decision(decision_id: str) -> str:
    """决策链回放：某决策的完整事件链（创建→复盘→资产卡版本→关联观点结果，时间升序）。
    decision_id 如 dec_2026-08-06_GOLD_001（用 list_user_decisions 查 id）。"""
    try:
        conn, et = _timeline_conn()
        try:
            chain = et.trace_decision(conn, decision_id)
        finally:
            conn.close()
        if not chain:
            return _gated(f"决策 {decision_id} 无时间轴事件（可能未 build/reconcile）",
                          tool="timeline_trace_decision")
        return _gated(json.dumps({"decision_id": decision_id, "chain": chain},
                                 ensure_ascii=False, indent=1), tool="timeline_trace_decision")
    except Exception as e:
        return _gated(f"决策链回放失败: {e}", tool="timeline_trace_decision")


if __name__ == "__main__":
    mcp.run()
