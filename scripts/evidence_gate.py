#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evidence_gate.py — #13 无来源数字门禁（确定性，零LLM）

红线：无来源数字不进首屏重大结论。任何观点数字（百分比/金额/价格/倍数/点位）若
无法追溯到观点证据链（view_id/证据链/🔍原文/BV 锚点）或行情类上下文 → error 阻断。

判定规则（v1.1，老手实测修正）：
1. 只认"观点数字"：%／％/亿/万/倍/bps/含小数价格/点位
   排除：日期、时间戳、view_id 哈希、BV 号、6位代码、章节序号、标题行
2. 来源判定（任一满足即有来源）：
   a. 行内含 view_id= / 证据链 / source_file / BV号 / 🔍原文 / evidence-锚点
   b. 行位于「原文详情」锚点区
   c. 上下各 2 行内出现上述来源标记
   d. 行情/持仓类上下文（收盘/点位/涨跌幅/ETF/指数/美元/昨收/份额/净值/仓位等）
      → warning（行情快照是合法来源，v1 不核对行情库）
3. 无来源观点数字 → error；errors>0 exit 1（阻断上线）

用法：
  python scripts/evidence_gate.py <简报.md>
  python scripts/evidence_gate.py <简报.md> --json
"""
import argparse
import json
import re
import sys
from pathlib import Path

NUM_RE = re.compile(
    r"(?<![\dA-Za-z])(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?\s*"
    r"(?:%|％|亿|万|万亿|倍|bps)?"
    r"(?![0-9A-Za-z])"
)
# 中文数字/约数/区间（gpt 复审补漏：数十亿/近两成/五六百点/负号）
CN_NUM_RE = re.compile(
    r"(?<![0-9A-Za-z])"
    r"(?:[一二两三四五六七八九十百千万亿]+(?:成|％|%|亿|万|点|倍)"
    r"|数十?[亿万亿]|[数几]十|近[一二两三四五六七八九十百千万亿]+[成%％亿万点倍])"
    r"(?![0-9A-Za-z])"
)
NEG_NUM_RE = re.compile(r"(?<![0-9A-Za-z])-\d+(?:\.\d+)?\s*(?:%|％|亿|万|点|倍)?(?![0-9A-Za-z])")
# 日期 / 时间戳 / BV / view_id / 6位代码 / 行首序号
STRIP_PATTERNS = [
    re.compile(r"\b20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}\b"),
    re.compile(r"\d{1,2}:\d{2}(?::\d{2})?"),
    re.compile(r"\bBV[0-9A-Za-z]+\b"),
    re.compile(r"\b[0-9a-f]{16}\b"),
    re.compile(r"\b\d{6}\b"),
]
SOURCE_MARK_RE = re.compile(r"view_id|证据链|source_file|BV[0-9A-Za-z]+|🔍原文|evidence-")
# 行情/持仓强信号词（v1.1 修正：去掉裸 %/亿/倍 等数字单位词——
# 观点数字本身常带单位，不能当行情上下文；只认"数据来自行情快照"的强信号）
MARKET_WORDS = (
    "昨收|收盘|报收|缓存价|行情扫描|开盘价|收盘价|最新价|涨跌幅|"
    "成交额|成交量|换手率|净值|份额|仓位|持仓|ETF基金"
)
OPINION_NUM_RE = re.compile(r"%|％|亿|万|倍|bps|\.\d")


def extract_number_lines(md: str):
    """返回 [(行号, 原文, 观点数字列表)]。只认观点数字，滤掉日期/序号/代码/标题。"""
    hits = []
    for i, line in enumerate(md.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue  # 标题行
        if re.match(r"^\|?\s*\d+[.、)]", s):
            continue  # 章节序号行
        clean = s
        for pat in STRIP_PATTERNS:
            clean = pat.sub(" ", clean)
        nums = [m.group(0).strip() for m in NUM_RE.finditer(clean)]
        nums += [m.group(0).strip() for m in CN_NUM_RE.finditer(clean)]
        nums += [m.group(0).strip() for m in NEG_NUM_RE.finditer(clean)]
        if not nums:
            continue
        real = [n for n in nums if OPINION_NUM_RE.search(n) or re.search(r"[一二两三四五六七八九十百千万亿]|^-", n)]
        if not real:
            continue
        hits.append((i, s, real))
    return hits


def has_source(line: str, ctx_before: str, ctx_after: str) -> tuple[bool, str]:
    if SOURCE_MARK_RE.search(line):
        return True, "inline"
    if re.search(MARKET_WORDS, line):
        return True, "market"
    if SOURCE_MARK_RE.search(ctx_before + ctx_after):
        return True, "context"
    return False, "none"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("brief", help="简报 md 路径")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    p = Path(args.brief)
    if not p.exists():
        print(f"!! 文件不存在: {p}")
        return 2
    md = p.read_text(encoding="utf-8", errors="replace")
    lines = md.splitlines()

    errors, warnings, dubious = [], [], []
    for lineno, s, nums in extract_number_lines(md):
        ctx_b = "\n".join(lines[max(0, lineno - 3):lineno - 1])
        ctx_a = "\n".join(lines[lineno:lineno + 2])
        if "原文存疑" in s or "⚠️原文存疑" in s:
            # gpt 复审：hash_mismatch 数字已显式标存疑（不伪装已验证），warning 不阻断
            dubious.append((lineno, s, nums))
            continue
        ok, kind = has_source(s, ctx_b, ctx_a)
        if ok and kind == "market":
            warnings.append((lineno, s, nums, kind))
        elif not ok:
            errors.append((lineno, s, nums, kind))

    if args.json:
        print(json.dumps({
            "errors": [{"line": e[0], "text": e[1], "numbers": e[2]} for e in errors],
            "warnings": [{"line": w[0], "text": w[1], "numbers": w[2]} for w in warnings],
            "dubious": [{"line": d[0], "text": d[1], "numbers": d[2]} for d in dubious],
            "error_count": len(errors),
        }, ensure_ascii=False, indent=1))
    else:
        print(f"[evidence_gate] {p.name}: 无来源观点数字 errors={len(errors)} "
              f"行情/持仓类 warning={len(warnings)} 原文存疑={len(dubious)}")
        for lineno, s, nums, _ in errors:
            print(f"  ⚠️ L{lineno} {nums}: {s[:110]}")
        for lineno, s, nums, _ in warnings[:6]:
            print(f"  ~ L{lineno} [行情/持仓] {nums}: {s[:80]}")
        for lineno, s, nums in dubious[:6]:
            print(f"  ? L{lineno} [原文存疑] {nums}: {s[:80]}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
