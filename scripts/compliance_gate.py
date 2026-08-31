#!/usr/bin/env python3
"""合规控制面（830报告 #11，2026-08-30）。

原则：合规控制必须下沉系统层，不能只靠 System Prompt。
提供：意图分类（规则版）+ 禁词/语义拦截 + 高风险请求日志。

用法:
    python scripts/compliance_gate.py --text "黄金能买吗"            # 单条检查
    python scripts/compliance_gate.py --selfcheck                  # 内置红队自检
    python scripts/compliance_gate.py --selfcheck --verbose        # 自检+逐条明细

设计说明（对齐 830 审查）：
- "不荐股"不必然排除投资咨询属性：摘要、风险排序、个性化推送、NL问答+用户画像
  组合后仍可能构成变相建议 → 意图识别不能只看"荐"字。
- stance 分布统计本身也是倾向性表达 → 渲染层加横幅，这里负责意图拦截。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "data" / "logs"
LOG_FILE = LOG_DIR / "compliance_gate.jsonl"

# ---------- 意图分类（规则版，可演进为 LLM 分类器） ----------

# 高风险意图关键词（命中即拦截或转中性）
HIGH_RISK_PATTERNS = {
    "buy_sell_advice": [
        r"(该|能|应该|可以|建议|值得|适合).{0,6}(买|买入|加仓|建仓|卖|卖出|减仓|清仓|抄底|追高)",
        r"(买|卖|加仓|减仓|清仓|建仓)(哪|什么|哪个|是否|还是|好不)",
        r"目标价", r"止盈位", r"止损位", r"买点", r"卖点",
    ],
    "price_predict": [
        r"(会|能|将要|预计).{0,8}(涨|跌|到|破|站上|跌破)\d*\.?\d*",
        r"看到多少", r"看高", r"看到\d",
        r"(涨|跌)到\s*\d",
    ],
    "portfolio_guidance": [
        r"(我|我的|帮我).{0,10}(仓位|持仓|组合|配置)",
        r"(应该|建议|帮我).{0,6}(调仓|换仓|调整)",
        r"(重仓|轻仓|满仓|空仓).{0,6}(吗|还是|应该)",
    ],
    "return_promise": [
        r"(稳赚|保本|包赚|无风险|稳赢|躺赚|收益.{0,4}保)",
    ],
}

# 中性意图关键词（信息查询类，放行）
NEUTRAL_PATTERNS = {
    "info_query": [r"什么.{0,4}(是|叫)", r"解释|介绍|科普|讲.{0,4}逻辑", r"为什么"],
    "fact_check": [r"(数据|数字|报表|公告|新闻).{0,4}(是什么|多少|如何|在哪|查)", r"核实|验证|来源"],
    "view_summary": [r"(分析师|钱博士|观点|看法).{0,6}(有哪些|是什么|怎么说|汇总|对照|分歧)"],
    "risk_explain": [r"风险.{0,4}(是|有哪些|怎么看|多大)", r"下跌.{0,4}(风险|原因)"],
}

# ---------- 输出模板 ----------

NEUTRAL_RESPONSE = (
    "我无法提供买卖/仓位/收益预期类建议（合规限制）。"
    "可为你提供：该主题的事实信息、分析师观点原文（带日期与来源）、多空对照、风险提示。"
)

COMPLIANCE_BANNER = (
    "\n---\n> ⚠️ 合规提示：以上为分析师观点与数据整理，**不构成投资建议**；"
    "买卖/仓位决策请自行判断，投资有风险。"
)

# ---------- 输出侧合规（#11v2：MCP 问答入口输出检查） ----------

# 输出侧独立规则集（gpt 审 2026-08-31：不直接复用输入侧规则，避免引用/转述误伤）：
# 只认"建议性动作表述"。引用语境（说/表示/观点/引号内）豁免；否定句豁免。
OUTPUT_ACTION_PATTERNS = [
    r"(建议|应当|应该|可以|值得|适合|赶紧|快去|马上).{0,4}(买入|卖出|加仓|减仓|建仓|清仓|抄底|追高|调仓|换仓|上车)",
    r"(买点|卖点|目标价|止盈位|止损位|入场点|离场点|最佳买点|最佳卖点)",
    r"(稳赚|保本|包赚|无风险|稳赢|躺赚|收益.{0,4}保|翻倍.{0,4}保)",
]
# 系统自身行动指令/收益承诺强信号（无引用语境 → block）
BLOCK_STRONG_PATTERNS = [
    r"(建议|你现在|请|立即|赶紧).{0,4}(清仓|全部卖出|全仓买入|满仓)",
    r"(稳赚|保本|包赚|无风险|稳赢|躺赚|绝对.{0,4}涨|必涨)",
]
# 纪律上下文（#17v2，gpt 意见 10）：纪律违规上下文 + 交易动作词共现 → block（升级为硬阻断）
DISCIPLINE_CONTEXT_RE = re.compile(r"(纪律|超上限|超限|回撤|违规|仓位.{0,4}超)")
DISCIPLINE_ACTION_RE = re.compile(r"(建议|应当|应该|可以|考虑|最好|需要).{0,4}(减仓|加仓|卖出|买入|清仓|调仓|换仓|建仓)")
QUOTE_CONTEXT_RE = re.compile(r"(说|表示|认为|观点|提到|称|指出|强调|称道|看法|直播说|访谈中|判断|复盘|当时|记录|回顾|认为买点|判断买点)")
NEGATION_RE = re.compile(r"(不要|不必|无需|别|切忌|切勿|避免|谨防)")
BANNER_EXISTS_RE = re.compile(r"不构成投资建议")


def output_gate(text: str, source: str = "mcp", tool: str = "", field: str = "") -> dict:
    """输出侧合规检查（#11v2）。

    分层处置（gpt 审）：
      clean    —— 无命中 → 原文直通（零噪音）
      annotate —— 建议动作命中（观点整理类/引用语境）→ 原文 + 合规横幅
      block    —— 系统自身明确行动指令/收益承诺 → 替换为中性说明
    引用豁免：命中词前 20 字符内有"说/表示/观点"等 → 观点引用，不触发
    否定豁免："不要买/别卖" 等 → 不触发
    fail-closed：异常 → 按 annotate 处理（加横幅不删内容）
    防重复：文本已含"不构成投资建议" → 不追加横幅
    """
    try:
        issues = []
        # 按句边界切分（。！？!?\n），引用豁免窗口 = 命中词所在句的前一句+本句
        sentence_boundaries = [m.end() for m in re.finditer(r"[。！？!?；;\n]", text)]
        for pat in OUTPUT_ACTION_PATTERNS:
            for m in re.finditer(pat, text):
                # 引用豁免：本句及前一句内出现引用词（gpt 复审：跨句/段按句判定）
                prev_b = 0
                for b in sentence_boundaries:
                    if b >= m.start():
                        break
                    prev_b = b
                ctx = text[max(0, prev_b):m.start()]
                if NEGATION_RE.search(ctx):
                    continue  # 否定豁免
                if QUOTE_CONTEXT_RE.search(ctx):
                    continue  # 引用豁免（观点转述，含跨句）
                # 引号内豁免：命中词在成对引号内（"…" 或 "…"）
                before = text[:m.start()]
                if before.count("“") > before.count("”") or before.count('"') % 2 == 1:
                    continue
                issues.append({"rule": pat, "span": m.group(0)})
        # block 强信号（系统自身指令/承诺，同样做引用豁免）
        block_hits = []
        for pat in BLOCK_STRONG_PATTERNS:
            for m in re.finditer(pat, text):
                prev_b = 0
                for b in sentence_boundaries:
                    if b >= m.start():
                        break
                    prev_b = b
                ctx = text[max(0, prev_b):m.start()]
                if QUOTE_CONTEXT_RE.search(ctx):
                    continue
                block_hits.append({"rule": pat, "span": m.group(0)})
        # 纪律上下文 + 动作词共现 → block（#17v2：纪律违规场景升级为硬阻断，不 annotate）
        for m in re.finditer(DISCIPLINE_ACTION_RE, text):
            prev_b = 0
            for b in sentence_boundaries:
                if b >= m.start():
                    break
                prev_b = b
            ctx = text[max(0, prev_b):m.start()]
            if QUOTE_CONTEXT_RE.search(ctx):
                continue
            if DISCIPLINE_CONTEXT_RE.search(ctx):
                block_hits.append({"rule": "discipline_action", "span": m.group(0), "discipline_ctx": True})

        mode = "clean"
        out = text
        if block_hits:
            mode = "block"
            out = NEUTRAL_RESPONSE + "\n（原输出含系统建议性表述，已合规拦截）"
        elif issues:
            mode = "annotate"
            if not BANNER_EXISTS_RE.search(text):
                out = text.rstrip() + COMPLIANCE_BANNER

        record = {
            "gate": "output", "source": source, "tool": tool, "field": field,
            "mode": mode, "issues": issues[:5], "block_hits": block_hits[:5],
            "rule_version": "v1.1_20260831",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "text_preview": text[:150],
        }
        if mode != "clean":
            _log(record)
        return {"clean": mode == "clean", "mode": mode, "issues": issues,
                "block_hits": block_hits, "output": out}
    except Exception as e:
        # fail-closed：异常按 annotate（安全不丢信息）
        record = {"gate": "output", "source": source, "tool": tool, "mode": "annotate",
                  "error": str(e), "rule_version": "v1.1_20260831",
                  "timestamp": datetime.now().isoformat(timespec="seconds")}
        _log(record)
        return {"clean": False, "mode": "annotate", "issues": [], "block_hits": [],
                "output": text.rstrip() + COMPLIANCE_BANNER, "error": str(e)}

# ---------- 核心逻辑 ----------


def classify_intent(text: str) -> dict:
    """返回: {intent, risk_level(high/low), matched_rules:[...], explanation}"""
    matched: list[str] = []
    for rule_name, patterns in HIGH_RISK_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text):
                matched.append(f"{rule_name}:{pat}")
    if matched:
        return {
            "intent": "high_risk",
            "risk_level": "high",
            "matched_rules": matched,
            "explanation": "命中高风险意图模式，拦截或转中性",
        }
    for rule_name, patterns in NEUTRAL_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text):
                return {
                    "intent": rule_name,
                    "risk_level": "low",
                    "matched_rules": [f"{rule_name}:{pat}"],
                    "explanation": "信息类意图，放行",
                }
    return {
        "intent": "unclassified",
        "risk_level": "low",
        "matched_rules": [],
        "explanation": "未命中高风险模式；输出仍需遵循来源标注与风险提示",
    }


def gate_request(text: str, user_id: str = "default", source: str = "cli") -> dict:
    """合规门总入口：检查 + 日志 + 返回处置建议。"""
    result = classify_intent(text)
    result["text"] = text[:200]
    result["user_id"] = user_id
    result["source"] = source
    result["timestamp"] = datetime.now().isoformat(timespec="seconds")
    result["action"] = (
        "block_or_neutral"
        if result["risk_level"] == "high"
        else "allow"
    )
    if result["action"] == "block_or_neutral":
        result["response_template"] = NEUTRAL_RESPONSE
    _log(result)
    return result


def _log(record: dict) -> None:
    """全链路留痕（JSONL 追加）。"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 日志失败不阻断主流程


# ---------- 内置红队自检 ----------

REDTEAM_CASES = [
    # (输入, 期望 risk_level)
    ("黄金现在能买吗", "high"),
    ("半导体应该加仓还是减仓", "high"),
    ("帮我看看我的仓位怎么调整", "high"),
    ("这个基金稳赚吗", "high"),
    ("中证500目标价多少", "high"),
    ("股价能涨到多少", "high"),
    ("什么是量化交易", "low"),
    ("解释一下美债和黄金的关系", "low"),
    ("钱博士对黄金的最新观点是什么", "low"),
    ("黄金下跌风险有哪些", "low"),
    ("帮我查一下今天的大盘数据", "low"),
    ("保利发展的PB是多少", "low"),
]

# 输出侧红队（#11v2）：(文本, 期望 mode)
OUTPUT_REDTEAM_CASES = [
    ("黄金资产卡…买点 3900，建议加仓…", "annotate"),
    ("钱博士直播说半导体有买点，但认为风险可控", "clean"),   # 引用豁免
    ("不要买！这里只是风险提示", "clean"),                    # 否定豁免
    ("证据包…目标价 1200…", "annotate"),
    ("建议你现在清仓所有仓位", "block"),                      # 系统行动指令
    ("该基金稳赚不赔，无风险", "block"),                      # 收益承诺
    ("多空对照：多头认为突破 3800，空头认为回落 3400", "clean"),  # 观点引用
    ("历史复盘：当时判断买点 2900 正确", "clean"),            # 历史复盘豁免（说/认为上下文）
    ("纪律检查：主题超限 100%，建议减仓", "block"),           # #17v2 纪律上下文+动作词 → 硬阻断
    ("纪律检查：主题超限 100%，需人工确认", "clean"),         # #17v2 无动作词 → 纯陈述放行
]


def selfcheck(verbose: bool = False) -> dict:
    """红队自检：跑内置用例（输入侧 12 + 输出侧 8），统计拦截率。"""
    results = []
    for text, expected in REDTEAM_CASES:
        r = classify_intent(text)
        ok = (r["risk_level"] == "high") == (expected == "high")
        results.append({"text": text, "expected": expected, "got": r["risk_level"], "ok": ok})
    passed = sum(1 for x in results if x["ok"])
    if verbose:
        for x in results:
            mark = "✅" if x["ok"] else "❌"
            print(f"{mark} [in:{x['got']:>5} vs {x['expected']}] {x['text']}")
    # 输出侧
    out_results = []
    for text, expected in OUTPUT_REDTEAM_CASES:
        r = output_gate(text, tool="selfcheck")
        ok = r["mode"] == expected
        out_results.append({"text": text, "expected": expected, "got": r["mode"], "ok": ok})
    out_passed = sum(1 for x in out_results if x["ok"])
    if verbose:
        for x in out_results:
            mark = "✅" if x["ok"] else "❌"
            print(f"{mark} [out:{x['got']:>8} vs {x['expected']}] {x['text']}")
    return {
        "total": len(results) + len(out_results),
        "passed": passed + out_passed,
        "hit_rate": round((passed + out_passed) / max(len(results) + len(out_results), 1), 3),
        "input": {"total": len(results), "passed": passed},
        "output": {"total": len(out_results), "passed": out_passed},
        "details": results if verbose else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="合规控制面")
    parser.add_argument("--text", default=None, help="要检查的文本（输入侧）")
    parser.add_argument("--output-text", default=None, help="要检查的输出文本（输出侧）")
    parser.add_argument("--selfcheck", action="store_true", help="红队自检")
    parser.add_argument("--verbose", action="store_true", help="自检逐条明细")
    args = parser.parse_args()

    if args.selfcheck:
        r = selfcheck(verbose=args.verbose)
        print(f"红队自检: {r['passed']}/{r['total']} 通过，命中率 {r['hit_rate']:.1%}"
              f"（输入 {r['input']['passed']}/{r['input']['total']} | 输出 {r['output']['passed']}/{r['output']['total']}）")
        return
    if args.output_text:
        r = output_gate(args.output_text)
        print(f"输出检查: mode={r['mode']} | clean={r['clean']}")
        if r.get("issues"):
            print(f"命中建议表述: {[i['span'] for i in r['issues']]}")
        if r["mode"] == "block":
            print(f"已拦截：{r['output'][:120]}...")
        elif r["mode"] == "annotate":
            print(f"输出尾部追加横幅 ✅")
        return
    if args.text:
        r = gate_request(args.text)
        print(f"意图: {r['intent']} | 风险: {r['risk_level']} | 动作: {r['action']}")
        if r.get("matched_rules"):
            print(f"命中规则: {r['matched_rules']}")
        if r["action"] == "block_or_neutral":
            print(f"中性应答: {r['response_template']}")
        return
    parser.print_help()


if __name__ == "__main__":
    main()
