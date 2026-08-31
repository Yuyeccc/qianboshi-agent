#!/usr/bin/env python3
"""重命名深研一点笔记(加分析师名) + 补充所有笔记的日期"""
import json, re, time
from pathlib import Path
from datetime import datetime

OBSIDIAN = Path("E:/obsidian-vault/学习/钱博士")
DATA_DIR = Path(__file__).parent.parent / "data"

# 加载映射
bv_source = json.loads((DATA_DIR / "bv_source_map.json").read_text())
shenyan_meta = json.loads((DATA_DIR / "shenyan_video_meta.json").read_text()) if (DATA_DIR / "shenyan_video_meta.json").exists() else {}

# ── 1. 从文件名提取BV号 ──
BV_RE = re.compile(r'(BV[\w]+(?:_p\d+)?)')

def extract_bv(name):
    m = BV_RE.search(name)
    return m.group(0) if m else None

# ── 2. 重命名深研一点笔记 ──
renamed = 0
for md in sorted(OBSIDIAN.glob("深研一点 *.md")):
    bv = extract_bv(md.name)
    if not bv:
        continue
    
    source = bv_source.get(bv, "深研一点")
    if source.startswith("深研一点-"):
        new_name = f"{source} {bv}.md"
        new_path = OBSIDIAN / new_name
        if new_path.exists():
            print(f"  ⏭ 已存在: {new_name}")
            continue
        md.rename(new_path)
        print(f"  ✅ {md.name} → {new_name}")
        renamed += 1

print(f"\n重命名深研一点: {renamed} 篇")
print()

# ── 3. 补充所有笔记的日期 ──
# 日期来源优先级:
#   a. 已有 frontmatter 中的 date（如果有效的话）
#   b. 深研一点：从B站API的pubdate
#   c. 文件名中的日期 (YYYY.M.D)
#   d. 从B站API批量获取
DATE_RE = re.compile(r'(\d{4})\.(\d{1,2})\.(\d{1,2})')
FRONTMATTER_DATE_RE = re.compile(r'^date:\s*(.+)$', re.MULTILINE)

updated_date = 0
for md in sorted(OBSIDIAN.glob("*.md")):
    text = md.read_text(encoding="utf-8")
    bv = extract_bv(md.name)
    
    # 检查已有 date
    dm = FRONTMATTER_DATE_RE.search(text)
    existing_date = dm.group(1).strip() if dm else ""
    
    # 跳过已经有效日期的
    if existing_date and existing_date not in ("", "未知", "未提供", "unknown", "无"):
        continue
    
    # 确定日期
    new_date = None
    
    # a. 从文件名提取
    fnm = DATE_RE.search(md.name)
    if fnm:
        y, m, d = fnm.groups()
        new_date = f"{y}-{int(m):02d}-{int(d):02d}"
    
    # b. 深研一点 B站API
    if not new_date and bv and bv in shenyan_meta:
        pub = shenyan_meta[bv].get("pubdate")
        if pub:
            new_date = datetime.fromtimestamp(pub).strftime("%Y-%m-%d")
    
    # c. 其他BV从B站API获取
    
    if new_date:
        if existing_date:
            # 替换已有无效日期
            text = FRONTMATTER_DATE_RE.sub(f"date: {new_date}", text, count=1)
        else:
            # 插入 date 字段（在 --- 后面）
            text = text.replace("---\n", f"---\ndate: {new_date}\n", 1)
        
        md.write_text(text, encoding="utf-8")
        print(f"  ✅ {md.name}: {existing_date or '无'} → {new_date}")
        updated_date += 1

print(f"\n补充日期: {updated_date} 篇")
