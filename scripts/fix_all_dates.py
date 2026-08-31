#!/usr/bin/env python3
"""只查缺日期的BV"""
import json, requests, re, time
from pathlib import Path
from datetime import datetime

OBSIDIAN = Path("E:/obsidian-vault/学习/钱博士")
DATA_DIR = Path(__file__).parent.parent / "data"
out_path = DATA_DIR / "bv_pubdates.json"

BV_RE = re.compile(r'(BV[\w]+(?:_p\d+)?)')
DATE_FM_RE = re.compile(r'^date:\s*(.+)$', re.MULTILINE)

# 找出缺日期的BV
missing_bvs = set()
for md in OBSIDIAN.glob("*.md"):
    text = md.read_text(encoding="utf-8")
    dm = DATE_FM_RE.search(text)
    d = dm.group(1).strip() if dm else ""
    if d in ("", "未知", "未提供", "unknown", "无"):
        bv_m = BV_RE.search(md.name)
        if bv_m:
            missing_bvs.add(bv_m.group(0))

print(f"缺日期的BV: {len(missing_bvs)} 个")

# 排除已有深研一点数据
shenyan_meta = {}
if (DATA_DIR / "shenyan_video_meta.json").exists():
    shenyan_meta = json.loads((DATA_DIR / "shenyan_video_meta.json").read_text())
    for bv in list(missing_bvs):
        if bv in shenyan_meta and shenyan_meta[bv].get("pubdate"):
            missing_bvs.discard(bv)

print(f"需API查询: {len(missing_bvs)} 个")

# 加载已有缓存
if out_path.exists():
    bv_dates = json.loads(out_path.read_text())
    print(f"已有缓存: {len(bv_dates)} 条")
else:
    bv_dates = {}

missing_bvs = sorted(missing_bvs)
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}
PROXIES = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}

success = sum(1 for v in bv_dates.values() if "pubdate" in v)
fail = 0

for i, bv in enumerate(missing_bvs):
    if bv in bv_dates:
        continue
    
    try:
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
        if data.get("code") != 0:
            r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=10)
            data = r.json()
        
        if data.get("code") == 0:
            v = data["data"]
            bv_dates[bv] = {"pubdate": v["pubdate"], "title": v["title"]}
            success += 1
        else:
            bv_dates[bv] = {"error": data.get("message", "unknown")}
            fail += 1
    except Exception as e:
        bv_dates[bv] = {"error": str(e)}
        fail += 1
    
    if (i + 1) % 50 == 0 or i == len(missing_bvs) - 1:
        out_path.write_text(json.dumps(bv_dates, ensure_ascii=False, indent=2))
        print(f"进度: {i+1}/{len(missing_bvs)}, 成功={success}, 失败={fail}", flush=True)
        time.sleep(0.5)

out_path.write_text(json.dumps(bv_dates, ensure_ascii=False, indent=2))
print(f"\n完成! 成功={success}, 失败={fail}")

# 给笔记补充日期
bv_pubdates = {**bv_dates}
# 合并深研一点数据
for bv, meta in shenyan_meta.items():
    if "pubdate" in meta:
        bv_pubdates[bv] = {"pubdate": meta["pubdate"]}

updated = 0
for md in OBSIDIAN.glob("*.md"):
    text = md.read_text(encoding="utf-8")
    dm = DATE_FM_RE.search(text)
    d = dm.group(1).strip() if dm else ""
    if d in ("", "未知", "未提供", "unknown", "无"):
        bv_m = BV_RE.search(md.name)
        if bv_m:
            bv = bv_m.group(0)
            if bv in bv_pubdates:
                pub = bv_pubdates[bv].get("pubdate")
                if pub:
                    new_date = datetime.fromtimestamp(pub).strftime("%Y-%m-%d")
                    if dm:
                        text = DATE_FM_RE.sub(f"date: {new_date}", text, count=1)
                    else:
                        text = text.replace("---\n", f"---\ndate: {new_date}\n", 1)
                    md.write_text(text, encoding="utf-8")
                    print(f"  ✅ {md.name}: {d} → {new_date}")
                    updated += 1

print(f"\n补充日期: {updated} 篇")
