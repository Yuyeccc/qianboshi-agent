#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reviewer_agent.py —— 日报独立审验 Executor（方案 C，只读 dry-run v0.1）

定位：对日报初稿 + 输入快照做**独立审验**，输出 33_reviewer 协议 JSON 到
data/reviews_reviewer/。与 generator（agent.py --brief）职责分离：
- 本步（④，dry-run）只做**确定性审验**（注入完整性/章节覆盖/证据链存在性/
  禁用来源/时间窗），不改日报、不调 LLM、只读；
- LLM 语义审验（claim 矛盾/证据支持度/风险表达）、repairs、装配器为后续
  步（未批），代码已留 run_llm_review 接口与 active-repair 参数位。

产物目录独立 data/reviews_reviewer/（审验/审计域，非 research 研究产物，
装配器消费；与研究产物 data/research/ 不混）。

用法:
    C:/Python314/python.exe scripts/reviewer_agent.py --report data/briefs/日报_2026-09-04.md \
        --date 2026-09-04 --mode dry-run [--no-save] [--input-check-json <check 输出>]

产物:
    data/reviews_reviewer/review_<date>_<run_id>.json  (33_reviewer schema)

退出码：0=pass / 1=pass_with_gaps / 2=fail_closed（同 findings 严重度映射）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJ / "docs" / "33_reviewer_v0.1.schema.json"
REVIEWS_DIR = PROJ / "data" / "reviews_reviewer"
BRIEFS_DIR = PROJ / "data" / "briefs"
VIEWS_FILE = PROJ / "data" / "views" / "structured_views.jsonl"

SECTION_RE = re.compile(r"^## (\d+)\.", re.M)
VIEW_ID_RE = re.compile(r"`([0-9a-f]{16,32})`")
BANNED_SOURCES = ["主力行为学", "汤山老王", "马跑跑", "邻居大爷", "八叔不啰嗦"]
# 硬故障：明确注入失败声明 → 该节必 high（9-04 持仓 BOM/决策台空注入即此类）
HARD_FAIL_MARKERS = ["BOM 解码错误", "未注入", "无法注入", "工具返回", "解码错误"]
# 软缺失：单点数据 N/A（行情某指标/无卡），节内若主体有数 → medium 常态
SOFT_NA_MARKERS = ["N/A", "未获取", "返回空", "待验证（缺基准", "数据未注入"]


def _read_report(path: str | Path) -> tuple[str, str]:
    """读日报 md；返回 (text, sha256)。BOM 兼容 utf-8-sig。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"日报不存在: {p}")
    raw = p.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sections(text: str) -> list[str]:
    return re.findall(SECTION_RE, text)


def check_sections(text: str) -> list[dict]:
    """章节覆盖：8 章必备（## 1. ~ ## 8.）。"""
    found = {s for s in _sections(text)}
    missing = [str(i) for i in range(1, 9) if str(i) not in found]
    if not missing:
        return []
    return [{
        "finding_id": "SEC-01", "category": "章节缺失", "severity": "high",
        "status": "open", "detector": "deterministic",
        "description": f"必备章节缺失: {missing}（现有: {sorted(found)}）",
        "section": None,
    }]


def check_missing_markers(text: str) -> list[dict]:
    """数据缺失标记扫描：按章节聚合（防逐行刷屏狼来了）。

    - 硬故障（未注入/BOM/解码错误声明）→ 该节 high（整节注入失败）
    - 软缺失（N/A 单点）：≥3 处或占该节内容 >50% → high；否则 medium
    """
    lines = text.splitlines()
    per_section: dict[int, list[str]] = {}
    soft_by_section: dict[int, list[str]] = {}
    section_content: dict[int, int] = {}
    current = None
    for ln in lines:
        m = re.match(r"^## (\d+)\.", ln)
        if m:
            current = int(m.group(1))
            continue
        if current is None:
            continue
        stripped = ln.strip()
        if not stripped or stripped.startswith(("|", "---")):
            continue  # 表格行/分隔线不参与
        section_content[current] = section_content.get(current, 0) + 1
        hard = [mk for mk in HARD_FAIL_MARKERS if mk in ln]
        if hard:
            per_section.setdefault(current, []).append(stripped[:140])
            continue
        soft = [mk for mk in SOFT_NA_MARKERS if mk in ln]
        if soft:
            soft_by_section.setdefault(current, []).append(stripped[:140])

    findings = []
    for sec in sorted(per_section):
        hits = per_section[sec]
        findings.append({
            "finding_id": f"DATA-{len(findings) + 1:02d}", "category": "数据缺失",
            "severity": "high",
            "status": "open", "detector": "deterministic",
            "description": f"章节 {sec} 注入失败声明 {len(hits)} 处: {hits[0][:100]}",
            "section": f"## {sec}",
            "evidence": "; ".join(h[:60] for h in hits[:3]),
        })
    for sec in sorted(soft_by_section):
        if sec in per_section:
            continue  # 该节已有硬故障，不再重复软缺失
        hits = soft_by_section[sec]
        total = section_content.get(sec, 0) or 1
        ratio = len(hits) / total
        severity = "high" if (len(hits) >= 3 or ratio > 0.5) else "medium"
        findings.append({
            "finding_id": f"DATA-{len(findings) + 1:02d}", "category": "数据缺失",
            "severity": severity,
            "status": "open", "detector": "deterministic",
            "description": (f"章节 {sec} N/A 标记 {len(hits)} 处"
                            f"（占该节内容 {ratio:.0%}）: {hits[0][:80]}" if len(hits) > 1
                            else f"章节 {sec} 数据缺失: {hits[0][:100]}"),
            "section": f"## {sec}",
            "evidence": "; ".join(h[:60] for h in hits[:3]),
        })
    return findings


def check_evidence_chain(text: str, view_ids: set[str]) -> list[dict]:
    """证据链：正文 view_id 引用必须存在且格式合法。"""
    seen = set()
    findings = []
    for m in VIEW_ID_RE.finditer(text):
        vid = m.group(1)
        if vid in seen:
            continue
        seen.add(vid)
        if vid not in view_ids:
            findings.append({
                "finding_id": f"EVID-{len(findings) + 1:02d}", "category": "证据链断裂",
                "severity": "high", "status": "open", "detector": "deterministic",
                "description": f"view_id `{vid}` 在观点库不存在（幻觉引用）",
                "evidence_refs": [vid],
            })
    return findings


def check_banned_sources(text: str) -> list[dict]:
    hit = [b for b in BANNED_SOURCES if b in text]
    if not hit:
        return []
    return [{
        "finding_id": "SRC-01", "category": "来源禁用", "severity": "blocker",
        "status": "open", "detector": "deterministic",
        "description": f"引用禁用来源: {hit}",
    }]


def check_time_window(text: str, report_date: str) -> list[dict]:
    """时间窗：报告头部日期与 --date 一致。"""
    head = text[:600]
    if report_date in head:
        return []
    return [{
        "finding_id": "TS-01", "category": "时间窗不一致", "severity": "high",
        "status": "open", "detector": "deterministic",
        "description": f"报告头部未见日期 {report_date}（cutoff 一致性存疑）",
        "section": "header",
    }]


def load_view_ids() -> set[str]:
    """观点库 view_id 全集（structured_views.jsonl 首字段）。文件缺失 → 空集 + 警告不阻断。"""
    if not VIEWS_FILE.exists():
        return set()
    ids = set()
    try:
        with VIEWS_FILE.open("r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                vid = row.get("view_id") or row.get("id")
                if vid:
                    ids.add(str(vid))
    except OSError:
        return set()
    return ids


# ── 33_reviewer 产物组装 ─────────────────────────────────────
def build_review(
    report_path: str, report_date: str, text: str, text_sha: str,
    det_findings: list[dict], checker_findings: list[dict], use_llm: bool,
) -> dict:
    """确定性审验产物组装。LLM 字段（claim_extracts 等）dry-run 留空并在 _meta 声明。"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = hashlib.sha256(f"{report_date}|{text_sha}|{ts}".encode()).hexdigest()[:8]

    all_findings = checker_findings + det_findings
    # 统一编号：确定性 findings 带原 id，无 id 的补 F-xxx
    findings = []
    for f in all_findings:
        fid = f.get("finding_id") or f"F-{len(findings) + 1:03d}"
        f = dict(f)
        f["finding_id"] = fid
        findings.append(f)

    sev = [f.get("severity") for f in findings]
    if "blocker" in sev:
        final_status = "fail_closed"
    elif sev:
        final_status = "pass_with_gaps"
    else:
        final_status = "pass"

    unresolved = [
        {
            "gap_id": f.get("finding_id"),
            "description": f.get("description", ""),
            "severity": f.get("severity", "low"),
            "delivery": "blocked" if f.get("severity") == "blocker" else "transparent",
        }
        for f in findings
    ]

    det_fields = [
        "review_run_id", "report_id", "job_id", "report_date", "input_snapshot_ids",
        "findings", "tool_calls", "unresolved_gaps", "final_status", "timestamps",
    ]
    return {
        "review_run_id": f"review_{report_date}_{run_id}",
        "report_id": f"daily-{report_date}",
        "job_id": "",
        "report_date": report_date,
        "generator_model": "agent.py-brief",
        "reviewer_model": "deterministic-dryrun" if not use_llm else "deepseek-v4-flash",
        "input_snapshot_ids": [
            "portfolio.json", "qianboshi_decision.db", "market_cache.json",
            "tracking_pool.json", "views/structured_views.jsonl",
        ],
        "tool_calls": [],
        "claim_extracts": [],
        "findings": findings,
        "repairs": [],
        "unresolved_gaps": unresolved,
        "final_status": final_status,
        "timestamps": {
            "started_at": now,
            "finished_at": now,
            "report_cutoff_at": f"{report_date}T22:00:00+08:00",
        },
        "_meta": {
            "schema_version": "33_reviewer_v0.1",
            "deterministic_fields": det_fields,
            "llm_fields": [] if not use_llm else ["claim_extracts"],
            "prompt_version": "dry-run-v0.1" if not use_llm else "llm-v0.1",
            "config_hash": hashlib.sha256(
                f"{report_path}|{text_sha}".encode()).hexdigest()[:12],
        },
    }


def validate_report(report: dict) -> tuple[bool, list[str]]:
    if not SCHEMA_PATH.exists():
        return False, [f"schema 缺失: {SCHEMA_PATH}"]
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errs = [e.message for e in validator.iter_errors(report)]
    return (len(errs) == 0), errs[:8]


def run_review(report_path: str, report_date: str, mode: str = "dry-run",
               use_llm: bool = False, save: bool = True,
               input_check_json: str | None = None) -> dict:
    """执行审验：注入检查（check_report_inputs 复用）→ 确定性审验 → 产物。"""
    if mode != "dry-run":
        raise NotImplementedError(f"mode={mode} 属后续步（active-repair 未批），本版仅 dry-run")
    if use_llm:
        raise NotImplementedError("LLM 语义审验属后续步（装配器后），dry-run 仅确定性")

    print(f"[1/4] 读日报 {Path(report_path).name}…")
    text, text_sha = _read_report(report_path)

    print("[2/4] 注入完整性（check_report_inputs 复用）…")
    sys.path.insert(0, str(PROJ / "scripts"))
    checker_findings: list[dict] = []
    try:
        import check_report_inputs as cri
        # 复用其数据目录检查（report 检查传当前报告，避免双查）
        errs, warns = cri.check_inputs(report_date, report_path)
        # 注入层发现（IN-xx）：high/blocker 才进审验 findings（info/medium 归 infos）
        checker_findings = [f for f in errs] + [
            f for f in warns if f.get("severity") in ("high", "blocker")
        ]
        print(f"      注入检查: {len(errs)} errors, {len(warns)} warns")
    except Exception as e:  # noqa: BLE001
        checker_findings.append({
            "finding_id": "CHK-ERR", "category": "注入检查自身异常", "severity": "high",
            "status": "open", "detector": "deterministic",
            "description": f"check_report_inputs 调用失败: {e}",
        })
        print(f"      ⚠ check_report_inputs 异常: {e}")

    print("[3/4] 确定性审验（章节/证据链/来源/时间窗）…")
    view_ids = load_view_ids()
    det_findings: list[dict] = []
    det_findings += check_sections(text)
    det_findings += check_evidence_chain(text, view_ids)
    det_findings += check_banned_sources(text)
    det_findings += check_time_window(text, report_date)
    det_findings += check_missing_markers(text)
    print(f"      确定性 findings: {len(det_findings)}")

    print("[4/4] 组装 33_reviewer 产物 + schema 校验…")
    report = build_review(report_path, report_date, text, text_sha,
                          det_findings, checker_findings, use_llm=False)
    ok, errs = validate_report(report)
    report["_meta"]["schema_valid"] = ok
    if errs:
        report["_meta"]["schema_errors"] = errs
    print(f"      schema 校验: {'通过' if ok else '失败: ' + '; '.join(errs)}")
    print(f"      final_status: {report['final_status']} | findings: {len(report['findings'])}")

    if save:
        REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
        fname = REVIEWS_DIR / f"review_{report_date}_{report['review_run_id'].split('_')[-1]}.json"
        fname.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已保存: {fname}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="日报独立审验 Executor（dry-run 只读）")
    ap.add_argument("--report", required=True, help="日报 md 路径")
    ap.add_argument("--date", required=True, help="报告日期 YYYY-MM-DD")
    ap.add_argument("--mode", default="dry-run", choices=["dry-run"],
                    help="dry-run=只读审验不改日报（本版仅此模式）")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--llm", action="store_true", help="预留：LLM 语义审验（未批，当前会拒绝）")
    ap.add_argument("--input-check-json", default=None, help="预留：check_report_inputs --json 产物路径")
    args = ap.parse_args()

    try:
        report = run_review(args.report, args.date, mode=args.mode,
                            use_llm=args.llm, save=not args.no_save,
                            input_check_json=args.input_check_json)
    except NotImplementedError as e:
        print(f"[拒绝] {e}")
        return 3
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        return 2

    code = {"pass": 0, "pass_with_gaps": 1, "fail_closed": 2}[report["final_status"]]
    print(f"退出码 {code} ({report['final_status']})")
    return code


if __name__ == "__main__":
    sys.exit(main())
