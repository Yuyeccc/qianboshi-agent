#!/usr/bin/env python3
"""
二次ASR纠错脚本 v1.0 — 对结构化笔记(.md)再跑一遍纠错表

结构化笔记由LLM从corrected转录生成，但:
1. LLM重述可能引入新的ASR风格错误
2. 原纠错表可能漏掉的错误在新格式下可被捕获
3. 部分公司名在段落文本中可能有不同写法

用法:
    python scripts/batch_note_asr_fix.py                          # 全量修正
    python scripts/batch_note_asr_fix.py --dry-run                # 预览不变更
    python scripts/batch_note_asr_fix.py --check                  # 只统计不修改
"""
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_obsidian_path

# ── 复用 ASR 纠错表（从 batch_asr_fix.py 同步） ──
# 按长度降序排列（长词优先匹配）
NOTE_CORRECTIONS = [
    # === 组合错误 ===
    ("议一体癌伏", "ETF"),
    ("半道体一体癌伏", "半导体ETF"),
    ("半道理一体癌伏", "半导体ETF"),
    ("归光进风状", "硅光封装"),
    ("归光共风状", "硅光共封装"),
    ("归光芯片", "硅光芯片"),
    ("归光纤片", "硅光芯片"),
    ("现金智商", "先进封装"),
    ("先进风装", "先进封装"),
    ("博摩林村里", "铌酸锂"),
    ("博摩林", "铌酸锂"),
    ("太山波鲜", "泰山玻纤"),
    ("山东波鲜", "泰山玻纤"),
    ("中心华红", "中芯国际/华虹"),
    ("华红半导体", "华虹半导体"),
    ("华红公司", "华虹公司"),
    ("华红", "华虹"),
    ("中心国际", "中芯国际"),
    ("通负风测", "通富微电"),
    ("盘钱资讯", "盘前资讯"),
    ("公路半导体", "功率半导体"),
    ("红胜科技", "恒生科技"),
    ("红尘科技", "恒生科技"),
    ("红灯科技", "恒生科技"),
    ("正积材料", "正极材料"),
    ("一体埋伏", "ETF"),

    # === 数据中心 ===
    ("强述理中心", "数据中心"),
    ("数集中心", "数据中心"),
    ("述理中心", "数据中心"),
    ("出于中心", "数据中心"),
    ("市伦中心", "数据中心"),
    ("数以中心", "数据中心"),
    ("处理中心", "数据中心"),

    # === 光模块 ===
    ("光摸块", "光模块"),
    ("光波块", "光模块"),
    ("光磨画", "光模块"),
    ("光灯块", "光模块"),
    ("光磨块", "光模块"),
    ("光波化", "光模块"),
    ("光体型", "光模块"),
    ("猪魔块", "光模块"),

    # === 科创板 ===
    ("割創板", "科创板"),

    # === 半导体 ===
    ("半章比设备", "半导体设备"),
    ("半章比", "半导体"),
    ("半脑体", "半导体"),
    ("半套体", "半导体"),
    ("半道体", "半导体"),
    ("半道理", "半导体"),

    # === PCB ===
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

    # === 公司名 ===
    ("哈姆纳克", "发那科"),
    ("路易斯飞哥", "菲利华"),
    ("路易斯菲力华", "菲利华"),
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
    ("英伟大", "英伟达"),
    ("硬为达", "英伟达"),
    ("台级店", "台积电"),
    ("台级院", "台积电"),
    ("紫金框也", "紫金矿业"),
    ("紫金框液", "紫金矿业"),
    ("得名力", "德明利"),
    ("蓝起科技", "澜起科技"),
    ("百威存储", "佰维存储"),
    ("相同形状", "香农芯创"),
    ("江博龙", "江波龙"),
    ("中威公司", "中微公司"),
    ("中威", "中微公司"),
    ("盛邦股份", "圣邦股份"),
    ("盛邦", "圣邦股份"),
    ("盛宏科技", "胜宏科技"),
    ("盛宏", "胜宏科技"),
    ("盛红", "胜宏科技"),
    ("天福通信", "天孚通信"),
    ("天福", "天孚通信"),
    ("护电股份", "沪电股份"),
    ("护电", "沪电股份"),
    ("维尔股份", "韦尔股份"),
    ("维尔", "韦尔股份"),

    # === 光通信/芯片术语 ===
    ("艳玛尔", "EML"),
    ("飞达不留", "FP激光器"),
    ("归光", "硅光"),
    ("规光", "硅光"),
    ("规片", "硅片"),
    ("光仙", "光纤"),
    ("SST", "Substrate(衬底)"),
    ("FST", "擎天柱"),

    # === 锂电池/资源 ===
    ("逃土礦", "稀土矿"),
    ("采黄镇", "采矿证"),
    ("李框", "锂矿"),
    ("礼礦", "锂矿"),
    ("力框", "锂矿"),
    ("离框", "锂矿"),
    ("同框", "铜矿"),
    ("金框", "金矿"),
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
    ("韩武计", "寒武纪"),
    ("韩武纪", "寒武纪"),
    ("韩武器", "寒武纪"),
    ("照一创新", "兆易创新"),
    ("赵玉床芯", "兆易创新"),
    ("赵玉床心", "兆易创新"),
    ("赵玉昌金", "兆易创新"),
    ("甩解", "衰竭"),
    ("货力", "获利"),
    ("剩算率", "胜算率"),
    ("村半企业", "村办企业"),
    ("欺货", "期货"),
    ("上正指数", "上证指数"),
    ("只数", "指数"),
    ("光客机", "光刻机"),
    ("光可调", "光刻胶"),
]

# 笔记特有的额外纠错（LLM重述引入的常见问题）
NOTE_ONLY_CORRECTIONS = [
    # LLM经常把"看多"写成"看涨"但是格式不对
    # LLM总结中容易遗漏/混淆的公司名变体
    ("存储芯片兆易创新", "兆易创新"),
    ("AI芯片寒武纪", "寒武纪"),
    # 时间戳格式统一
]


def apply_note_corrections(text):
    """对笔记文本执行二次ASR纠错"""
    total_changes = 0
    change_details = []

    for wrong, right in NOTE_CORRECTIONS + NOTE_ONLY_CORRECTIONS:
        c = text.count(wrong)
        if c > 0:
            text = text.replace(wrong, right)
            total_changes += c
            change_details.append(f"  [{c:>3}] {wrong} → {right}")

    return text, total_changes, change_details


def scan_notes_for_errors(notes_dir):
    """扫描所有笔记，统计已知ASR错误残留（不修改）"""
    results = {}
    for md_file in sorted(notes_dir.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        file_errors = {}
        for wrong, right in NOTE_CORRECTIONS + NOTE_ONLY_CORRECTIONS:
            c = text.count(wrong)
            if c > 0:
                file_errors[wrong] = c
        if file_errors:
            results[md_file.name] = file_errors
    return results


def main():
    parser = argparse.ArgumentParser(description="结构化笔记二次ASR纠错")
    parser.add_argument("--dry-run", action="store_true", help="预览不变更")
    parser.add_argument("--check", action="store_true", help="只统计不修改")
    parser.add_argument("--file", help="处理单个笔记文件")
    parser.add_argument("--config", help="config.yaml路径")
    args = parser.parse_args()

    config = load_config(args.config)
    notes_dir = Path(get_obsidian_path(config))

    if not notes_dir.exists():
        print(f"❌ 笔记目录不存在: {notes_dir}")
        sys.exit(1)

    if args.check:
        print(f"🔍 扫描 {notes_dir} 中已知ASR错误残留...")
        results = scan_notes_for_errors(notes_dir)
        total_errors = 0
        for fname, errors in sorted(results.items()):
            err_str = ", ".join(f"{w}({c})" for w, c in errors.items())
            file_total = sum(errors.values())
            total_errors += file_total
            print(f"  ❌ {fname}: {err_str}")
        print(f"\n总计: {len(results)} 个文件含残留, {total_errors} 处错误")
        return

    # 收集待处理文件
    if args.file:
        md_files = [notes_dir / args.file]
    else:
        md_files = sorted(notes_dir.glob("*.md"))

    print(f"📂 笔记目录: {notes_dir}")
    print(f"📝 待检查: {len(md_files)} 篇笔记")
    print(f"📋 纠错条目: {len(NOTE_CORRECTIONS + NOTE_ONLY_CORRECTIONS)} 条")
    print(f"{' [DRY RUN]' if args.dry_run else ''}")
    print()

    total_fixed = 0
    total_changes = 0

    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        corrected_text, changes, details = apply_note_corrections(text)

        if changes > 0:
            total_changes += changes
            total_fixed += 1
            print(f"✅ {md_file.name}: {changes} 处修正")
            for d in details:
                print(d)

            if not args.dry_run:
                md_file.write_text(corrected_text, encoding="utf-8")
        else:
            print(f"  ✓ {md_file.name}: 无残留")

    print(f"\n{'=' * 50}")
    print(f"完成！{total_fixed}/{len(md_files)} 个文件修正，共 {total_changes} 处变更")
    if args.dry_run:
        print("（DRY RUN 模式，未实际修改）")


if __name__ == "__main__":
    main()
