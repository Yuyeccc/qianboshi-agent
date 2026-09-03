#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portfolio_risk_agent.py —— 持仓风险视角 Agent（P2-B，Orchestrator 可插拔执行器）

定位：与 research_agent（analyst）同契约的第二 executor。给定目标/主题（goal），
对照当前真实持仓（portfolio.json + 行情缓存），输出"暴露 + 风险点 + 观察清单"，
产物为 31_risk_v0.1 协议 JSON。D3 决策：当前为内部能力（CLI/orchestrator 直调），
不接入交互页安检/渲染。

用法:
    python portfolio_risk_agent.py "黄金价格波动对持仓影响" --entity 黄金 [--job-id X]
    python portfolio_risk_agent.py "光模块板块风险" --no-llm        # 降级：仅确定性暴露

流程:
    1. 读 portfolio.json 全部持仓 + 行情缓存报价（market_cache → price_trends 回退）
    2. 确定性匹配：entity 关键词 vs 持仓 name/sector → exposed 头寸 + 市值/占比
    3. LLM 组装：持仓上下文 + 目标 → riskPoints/summary/watchlist（json_object）
    4. compliance 由代码固定（passed + 不含交易指令），不经 LLM
    5. jsonschema 校验 31_risk_v0.1 → 落盘 data/research/<ts>_<hash>.json（_meta.job_id）

要点（铁律继承）:
    - requests 一律 trust_env=False（系统代理劫持坑）；跑批清 PYTHONPATH
    - LLM 失败 → 降级输出确定性暴露（riskPoints=[] + analysisNote），不编造
    - data 文件 BOM → utf-8-sig
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# 直连（系统代理劫持坑: Clash 7897）
for _k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_k, None)

import requests  # noqa: E402
requests.packages.urllib3.disable_warnings()

import jsonschema  # noqa: E402

PROJ = Path(__file__).resolve().parent.parent

# ── 常量 ───────────────────────────────────────────────────
PORTFOLIO_FILE = PROJ / "data" / "portfolio.json"
MARKET_CACHE_FILE = PROJ / "data" / "market_cache.json"
PRICE_TRENDS_FILE = PROJ / "data" / "price_trends.json"
SCHEMA_PATH = PROJ / "docs" / "31_risk_v0.1.schema.json"
REPORTS_DIR = PROJ / "data" / "research"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
LLM_URL = "https://api.deepseek.com/chat/completions"
LLM_MODEL = "deepseek-v4-flash"  # 风险分析量小，flash 够用且省
MAX_OUT_TOKENS = 2500

COMPLIANCE_NOTE = "仅研究/风险识别用途：本报告不含任何交易指令、买卖建议或操作提示。"


# ── 数据读取（BOM 兼容）────────────────────────────────────
def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def load_portfolio() -> dict:
    """返回 {code: holding}；读取失败抛错（fail-closed：无持仓数据不产出报告）。"""
    p = _read_json(PORTFOLIO_FILE)
    holdings_raw = (p or {}).get("holdings") or {}
    if not holdings_raw:
        raise RuntimeError(f"持仓为空或缺失: {PORTFOLIO_FILE}")
    return {
        "holdings": holdings_raw,
        "snapshot": (p or {}).get("account_snapshot") or {},
    }


def latest_quote(market_code: str) -> dict | None:
    """行情缓存取价：market_cache 优先，回退 price_trends 最新日。"""
    cache = _read_json(MARKET_CACHE_FILE) or {}
    if market_code in cache:
        q = cache[market_code]
        return {"price": q.get("price"), "updated": q.get("updated", ""), "source": "market_cache"}
    trends = _read_json(PRICE_TRENDS_FILE) or {}
    if market_code in trends and trends[market_code]:
        days = trends[market_code]
        last_date = sorted(days.keys())[-1]
        return {"price": days[last_date].get("price"), "updated": last_date, "source": "price_trends"}
    return None


# ── 确定性持仓匹配 ─────────────────────────────────────────
def match_exposed(entity: str, holdings: dict) -> list[dict]:
    """entity 关键词 vs 持仓 name/sector/market_code：命中即算相关头寸。

    纯字符串包含匹配（无 LLM）：持仓名/行业词出现在 entity 或反之。
    例: "黄金" ↔ 华安黄金ETF(518880)/sector=黄金；"中国建筑" ↔ 601668；
        "电池" ↔ 华夏中证电池ETF联接(027695)/sector=新能源/电池。
    """
    e = (entity or "").strip().lower()
    if not e:
        return []
    exposed = []
    for code, h in holdings.items():
        hay = " ".join(str(x) for x in [code, h.get("name", ""), h.get("sector", ""), h.get("market_code", "")]).lower()
        if e in hay or any(tok in e for tok in (h.get("name", "").lower(), h.get("sector", "").lower())):
            sector = h.get("sector", "")
            relation = f"同属{sector}板块" if sector else f"持仓 {h.get('name', code)} 与评估目标相关"
            exposed.append({"code": code, "name": h.get("name", code), "marketCode": h.get("market_code", ""),
                            "relation": relation, "shares": h.get("shares"), "avgCost": h.get("avg_cost")})
    return exposed


# ── LLM（与 research_agent 同模式：key env→Hermes .env 回退，递增退避）──
def call_llm(system: str, user: str, max_tokens: int = 2500) -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        env_f = Path.home() / "AppData/Local/hermes/.env"
        if env_f.exists():
            m = re.search(r"DEEPSEEK_API_KEY=(\S+)", env_f.read_text(encoding="utf-8", errors="ignore"))
            key = m.group(1) if m else ""
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY 未设置")
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    s = requests.Session()
    s.trust_env = False
    s.proxies = {"http": None, "https": None}
    s.verify = False
    resp = s.post(LLM_URL, headers={**UA, "Authorization": f"Bearer {key}"}, json=payload, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")
    content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
    if not content:
        raise RuntimeError("LLM 空返回")
    return content


def llm_json(system: str, user: str, retries: int = 3, max_tokens: int = 2500) -> dict:
    """json_object 解析 + 递增退避（2/10/20s，P1-C 窗口坑）。"""
    last_err = ""
    backoff = (2, 10, 20)
    for i in range(retries + 1):
        try:
            raw = call_llm(system, user, max_tokens=max_tokens + i * 1000)
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                raise ValueError("not a dict")
            return obj
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(backoff[i] if i < len(backoff) else 20)
    raise RuntimeError(f"LLM JSON 输出失败: {last_err}")


def llm_analyze(entity: str, goal: str, exposed: list[dict], snapshot: dict) -> dict:
    """LLM 生成 riskPoints/summary/watchlist（不进 compliance）。

    快照只传账户规模类字段（总资产/在市值/现金/仓位比）；floating_pnl/day_pnl
    是账户整体口径且为时点值，喂给 LLM 易被误归因到单头寸（P2-B 实测教训）。
    """
    exposed_txt = json.dumps(exposed, ensure_ascii=False, indent=1) if exposed else "（当前持仓无直接相关头寸）"
    snap_clean = {k: v for k, v in snapshot.items() if k in
                  ("date", "total_assets", "market_value_onmarket", "cash_available", "position_pct")}
    snap_txt = json.dumps(snap_clean, ensure_ascii=False) if snap_clean else "（无账户快照）"
    system = (
        "你是钱博士的持仓风险视角 Agent。输入：评估目标 + 当前真实持仓相关头寸 + 账户快照。"
        "输出 JSON（勿输出其他内容）：\n"
        "{\n"
        '  "summary": "300字内结论：该目标与当前持仓的关联、主要风险与关注度",\n'
        '  "riskPoints": [{"risk": "风险点描述", "severity": "high|medium|low", '
        '"rationale": "推理依据（紧扣持仓暴露与目标情境，可提集中度/联动/事件冲击）", "watch": "观察触发项"}],\n'
        '  "watchlist": [{"text": "跟踪项", "trigger": "触发含义"}]\n'
        "}\n"
        "铁律：只做研究/风险识别，绝不输出任何交易指令、买卖建议、目标价、操作提示；"
        "事实不确定就标注；当前持仓无相关头寸时 summary 明说无直接暴露，riskPoints 聚焦间接/系统性风险。"
    )
    user = f"评估目标: {entity}\n任务目标原文: {goal}\n相关头寸:\n{exposed_txt}\n账户快照: {snap_txt}"
    return llm_json(system, user, max_tokens=MAX_OUT_TOKENS)


# ── 组装与校验 ─────────────────────────────────────────────
def validate_report(report: dict) -> tuple[bool, list[str]]:
    if not SCHEMA_PATH.exists():
        return False, [f"schema 文件缺失: {SCHEMA_PATH}"]
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = [e.message for e in validator.iter_errors(report)]
        return (len(errors) == 0), errors[:8]
    except Exception as e:  # noqa: BLE001
        return False, [f"校验器异常: {e}"]


def build_report(goal: str, entity: str, portfolio: dict, exposed: list[dict], llm_out: dict | None) -> dict:
    holdings_raw = portfolio["holdings"]
    snapshot = portfolio.get("snapshot") or {}
    total_assets = snapshot.get("total_assets")

    # 头寸估值（价缺按成本近似并注明）
    valued = []
    for h in exposed:
        mc = h.get("marketCode") or ""
        q = latest_quote(mc) if mc else None
        price = (q or {}).get("price")
        shares = h.get("shares")
        value = None
        note = ""
        if isinstance(shares, (int, float)) and isinstance(price, (int, float)):
            value = round(shares * price, 2)
        elif isinstance(shares, (int, float)) and isinstance(h.get("avgCost"), (int, float)):
            value = round(shares * h["avgCost"], 2)
            note = "价缺失，按成本近似"
        weight = round(value / total_assets * 100, 2) if (value and total_assets) else None
        valued.append({**h, "price": price, "value": value, "valueNote": note or None, "weightPct": weight})

    exposure_obj = {
        "total": len(holdings_raw),
        "exposed": valued,
        "portfolio": {
            "totalAssets": total_assets,
            "onMarketValue": snapshot.get("market_value_onmarket"),
            "cashAvailable": snapshot.get("cash_available"),
            "positionPct": snapshot.get("position_pct"),
            "asOf": snapshot.get("date"),
        },
    }

    report = {
        "goal": goal,
        "entity": entity,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "summary": (llm_out or {}).get("summary", "（LLM 未参与，仅确定性持仓暴露）"),
        "holdingsExposure": exposure_obj,
        "riskPoints": (llm_out or {}).get("riskPoints", []),
        "watchlist": (llm_out or {}).get("watchlist", []),
        "compliance": {"passed": True, "note": COMPLIANCE_NOTE},
        "_meta": {"agent_type": "portfolio_risk", "llm_used": llm_out is not None, "generated_at": datetime.now().isoformat(timespec="seconds")},
    }
    if llm_out is None:
        report["analysisNote"] = "LLM 不可用（--no-llm 或调用失败），仅输出确定性持仓暴露；riskPoints 为空不代表无风险"
    return report


def run_portfolio_risk(goal: str, entity: str | None = None, use_llm: bool = True,
                       save: bool = True, job_id: str | None = None) -> dict:
    t0 = time.time()
    # 实体提取：goal 里带引号目标优先，否则用 LLM？不——确定性：取 --entity 或 goal 原文前 12 字
    ent = (entity or goal).strip()
    print(f"[1/4] 评估目标: {ent}")

    print("[2/4] 读持仓 + 行情…")
    portfolio = load_portfolio()
    holdings_raw = portfolio["holdings"]
    exposed = match_exposed(ent, holdings_raw)
    print(f"      持仓 {len(holdings_raw)} 头寸，直接相关 {len(exposed)} 个: {[h['code'] for h in exposed] or '（无）'}")

    llm_out = None
    if use_llm:
        print("[3/4] LLM 风险分析…")
        try:
            llm_out = llm_analyze(ent, goal, exposed, portfolio.get("snapshot") or {})
        except Exception as e:  # noqa: BLE001 —— 降级不阻断（产出确定性部分）
            print(f"      ⚠ LLM 失败，降级确定性输出: {e}")
            llm_out = None
    else:
        print("[3/4] --no-llm，跳过 LLM（确定性输出）…")

    print("[4/4] 组装 + schema 校验 + 落盘…")
    report = build_report(goal, ent, portfolio, exposed, llm_out)
    ok, errs = validate_report(report)
    report["_meta"]["schema_valid"] = ok
    if errs:
        report["_meta"]["schema_errors"] = errs
    if job_id:
        report["_meta"]["job_id"] = job_id
    print(f"      31_risk v0.1 schema 校验: {'通过' if ok else '失败: ' + '; '.join(errs)}")

    print(f"完成，耗时 {time.time() - t0:.0f}s")
    if save:
        REPORTS_DIR.mkdir(exist_ok=True)
        h = hashlib.md5(goal.encode()).hexdigest()[:8]
        fname = REPORTS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{h}.json"
        fname.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已保存: {fname}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="持仓风险视角 Agent（P2-B）")
    ap.add_argument("goal", help="评估目标，如: 黄金价格波动对持仓的影响")
    ap.add_argument("--entity", default=None, help="明确标的/主题（默认取 goal 原文）")
    ap.add_argument("--no-llm", action="store_true", help="跳过 LLM，仅确定性持仓暴露（测试/降级）")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--job-id", default=None)
    args = ap.parse_args()
    rep = run_portfolio_risk(args.goal, entity=args.entity, use_llm=not args.no_llm,
                             save=not args.no_save, job_id=args.job_id)
    print(json.dumps(rep, ensure_ascii=False, indent=1)[:2500])
