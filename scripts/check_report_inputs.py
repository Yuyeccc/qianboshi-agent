#!/usr/bin/env python3
"""日报生成前/后确定性注入完整性检查（审验-自补 第 0 步，纯代码无 LLM）。

定位：brief_post_check.py 管"格式层"（字数/章节/禁词），本脚本管"注入层"——
核心输入（持仓/决策台/指数快照/tracking pool）是否成功解码注入。2026-09-04
实况：持仓整节 N/A（portfolio.json BOM 裸读）+ 决策台整节 N/A（decision_desk
空注入）照常交付，就是缺这层确定性闸门。

检查项（findings，前缀 IN-xx）：
  IN-01 portfolio.json 存在 + utf-8-sig 解码 + holdings 非空（BOM 检测）
  IN-02 decision_desk 四模块注入：user_decisions/debate_cards/factor_states
        非空或显式说明（近 30 日窗口语义）+ discipline 无 error
  IN-03 指数快照 market_cache.json：存在 + 解码 + 核心指数条目
  IN-04 tracking_pool.json：存在 + 解码 + stocks/etfs/us_stocks 非空
  IN-05 报告 md 存在 + 头部日期与 --date 一致（回放/装配时报告生成时刻）
  IN-06 报告文本不引用禁用来源（来源白名单，同 brief_post_check BANNED）
  IN-07 33_reviewer schema v0.1 存在 + JSON 解析 + Draft202012 自校验

用法：
    C:/Python314/python.exe scripts/check_report_inputs.py --date YYYY-MM-DD [--report <md路径>] [--json <out>]
退出码：0=PASS（全过）/ 1=WARN（仅 🟡）/ 2=FAIL（有 🔴，核心输入损坏）

核心输入损坏 → 记 finding（status=open）供 Reviewer 引用，本脚本只读不阻断。
输出 --json 可被 reviewer_agent.py collect_input_snapshot 复用。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SCHEMA_PATH = ROOT / "docs" / "33_reviewer_v0.1.schema.json"
BOM = b"\xef\xbb\xbf"

# 运行时动态取（BRIEFS_DIR 依赖 DATA_DIR，patch DATA_DIR 时须随之生效）
def _briefs_dir() -> Path:
    return DATA_DIR / "briefs"

# 核心指数白名单：market_cache.json 内应存在的关键条目（A股大盘）
CORE_INDEX_KEYS = ["000001.SS", "399001.SZ", "399006.SZ"]
# 禁用来源（与 brief_post_check.BANNED 同步，勿单独改）
BANNED_SOURCES = ["主力行为学", "汤山老王", "马跑跑", "邻居大爷", "八叔不啰嗦"]


def _load_json_sig(path: Path) -> tuple[dict, bool]:
    """utf-8-sig 读 JSON；返回 (data, had_bom)。失败抛异常由调用方兜底。"""
    raw = path.read_bytes()
    had_bom = raw.startswith(BOM)
    return json.loads(raw.decode("utf-8-sig")), had_bom


def check_inputs(report_date: str, report_path: str | None = None) -> tuple[list[dict], list[dict]]:
    """跑全部确定性检查。返回 (errors🔴, warns🟡)，每项含 id/category/severity/description/evidence。"""
    errors: list[dict] = []
    warns: list[dict] = []
    fid = 0

    def finding(category: str, severity: str, description: str, evidence: str = "") -> None:
        nonlocal fid
        fid += 1
        item = {
            "finding_id": f"IN-{fid:02d}",
            "category": category,
            "severity": severity,
            "status": "open",
            "description": description,
            "detector": "deterministic",
        }
        if evidence:
            item["evidence"] = evidence
        # blocker/high → errors(🔴, 退出码 1/2)；medium/low/info → warns(🟡, 退出码 0)
        (errors if severity in ("blocker", "high") else warns).append(item)

    # ---------- IN-01 portfolio.json ----------
    pf_path = DATA_DIR / "portfolio.json"
    if not pf_path.exists():
        finding("持仓注入", "blocker", "portfolio.json 不存在，持仓整节必 N/A", str(pf_path))
    else:
        try:
            pf, had_bom = _load_json_sig(pf_path)
            holdings = pf.get("holdings") or {}
            n = len(holdings)
            if not n:
                finding("持仓注入", "blocker", "portfolio.json 存在但 holdings 为空", "holdings={}")
            else:
                codes = sorted(holdings.keys())[:6]
                desc = f"holdings {n} 项解码成功"
                ev = f"codes={codes} had_bom={had_bom} 编码=utf-8-sig"
                if had_bom:
                    ev += "（文件带 BOM，必须 utf-8-sig 读——裸 utf-8 会炸）"
                warns.append({"finding_id": "", "category": "持仓注入", "severity": "info",
                              "status": "accepted", "detector": "deterministic",
                              "description": desc, "evidence": ev})
        except Exception as e:
            finding("持仓注入", "blocker", f"portfolio.json 解码失败: {e}", str(pf_path))

    # ---------- IN-02 decision_desk 四模块 ----------
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from decision_desk import build_decision_desk_context

        ddc = build_decision_desk_context()
        if "error" in ddc:
            finding("决策台注入", "blocker", f"build_decision_desk_context() 返回 error: {ddc['error']}")
        else:
            n_ud = len(ddc.get("user_decisions") or [])
            n_dc = len(ddc.get("debate_cards") or [])
            n_fs = len(ddc.get("factor_states") or [])
            disc = ddc.get("discipline") or {}
            if n_ud == 0:
                finding("决策台注入", "blocker",
                        "user_decisions 空：库中无 open 在途决策且近 30 日无 reviewed 复盘决策",
                        "两段式查询(open + review_date>=now-30d) 窗口内无命中")
            else:
                assets = sorted({x.get("asset_id") for x in ddc["user_decisions"] if x.get("asset_id")})
                warns.append({"finding_id": "", "category": "决策台注入", "severity": "info",
                              "status": "accepted", "detector": "deterministic",
                              "description": f"user_decisions {n_ud} 条注入成功",
                              "evidence": f"assets={assets}"})
            if n_dc == 0 and n_ud > 0:
                finding("决策台注入", "blocker", "user_decisions 非空但 debate_cards 为 0（资产遍历断链）")
            if n_fs == 0 and n_ud > 0:
                finding("决策台注入", "blocker", "user_decisions 非空但 factor_states 为 0（资产遍历断链）")
            if disc.get("status") == "error":
                finding("决策台注入", "high", f"discipline 段 error: {disc.get('error')}")
    except Exception as e:
        finding("决策台注入", "blocker", f"decision_desk 检查自身异常: {e}")

    # ---------- IN-03 指数快照 market_cache.json ----------
    mc_path = DATA_DIR / "market_cache.json"
    if not mc_path.exists():
        finding("指数快照", "blocker", "market_cache.json 不存在，大势行情引用无缓存", str(mc_path))
    else:
        try:
            mc, _ = _load_json_sig(mc_path)
            if not isinstance(mc, dict):
                finding("指数快照", "blocker", "market_cache.json 顶层非 dict")
            else:
                missing_idx = [k for k in CORE_INDEX_KEYS if k not in mc]
                if missing_idx:
                    finding("指数快照", "high",
                            f"核心指数缺条目: {missing_idx}", f"现有 {len(mc)} 条缓存")
                else:
                    warns.append({"finding_id": "", "category": "指数快照", "severity": "info",
                                  "status": "accepted", "detector": "deterministic",
                                  "description": f"核心指数 {len(CORE_INDEX_KEYS)} 项齐",
                                  "evidence": f"market_cache {len(mc)} 条目"})
        except Exception as e:
            finding("指数快照", "blocker", f"market_cache.json 解码失败: {e}", str(mc_path))

    # ---------- IN-04 tracking_pool ----------
    tp_path = DATA_DIR / "tracking_pool.json"
    if not tp_path.exists():
        finding("标的池", "blocker", "tracking_pool.json 不存在", str(tp_path))
    else:
        try:
            tp, _ = _load_json_sig(tp_path)
            stocks = tp.get("stocks") or {}
            etfs = tp.get("etfs") or {}
            us = tp.get("us_stocks") or {}
            if not (stocks or etfs or us):
                finding("标的池", "blocker", "tracking_pool stocks/etfs/us_stocks 全空")
            else:
                warns.append({"finding_id": "", "category": "标的池", "severity": "info",
                              "status": "accepted", "detector": "deterministic",
                              "description": "标的池注入成功",
                              "evidence": f"stocks={len(stocks)} etfs={len(etfs)} us={len(us)}"})
        except Exception as e:
            finding("标的池", "blocker", f"tracking_pool.json 解码失败: {e}", str(tp_path))

    # ---------- IN-05 报告存在 + 日期一致 ----------
    resolved_report = report_path
    if not resolved_report:
        candidate = _briefs_dir() / f"日报_{report_date}.md"
        if candidate.exists():
            resolved_report = str(candidate)
    if not resolved_report or not Path(resolved_report).exists():
        # 报告未生成属正常时序（check 在生成前/后都可用）→ WARN 不 FAIL
        warns.append({"finding_id": "", "category": "报告日期", "severity": "medium",
                      "status": "accepted", "detector": "deterministic",
                      "description": f"报告 {report_date} 不存在（检查点在生成前，或回放日期无简报）",
                      "evidence": str(Path(resolved_report) if resolved_report else _briefs_dir())})
    else:
        head = Path(resolved_report).read_text(encoding="utf-8", errors="replace")[:400]
        if report_date not in head:
            finding("报告日期", "high",
                    f"报告头部未见日期 {report_date}（cutoff 一致性存疑）",
                    f"head: {head[:120]!r}")

    # ---------- IN-06 来源白名单 ----------
    if resolved_report and Path(resolved_report).exists():
        text = Path(resolved_report).read_text(encoding="utf-8", errors="replace")
        hit = [b for b in BANNED_SOURCES if b in text]
        if hit:
            finding("来源白名单", "high", f"报告引用禁用来源: {hit}", str(resolved_report))

    # ---------- IN-07 33_reviewer schema 自校验 ----------
    if not SCHEMA_PATH.exists():
        finding("schema", "high", f"33_reviewer schema 缺失: {SCHEMA_PATH}")
    else:
        try:
            from jsonschema import Draft202012Validator

            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            warns.append({"finding_id": "", "category": "schema", "severity": "info",
                          "status": "accepted", "detector": "deterministic",
                          "description": f"33_reviewer schema v0.1 自校验通过",
                          "evidence": f"{SCHEMA_PATH.name} check_schema OK"})
        except Exception as e:
            finding("schema", "high", f"33_reviewer schema 无效: {e}", str(SCHEMA_PATH))

    return errors, warns


def _exit_code(errors: list[dict], warns: list[dict]) -> int:
    """退出码：0=PASS / 1=WARN(有 high 无 blocker) / 2=FAIL(有 blocker)。"""
    if not errors:
        return 0
    return 1 if all(e["severity"] != "blocker" for e in errors) else 2


def main() -> int:
    ap = argparse.ArgumentParser(description="日报确定性注入完整性检查（审验第 0 步）")
    ap.add_argument("--date", required=True, help="报告日期 YYYY-MM-DD")
    ap.add_argument("--report", default=None, help="日报 md 路径（缺省按 date 在 data/briefs/ 找）")
    ap.add_argument("--json", default=None, help="输出 findings JSON 到文件（供 Reviewer 复用）")
    args = ap.parse_args()

    errors, warns = check_inputs(args.date, args.report)

    print(f"== check_report_inputs --date {args.date} ==")
    for w in warns:
        tag = "INFO" if w["severity"] == "info" else "🟡WARN"
        print(f"[{tag}] {w['description']}")
    for e in errors:
        print(f"[🔴FAIL] {e['finding_id']} {e['description']}")

    if args.json:
        code = _exit_code(errors, warns)
        out = {
            "date": args.date,
            "checker": "check_report_inputs",
            "findings": errors + [w for w in warns if w["severity"] != "info"],
            "infos": [w for w in warns if w["severity"] == "info"],
            "exit_code": code,
        }
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[json] {args.json}")

    return _exit_code(errors, warns)


if __name__ == "__main__":
    sys.exit(main())
