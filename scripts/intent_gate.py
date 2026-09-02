# -*- coding: utf-8 -*-
"""
intent_gate.py —— 后端意图分诊（研究提交的第二道闸，fail-closed）

前端 agentScreening.ts 是第一道快筛（P0，体验层）；
本模块是后端安全边界（P1），不信任前端，对用户提交的研究目标做确定性分类。

设计原则（fail-closed）：
  - 命中强违禁模式 → block（合规红线，不给 LLM）
  - 命中闲聊/范围外 → block（礼貌引导回投研类目）
  - 有分析意图但缺实体/时间 → clarify（引导补充）
  - 规则无法覆盖的模糊输入 → clarify（宁可多问一次，不误放行）

规则与 frontend/src/utils/agentScreening.ts 保持 1:1 同步（2026-09-03 移植）；
RULE_VERSION 用于前后端规则漂移对账。

CLI:  python intent_gate.py "问题文本"
输出:  JSON {verdict, reason, category/suggested_category, rule_version}
"""
from __future__ import annotations

import re
import sys

RULE_VERSION = "20260903-1"

# ---- 强违禁模式：直接给操作指令/要求买卖仓位目标价 —— 合规红线，一律拦截 ----
HARD_BLOCK_PATTERNS: list[re.Pattern] = [
    re.compile(r"(现在|可以|应该|能不能|帮我|带我|推荐|建议).{0,6}(买入|买进|买点|建仓|加仓|满仓|梭哈|抄底|上车)"),
    re.compile(r"(现在|可以|应该|能不能|帮我|带我|推荐|建议).{0,6}(卖出|卖点|清仓|减仓|割肉|下车|止盈)"),
    re.compile(r"(该|要不要|能不能|可以|帮我|建议).{0,6}(买|卖|加|减).{0,4}(多少|几成|仓位|份额|股)"),
    re.compile(r"目标价|止盈价|止损价设|仓位(加到|减到|多少|比例)"),
    re.compile(r"(买|卖|加仓|清仓).{0,8}(哪个|什么股|什么板块|哪只|哪支)"),
    re.compile(r"(推荐|带(我|我们)|带我).{0,8}(买|卖|股票|基金|etf)"),
    re.compile(r"保证.{0,6}(涨|赚|收益)|稳赚|必涨|内幕|明天(会|必|一定)"),
    re.compile(r"帮我(操作|下单|交易|挂单|买入|卖出)"),
]

# ---- 闲聊/范围外：问候、非投研话题 ----
OFFTOPIC_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(你好|您好|hi|hello|hey|在吗|早上好|晚上好|下午好|哈喽|嗨)[!！。~\\s]*$", re.I),
    re.compile(r"(讲个笑话|写首诗|写代码|翻译一下|你是谁|你叫什么|你会什么|你能做什么)$"),
    re.compile(r"(今天天气|帮我(点外卖|订机票|找房子))|(游戏|追星|娱乐八卦)"),
]

# ---- 明确投资研究意图的指示词（配合实体判断用） ----
RESEARCH_HINTS = [
    "怎么看", "怎么样", "如何", "最近", "走势", "复盘", "推演", "情景",
    "观点", "逻辑", "驱动", "风险", "情绪", "热度", "涨停", "板块", "仓位触发",
    "触发", "规则", "盈亏", "多空", "共识", "分歧", "分析", "影响", "展望",
    "信号", "异动", "轮动", "催化",
]

# ---- 买卖建议的弱信号（出现在查询自身规则/持仓场景时不算违规，仅提示） ----
WEAK_ADVICE_HINTS = ["止损", "止盈", "风险", "回调", "追高", "支撑", "压力"]

# ---- 常见实体前缀，帮助识别"有没有具体对象" ----
ENTITY_HINTS = [
    "黄金", "白银", "铜", "铝", "原油", "地产", "房地产", "半导体", "芯片", "光模块",
    "光通信", "机器人", "创新药", "医药", "医疗", "白酒", "消费", "新能源", "锂电",
    "电池", "光伏", "储能", "军工", "券商", "银行", "保险", "煤炭", "有色", "钢铁",
    "化工", "汽车", "整车", "智能驾驶", "AI", "人工智能", "算力", "游戏", "传媒",
    "纳指", "标普", "道指", "上证", "深证", "创业板", "恒生", "港股", "美股", "A股",
    "ETF", "板块", "大盘", "指数", "美联储", "降息", "加息", "CPI", "非农", "政策",
    "会议", "财报", "业绩", "减持", "增持", "重组", "PCB", "覆铜板", "存储", "面板",
    "核电", "电力", "航运", "猪肉", "农业", "地产链", "基建", "中字头", "科技",
    "半导体设备", "先进封装", "液冷", "电源", "铜缆", "交换机", "HBM", "PCB",
]

STRIP_RE = re.compile(r"[，。！？、,.!?;；:：\"\"''「」()（）\s]")


def normalize(q: str) -> str:
    return STRIP_RE.sub("", q).lower()


def match_pattern(text: str, patterns: list[re.Pattern]) -> str | None:
    for p in patterns:
        m = p.search(text)
        if m:
            return m.group(0)
    return None


def has_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def suggest_category(norm: str) -> str | None:
    if re.search(r"(涨停|连板|情绪|热度|最热|龙虎榜|题材|异动)", norm):
        return "heat"
    if re.search(r"(复盘|推演|情景|政策|会议|降息|加息|如果|落地)", norm):
        return "scenario"
    if re.search(r"(持仓|盈亏|触发|规则|止损|止盈|我的)", norm):
        return "position"
    if re.search(r"(钱博士|李一恩|旗帜|任泽平|柏年|天哥|分析师|观点|直播|最新)", norm):
        return "views"
    return "sector"


def classify_question(raw: str) -> dict:
    """与前端 classifyQuestion 保持同逻辑；返回 dict 而非对象便于跨进程 JSON。"""
    q = raw.strip()
    if len(q) == 0:
        return {"verdict": "clarify", "reason": "empty", "rule_version": RULE_VERSION}
    if len(q) > 500:
        return {"verdict": "block", "reason": "too_long", "rule_version": RULE_VERSION}
    text = q.lower()
    norm = normalize(text)

    # 1) 强违禁：合规红线
    hard = match_pattern(text, HARD_BLOCK_PATTERNS)
    if hard:
        return {
            "verdict": "block",
            "reason": "hard_advice",
            "category": "compliance",
            "matched": hard,
            "rule_version": RULE_VERSION,
        }

    # 2) 闲聊 / 范围外
    if any(p.search(text) for p in OFFTOPIC_PATTERNS):
        return {"verdict": "block", "reason": "offtopic", "rule_version": RULE_VERSION}

    # 3) 明显投研意图 + 有实体 → pass
    has_entity = has_any(norm, ENTITY_HINTS)
    has_intent = has_any(norm, RESEARCH_HINTS)
    if has_entity and has_intent:
        return {
            "verdict": "pass",
            "reason": "research_ok",
            "suggested_category": suggest_category(norm),
            "rule_version": RULE_VERSION,
        }

    # 4) 弱信号（含止损止盈等词，但无操作指令）→ 放行给 Agent 做查询/提示
    if has_any(norm, WEAK_ADVICE_HINTS) and has_entity:
        return {
            "verdict": "pass",
            "reason": "research_weak",
            "suggested_category": "position",
            "rule_version": RULE_VERSION,
        }

    # 5) 有实体但意图不清 → clarify
    if has_entity:
        return {
            "verdict": "clarify",
            "reason": "no_intent",
            "category": suggest_category(norm),
            "rule_version": RULE_VERSION,
        }

    # 6) 有意图但无实体 → clarify
    if has_intent:
        return {"verdict": "clarify", "reason": "no_entity", "rule_version": RULE_VERSION}

    # 7) 兜底：无法识别 → clarify（fail-closed，不误放行）
    return {"verdict": "clarify", "reason": "unrecognized", "rule_version": RULE_VERSION}


if __name__ == "__main__":
    import json

    args = sys.argv[1:]
    if not args:
        print("usage: python intent_gate.py \"问题文本\"", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(classify_question(" ".join(args)), ensure_ascii=False))
