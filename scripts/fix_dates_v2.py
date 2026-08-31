#!/usr/bin/env python3
"""快速补完剩余缺失的B站发布日期"""
import json, requests, re, time
from pathlib import Path
from datetime import datetime

OBSIDIAN = Path("E:/obsidian-vault/学习/钱博士")
DATA_DIR = Path(__file__).parent.parent / "data"

# 加载已有缓存
bv_dates = json.loads((DATA_DIR / "bv_pubdates.json").read_text()) if (DATA_DIR / "bv_pubdates.json").exists() else {}
fetched = set(bv_dates.keys())

# 合并深研一点
shenyan = {}
if (DATA_DIR / "shenyan_video_meta.json").exists():
    shenyan = json.loads((DATA_DIR / "shenyan_video_meta.json").read_text())
    for bv in shenyan:
        fetched.add(bv)

# 找出未拉取的
BV_RE = re.compile(r'(BV[\w]+(?:_p\d+)?)')
DATE_RE = re.compile(r'^date:\s*(.+)$', re.MULTILINE)
missing = set()
for md in OBSIDIAN.glob("*.md"):
    text = md.read_text(encoding="utf-8")
    dm = DATE_RE.search(text)
    d = dm.group(1).strip() if dm else ""
    if d in ("", "未知", "未提供", "unknown", "无"):
        bv_m = BV_RE.search(md.name)
        if bv_m:
            bv = bv_m.group(0)
            if bv not in fetched:
                missing.add(bv)

missing = sorted(missing)
print(f"需查询: {len(missing)} 个BV")

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}
PROXIES = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}

new_ok = 0
new_fail = 0

for i, bv in enumerate(missing):
    try:
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
        if data.get("code") != 0:
            r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=10)
            data = r.json()
        
        if data.get("code") == 0:
            bv_dates[bv] = {"pubdate": data["data"]["pubdate"], "title": data["data"]["title"]}
            new_ok += 1
        else:
            bv_dates[bv] = {"error": data.get("message", "unknown")}
            new_fail += 1
    except Exception as e:
        bv_dates[bv] = {"error": str(e)}
        new_fail += 1
    
    if (i + 1) % 50 == 0 or i == len(missing) - 1:
        (DATA_DIR / "bv_pubdates.json").write_text(json.dumps(bv_dates, ensure_ascii=False, indent=2))
        print(f"进度: {i+1}/{len(missing)}, 新成功={new_ok}, 新失败={new_fail}", flush=True)
        time.sleep(0.3)

(DATA_DIR / "bv_pubdates.json").write_text(json.dumps(bv_dates, ensure_ascii=False, indent=2))
print(f"\n拉取完成! 新成功={new_ok}, 新失败={new_fail}")

# 合并所有日期
all_pubdates = {}
for bv, meta in bv_dates.items():
    if "pubdate" in meta:
        all_pubdates[bv] = meta["pubdate"]
for bv, meta in shenyan.items():
    if "pubdate" in meta:
        all_pubdates[bv] = meta["pubdate"]

print(f"总计可用日期: {len(all_pubdates)} 条")

# 补全笔记日期
updated = 0
for md in OBSIDIAN.glob("*.md"):
    text = md.read_text(encoding="utf-8")
    dm = DATE_RE.search(text)
    d = dm.group(1).strip() if dm else ""
    if d in ("", "未知", "未提供", "unknown", "无"):
        bv_m = BV_RE.search(md.name)
        if bv_m:
            bv = bv_m.group(0)
            if bv in all_pubdates:
                new_date = datetime.fromtimestamp(all_pubdates[bv]).strftime("%Y-%m-%d")
                if dm:
                    text = DATE_RE.sub(f"date: {new_date}", text, count=1)
                else:
                    text = text.replace("---\n", f"---\ndate: {new_date}\n", 1)
                md.write_text(text, encoding="utf-8")
                updated += 1

# 最终统计
remaining = 0
for md in OBSIDIAN.glob("*.md"):
    text = md.read_text(encoding="utf-8")
    dm = DATE_RE.search(text)
    d = dm.group(1).strip() if dm else ""
    if d in ("", "未知", "未提供", "unknown", "无"):
        remaining += 1

print(f"补充日期: {updated} 篇")
print(f"仍缺日期: {remaining} 篇")
print(f"总笔记: {len(list(OBSIDIAN.glob('*.md')))}")
