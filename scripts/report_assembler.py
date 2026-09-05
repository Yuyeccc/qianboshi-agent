#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report_assembler.py —— 日报审验结果装配器（审验-自补 ⑤，方案 C 第三步：缺漏透明交付）

定位：读 Reviewer 审验报告（33_reviewer 产物 JSON）+ 日报初稿 md → 把
审验结果透明写回日报正文，让日报自行携带"审验与数据缺漏"信息：

1. 头部三行（插在 `# 钱博士盘前简报｜...` 标题行之后）：
       > **审验状态**：通过（含 N 项非阻断缺漏）
       > **数据截止**：2026-09-04 22:00 Asia/Shanghai
       > **审验批次**：review_2026-09-04_xxxx
2. 文末 "## 审验与数据缺漏" 表（编号|类型|影响章节|缺失内容|已尝试动作|未补原因|影响等级）
3. 高危（blocker/high）缺漏所在章节标题下插入旁标行（引用块，飞书渲染可见）

语义：
- pass / pass_with_gaps → 装配并退出码 0（fail_open：缺漏透明交付，不阻塞）
- fail_closed → **不装配**日报，退出码 2（cron 转"生成失败待人工"通知，保留初稿与审验产物）
- 幂等：装配块由 HTML 注释锚（review-meta / review-gaps / review-annot）包裹，
  重复运行先剥离旧块再插，结果可重跑一致
- 只读消费审验产物，不调 LLM、不改审验报告

用法:
    C:/Python314/python.exe scripts/report_assembler.py --report data/briefs/日报_2026-09-04.md \
        --review data/reviews_reviewer/review_2026-09-04_67e12a50.json [--out <out.md>]

退出码：0=装配完成 / 2=输入错误或 fail_closed（日报未被装配）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

META_START = "<!-- review-meta:start -->"
META_END = "<!-- review-meta:end -->"
GAPS_START = "<!-- review-gaps:start -->"
GAPS_END = "<!-- review-gaps:end -->"
ANNOT_PREFIX = "> ⚠ 本章存在审验缺漏 ["
SECTION_RE = re.compile(r"^## (\d+)\.\s*(.*)$")
ANNOT_RE = re.compile(r"^> ⚠ 本章存在审验缺漏 \[.*$", re.M)

SEVERITY_CN = {"blocker": "阻断", "high": "高", "medium": "中", "low": "低", "info": "信息"}
DELIVERY_CN = {
    "transparent": "透明交付（已在正文披露）",
    "blocked": "阻断·待人工",
}
STATUS_CN = {"pass": "通过", "pass_with_gaps": "通过（含非阻断缺漏）", "fail_closed": "未通过（阻断）"}


def _read_text(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {p}")
    return p.read_text(encoding="utf-8-sig")


def load_review(path: str | Path) -> dict:
    """读审验报告 JSON；防御式校验必需字段（schema 已由 reviewer 校验，这里不重复引 jsonschema）。"""
    data = json.loads(_read_text(path))
    for key in ("review_run_id", "final_status", "findings", "unresolved_gaps", "timestamps"):
        if key not in data:
            raise ValueError(f"审验报告缺字段 {key}: {path}")
    if data["final_status"] not in ("pass", "pass_with_gaps", "fail_closed"):
        raise ValueError(f"final_status 非法: {data['final_status']}")
    return data


def _section_titles(text: str) -> dict[int, str]:
    """日报章节号 → 标题（用于表列显示与旁标定位）。"""
    out: dict[int, str] = {}
    for ln in text.splitlines():
        m = SECTION_RE.match(ln)
        if m:
            out[int(m.group(1))] = m.group(2).strip()
    return out


def _clean_cell(s: str, max_len: int = 150) -> str:
    """md 表单元格清洗：压缩空白、转义竖线、截断。"""
    s = re.sub(r"\s+", " ", str(s)).strip()
    s = s.replace("|", "\\|")
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def _fmt_cutoff(cutoff_at: str | None) -> str:
    """2026-09-04T22:00:00+08:00 → 2026-09-04 22:00 Asia/Shanghai"""
    if not cutoff_at:
        return "—"
    try:
        dt = datetime.fromisoformat(cutoff_at)
    except ValueError:
        return str(cutoff_at)
    return dt.strftime("%Y-%m-%d %H:%M") + " Asia/Shanghai"


def build_gap_rows(review: dict, titles: dict[int, str]) -> list[dict]:
    """缺漏表行：源 = unresolved_gaps[]（未修复缺漏清单），join findings 补 category/section/severity。
    status=repaired 的 finding 视为已修复，不进缺漏表。"""
    by_id = {f.get("finding_id"): f for f in review.get("findings", [])}
    rows = []
    for gap in review.get("unresolved_gaps", []):
        gid = gap.get("gap_id", "")
        finding = by_id.get(gid, {})
        if finding.get("status") == "repaired":
            continue
        sec = finding.get("section") or gap.get("section")
        sec_disp = "—"
        if sec:
            m = re.match(r"^## (\d+)$", str(sec))
            if m:
                n = int(m.group(1))
                sec_disp = f"§{n} {titles.get(n, '')}".rstrip()
            elif sec == "header":
                sec_disp = "报告头部"
            else:
                sec_disp = str(sec)
        sev = gap.get("severity") or finding.get("severity") or "medium"
        delivery = gap.get("delivery", "transparent")
        # 已尝试动作：本轮 dry-run 无 repairs；若审验产物带 repairs 则按 finding_id 关联
        actions = [
            r.get("action", "")
            for r in review.get("repairs", [])
            if r.get("finding_id") == gid
        ]
        rows.append({
            "gap_id": gid or "—",
            "category": finding.get("category") or "数据缺失",
            "section": sec_disp,
            "description": _clean_cell(gap.get("description", "")),
            "actions": "；".join(actions) if actions else "—",
            "delivery": DELIVERY_CN.get(delivery, delivery),
            "severity": SEVERITY_CN.get(sev, str(sev)),
            "raw_severity": sev,
        })
    return rows


def _meta_block(review: dict, n_gaps: int) -> str:
    status = review["final_status"]
    if status == "pass_with_gaps":
        status_cn = f"通过（含 {n_gaps} 项非阻断缺漏）"
    else:
        status_cn = STATUS_CN[status]
    cutoff = _fmt_cutoff(review.get("timestamps", {}).get("report_cutoff_at"))
    return "\n".join([
        META_START,
        f"> **审验状态**：{status_cn}",
        f"> **数据截止**：{cutoff}",
        f"> **审验批次**：{review.get('review_run_id', '—')}",
        META_END,
    ])


def _gaps_block(rows: list[dict]) -> str:
    if not rows:
        return ""
    head = ["| 编号 | 类型 | 影响章节 | 缺失内容 | 已尝试动作 | 未补原因 | 影响等级 |",
            "|---|---|---|---|---|---|---|"]
    body = [
        f"| {_clean_cell(r['gap_id'], 30)} | {_clean_cell(r['category'], 30)} | "
        f"{_clean_cell(r['section'], 40)} | {r['description']} | {_clean_cell(r['actions'], 40)} | "
        f"{_clean_cell(r['delivery'], 30)} | {_clean_cell(r['severity'], 10)} |"
        for r in rows
    ]
    return "\n".join([GAPS_START, "", "## 审验与数据缺漏", "", *head, *body, "", GAPS_END])


def _annot_lines(review: dict, titles: dict[int, str]) -> list[tuple[int, str]]:
    """高危（blocker/high）且可定位章节的缺漏 → (章节号, 旁标行)。同章节多 id 合并。"""
    per_sec: dict[int, list[str]] = {}
    for f in review.get("findings", []):
        if f.get("status") == "repaired":
            continue
        if f.get("severity") not in ("blocker", "high"):
            continue
        sec = f.get("section")
        m = re.match(r"^## (\d+)$", str(sec)) if sec else None
        if not m:
            continue
        n = int(m.group(1))
        if n not in titles:
            continue
        per_sec.setdefault(n, []).append(f.get("finding_id", "?"))
    out = []
    for n in sorted(per_sec):
        ids = ", ".join(per_sec[n])
        out.append((n, f"{ANNOT_PREFIX}{ids}]（详见文末「审验与数据缺漏」表）"))
    return out


def _strip_old(text: str) -> str:
    """剥离旧装配块：meta 锚块、gaps 锚块、章节旁标行。幂等关键。"""
    # meta 块（跨行）
    text = re.sub(rf"{re.escape(META_START)}.*?{re.escape(META_END)}", "", text, flags=re.S)
    # gaps 块（跨行）
    text = re.sub(rf"{re.escape(GAPS_START)}.*?{re.escape(GAPS_END)}", "", text, flags=re.S)
    # 旁标行
    text = ANNOT_RE.sub("", text)
    # 清残留空行（3+ 连续空行 → 2）
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def assemble(report_text: str, review: dict) -> str:
    """核心纯函数：剥离旧块 → 插头部三行 → 插章节旁标 → 末尾插缺漏表。"""
    text = _strip_old(report_text)
    titles = _section_titles(text)
    rows = build_gap_rows(review, titles)
    n_gaps = len(rows)

    # 1) 头部三行：插在 "# 钱博士盘前简报｜" 标题行后
    meta = _meta_block(review, n_gaps)
    h = re.search(r"^(# 钱博士盘前简报.*)$", text, re.M)
    if h:
        text = text[: h.end()] + "\n\n" + meta + "\n" + text[h.end():].lstrip("\n")
    else:
        text = meta + "\n\n" + text

    # 2) 高危章节旁标：插在对应 ## N. 标题行后（标题/旁标/正文各隔空行，保 MD 渲染）
    for n, line in _annot_lines(review, titles):
        pat = re.compile(rf"^(## {n}\..*)$", re.M)
        m = pat.search(text)
        if m:
            text = (text[: m.end()] + "\n\n" + line + "\n\n"
                    + text[m.end():].lstrip("\n"))

    # 3) 文末缺漏表
    gaps = _gaps_block(rows)
    if gaps:
        text = text.rstrip() + "\n\n" + gaps + "\n"

    return text


def main() -> int:
    ap = argparse.ArgumentParser(description="日报审验结果装配器（缺漏透明交付，⑤ 第三步）")
    ap.add_argument("--report", required=True, help="日报 md 路径（就地写回；--out 指定则写 out）")
    ap.add_argument("--review", required=True, help="审验报告 JSON 路径（33_reviewer 产物）")
    ap.add_argument("--out", default=None, help="输出路径（默认就地覆盖 --report）")
    args = ap.parse_args()

    try:
        report_text = _read_text(args.report)
        review = load_review(args.review)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"[错误] {e}")
        return 2

    if review["final_status"] == "fail_closed":
        print("[阻断] 审验 fail_closed——日报不装配，转人工处理（保留初稿与审验产物）")
        return 2

    out_text = assemble(report_text, review)
    out_path = Path(args.out) if args.out else Path(args.report)
    out_path.write_text(out_text, encoding="utf-8")
    n_rows = len(build_gap_rows(review, _section_titles(report_text)))
    print(f"[OK] 装配完成: {out_path} | final_status={review['final_status']} | 缺漏 {n_rows} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
