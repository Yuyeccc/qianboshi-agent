#!/usr/bin/env python3
"""从B站API批量获取所有BV的发布日期"""
import json, requests, re, time, sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
out_path = DATA_DIR / "bv_pubdates.json"

# 收集所有需要查日期的BV
all_bvs = set()
for f in DATA_DIR.glob("*_bvs.json"):
    name = f.name.replace("_bvs.json", "")
    data = json.loads(f.read_text())
    bvs = data if isinstance(data, list) else list(data.keys())
    all_bvs.update(bvs)

# 排除已有深研一点数据
shenyan_meta = {}
if (DATA_DIR / "shenyan_video_meta.json").exists():
    shenyan_meta = json.loads((DATA_DIR / "shenyan_video_meta.json").read_text())
    for bv in shenyan_meta:
        all_bvs.discard(bv)

all_bvs = sorted(all_bvs)
print(f"需查询: {len(all_bvs)} 个BV")

# 加载已有进度
if out_path.exists():
    bv_dates = json.loads(out_path.read_text())
    print(f"已有 {len(bv_dates)} 条缓存")
else:
    bv_dates = {}

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}
PROXIES = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}

success = len(bv_dates)
fail = 0

for i, bv in enumerate(all_bvs):
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
            bv_dates[bv] = {
                "pubdate": v["pubdate"],
                "title": v["title"],
            }
            success += 1
        else:
            bv_dates[bv] = {"error": data.get("message", "unknown")}
            fail += 1
    except Exception as e:
        bv_dates[bv] = {"error": str(e)}
        fail += 1
    
    if (i + 1) % 100 == 0 or i == len(all_bvs) - 1:
        out_path.write_text(json.dumps(bv_dates, ensure_ascii=False, indent=2))
        print(f"进度: {i+1}/{len(all_bvs)}, 成功={success}, 失败={fail}", flush=True)
        time.sleep(0.5)

out_path.write_text(json.dumps(bv_dates, ensure_ascii=False, indent=2))
print(f"\n完成! 成功={success}, 失败={fail}")
print(f"文件: {out_path}")
