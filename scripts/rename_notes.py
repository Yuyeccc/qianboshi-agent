#!/usr/bin/env python3
"""重命名现有笔记 + 生成BV→来源映射表，供transcribe_to_note.py使用"""
import json, os, re
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
OBSIDIAN = Path("E:/obsidian-vault/学习/钱博士")

# ── 1. 构建BV→来源映射 ──
SOURCE_NAMES = {
    "qianboshi_live": "钱博士直播",
    "qianboshi_short": "钱博士短视频",
    "shenyan": "深研一点",
    "benben": "笨笨的韭菜",
    "shishi": "史诗级韭菜",
    "qushi": "趋势天哥",
}

bv_to_source = {}
for f in DATA_DIR.glob("*_bvs.json"):
    name = f.name.replace("_bvs.json", "")
    source_cn = SOURCE_NAMES.get(name, name)
    data = json.loads(f.read_text())
    bvs = data if isinstance(data, list) else list(data.keys())
    for bv in bvs:
        if bv not in bv_to_source:
            bv_to_source[bv] = source_cn

print(f"BV→来源映射: {len(bv_to_source)} 条")

# 保存映射表，供 transcribe_to_note.py 使用
map_path = DATA_DIR / "bv_source_map.json"
with open(map_path, "w", encoding="utf-8") as f:
    json.dump(bv_to_source, f, ensure_ascii=False, indent=2)
print(f"映射表已保存: {map_path}")

# ── 2. 重命名现有笔记 ──
renamed = 0
skipped = 0
for md in sorted(OBSIDIAN.glob("*.md")):
    name = md.name
    if not name.startswith("钱博士直播复盘"):
        skipped += 1
        continue

    # 提取 BV号
    m = re.search(r'BV\w+', name)
    if not m:
        skipped += 1
        continue
    bv = m.group(0)

    source = bv_to_source.get(bv, "钱博士")
    if source == "钱博士":
        # 判断是直播还是短视频
        if "short" in str(DATA_DIR / f"qianboshi_short_bvs.json"):
            pass  # 后面通过映射判断
    
    # 新文件名: "来源 BVxxx.md"
    new_name = f"{source} {bv}.md"
    new_path = OBSIDIAN / new_name

    if new_path.exists():
        print(f"  ⏭ 目标已存在: {new_name}")
        skipped += 1
        continue

    md.rename(new_path)
    print(f"  ✅ {name} → {new_name}")
    renamed += 1

print(f"\n重命名: {renamed}, 跳过: {skipped}")
