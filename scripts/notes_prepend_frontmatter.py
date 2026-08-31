#!/usr/bin/env python3
"""给 frontmatter 不在文件开头的 21 篇笔记补标准开头 frontmatter。
保留原内容不变；日期/来源从文中已有 frontmatter 提取。"""
import io, sys, re
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

NOTES = Path(r"E:\obsidian-vault\学习\钱博士")
fixed = 0
for f in sorted(NOTES.glob("*.md")):
    text = f.read_text(encoding="utf-8", errors="replace")
    if re.match(r"^---\r?\n", text):
        continue
    # 找文中已有的 frontmatter 块
    m = re.search(r"^---\r?\n(.*?)\r?\n---", text, re.M | re.S)
    if not m:
        print("  SKIP(无内嵌frontmatter):", f.name)
        continue
    fm = m.group(1)
    dm = re.search(r"^date:\s*(\S+)", fm, re.M)
    sm = re.search(r"^source:\s*(.+)$", fm, re.M)
    if not dm:
        print("  SKIP(无date):", f.name)
        continue
    date = dm.group(1)
    source = sm.group(1).strip() if sm else ""
    # 构造标准 frontmatter
    header = f"---\ndate: {date}\n"
    if source:
        header += f"source: {source}\n"
    header += "---\n\n"
    if not text.startswith(header):
        f.write_text(header + text, encoding="utf-8")
        fixed += 1
        print(f"  ✅ {f.name}  date={date} source={source}")
print(f"\n补 frontmatter: {fixed}")
