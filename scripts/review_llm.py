"""A股决策复盘教训提炼模块。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import get_llm_config, load_config
from llm_fallback import call_analysis_llm


LESSON_PROMPT_VERSION = "v2-20260827"

LESSON_SYSTEM = """你是严谨的投研复盘员。
铁律：
1. 只允许引用证据包中出现的字段和数字，严禁出现市场原因、新闻、政策或任何证据包外信息。
2. 无法从证据确认的原因必须写为 unknown。
3. 不得将相关性表述为因果关系。
4. 不得虚构“当时可知信息”。
5. 每条结论必须能够追溯到证据包中的具体字段或数字。"""


def build_evidence(decision: dict, review_row: dict) -> dict:
    """构造仅包含决策原文和实际复盘数字的紧凑证据包。"""
    decision_fields = (
        "thesis",
        "key_reasons",
        "invalidation_conditions",
        "horizon",
        "direction",
        "conviction",
        "action_note",
    )
    review_fields = (
        "outcome_return",
        "benchmark_return",
        "excess_return",
        "result_label",
        "result_grade",
        "p0",
        "p1",
        "p0_date",
        "p1_date",
    )
    evidence: dict = {}
    for field in decision_fields:
        if field in decision:
            evidence[field] = decision[field]
    for field in review_fields:
        if field in review_row:
            evidence[field] = review_row[field]
    return evidence


def build_user_prompt(evidence: dict) -> str:
    """生成要求严格 JSON 输出的用户消息。"""
    evidence_json = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    return f"""证据包：
{evidence_json}

仅基于以上证据包输出严格 JSON，不要输出 Markdown、解释或额外字段：
{{"what_went_right":["字符串"],"what_went_wrong":["字符串"],"missed_factors":["字符串"],"new_rule_learned":"字符串"}}

要求：
- 每个数组包含 0 到 3 条；证据不足时宁缺毋滥。
- 结论只能引用证据包中的字段、原文和数字。
- 无法确认的原因写 unknown。
- new_rule_learned 必须是一条包含“适用条件 + 动作”的具体规则句式，禁止“加强研究”“保持谨慎”等空话。"""


def validate_lesson(data: dict) -> bool:
    """检查 LLM 输出的基本结构与最低质量要求。"""
    required_keys = {
        "what_went_right",
        "what_went_wrong",
        "missed_factors",
        "new_rule_learned",
    }
    if not isinstance(data, dict) or set(data) != required_keys:
        return False

    for field in ("what_went_right", "what_went_wrong", "missed_factors"):
        value = data[field]
        if (
            not isinstance(value, list)
            or len(value) > 3
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            return False

    new_rule = data["new_rule_learned"]
    if (
        not isinstance(new_rule, str)
        or not new_rule.strip()
        or new_rule.strip().lower() == "unknown"
    ):
        return False

    subjective_words = ("可能", "也许", "感觉")
    return not any(
        word in item
        for item in data["missed_factors"]
        for word in subjective_words
    )


def _parse_json_content(content: str) -> dict | None:
    """解析普通 JSON、Markdown 围栏 JSON 或文本中的首个对象。"""
    text = content.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].strip()

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _validation_error(data: dict | None) -> str:
    """生成用于重试的简短格式修正提示。"""
    if not isinstance(data, dict):
        return "输出不是可解析的 JSON 对象"
    required = {
        "what_went_right",
        "what_went_wrong",
        "missed_factors",
        "new_rule_learned",
    }
    missing = required - set(data)
    extra = set(data) - required
    details: list[str] = []
    if missing:
        details.append("缺少键: " + ", ".join(sorted(missing)))
    if extra:
        details.append("存在额外键: " + ", ".join(sorted(extra)))
    if not details:
        details.append("字段类型、数组条数、主观词或 new_rule_learned 内容不符合要求")
    return "；".join(details)


def generate_lessons(
    decision: dict,
    review_row: dict,
    llm_config: dict,
) -> dict:
    """调用 LLM 提炼教训；任何失败均转换为可处理的失败结果。"""
    evidence = build_evidence(decision, review_row)
    prompt = build_user_prompt(evidence)
    last_error = "未知错误"

    for attempt in range(2):
        current_prompt = prompt
        if attempt == 1:
            current_prompt += (
                "\n\n你上次的输出不符合格式。请严格修正："
                + last_error
            )
        try:
            content, used_model = call_analysis_llm(
                llm_config,
                [
                    {"role": "system", "content": LESSON_SYSTEM},
                    {"role": "user", "content": current_prompt},
                ],
                temperature=0.2,
                max_tokens=1200,
                json_mode=True,
            )
            parsed = _parse_json_content(content)
            if parsed is not None and validate_lesson(parsed):
                return {
                    "lessons": parsed,
                    "model": used_model,
                    "prompt_version": LESSON_PROMPT_VERSION,
                    "status": "ok",
                }
            last_error = _validation_error(parsed)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            # 网络/服务抖动（超时、5xx）退避20s再试第二次
            if attempt == 0:
                import time as _time
                _time.sleep(20)

    return {
        "lessons": None,
        "status": "failed",
        "error": last_error,
    }


if __name__ == "__main__":
    sample_decision = {
        "thesis": "盈利改善将支撑股价",
        "key_reasons": '["季度营收增长","估值处于历史低位"]',
        "invalidation_conditions": "营收增速低于预期",
        "horizon": "medium",
        "direction": "bullish",
        "conviction": 0.8,
        "action_note": "分批买入",
    }
    sample_review = {
        "outcome_return": -4.25,
        "benchmark_return": -1.1,
        "excess_return": -3.15,
        "result_label": "wrong",
        "result_grade": "strong_wrong",
        "p0": 12.5,
        "p1": 11.97,
        "p0_date": "2026-08-01",
        "p1_date": "2026-08-21",
    }
    evidence = build_evidence(sample_decision, sample_review)
    prompt = build_user_prompt(evidence)
    valid_example = {
        "what_went_right": [],
        "what_went_wrong": ["outcome_return 为 -4.25，bullish 判断对应 result_label 为 wrong。"],
        "missed_factors": ["unknown"],
        "new_rule_learned": "当 conviction >= 0.7 且设定 bullish 判断时，若出现失效条件则执行复核仓位。",
    }
    invalid_example = {
        "what_went_right": "不是数组",
        "what_went_wrong": [],
        "missed_factors": [],
        "new_rule_learned": "",
    }

    print("prompt_length", len(prompt))
    print("validate_positive", validate_lesson(valid_example))
    print("validate_negative", validate_lesson(invalid_example))
