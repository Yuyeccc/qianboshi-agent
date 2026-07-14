#!/usr/bin/env python3
"""
批量 ASR 修正脚本 (v2.1)
用法: python scripts/batch_asr_fix.py

对所有转录文件执行修正：
- 已有的 *_corrected.txt：修复残留错误
- 新的 *_transcript.txt（无 corrected）：创建 *_corrected.txt

修正表按长度降序排列，避免短词误改长词。
"""
import os
import re
from pathlib import Path

TRANSCRIPTS_DIR = Path("E:/qianboshi-agent/transcripts")

# ── 修正表（按长度降序，长词在前） ──
CORRECTIONS = [
    # === 组合错误（长词优先）===
    ("半道体一体癌伏", "半导体ETF"),
    ("半道理一体癌伏", "半导体ETF"),
    ("半章比设备", "半导体设备"),
    ("归光进风状", "硅光封装"),
    ("归光共风状", "硅光共封装"),
    ("归光纤片", "硅光芯片"),
    ("强述理中心", "数据中心"),
    ("数集中心", "数据中心"),
    ("述理中心", "数据中心"),
    ("出于中心", "数据中心"),
    ("市伦中心", "数据中心"),
    ("数以中心", "数据中心"),
    ("处理中心", "数据中心"),
    ("屁费地板", "PCB"),

    # === 普通词 ===
    ("半脑体", "半导体"),
    ("半章比", "半导体"),
    ("半道体", "半导体"),
    ("半道理", "半导体"),
    ("一体癌伏", "ETF"),
    ("议一体癌伏", "ETF"),
    ("归光芯片", "硅光芯片"),
    ("归光", "硅光"),
    ("光体型", "光模块"),

    # === 通用词 ===
    ("偷懇", "投资"),
    ("斗包", "豆包"),
    ("圆宝", "元宝"),
    ("朱雀酸", "朱雀三"),
    ("十方号", "三号"),

    # === 公司名（多重证据确认）===
    ("飞鸽", "菲利华"),
    ("飞哥", "菲利华"),
    ("互规", "沪硅"),
]

# 需要保留原文的待定项（已标记，不修正）
PENDING = [
    "路易斯", "陆与斯", "路尔斯", "路里斯", "路一次", "录一次",
    "DB2", "少终", "买茶",
]


def apply_corrections(text):
    """按长度降序逐条替换"""
    for wrong, right in CORRECTIONS:
        text = text.replace(wrong, right)
    return text


def process_file(src_path, dst_path=None):
    """处理单个转录文件"""
    if dst_path is None:
        # 自动生成 corrected 文件名
        name = src_path.name
        if name.endswith("_transcript.txt"):
            dst_name = name.replace("_transcript.txt", "_transcript_corrected.txt")
        else:
            dst_name = name.replace(".txt", "_corrected.txt")
        dst_path = src_path.parent / dst_name

    original = src_path.read_text(encoding="utf-8")
    corrected = apply_corrections(original)

    # 统计变更
    changes = 0
    for wrong, right in CORRECTIONS:
        c = corrected.count(right) - original.count(right)
        if c > 0:
            print(f"  [+{c}] {wrong} → {right}")
            changes += c

    if changes == 0 and dst_path.exists():
        print(f"  → 无变更 (跳过)")
        return False

    dst_path.write_text(corrected, encoding="utf-8")
    print(f"  → 共修正 {changes} 处 → {dst_path.name}")
    return True


def main():
    print("=" * 60)
    print("钱博士Agent — ASR批量修正 v2.1")
    print("=" * 60)

    # 第1轮：所有已有 *_corrected.txt（修复残留）
    print("\n[第1轮] 已有 corrected 文件 — 修复残留...")
    done = 0
    for f in sorted(TRANSCRIPTS_DIR.glob("*_corrected.txt")):
        print(f"\n  [{f.name}]")
        if process_file(f, f):  # 原地覆盖
            done += 1
    print(f"\n  ✓ 修复 {done} 个文件")

    # 第2轮：没有 corrected 的原始转录 → 创建 corrected
    print("\n[第2轮] 新转录文件 — 创建 corrected...")
    created = 0
    for f in sorted(TRANSCRIPTS_DIR.glob("*_transcript.txt")):
        corrected_name = f.name.replace("_transcript.txt", "_transcript_corrected.txt")
        corrected_path = TRANSCRIPTS_DIR / corrected_name
        if corrected_path.exists():
            continue  # 已有 corrected，跳过
        print(f"\n  [{f.name}] → 创建 corrected")
        if process_file(f):
            created += 1
    print(f"\n  ✓ 创建 {created} 个新 corrected 文件")

    print("\n" + "=" * 60)
    print("完成！")


if __name__ == "__main__":
    main()
