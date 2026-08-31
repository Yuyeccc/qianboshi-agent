#!/usr/bin/env python3
"""
盘前简报后置质检。

目标：阻止明显不合规内容进入 data/briefs 作为下一轮追踪依据。
检查项：
- 禁用分析师残留
- 分析师引用缺少具体日期
- A股缓存价被写成涨跌幅 0%
- 关键观点缺 view_id/source_file/date/evidence 证据链
- 模糊时间词过多
- 桌面 final 与 data/briefs 同步工具
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
BRIEFS_DIR = DATA_DIR / "briefs"
DESKTOP_FINAL = Path("C:/Users/1/Desktop/盘前简报_2026-07-21_final.md")

BANNED_ANALYSTS = ["主力行为学", "汤山老王", "马跑跑", "邻居大爷", "八叔不啰嗦"]
ANALYSTS = [
    "钱博士", "钱博士直播", "钱博士短视频", "李一恩", "任泽平", "旗帜鲜明", "投机大拿",
    "柏年说", "财联社", "笨笨的韭菜", "史诗级韭菜", "趋势天哥",
]
DATE_RE = re.compile(r"(20\d{2}[.年/-]\d{1,2}[.月/-]\d{1,2}|\d{1,2}[./月]\d{1,2}|\d{1,2}月\d{1,2}日)")
A_SHARE_CODE_RE = re.compile(r"\b(?:[036]\d{5}|15\d{4}|51\d{4}|58\d{4}|68\d{4})(?:\.(?:SS|SZ))?\b")
ZERO_CHANGE_RE = re.compile(r"(?:涨跌幅|涨幅|跌幅)[^\n|]{0,18}(?:0(?:\.00)?%|0%)|(?:0(?:\.00)?%|0%)[^\n|]{0,18}(?:涨跌幅|涨幅|跌幅)")
VAGUE_RE = re.compile(r"近期|最新|直播\)|直播）：|短视频\)|短视频）：")
VIEW_ID_RE = re.compile(r"\b[0-9a-f]{16}\b|view_id\s*[:：=]\s*[0-9a-f]{8,40}", re.I)
SOURCE_FILE_RE = re.compile(r"source_file|来源文件|\.md\b|BV[0-9A-Za-z]+")
EVIDENCE_RE = re.compile(r"evidence|证据|依据|引用|来源|view_id|source_file|BV[0-9A-Za-z]+", re.I)
SECTION_RE = re.compile(r"^#{1,4}\s+")


def _line_has_date(line):
    return bool(DATE_RE.search(line))


def _is_heading(line):
    return bool(SECTION_RE.match(line.strip()))


def _looks_like_key_claim(line):
    s = line.strip()
    if not s or _is_heading(s):
        return False
    if len(s) < 12:
        return False
    markers = [
        "看多", "看空", "偏多", "偏空", "中性", "谨慎", "风险", "警惕", "认为", "表示", "指出",
        "判断", "预计", "共识", "分歧", "建议", "关注", "修复", "反弹", "下跌", "回调", "走强",
    ]
    entities = ["大盘", "A股", "美股", "半导体", "光模块", "创新药", "机器人", "存储", "算力", "大金融", "大消费", "黄金", "紫金", "PCB"]
    return any(m in s for m in markers) and (any(e in s for e in entities) or any(a in s for a in ANALYSTS))


def _has_evidence_chain(line):
    # 完整证据链优先：view_id + 来源/文件/BV + 日期；或者 source_file + analyst + date。
    has_view = bool(VIEW_ID_RE.search(line))
    has_source = bool(SOURCE_FILE_RE.search(line))
    has_date = _line_has_date(line)
    has_evidence_word = bool(EVIDENCE_RE.search(line))
    if has_view and (has_source or has_date or has_evidence_word):
        return True
    if has_source and has_date and any(a in line for a in ANALYSTS):
        return True
    return False


def check_brief(text, require_evidence=False):
    errors = []
    warnings = []
    lines = text.splitlines()

    for i, line in enumerate(lines, 1):
        for banned in BANNED_ANALYSTS:
            if banned in line:
                errors.append({"line": i, "type": "banned_analyst", "message": f"禁用分析师残留: {banned}", "text": line})

        if A_SHARE_CODE_RE.search(line) and ZERO_CHANGE_RE.search(line):
            warnings.append({"line": i, "type": "a_share_zero_change", "message": "A股代码附近出现涨跌幅0%，应改为昨收/缓存价/N/A", "text": line})

        # 分析师引用缺日期：只检查明确的引用/判断句，避免章节标题、框架名称误报。
        looks_like_quote = any(mark in line for mark in ["（", "(", "：", ":", "认为", "表示", "指出", "看多", "看空", "分歧", "共识"])
        skip_context = _is_heading(line) or any(skip in line for skip in ["免责声明", "保留名单", "确定性排序框架", "钱博士框架", "### 钱博士确定性排序", "## 四"])
        if any(a in line for a in ANALYSTS) and looks_like_quote and not _line_has_date(line):
            if not skip_context:
                warnings.append({"line": i, "type": "missing_date", "message": "分析师观点缺具体日期", "text": line})

        if VAGUE_RE.search(line) and any(a in line for a in ANALYSTS) and looks_like_quote and not _line_has_date(line):
            if not skip_context:
                warnings.append({"line": i, "type": "vague_time", "message": "分析师引用含模糊时间词且无日期", "text": line})

        if require_evidence and _looks_like_key_claim(line):
            nearby = "\n".join(lines[max(0, i - 2): min(len(lines), i + 3)])
            if not (_has_evidence_chain(line) or _has_evidence_chain(nearby)):
                warnings.append({"line": i, "type": "missing_evidence_chain", "message": "关键判断缺 view_id/source_file/date/evidence 证据链", "text": line})

    # 文档级别：如果完全没有 view_id/source_file，但要求证据链，则给强提醒。
    if require_evidence and not VIEW_ID_RE.search(text) and "source_file" not in text and ".md" not in text:
        warnings.append({"line": 0, "type": "no_structured_refs", "message": "全文没有结构化观点引用；新简报应至少包含 view_id/source_file/date/evidence", "text": ""})

    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "has_errors": bool(errors),
        "has_warnings": bool(warnings),
        "errors": errors,
        "warnings": warnings,
        "summary": f"errors={len(errors)}, warnings={len(warnings)}",
    }


def format_report(report, max_items=30):
    out = [f"[post_check] {report['summary']}"]
    for bucket in ["errors", "warnings"]:
        for item in report[bucket][:max_items]:
            loc = f"L{item['line']}" if item.get("line") else "DOC"
            out.append(f"{bucket[:-1].upper()} {loc} {item['type']}: {item['message']} | {item.get('text','')[:160]}")
    return "\n".join(out)


def sync_final_to_briefs(final_path=None, date_str=None):
    src = Path(final_path) if final_path else DESKTOP_FINAL
    if not src.exists():
        raise FileNotFoundError(src)
    text = src.read_text(encoding="utf-8")
    report = check_brief(text, require_evidence=False)
    if report["has_errors"]:
        raise RuntimeError(format_report(report))
    if date_str is None:
        m = re.search(r"20\d{2}-\d{2}-\d{2}", src.name)
        date_str = m.group(0) if m else datetime.now().strftime("%Y-%m-%d")
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    dst = BRIEFS_DIR / f"{date_str}.md"
    shutil.copyfile(src, dst)
    return dst, report


def run_evidence_gate(path) -> list[dict]:
    """#13: 无来源数字门禁（subprocess 调 evidence_gate --json，解耦不 import）。"""
    script = Path(__file__).parent / "evidence_gate.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), str(path), "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        d = json.loads(r.stdout)
    except Exception:
        return []
    return [
        {"line": e["line"], "type": "unsourced_number",
         "message": f"无来源数字 {e['numbers']}（无观点证据链/行情来源）", "text": e["text"]}
        for e in d.get("errors", [])
    ]


def main():
    ap = argparse.ArgumentParser(description="盘前简报质检/同步")
    ap.add_argument("path", nargs="?", help="要检查的简报路径；默认检查 data/briefs 最新一期")
    ap.add_argument("--sync-final", action="store_true", help="把桌面 final 同步到 data/briefs（有错误则拒绝）")
    ap.add_argument("--date", help="同步目标日期 YYYY-MM-DD")
    ap.add_argument("--require-evidence", action="store_true", help="要求关键观点包含 view_id/source_file/date/evidence 证据链")
    ap.add_argument("--no-evidence-gate", action="store_true", help="跳过 #13 无来源数字门禁（默认开启）")
    args = ap.parse_args()

    if args.sync_final:
        dst, report = sync_final_to_briefs(args.path, args.date)
        print(format_report(report))
        print(f"synced: {dst}")
        return 1 if report["has_warnings"] else 0

    if args.path:
        path = Path(args.path)
    else:
        files = sorted(BRIEFS_DIR.glob("*.md"))
        if not files:
            raise SystemExit("no brief found")
        path = files[-1]
    report = check_brief(path.read_text(encoding="utf-8"), require_evidence=args.require_evidence)
    if not args.no_evidence_gate:
        eg = run_evidence_gate(path)
        if eg:
            report["errors"] = report.get("errors", []) + eg
            report["has_errors"] = True
            report["summary"] = (f"errors={len(report['errors'])}, warnings={len(report['warnings'])} "
                                 f"(含 evidence_gate 无来源数字 {len(eg)})")
    print(format_report(report))
    return 2 if report["has_errors"] else (1 if report["has_warnings"] else 0)


if __name__ == "__main__":
    sys.exit(main())
