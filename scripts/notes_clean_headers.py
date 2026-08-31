#!/usr/bin/env python3
"""清理笔记文件头：BOM、开头空行、```markdown 残留围栏。"""
import io, sys, re
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

NOTES = Path(r"E:\obsidian-vault\学习\钱博士")
fixed = 0
for f in sorted(NOTES.glob("*.md")):
    text = f.read_text(encoding="utf-8", errors="replace")
    orig = text
    if text.startswith("\ufeff"):
        text = text[1:]
    m = re.match(r"^(?:\s*\r?\n)+", text)
    if m:
        text = text[m.end():]
    text = re.sub(r"^```markdown\r?\n", "", text)
    text = re.sub(r"^```\r?\n", "", text)
    if text != orig:
        f.write_text(text, encoding="utf-8")
        fixed += 1
print("清洗:", fixed)

bad = []
for f in sorted(NOTES.glob("*.md")):
    t = f.read_text(encoding="utf-8", errors="replace")
    if not re.match(r"^---\r?\n", t):
        bad.append((f.name, repr(t[:40])))
print("frontmatter 不在开头:", len(bad))
for b in bad[:10]:
    print("   ", b)
