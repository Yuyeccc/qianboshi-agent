#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decision_review_agent.py —— 决策复盘视角 Agent（P2-C，Orchestrator 可插拔执行器）

定位：第三 executor。给定标的/主题（goal），从 qianboshi_decision.db 选出相关
用户决策 → 判定结果复用现役回填（decision_reviews 表，review_judge 引擎产物，
C 只读不重判）→ LLM 产出认知修正（lessons 按 前提/推理/执行/结果 分类）→
产物为 32_review_v0.1 协议 JSON，落 data/research/（与其它 agent 同契约）。

用法:
    python decision_review_agent.py "复盘黄金决策" --entity GOLD [--job-id X]
    python decision_review_agent.py "复盘创新药" --entity INNOV_DRUG --no-llm
    python decision_review_agent.py "复盘"                                    # 无匹配→最新决策

与现役关系:
    - backfill_decision_outcomes（daily_decision_review 自动跑）= 结果回填写入方
    - decision_review_generator --report = markdown 报告（现役保留）
    - 本 agent = 按需触发 + 结构化 JSON + job 契约 + LLM 认知修正（不替代现役）

铁律（继承）:
    - requests trust_env=False；data 文件 utf-8-sig；LLM 失败降级不编造
    - 判定数据只读：本 agent 绝不写 user_decision_logs/decision_reviews
    - compliance 代码固定，不经 LLM
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
sys.path.insert(0, str(PROJ / "scripts"))

import decision_db  # noqa: E402

# ── 常量 ───────────────────────────────────────────────────
SCHEMA_PATH = PROJ / "docs" / "32_review_v0.1.schema.json"
REPORTS_DIR = PROJ / "data" / "research"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
LLM_URL = "https://api.deepseek.com/chat/completions"
LLM_MODEL = "deepseek-v4-flash"  # 复盘修正量小，flash 够用且省
MAX_OUT_TOKENS = 2500
JSON_FIELDS = ("key_reasons", "premise", "invalidation_conditions")

COMPLIANCE_NOTE = "仅复盘/认知记录用途：本报告不含任何交易指令、买卖建议或操作提示。"


# ── 数据读取（只读现役 DB）────────────────────────────────
def _fetch_decisions() -> list[dict]:
    """全量决策 + JSON 字段还原 + review 判定关联。"""
    decs = decision_db.fetch_decisions()
    out = []
    for d in decs:
        for f in JSON_FIELDS:
            v = d.get(f)
            if isinstance(v, str):
                try:
                    d[f] = json.loads(v)
                except json.JSONDecodeError:
                    d[f] = []
        out.append(d)
    return out


def _fetch_review(decision_id: str) -> dict | None:
    """读该决策的现役判定行（只读，不触发回填）。"""
    with decision_db.connect() as conn:
        row = conn.execute(
            "SELECT review_date, horizon_days, outcome_return, benchmark_return, excess_return,"
            " max_drawdown, result_label, what_went_right, what_went_wrong, missed_factors,"
            " over_weighted_factors, new_rule_learned FROM decision_reviews WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
    return dict(row) if row else None


def _pick_decision(entity: str, decs: list[dict]) -> dict | None:
    """entity 匹配 asset_id/asset_name/名称词；无匹配取最新一条（decision_date 降序首位）。"""
    e = (entity or "").strip().lower()
    if e:
        for d in decs:
            hay = " ".join(str(x) for x in [d.get("asset_id", ""), d.get("asset_name", ""),
                                            d.get("decision_id", "")]).lower()
            if e in hay or any(tok and tok.lower() in e for tok in
                               (d.get("asset_name", "").split() if d.get("asset_name") else [])):
                return d
    return decs[0] if decs else None


# ── LLM（与 B/analyst 同模式）──────────────────────────────
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


def llm_lessons(decision: dict, review: dict | None) -> dict:
    """LLM 产出 lessons + summary（不进 compliance；判定数据只读透传）。"""
    dec_txt = json.dumps({k: decision.get(k) for k in
                          ("decision_id", "asset_id", "asset_name", "direction", "horizon",
                           "conviction", "decision_date", "thesis", "key_reasons", "premise",
                           "invalidation_conditions", "action_note", "status")},
                         ensure_ascii=False, indent=1)
    rev_txt = json.dumps(review, ensure_ascii=False, indent=1) if review else "（决策未到期/无判定结果）"
    system = (
        "你是钱博士的决策复盘视角 Agent。输入：一条用户决策（方向/信心/期限/理由/前提/证伪条件）"
        "+ 现役判定结果（对错/收益/复盘要点）。输出 JSON（勿输出其他内容）：\n"
        "{\n"
        '  "summary": "250字内复盘结论：判断对错 + 关键认知点",\n'
        '  "lessons": [{"type": "premise|reasoning|execution|outcome|other", "lesson": "可复用的认知修正", '
        '"evidence": "支撑该修正的决策/结果事实"}]\n'
        "}\n"
        "铁律：复盘的是认知与决策质量，绝不输出交易指令/买卖建议/目标价；"
        "区分事实错误与推理错误；未到期决策 lessons 聚焦前提质量与证伪条件是否可执行；"
        "判定数据只读透传，禁止编造结果。lessons 2-5 条，每条一句话可执行。"
    )
    user = f"任务目标: {decision.get('asset_name', decision.get('asset_id'))} 复盘\n决策:\n{dec_txt}\n判定结果:\n{rev_txt}"
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


def build_report(goal: str, entity: str, decision: dict, review: dict | None,
                 llm_out: dict | None) -> dict:
    dec = {
        "assetId": decision.get("asset_id", ""),
        "assetName": decision.get("asset_name", ""),
        "direction": decision.get("direction", ""),
        "horizon": decision.get("horizon"),
        "conviction": decision.get("conviction"),
        "decisionDate": decision.get("decision_date", ""),
        "thesis": decision.get("thesis", ""),
        "keyReasons": decision.get("key_reasons") or [],
        "premise": decision.get("premise") or [],
        "invalidationConditions": decision.get("invalidation_conditions") or [],
        "actionNote": decision.get("action_note"),
    }
    if dec["conviction"] is None:
        dec["convictionNote"] = "现役决策未记录信心度"
    review_status = "reviewed" if review else (
        "pending_outcome" if decision.get("status") == "open" else "no_decision_found")
    outcome = None
    if review:
        # DB 行字段为 snake_case；产物协议为 camelCase（显式映射，P2-C 实测修）
        _OUTCOME_MAP = {
            "review_date": "reviewDate", "horizon_days": "horizonDays", "result_label": "resultLabel",
            "outcome_return": "outcomeReturn", "benchmark_return": "benchmarkReturn",
            "excess_return": "excessReturn", "max_drawdown": "maxDrawdown",
        }
        outcome = {_OUTCOME_MAP[k]: v for k, v in review.items() if k in _OUTCOME_MAP and v is not None}
        outcome = outcome or None  # 全空（仅有 label 无数值）→ null，不留空对象
    assessment = {
        "whatWentRight": (review or {}).get("what_went_right"),
        "whatWentWrong": (review or {}).get("what_went_wrong"),
        "missedFactors": (review or {}).get("missed_factors"),
        "overWeightedFactors": (review or {}).get("over_weighted_factors"),
        "newRuleLearned": (review or {}).get("new_rule_learned"),
    }

    report = {
        "goal": goal,
        "entity": entity,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "decisionId": decision.get("decision_id", ""),
        "reviewStatus": review_status,
        "decision": dec,
        "outcome": outcome,
        "assessment": assessment,
        "lessons": (llm_out or {}).get("lessons", []),
        "compliance": {"passed": True, "note": COMPLIANCE_NOTE},
        "_meta": {"agent_type": "decision_review", "llm_used": llm_out is not None,
                  "generated_at": datetime.now().isoformat(timespec="seconds"),
                  "decision_count": 1},
    }
    if llm_out is None:
        report["analysisNote"] = "LLM 不可用（--no-llm 或调用失败），仅输出现役判定数据；lessons 为空不代表无教训"
    else:
        report["summary"] = llm_out.get("summary", "")
    return report


def run_decision_review(goal: str, entity: str | None = None, use_llm: bool = True,
                        save: bool = True, job_id: str | None = None) -> dict:
    t0 = time.time()
    ent = (entity or goal).strip()
    print(f"[1/4] 复盘目标: {ent}")

    print("[2/4] 读决策日志 + 现役判定…")
    decs = _fetch_decisions()
    decision = _pick_decision(ent, decs)
    if decision is None:
        report = {
            "goal": goal, "entity": ent, "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "decisionId": "", "reviewStatus": "no_decision_found",
            "decision": {"assetId": "", "assetName": "", "direction": "", "decisionDate": ""},
            "outcome": None,
            "assessment": {"whatWentRight": None, "whatWentWrong": None,
                           "missedFactors": None, "overWeightedFactors": None, "newRuleLearned": None},
            "lessons": [], "analysisNote": "决策日志为空，无决策可复盘",
            "compliance": {"passed": True, "note": COMPLIANCE_NOTE},
            "_meta": {"agent_type": "decision_review", "llm_used": False,
                      "generated_at": datetime.now().isoformat(timespec="seconds"), "decision_count": 0},
        }
        ok, errs = validate_report(report)
        report["_meta"]["schema_valid"] = ok
        print(f"      ⚠ 无决策可复盘（schema 校验: {'通过' if ok else errs}）")
        if save:
            REPORTS_DIR.mkdir(exist_ok=True)
            h = hashlib.md5(goal.encode()).hexdigest()[:8]
            fname = REPORTS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{h}.json"
            fname.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"已保存: {fname}")
        return report

    review = _fetch_review(decision["decision_id"])
    print(f"      命中决策: {decision['decision_id']}（{decision.get('asset_name')}，"
          f"{decision.get('direction')}）判定: {'有' if review else '无/未到期'}")

    llm_out = None
    if use_llm:
        print("[3/4] LLM 认知修正…")
        try:
            llm_out = llm_lessons(decision, review)
        except Exception as e:  # noqa: BLE001 —— 降级不阻断
            print(f"      ⚠ LLM 失败，降级确定性输出: {e}")
            llm_out = None
    else:
        print("[3/4] --no-llm，跳过 LLM…")

    print("[4/4] 组装 + schema 校验 + 落盘…")
    report = build_report(goal, ent, decision, review, llm_out)
    ok, errs = validate_report(report)
    report["_meta"]["schema_valid"] = ok
    if errs:
        report["_meta"]["schema_errors"] = errs
    if job_id:
        report["_meta"]["job_id"] = job_id
    print(f"      32_review v0.1 schema 校验: {'通过' if ok else '失败: ' + '; '.join(errs)}")

    print(f"完成，耗时 {time.time() - t0:.0f}s")
    if save:
        REPORTS_DIR.mkdir(exist_ok=True)
        h = hashlib.md5(goal.encode()).hexdigest()[:8]
        fname = REPORTS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{h}.json"
        fname.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已保存: {fname}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="决策复盘视角 Agent（P2-C）")
    ap.add_argument("goal", help="复盘目标，如: 复盘黄金决策")
    ap.add_argument("--entity", default=None, help="标的 asset_id/名称（默认取 goal 原文，无匹配取最新决策）")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--job-id", default=None)
    args = ap.parse_args()
    rep = run_decision_review(args.goal, entity=args.entity, use_llm=not args.no_llm,
                              save=not args.no_save, job_id=args.job_id)
    print(json.dumps(rep, ensure_ascii=False, indent=1)[:2500])
