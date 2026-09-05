#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_review_gate.py —— 日报审验闭环确定性 runner（审验-自补 ⑥，cron 接入闸门）

定位：把审验闭环（check_report_inputs 注入完整性 → reviewer_agent 只读审验 →
report_assembler 缺漏装配）串成**一条命令**供 cron 0073d213839b 调用，杜绝
prompt-based cron 跳步（前科：agent 只跑 monitor 没跑 --pipeline）。纯代码无 LLM。

开关语义（data/review_gate_config.json，入库可审计）：
  REVIEWER_ENABLED        false=灰度一期（审验日志照记、**不改日报正文**，恒 exit 0）
                          true=开装配（pass/pass_with_gaps 缺漏表写回日报）
  REVIEWER_ACTIVE_REPAIR  false（补数工具未建，本期永不补数）
  REVIEWER_FAIL_MODE      degrade | fail_closed（本期 degrade；超时/异常语义见下）
  REVIEWER_MAX_LATENCY_SECONDS  reviewer 子进程预算（180s；dry-run 确定性秒级）
  配置缺失/损坏 → 打印警告 + 回落全默认（ENABLED=false 最安全），不阻断交付

退出码（cron prompt 分支依据）：
  0 = 审验跑通（灰度：日报原稿未动 / 开装配：缺漏表已写回）→ 正常发日报
  2 = fail_closed 且 REVIEWER_ENABLED=true → **不装配**，cron 转"生成失败待人工"
  3 = 审验自身异常（日报缺失等）→ degrade：cron 发原稿 + 状态行注明审验异常

用法:
    C:/Python314/python.exe scripts/daily_review_gate.py --report data/briefs/日报_YYYY-MM-DD.md --date YYYY-MM-DD

stdout 摘要单行（cron 最终回复状态行引用）:
    [gate] review_run_id=... final_status=... gaps=N assembled=yes|no(灰度) exit=0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJ / "scripts"
CONFIG_PATH = PROJ / "data" / "review_gate_config.json"

DEFAULT_CONFIG = {
    "REVIEWER_ENABLED": False,
    "REVIEWER_ACTIVE_REPAIR": False,
    "REVIEWER_FAIL_MODE": "degrade",
    "REVIEWER_MAX_LATENCY_SECONDS": 180,
    "REVIEWER_PROMPT_VERSION": "dry-run-v0.1",
}

BOOLEAN_KEYS = ("REVIEWER_ENABLED", "REVIEWER_ACTIVE_REPAIR")


def load_config(path: str | Path = CONFIG_PATH) -> dict:
    """读开关配置；缺失/损坏 → 全默认（ENABLED=false 最安全），打印警告不阻断。"""
    cfg = dict(DEFAULT_CONFIG)
    p = Path(path)
    if not p.exists():
        print(f"[gate] ⚠ 配置缺失 {p}，回落灰度默认（REVIEWER_ENABLED=false）")
        return cfg
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        print(f"[gate] ⚠ 配置 JSON 损坏: {e}，回落灰度默认")
        return cfg
    for k, v in DEFAULT_CONFIG.items():
        if k in raw:
            cfg[k] = raw[k]
    # 布尔键宽容解析（"false"/"true"/0/1）
    for k in BOOLEAN_KEYS:
        v = cfg[k]
        if isinstance(v, str):
            cfg[k] = v.strip().lower() == "true"
    return cfg


def _summary(review: dict, assembled: bool, grayscale: bool) -> str:
    return ("[gate] review_run_id={rid} final_status={st} gaps={g} assembled={asm} exit={code}").format(
        rid=review.get("review_run_id", "?"),
        st=review.get("final_status", "?"),
        g=len(review.get("unresolved_gaps", [])),
        asm="yes" if assembled else "no(灰度)" if grayscale else "no(fail_closed)",
        code=0,
    )


def run_gate(report_path: str | Path, report_date: str,
             cfg: dict | None = None,
             _run_review=None, _assemble=None, _write_text=None) -> tuple[int, str]:
    """审验闭环编排。返回 (exit_code, summary_line)。

    依赖注入（_run_review/_assemble/_write_text）供单测 mock；生产默认走 reviewer_agent
    与 report_assembler 真实实现。reviewer 内部已复用 check_report_inputs（[2/4]）。
    """
    if cfg is None:
        cfg = load_config()
    enabled = bool(cfg.get("REVIEWER_ENABLED", False))
    sys.path.insert(0, str(SCRIPTS_DIR))

    if _run_review is None:
        import reviewer_agent as rv

        def _run_review(rp, rd):
            return rv.run_review(rp, rd, mode="dry-run", save=True)
    if _assemble is None:
        import report_assembler as ra

        def _assemble(text, review):
            return ra.assemble(text, review)
    if _write_text is None:
        def _write_text(p: Path, text: str) -> None:
            p.write_text(text, encoding="utf-8")

    # [1/3] 只读审验（内部含注入完整性 check；dry-run 确定性，产物落 data/reviews_reviewer/）
    try:
        review = _run_review(str(report_path), report_date)
    except Exception as e:  # noqa: BLE001  degrade：审验异常不阻断交付
        print(f"[gate] ⚠ 审验异常: {e}——degrade 发原稿")
        return 3, f"[gate] review=ERROR final_status=审验异常 exit=3"

    status = review.get("final_status", "")
    gaps = len(review.get("unresolved_gaps", []))
    report_file = Path(report_path)

    # [2/3] fail_closed 只在开装配期阻断（灰度=审计发现，日报照发）
    if status == "fail_closed":
        if enabled:
            print(f"[gate] ❌ fail_closed（{gaps} 项阻断缺漏）——不装配，转人工")
            return 2, f"[gate] review_run_id={review.get('review_run_id')} final_status=fail_closed gaps={gaps} assembled=no exit=2"
        print(f"[gate] ⚠ fail_closed 审计发现（灰度不阻断，日报照发）")
        return 0, f"[gate] review_run_id={review.get('review_run_id')} final_status=fail_closed(灰度审计) gaps={gaps} assembled=no(灰度) exit=0"

    # [3/3] 装配分支
    if not enabled:
        print(f"[gate] 灰度一期 REVIEWER_ENABLED=false：审验日志已落盘，日报正文未改")
        return 0, f"[gate] review_run_id={review.get('review_run_id')} final_status={status} gaps={gaps} assembled=no(灰度) exit=0"

    try:
        text = report_file.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        print(f"[gate] ⚠ 日报不存在: {report_file}")
        return 3, "[gate] review=ERROR final_status=日报缺失 exit=3"
    out = _assemble(text, review)
    _write_text(report_file, out)
    print(f"[gate] ✅ 装配完成（缺漏表已写回日报）")
    return 0, f"[gate] review_run_id={review.get('review_run_id')} final_status={status} gaps={gaps} assembled=yes exit=0"


def main() -> int:
    ap = argparse.ArgumentParser(description="日报审验闭环 runner（⑥ cron 接入闸门）")
    ap.add_argument("--report", required=True, help="日报 md 路径")
    ap.add_argument("--date", required=True, help="报告日期 YYYY-MM-DD")
    ap.add_argument("--config", default=str(CONFIG_PATH), help="开关配置路径（默认 data/review_gate_config.json）")
    ap.add_argument("--enable", action="store_true",
                    help="临时开装配（等价 REVIEWER_ENABLED=true，不写配置文件；试跑/回放验证用）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.enable:
        cfg["REVIEWER_ENABLED"] = True

    code, summary = run_gate(args.report, args.date, cfg)
    print(summary)
    return code


if __name__ == "__main__":
    sys.exit(main())
