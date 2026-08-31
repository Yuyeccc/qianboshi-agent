#!/usr/bin/env python3
"""盘前简报产物自动校验（pro/flash 直出后必跑）。

校验项：
1. 8章完整性（## 1. ~ ## 8.）
2. 证据链幻觉占位符（"view_id: bullish items" 等键名被当view_id）
3. 决策ID格式（dec_YYYY-MM-DD_ASSET_001）
4. 字数预算（模板要求1200-1800字；>2500 警告）
5. 价格口径标注（"实时/净值推算/缓存/N/A"至少出现）
6. 禁用来源（主力行为学/汤山老王/马跑跑/邻居大爷/八叔不啰嗦）

用法：
    C:\\Python314\\python.exe scripts/brief_post_check.py <简报md路径>
退出码：0=通过 / 1=有🔴 / 2=有🟡
"""
import re
import sys
from pathlib import Path

BANNED = ["主力行为学", "汤山老王", "马跑跑", "邻居大爷", "八叔不啰嗦"]
PHANTOM_PATTERNS = [
    r"view_id:\s*bullish\s*items",
    r"view_id:\s*bearish\s*items",
    r"view_id:\s*[a-zA-Z]+\s*items",
    r"view_id:\s*[\w-]{4,}\s+items",
]
DECISION_ID_RE = re.compile(r"dec_\d{4}-\d{2}-\d{2}_[A-Z_]+_\d{3}")


def check(path: str) -> tuple[int, list[str], list[str]]:
    text = Path(path).read_text(encoding="utf-8")
    errors: list[str] = []
    warns: list[str] = []

    # 1. 8章完整性
    sections = re.findall(r"^## (\d)\.", text, re.M)
    missing = [str(i) for i in range(1, 9) if str(i) not in sections]
    if missing:
        errors.append(f"🔴 缺章节: {missing}（现有: {sections}）")

    # 2. 幻觉占位符
    for pat in PHANTOM_PATTERNS:
        for m in re.finditer(pat, text):
            errors.append(f"🔴 幻觉占位符: '{m.group(0)}'")
            break  # 每类报一次

    # 3. 决策ID格式（抽查：出现的 dec_ 必须合法）
    for m in re.finditer(r"dec_[A-Za-z0-9_\-]+", text):
        token = m.group(0)
        if not DECISION_ID_RE.match(token):
            errors.append(f"🔴 决策ID格式异常: {token}")

    # 4. 字数（中文字；2026-08-06 用户确认日报 2500字左右可接受，阈值放宽）
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cn_chars > 3000:
        errors.append(f"🔴 过长: {cn_chars} 中文字（用户接受上限约2500-3000）")
    elif cn_chars > 1800:
        warns.append(f"🟡 偏长: {cn_chars} 中文字（模板目标1200-1800，用户接受至~2500）")
    elif cn_chars < 800:
        warns.append(f"🟡 偏短: {cn_chars} 中文字")

    # 5. 价格口径标注
    if not re.search(r"实时|净值推算|缓存|昨收|N/A", text):
        warns.append("🟡 未见价格口径标注（实时/净值推算/缓存/N/A）")

    # 6. 禁用来源
    for b in BANNED:
        if b in text:
            errors.append(f"🔴 引用禁用来源: {b}")

    # 7. 总览4要素
    for kw in ["主线", "分歧", "盯盘", "决策台"]:
        if kw not in text[:600]:
            warns.append(f"🟡 今日总览缺'{kw}'要素")

    return 0 if not errors else (1 if errors else 2), errors, warns


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    code, errors, warns = check(sys.argv[1])
    for e in errors:
        print(e)
    for w in warns:
        print(w)
    if not errors and not warns:
        print("✅ 全部通过")
    print(f"结论: {'🔴 需修复' if code == 1 else ('🟡 有警告' if code == 2 else '✅ 通过')}")
    sys.exit(code)
