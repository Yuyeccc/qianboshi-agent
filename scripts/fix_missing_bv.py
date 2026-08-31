#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_missing_bv.py — 补 MISSING_BV 1049（确定性反查，无 LLM）

根因：1049 条 view 来自 notes/深研一点/{分析师}/直播总结 md（source_type=livestream 总结），
导入时无 source_bv。每条 md 正文含《{分析师}直播录像-{日期}-{场次}》视频名，
与 bv_pubdates.json 的 title 精确匹配 → BV（2026-08-30 实测 1049/1049 命中）。

动作（apply 模式）：
- view_provenance: bv_id 填入 + anchor_status='anchored' + ts 解析 + duration_ms + notes 标注
- view_quality_issue: 删除该 view 的 MISSING_BV 记录

用法:
  env -u PYTHONPATH python scripts/fix_missing_bv.py            # dry-run 报告
  env -u PYTHONPATH python scripts/fix_missing_bv.py --apply    # 真实修复
"""
import os, re, json, sqlite3, sys, datetime, shutil
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
JSONL = PROJ / "data" / "views" / "structured_views.jsonl"

APPLY = "--apply" in sys.argv

# --- 反查表：title -> BV ---
bp = json.load(open(PROJ / "data" / "bv_pubdates.json", encoding="utf-8"))
title2bv = {str(v.get("title", "")).strip(): bv for bv, v in bp.items() if isinstance(v, dict) and v.get("title")}
# 音频时长（填 duration_ms 用）
audio_dur = json.load(open(PROJ / "data" / "evidence" / "audio_duration.json", encoding="utf-8"))

PAT = re.compile(r"《([^》]*直播录像[^》]*)》")

def ts_to_ms(t):
    """HH:MM:SS[-HH:MM:SS] -> (start_ms, end_ms)；秒可含小数。失败返回 None。"""
    try:
        s, e = t.split("-")
        def one(x):
            x = x.strip()
            if ":" not in x:
                return None
            parts = [float(p) for p in x.split(":")]
            if len(parts) == 3 and parts[1] < 60 and parts[2] < 60:
                return int((parts[0] * 3600 + parts[1] * 60 + parts[2]) * 1000)
            return None
        sm, em = one(s), one(e)
        if sm is None or em is None:
            return None
        return sm, em
    except Exception:
        return None

def main():
    conn = sqlite3.connect(QB)
    cur = conn.cursor()
    # 目标 view_id（provenance 无 bv_id）
    rows = cur.execute("SELECT view_id FROM view_provenance WHERE bv_id IS NULL OR bv_id=''").fetchall()
    targets = set(r[0] for r in rows)
    print(f"待补 MISSING_BV: {len(targets)}")
    # source_path 索引（jsonl）
    idx = {}
    with open(JSONL, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("view_id") in targets:
                idx[d["view_id"]] = (d.get("source_path", ""), d.get("timestamp", ""))
    # 反查
    found, no_file, no_video, no_title = 0, 0, 0, 0
    plan = []  # (view_id, bv, start_ms, end_ms, duration_ms)
    for vid in sorted(targets):
        sp, ts = idx.get(vid, ("", ""))
        if not sp or not os.path.exists(sp):
            no_file += 1
            continue
        try:
            txt = open(sp, encoding="utf-8").read(2000)
        except Exception:
            no_file += 1
            continue
        m = PAT.search(txt)
        if not m:
            no_video += 1
            continue
        bv = title2bv.get(m.group(1).strip())
        if not bv:
            no_title += 1
            continue
        t = ts_to_ms(ts)
        if bv in audio_dur:
            dur = audio_dur[bv]
        else:
            ev = sqlite3.connect(PROJ / "data" / "evidence" / "qianboshi_evidence.db")
            dur = ev.execute("SELECT MAX(end_ms) FROM transcript_segment WHERE raw_asset_id=?", (bv,)).fetchone()[0]
            ev.close()
        plan.append((vid, bv, t[0] if t else None, t[1] if t else None, dur))
        found += 1
    print(f"反查结果: 命中 {found} / md缺失 {no_file} / 无视频名 {no_video} / 未收录 {no_title}")
    if not APPLY:
        print(f"[dry-run] 将更新 {len(plan)} 条 provenance + 删除对应 MISSING_BV issue")
        for p in plan[:3]:
            print("  样例:", p)
        conn.close()
        return
    # 备份
    bak = QB.with_name(f"qianboshi_quality.db.bak_{datetime.datetime.now():%Y%m%d_%H%M%S}_fix_missing_bv")
    shutil.copy2(QB, bak)
    print(f"备份: {bak}")
    n_ok = 0
    for vid, bv, sm, em, dur in plan:
        if sm is None or em is None:
            cur.execute("UPDATE view_provenance SET bv_id=?, anchor_status='unanchored', notes='bv已补(直播总结md反查),ts未解析' WHERE view_id=?",
                        (bv, vid))
        else:
            cur.execute("""UPDATE view_provenance SET bv_id=?, anchor_status='anchored',
                           anchor_start_ms=?, anchor_end_ms=?, anchor_confidence='high',
                           duration_ms=COALESCE(?, duration_ms), notes='bv从直播总结md视频名反查(2026-08-30)'
                           WHERE view_id=?""", (bv, sm, em, dur, vid))
        cur.execute("DELETE FROM view_quality_issue WHERE view_id=? AND issue_code='MISSING_BV'", (vid,))
        n_ok += 1
    conn.commit()
    # 复核
    left = cur.execute("SELECT COUNT(*) FROM view_provenance WHERE bv_id IS NULL OR bv_id=''").fetchone()[0]
    mbv_left = cur.execute("SELECT COUNT(*) FROM view_quality_issue WHERE issue_code='MISSING_BV'").fetchone()[0]
    print(f"✅ 更新 {n_ok} 条 | 剩余无bv {left} | 剩余MISSING_BV issue {mbv_left}")
    conn.close()

if __name__ == "__main__":
    main()
