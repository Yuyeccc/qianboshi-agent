#!/usr/bin/env python3
"""笔记全量修复：990 篇
1. 备份整个目录到 E:\\qianboshi-agent\\data\\notes_backup_YYYYMMDD_HHMMSS\\
2. BV 提取：文件名 -> 正文
3. 博主名：bv_source_map -> 文件名首词 -> 内容特征（钱博士直播/短视频）
4. 日期：bv_pubdates -> 文件名 -> 正文 frontmatter
5. 重命名：YYYY-MM-DD （博主名） BV号.md
6. 修 frontmatter：date 写入标准位置，source 统一为博主名
用法: python scripts/notes_fix_all.py [--apply]
不带 --apply = dry-run 只打印计划
"""
import re, sys, json, io, shutil, datetime
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

APPLY = "--apply" in sys.argv
NOTES = Path(r"E:\obsidian-vault\学习\钱博士")
SM = json.load(io.open(r"E:\qianboshi-agent\data\bv_source_map.json", encoding="utf-8"))
PD = json.load(io.open(r"E:\qianboshi-agent\data\bv_pubdates.json", encoding="utf-8"))
AU = json.load(io.open(r"E:\qianboshi-agent\data\analyst_uids.json", encoding="utf-8"))

known_names = set(v.get("uname", k) for k, v in AU.items())
# 已知博主名单（来源：analyst_uids + 标题特征 + source_map 清洗）
known_names |= {"钱博士", "笨笨的韭菜", "趋势天哥", "史诗级韭菜", "投机大拿",
                "旗帜鲜明", "柏年说", "财联社", "李一恩", "任泽平", "主力行为学",
                "汤山老王", "马跑跑", "八叔不啰嗦", "马安强"}
KNOWN = sorted(known_names, key=len, reverse=True)

def parse_name_from_bili(bv):
    """从 bv_pubdates 标题提取博主名：'投机大拿直播录像-2026-07-20-上午场' -> 投机大拿
    只处理直播类标题；短视频/解读类标题（如'阿里巴巴中报解读'）是内容主题不是博主名，返回 None 走降级。"""
    v = PD.get(bv)
    if not isinstance(v, dict): return None
    title = v.get("title", "")
    if not title: return None
    # 已知名单优先（长名在前）
    for kn in KNOWN:
        if kn in title:
            return kn
    # 通用规则：仅直播类标题 'X直播录像' / 'X:直播回放'；短视频/解读类不提取
    m = re.match(r"(.+?)(?:直播录像|:直播|直播回放)", title)
    if m:
        cand = m.group(1).strip()
        if re.search(r"[\u4e00-\u9fff]", cand) and len(cand) <= 8:
            return cand
    return None

def extract_bv(name, text):
    m = re.search(r"BV[0-9A-Za-z]{8,}", name) or re.search(r"BV[0-9A-Za-z]{8,}", text)
    return m.group(0) if m else None

def parse_name(name, text, bv):
    """博主名：B站标题 -> source_map(清洗) -> 文件名首词 -> 内容特征"""
    if bv:
        n = parse_name_from_bili(bv)
        if n: return n
    if bv and bv in SM:
        sv = SM[bv]
        # 清洗脏值：'钱博士短视频'/'钱博士直播' -> '钱博士'；'深研一点'=聚合频道，跳过
        sv_clean = re.sub(r"(直播|短视频|解读|:.*$|录像.*$)", "", sv).strip()
        if sv_clean and sv_clean != "深研一点" and sv_clean in known_names:
            return sv_clean
    for kn in KNOWN:
        if name.startswith(kn) or f" {kn} " in name:
            return kn
    first = name.split(" ")[0]
    if re.search(r"[\u4e00-\u9fff]", first) and "短视频" not in first and "直播" not in first:
        return first
    # 内容特征：短视频解读 = 钱博士
    if "钱博士" in text or "短视频解读" in name or "直播复盘" in name:
        return "钱博士"
    return None

def date_from_bili(bv):
    v = PD.get(bv)
    if not v: return None
    ts = v.get("pubdate") if isinstance(v, dict) else v
    if not ts or not isinstance(ts, (int, float)) or ts <= 0: return None
    return datetime.datetime.fromtimestamp(ts).date()

def date_from_name(name):
    m = re.search(r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})", name)
    if m:
        try: return datetime.date(int(m[1]), int(m[2]), int(m[3]))
        except: pass
    return None

def date_from_text(text):
    m = re.search(r"date:\s*(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        try: return datetime.date(int(m[1]), int(m[2]), int(m[3]))
        except: pass
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text[:500])
    if m:
        try: return datetime.date(int(m[1]), int(m[2]), int(m[3]))
        except: pass
    return None

def fix_frontmatter(text, date, source):
    """统一 frontmatter：date + source 写入标准位置（文件开头 --- 块）。
    保留其余 frontmatter 字段；无 frontmatter 的创建。"""
    iso = date.isoformat()
    # 已有标准 frontmatter
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if m:
        fm = m.group(1)
        body = text[m.end():]
        fm2 = re.sub(r"(?m)^date:.*$", f"date: {iso}", fm)
        if fm2 == fm and not re.search(r"(?m)^date:", fm):
            fm2 += f"\ndate: {iso}"
        fm2 = re.sub(r"(?m)^source:.*$", f"source: {source}", fm2)
        if fm2 == fm and not re.search(r"(?m)^source:", fm):
            fm2 += f"\nsource: {source}"
        return f"---\n{fm2}\n---\n\n{body}"
    # 无标准 frontmatter：正文有 date: 行（藏在标题/引用后）
    m2 = re.search(r"^---\r?\n?.*?^date:.*$", text, re.M)
    has_fm_open = bool(re.search(r"(?m)^---\s*$", text))
    if has_fm_open:
        # 找第一个 --- 之后的 date 行，就地替换；再补 source
        text2 = re.sub(r"(?m)^date:.*$", f"date: {iso}", text, count=1)
        if not re.search(r"(?m)^source:", text2):
            text2 = re.sub(r"(?m)^date:\s*\S+.*$", f"date: {iso}\nsource: {source}", text2, count=1)
        else:
            text2 = re.sub(r"(?m)^source:.*$", f"source: {source}", text2, count=1)
        return text2
    # 完全没有 ---：在文件头创建标准 frontmatter
    return f"---\ndate: {iso}\nsource: {source}\n---\n\n{text}"

files = sorted(NOTES.glob("*.md"))
# 工具文档白名单（正文含 BV 号但不是笔记，禁止改名/改 frontmatter）
TOOL_DOCS = {"B站视频源清单.md"}
plans = []   # (old_name, new_name, bv, name, date, ok)
problems = []
for f in files:
    if f.name in TOOL_DOCS:
        continue
    text = f.read_text(encoding="utf-8", errors="replace")
    bv = extract_bv(f.name, text)
    name = parse_name(f.name, text, bv)
    date = date_from_bili(bv) if bv else None
    if not date: date = date_from_name(f.name)
    if not date: date = date_from_text(text)
    if name and date:
        # 保留分片后缀（长直播拆成 _p1/_p2/...）
        part = ""
        mp = re.search(r"_p\d+$", f.stem)
        if mp: part = mp.group(0)
        new_name = f"{date.isoformat()} （{name}） {bv}{part}.md" if bv else f"{date.isoformat()} （{name}）.md"
        # 历史重复文件（同 BV 多版本）冲突时加 _dup 后缀，不丢数据
        dup = 1
        base = new_name
        while (NOTES / new_name).exists() and (NOTES / new_name) != f:
            new_name = base.replace(".md", f"_dup{dup}.md")
            dup += 1
        plans.append((f.name, new_name, bv, name, date, True))
    else:
        problems.append((f.name, bv, name, date))

print(f"总笔记: {len(files)}, 可修复: {len(plans)}, 有问题: {len(problems)}")
print()
# 预览前 20
for p in plans[:20]:
    flag = "" if p[0] == p[1] else "RENAME"
    print(f"  [{flag:6}] {p[0]}  ->  {p[1]}")
if len(plans) > 20:
    print(f"  ... 还有 {len(plans)-20} 篇")
print()
if problems:
    print("=== 有问题（需人工） ===")
    for p in problems:
        print(f"  {p[0]}  bv={p[1]} name={p[2]} date={p[3]}")

if not APPLY:
    print("\n[dry-run 结束，加 --apply 执行]")
    sys.exit(0)

# ==== 执行 ====
backup_dir = Path(rf"E:\qianboshi-agent\data\notes_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}")
shutil.copytree(NOTES, backup_dir)
print(f"\n✅ 已备份 -> {backup_dir}")

renamed = fixed = skipped = 0
for old_name, new_name, bv, name, date, _ok in plans:
    f = NOTES / old_name
    if old_name == new_name:
        # 只修 frontmatter
        text = f.read_text(encoding="utf-8", errors="replace")
        new_text = fix_frontmatter(text, date, name)
        if new_text != text:
            f.write_text(new_text, encoding="utf-8")
            fixed += 1
        else:
            skipped += 1
        continue
    target = NOTES / new_name
    if target.exists():
        print(f"  ⚠️ 目标已存在，跳过: {new_name}")
        skipped += 1
        continue
    text = f.read_text(encoding="utf-8", errors="replace")
    new_text = fix_frontmatter(text, date, name)
    if new_text != text:
        target.write_text(new_text, encoding="utf-8")
    else:
        target.write_text(text, encoding="utf-8")
    f.unlink()
    renamed += 1
    fixed += 1

print(f"\n✅ 重命名: {renamed}, 修 frontmatter: {fixed}, 跳过: {skipped}")
