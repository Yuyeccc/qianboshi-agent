#!/usr/bin/env python3
"""
批量 ASR 修正脚本 (v2.2 — 完整纠错表)

用法: python scripts/batch_asr_fix.py

对所有转录文件执行修正：
- 已有 *_corrected.txt：原地覆盖修复残留
- 新的 *_transcript.txt（无 corrected）：创建 *_corrected.txt

修正表按长度降序排列，避免短词误改长词。
基于6-7月直播转写经验，涵盖行业术语/公司名/金融术语。
"""
import os
import re
from pathlib import Path

TRANSCRIPTS_DIR = Path("E:/qianboshi-agent/transcripts")

# ── 修正表（按长度降序，长词在前） ──
CORRECTIONS = [
    # === 组合错误（长词优先，防止短词误改）===
    ("议一体癌伏", "ETF"),
    ("半道体一体癌伏", "半导体ETF"),
    ("半道理一体癌伏", "半导体ETF"),
    ("归光进风状", "硅光封装"),
    ("归光共风状", "硅光共封装"),
    ("归光芯片", "硅光芯片"),
    ("归光纤片", "硅光芯片"),
    ("现金智商", "先进封装"),
    ("博摩林村里", "铌酸锂"),
    ("博摩林", "铌酸锂"),
    ("太山波鲜", "泰山玻纤"),
    ("山东波鲜", "泰山玻纤"),
    ("中心华红", "中芯国际/华虹"),
    ("通负风测", "通富微电"),
    ("盘钱资讯", "盘前资讯"),

    # === 数据中心（大量变体）===
    ("强述理中心", "数据中心"),
    ("数集中心", "数据中心"),
    ("述理中心", "数据中心"),
    ("出于中心", "数据中心"),
    ("市伦中心", "数据中心"),
    ("数以中心", "数据中心"),
    ("处理中心", "数据中心"),

    # === 光模块（大量变体）===
    ("光摸块", "光模块"),
    ("光波块", "光模块"),
    ("光磨画", "光模块"),
    ("光灯块", "光模块"),
    ("光磨块", "光模块"),
    ("光波化", "光模块"),
    ("光体型", "光模块"),

    # === 半导体（大量变体）===
    ("半章比设备", "半导体设备"),
    ("半章比", "半导体"),
    ("半脑体", "半导体"),
    ("半套体", "半导体"),
    ("半道体", "半导体"),
    ("半道理", "半导体"),

    # === PCB相关 ===
    ("屁费地板", "PCB"),
    ("副同板", "覆铜板"),
    ("爱飞击版", "IC基板"),
    ("几百公司", "基板公司"),
    ("批飞笔", "PCB"),
    ("PZB", "PCB"),
    ("二代部", "二代基板"),
    ("电子部", "基板"),

    # === PE / 估值 ===
    ("批秘", "PE"),
    ("皮秘", "PE"),
    ("批一", "PE"),
    ("批议", "PE"),
    ("秘地", "PE"),
    ("败书", "倍数"),

    # === 涨停 ===
    ("长屏", "涨停"),
    ("长廷", "涨停"),
    ("长停", "涨停"),
    ("掌听", "涨停"),
    ("张停", "涨停"),
    ("掌铭", "涨停"),
    ("长平", "涨停"),
    ("长疼", "涨停"),

    # === 公司名（多重证据确认）===
    ("哈姆纳克", "发那科"),
    ("路易斯飞哥", "【路易斯】菲利华"),
    ("路易斯菲力华", "【路易斯】菲利华"),
    ("飞鸽", "菲利华"),
    ("飞哥", "菲利华"),
    ("海利市", "SK海力士"),
    ("深灵", "申菱环境"),
    ("鸿河", "宏和科技"),
    ("好贵", "沪硅产业"),
    ("盘王", "寒武纪"),
    ("金融方", "京东方"),
    ("光可调", "光刻胶"),
    ("通负", "通富微电"),
    ("风测", "封测"),
    ("蓝丝", "蓝思科技"),
    ("绿地", "绿的谐波"),
    ("互规", "沪硅"),
    ("常电", "长电科技"),
    ("长电", "长电科技"),
    ("主角三", "朱雀三号"),

    # === 光通信/芯片术语 ===
    ("艳玛尔", "EML"),
    ("飞达不留", "FP激光器"),
    ("归光", "硅光"),
    ("规光", "硅光"),
    ("规片", "硅片"),
    ("光仙", "光纤"),
    ("SST", "Substrate(衬底)"),
    ("FST", "Optimus(擎天柱)"),

    # === 锂电池/资源 ===
    ("逃土礦", "稀土矿"),
    ("采黄镇", "采矿证"),
    ("李框", "锂矿"),
    ("礼礦", "锂矿"),
    ("力框", "锂矿"),
    ("纳点池", "钠电池"),
    ("那点迟", "钠电池"),

    # === 通用词 ===
    ("一体癌伏", "ETF"),
    ("偷懇", "投资"),
    ("斗包", "豆包"),
    ("圆宝", "元宝"),
    ("朱雀酸", "朱雀三"),
    ("十方号", "三号"),
    ("小某书", "小红书"),
    ("愚伪行情", "鱼尾行情"),
    ("相关顾门", "相关部门"),
    ("大画头", "大话筒"),
    ("中头度", "忠诚度"),
    ("台杠", "抬杠"),
    ("抬钢", "抬杠"),
    ("日东坊", "日东纺"),
    ("姚鲁", "窑炉"),
    ("支部机", "植球机"),
    ("盘王", "寒武纪"),
]

# 需要保留原文的待定项（已标记，不修正）
PENDING = [
    "DB2", "少终", "买茶",
]


def apply_corrections(text):
    """按长度降序逐条替换"""
    for wrong, right in CORRECTIONS:
        text = text.replace(wrong, right)
    return text


def process_file(src_path, dst_path=None):
    """处理单个转录文件，返回(changed, count)"""
    if dst_path is None:
        name = src_path.name
        if name.endswith("_transcript.txt"):
            dst_name = name.replace("_transcript.txt", "_transcript_corrected.txt")
        else:
            dst_name = name.replace(".txt", "_corrected.txt") if not name.endswith("_corrected.txt") else name
        dst_path = src_path.parent / dst_name

    original = src_path.read_text(encoding="utf-8")
    corrected = apply_corrections(original)

    # 统计变更
    changes = 0
    change_details = []
    for wrong, right in CORRECTIONS:
        c = original.count(wrong)
        if c > 0:
            change_details.append(f"  [{c:>3}] {wrong} → {right}")
            changes += c

    if changes == 0:
        return False, 0

    dst_path.write_text(corrected, encoding="utf-8")
    for line in change_details:
        print(line)
    print(f"  → 共修正 {changes} 处 → {dst_path.name}")
    return True, changes


def main():
    print("=" * 60)
    print("钱博士Agent — ASR批量修正 v2.2 (完整纠错表)")
    print(f"  纠错条目: {len(CORRECTIONS)}")
    print("=" * 60)

    # 第1轮：已有 *_corrected.txt → 原地覆盖修复残留
    print("\n[第1轮] 已有 corrected 文件 — 修复残留...")
    fixed = 0
    total_changes = 0
    for f in sorted(TRANSCRIPTS_DIR.glob("*_corrected.txt")):
        print(f"\n  [{f.name}]")
        changed, count = process_file(f, f)
        if changed:
            fixed += 1
            total_changes += count
    print(f"\n  ✓ 修复 {fixed} 个文件，共 {total_changes} 处")

    # 第2轮：没有 corrected 的原始转录 → 创建 corrected
    print("\n[第2轮] 新转录文件 — 创建 corrected...")
    created = 0
    for f in sorted(TRANSCRIPTS_DIR.glob("*_transcript.txt")):
        corrected_name = f.name.replace("_transcript.txt", "_transcript_corrected.txt")
        if (TRANSCRIPTS_DIR / corrected_name).exists():
            continue
        print(f"\n  [{f.name}] → 创建 corrected")
        changed, _ = process_file(f)
        if changed:
            created += 1
    print(f"\n  ✓ 创建 {created} 个新 corrected 文件")

    print("\n" + "=" * 60)
    print(f"完成！修正 {fixed + created} 个文件，{total_changes} 处变更")


if __name__ == "__main__":
    main()
