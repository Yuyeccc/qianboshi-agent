#!/usr/bin/env python3
"""Dry-run: 分析 990 篇笔记的 date/source/BV 提取可行性，输出三类清单。
本地能修的 / 需B站爬的 / 完全无法修的。不写任何文件。"""
import re, sys, json, io, datetime
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

NOTES = Path(r"E:\obsidian-vault\学习\钱博士")
SM = json.load(io.open(r"E:\qianboshi-agent\data\bv_source_map.json", encoding="utf-8"))
PD = json.load(io.open(r"E:\qianboshi-agent\data\bv_pubdates.json", encoding="utf-8"))

# 已知博主名集合（analyst_uids 的 uname + source_map 的值）
AU = json.load(io.open(r"E:\qianboshi-agent\data\analyst_uids.json", encoding="utf-8"))
known_names = set(v.get("uname", k) for k, v in AU.items())
known_names |= set(SM.values())
KNOWN = sorted(known_names, key=len, reverse=True)

def extract_bv(name, text):
    m = re.search(r"BV[0-9A-Za-z]{8,}", name) or re.search(r"BV[0-9A-Za-z]{8,}", text)
    return m.group(0) if m else None

def parse_name_from_filename(name):
    """从文件名首词解析博主名：'投机大拿 2026.07.20 BVxxx.md' -> 投机大拿"""
    for kn in KNOWN:
        if name.startswith(kn) or f" {kn} " in name:
            return kn
    # 首词中文
    first = name.split(" ")[0]
    if re.search(r"[\u4e00-\u9fff]", first) and "短视频" not in first:
        return first
    return None

def date_from_name(name):
    m = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", name)
    if m:
        try: return datetime.date(int(m[1]), int(m[2]), int(m[3]))
        except: pass
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", name)
    if m:
        try: return datetime.date(int(m[1]), int(m[2]), int(m[3]))
        except: pass
    return None

def date_from_pubdate(bv):
    v = PD.get(bv)
    if not v: return None
    ts = v.get("pubdate") if isinstance(v, dict) else v
    if not ts or not isinstance(ts, (int, float)) or ts <= 0: return None
    return datetime.datetime.fromtimestamp(ts).date()

files = sorted(NOTES.glob("*.md"))
local_ok, need_bili, impossible = [], [], []
for f in files:
    text = f.read_text(encoding="utf-8", errors="replace")
    bv = extract_bv(f.name, text)
    # 博主名：source_map -> 文件名解析
    name = SM.get(bv) if bv else None
    if not name: name = parse_name_from_filename(f.name)
    # 日期：pubdate -> 文件名 -> 正文
    date = date_from_pubdate(bv) if bv else None
    if not date: date = date_from_name(f.name)
    if not date:
        dm = re.search(r"date:\s*(\d{4})-(\d{1,2})-(\d{1,2})", text)
        if dm:
            try: date = datetime.date(int(dm[1]), int(dm[2]), int(dm[3]))
            except: date = None
    if name and date and bv:
        local_ok.append((f.name, bv, name, date))
    elif bv:
        need_bili.append((f.name, bv, bool(name), bool(date)))
    else:
        impossible.append((f.name, name, date))

print(f"总笔记: {len(files)}")
print(f"✅ 本地完整可修: {len(local_ok)}  (name+date+BV 全有)")
print(f"🆘 需B站补爬: {len(need_bili)}")
need_name_missing = sum(1 for x in need_bili if not x[2])
need_date_missing = sum(1 for x in need_bili if not x[3])
print(f"   其中缺博主名: {need_name_missing}, 缺日期: {need_date_missing}")
print(f"❌ 完全无法修: {len(impossible)}")
print()
print("=== 需B站爬的样例 ===")
for x in need_bili[:10]: print(f"  {x[0]}  BV={x[1]}  hasName={x[2]} hasDate={x[3]}")
print()
print("=== 无法修的 ===")
for x in impossible[:10]: print(f"  {x[0]}  name={x[1]} date={x[2]}")
