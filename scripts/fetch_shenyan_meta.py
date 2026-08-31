#!/usr/bin/env python3
"""从B站API获取深研一点视频的标题和发布日期，按批保存"""
import json, requests, re, time, sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
shenyan_bvs = json.loads((DATA_DIR / "shenyan_bvs.json").read_text())
shenyan_bvs = shenyan_bvs if isinstance(shenyan_bvs, list) else list(shenyan_bvs.keys())

# 只保留当前允许进入知识库/监控的分析师；旧分析师不再标注。
ANALYST_PATTERNS = [
    ("钱博士", r"钱博士"),
    ("李一恩", r"李一恩"),
    ("旗帜鲜明", r"旗帜鲜明"),
    ("任泽平", r"任泽平"),
    ("投机大拿", r"投机大拿"),
    ("柏年说", r"柏年说"),
    ("深研一点", r"深研一点"),
    ("财联社", r"财联社"),
]

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}
# 先直连，失败再用代理
PROXIES = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}

out_path = DATA_DIR / "shenyan_video_meta.json"

# 加载已有进度
if out_path.exists():
    bv_meta = json.loads(out_path.read_text())
    print(f"已有 {len(bv_meta)} 条，继续...")
else:
    bv_meta = {}

success = sum(1 for v in bv_meta.values() if "analyst" in v)
fail = sum(1 for v in bv_meta.values() if "error" in v)

for i, bv in enumerate(shenyan_bvs):
    if bv in bv_meta:
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
            title = v["title"]
            pubdate = v["pubdate"]
            
            analyst = None
            for name, pattern in ANALYST_PATTERNS:
                if re.search(pattern, title):
                    analyst = name
                    break
            
            bv_meta[bv] = {
                "title": title,
                "pubdate": pubdate,
                "analyst": analyst or "未知",
            }
            success += 1
        else:
            bv_meta[bv] = {"error": data.get("message", "unknown")}
            fail += 1
    except Exception as e:
        bv_meta[bv] = {"error": str(e)}
        fail += 1
    
    # 每50批保存一次
    if (i + 1) % 50 == 0 or i == len(shenyan_bvs) - 1:
        out_path.write_text(json.dumps(bv_meta, ensure_ascii=False, indent=2))
        done = success + fail
        print(f"进度: {i+1}/{len(shenyan_bvs)}, 成功={success}, 失败={fail}", flush=True)
        time.sleep(0.5)

# 最终保存
out_path.write_text(json.dumps(bv_meta, ensure_ascii=False, indent=2))

analyst_counts = {}
for bv, meta in bv_meta.items():
    a = meta.get("analyst", "未知")
    analyst_counts[a] = analyst_counts.get(a, 0) + 1

print(f"\n完成! 成功={success}, 失败={fail}")
print(f"文件: {out_path}")
for a, c in sorted(analyst_counts.items(), key=lambda x: -x[1]):
    print(f"  {a}: {c}")
