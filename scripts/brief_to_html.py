# -*- coding: utf-8 -*-
"""日报 md → 精美 HTML（简约高级风，放桌面）"""
import sys
import markdown
from pathlib import Path

CSS = """
:root { --accent:#1a6bff; --bg:#f4f5f7; --card:#ffffff; --text:#2b2f36; --muted:#8a919c; --border:#e6e8ec; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:"Microsoft YaHei","PingFang SC",-apple-system,sans-serif; line-height:1.75; padding:32px 16px; }
.wrap { max-width:860px; margin:0 auto; }
.card { background:var(--card); border-radius:14px; padding:36px 42px; box-shadow:0 2px 14px rgba(20,30,50,.06); }
h1 { font-size:24px; font-weight:700; margin-bottom:6px; }
h2 { font-size:18px; font-weight:700; margin:28px 0 12px; padding-left:12px; border-left:4px solid var(--accent); }
h3 { font-size:15px; font-weight:600; margin:16px 0 8px; }
p { margin:8px 0; }
strong { color:#11151c; }
em { color:var(--muted); font-style:normal; }
table { width:100%; border-collapse:collapse; margin:12px 0; font-size:13.5px; }
th { background:#f0f4ff; color:#1a3a8f; font-weight:600; padding:9px 10px; text-align:left; border:1px solid var(--border); white-space:nowrap; }
td { padding:8px 10px; border:1px solid var(--border); vertical-align:top; }
tr:nth-child(even) td { background:#fafbfc; }
ul,ol { margin:8px 0 8px 22px; }
li { margin:4px 0; }
code { background:#eef1f5; padding:2px 6px; border-radius:4px; font-size:12.5px; color:#0b4fb8; }
hr { border:none; border-top:1px solid var(--border); margin:24px 0; }
blockquote { border-left:4px solid #ffb02e; background:#fffaf0; padding:10px 14px; margin:12px 0; border-radius:0 8px 8px 0; color:#5a4a20; font-size:13.5px; }
a { color:var(--accent); text-decoration:none; }
pre { background:#f6f8fa; padding:12px; border-radius:8px; overflow-x:auto; }
.meta { color:var(--muted); font-size:13px; margin-bottom:18px; }
.footer { text-align:center; color:var(--muted); font-size:12px; margin-top:18px; }
"""

def convert(src: Path, dst: Path) -> None:
    md_text = src.read_text(encoding="utf-8")
    # 提取标题（第一个 # 行）
    first_line = md_text.splitlines()[0] if md_text.splitlines() else ""
    title = first_line.lstrip("# ").strip() if first_line.startswith("#") else src.stem
    html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "nl2br"])
    page = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{CSS}</style></head>
<body><div class="wrap"><div class="card">
{html_body}
<div class="footer">钱博士Agent · 盘前简报 · 观点整理与数据跟踪，不构成投资建议</div>
</div></div></body></html>"""
    dst.write_text(page, encoding="utf-8")
    print(f"✅ 已生成: {dst}")

if __name__ == "__main__":
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".html")
    convert(src, dst)
