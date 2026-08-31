#!/usr/bin/env python3
"""B站补爬：给缺日期的笔记 BV 号批量拉 pubdate，写回 bv_pubdates.json。
幂等：已有 pubdate 的跳过。用法: python scripts/notes_fetch_bili_dates.py"""
import re, sys, json, io, time, urllib.request
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

NOTES = Path(r"E:\obsidian-vault\学习\钱博士")
PUB_FILE = Path(r"E:\qianboshi-agent\data\bv_pubdates.json")

pub = json.loads(PUB_FILE.read_text(encoding="utf-8"))

# 收集缺日期的 BV（pubdate 不存在或为 0）
def load_cookie():
    cookies = []
    for line in io.open(r"E:\qianboshi-agent\data\bilibili_cookies.txt", encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"): continue
        parts = line.split("\t")
        if len(parts) >= 7: cookies.append(f"{parts[5]}={parts[6]}")
    return "; ".join(cookies)

COOKIE = load_cookie()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Cookie": COOKIE,
    "Referer": "https://www.bilibili.com/",
}

need = set()
for f in NOTES.glob("*.md"):
    text = f.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"BV[0-9A-Za-z]{8,}", f.name) or re.search(r"BV[0-9A-Za-z]{8,}", text)
    if not m: continue
    bv = m.group(0)
    ts = pub.get(bv)
    if isinstance(ts, dict): ts = ts.get("pubdate", 0)
    if not ts or not isinstance(ts, (int, float)) or ts <= 0:
        need.add(bv)

print(f"待爬 BV 数: {len(need)}")
ok = fail = 0
for i, bv in enumerate(sorted(need), 1):
    try:
        req = urllib.request.Request(
            f"https://api.bilibili.com/x/web-interface/view?bvid={bv}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
        if d.get("code") == 0:
            v = d["data"]
            pub[bv] = {"pubdate": v["pubdate"], "title": v.get("title", "")}
            ok += 1
            print(f"  [{i}/{len(need)}] {bv} {v['pubdate']} {v.get('title','')[:30]}")
        else:
            fail += 1
            print(f"  [{i}/{len(need)}] {bv} API code={d.get('code')} {d.get('message')}")
    except Exception as e:
        fail += 1
        print(f"  [{i}/{len(need)}] {bv} ERR {e}")
    time.sleep(0.6)  # 限流保护

PUB_FILE.write_text(json.dumps(pub, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n完成: 成功 {ok}, 失败 {fail}, 已写回 bv_pubdates.json (共 {len(pub)} 条)")
