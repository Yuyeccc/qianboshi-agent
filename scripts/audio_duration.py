#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_duration.py — 生成 audio/WAV 时长映射（BV→duration_ms），供 out_of_duration 修复用。

transcript_segment 的 MAX(end_ms) 可能因转写截断低估时长，导致合法 timestamp 被判 out_of_duration。
改用**真实音频文件时长**（读 WAV 头算，确定性本地，不依赖 API）。

用法:
  env -u PYTHONPATH python scripts/audio_duration.py
"""
import os, json, wave, glob
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
AUDIO_DIR = PROJ / "audio"
OUT = PROJ / "data" / "evidence" / "audio_duration.json"


def wav_duration_ms(path):
    """读 WAV 头算时长（getnframes/framerate），不读全文件。"""
    try:
        with wave.open(str(path), "rb") as w:
            n = w.getnframes()
            fr = w.getframerate()
            if fr <= 0:
                return None
            return int(n / fr * 1000)
    except Exception as e:
        return None


def main():
    files = sorted(glob.glob(str(AUDIO_DIR / "*.wav")))
    print(f"[audio] 扫描 {len(files)} 个 WAV 文件")
    m = {}
    ok = fail = 0
    for i, f in enumerate(files, 1):
        bv = Path(f).stem
        d = wav_duration_ms(f)
        if d and d > 0:
            m[bv] = d
            ok += 1
        else:
            fail += 1
        if i % 100 == 0:
            print(f"  [{i}/{len(files)}] ok={ok} fail={fail}")
            # 写增量
            OUT.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[duration] BV 时长映射 {len(m)} 条 (fail {fail})")
    print(f"  输出: {OUT}")
    # 对比 transcript 时长 vs audio 时长，看低估程度
    import sqlite3
    try:
        e = sqlite3.connect(str(PROJ / "data" / "evidence" / "qianboshi_evidence.db"))
        under = 0
        for bv, ad in m.items():
            row = e.execute("SELECT MAX(end_ms) FROM transcript_segment WHERE raw_asset_id=?", (bv,)).fetchone()
            if row and row[0]:
                if row[0] < ad * 0.9:  # transcript 时长比音频短 >10%
                    under += 1
        e.close()
        print(f"  transcript 低估(比音频短>10%)的 BV: {under}/{len(m)}")
    except Exception as ex:
        print("  对比失败", ex)


if __name__ == "__main__":
    main()
