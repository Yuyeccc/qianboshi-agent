#!/usr/bin/env python3
"""audio 半年外清理 v2 — 四源日期判断: shenyan_meta → bv_pubdates → 笔记提取 → mtime"""
import os, sys, json, re, glob
from datetime import datetime, date, timedelta

AUDIO = r'E:\qianboshi-agent\audio'
OBSIDIAN = r'E:\obsidian-vault\学习\钱博士'
CUTOFF = date.today() - timedelta(days=180)  # 2026-02-05

bv_date = {}  # BV -> (date, 来源)

# 来源1: shenyan_video_meta.json
try:
    meta = json.load(open(r'E:\qianboshi-agent\data\shenyan_video_meta.json', encoding='utf-8'))
    for bv, v in meta.items():
        if isinstance(v, dict) and v.get('pubdate'):
            bv_date[bv] = (datetime.fromtimestamp(v['pubdate']).date(), 'shenyan_meta')
except Exception as e:
    print('meta ERR', e)

# 来源2: bv_pubdates.json (值可能是 dict 或旧格式)
try:
    pd = json.load(open(r'E:\qianboshi-agent\data\bv_pubdates.json', encoding='utf-8'))
    for bv, v in pd.items():
        if isinstance(v, dict):
            v = v.get('pubdate', 0)
        if isinstance(v, (int, float)) and v > 0:
            bv_date.setdefault(bv, (datetime.fromtimestamp(v).date(), 'pubdates'))
        elif isinstance(v, str) and v[:4] == '20':
            try:
                bv_date.setdefault(bv, (datetime.strptime(v[:10], '%Y-%m-%d').date(), 'pubdates'))
            except Exception:
                pass
except Exception as e:
    print('pubdates ERR', e)

# 来源3: 笔记文件名日期 + 内容BV关联
note_count = 0
for md in glob.glob(os.path.join(OBSIDIAN, '*.md')):
    name = os.path.basename(md)
    m = re.search(r'(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})', name)
    if not m:
        continue
    try:
        nd = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        continue
    try:
        content = open(md, encoding='utf-8').read(2000)
    except Exception:
        continue
    bvm = re.search(r'BV[0-9A-Za-z]{10,}', content)
    if bvm:
        bv_date.setdefault(bvm.group(0), (nd, 'note'))
        note_count += 1
print(f'日期映射: shenyan_meta+pubdates={sum(1 for v in bv_date.values() if v[1] in ("shenyan_meta","pubdates"))}, 笔记关联={note_count}, 总计={len(bv_date)}')

def get_date(fname):
    bv = os.path.splitext(fname)[0]
    if bv in bv_date:
        return bv_date[bv]
    mt = datetime.fromtimestamp(os.path.getmtime(os.path.join(AUDIO, fname))).date()
    return (mt, 'mtime')

to_delete, keep, unknown = [], [], []
for f in sorted(os.listdir(AUDIO)):
    if not f.startswith('BV'):
        continue
    size = os.path.getsize(os.path.join(AUDIO, f))
    d, src = get_date(f)
    if d < CUTOFF:
        to_delete.append((f, d, src, size))
    else:
        keep.append((f, d, src, size))

del_gb = sum(s for *_, s in to_delete) / 1024**3
keep_gb = sum(s for *_, s in keep) / 1024**3
print(f'\n阈值: {CUTOFF}')
print(f'半年外(删除): {len(to_delete)} 个, {del_gb:.1f} GB')
print(f'半年内(保留): {len(keep)} 个, {keep_gb:.1f} GB')
print('删除源分布:', {s: sum(1 for *_, src, _ in to_delete if src == s) for s in set(x[2] for x in to_delete)})
print('保留源分布:', {s: sum(1 for *_, src, _ in keep if src == s) for s in set(x[2] for x in keep)})

if '--execute' in sys.argv:
    print(f'\n执行删除 {len(to_delete)} 个...')
    freed = 0
    for f, d, src, size in to_delete:
        os.remove(os.path.join(AUDIO, f))
        freed += size
    print(f'✅ 已删除, 释放 {freed/1024**3:.1f} GB')
else:
    print('\n[dry-run] 未删除。加 --execute 执行。')
    print('--- 删除列表(按日期倒序, 前30个) ---')
    for f, d, src, size in sorted(to_delete, key=lambda x: x[1], reverse=True)[:30]:
        print(f'  {d} [{src}] {f} ({size/1024**2:.0f}MB)')
    if len(to_delete) > 30:
        print(f'  ... 共 {len(to_delete)} 个')
