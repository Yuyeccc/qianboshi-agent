#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
timestamp_validator.py — Phase 0 数据质量闸门 第2步（核心，依赖 gpt-5.6-sol 判定方案）

确定性、零LLM 的时间戳校验器。输入 timestamp_raw + duration_ms，
输出 (status, anchor_start_ms, anchor_end_ms, normalized_ts, reason)。

判定树（gpt 方案，宁标 invalid 不硬修）：
  invalid_format -> unit_ambiguous / unresolvable -> reversed
  -> out_of_duration -> normalized / valid

关键原则：
  - 秒位>59（如 00:02:82）不直接进位：判 unit_ambiguous（可能紧凑毫秒），导候选/人工
  - duration_ms=None 时跳过时长校验
  - 毫秒>3位 / 非整数 → invalid_format
  - 无范围 → point(start=end)
  - 分>59（两段式疑小时被当分）→ unit_ambiguous

解析策略：split 分隔符（-、–、~、空格）成两段，每段各自解析单时间点。
  绕开单个大正则 + alternation group 索引易错的坑。

用法:
  env -u PYTHONPATH python scripts/timestamp_validator.py
"""
import os, re, sqlite3
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
EV = PROJ / "data" / "evidence" / "qianboshi_evidence.db"

# 单个时间点：HH:MM:SS.mmm (三段) 或 MM:SS.mmm (两段)
TOKEN_RE = re.compile(
    r'^(?:(\d{1,4}):(\d{1,2}):(\d{1,3})(?:\.(\d{1,3}))?)$'   # HH:MM:SS.mmm
    r'|^(?:(\d{1,6}):(\d{1,3})(?:\.(\d{1,3}))?)$'            # MM:SS.mmm
)
# 纯秒格式：ASR 泄出的 `1433.00s` / `209.52s`（LLM 抄了 [x.xxs -> y.yys] 时间戳）
SEC_RE = re.compile(r'^(\d{1,7}(?:\.\d{1,3})?)s$')
# 区间分隔符：-、en-dash、em-dash、~、以及可选空格
SEP_RE = re.compile(r'[-–—~]')


def _to_ms(h=None, m=None, s=None, ms=None):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms or 0)


def _to_ms2(m, s, ms=None):
    return (int(m) * 60 + int(s)) * 1000 + int(ms or 0)


def parse_single_token(tok):
    """解析一个时间点 token → dict(ms, sec_overflow, min_overflow) 或 None。
    tok 已去括号/空格。支持 HH:MM:SS / MM:SS / 纯秒 N.Ns。"""
    if not tok:
        return None
    # 纯秒格式（ASR 泄出）：1433.00s / 209.52s → ms
    if SEC_RE.match(tok):
        return {"ms": int(round(float(tok[:-1]) * 1000)),
                "sec_overflow": False, "min_overflow": False}
    m = TOKEN_RE.match(tok)
    if not m:
        return None
    h, mm, s, ms = m.group(1), m.group(2), m.group(3), m.group(4)
    mm2, s2, ms2 = m.group(5), m.group(6), m.group(7)
    sec_overflow = min_overflow = False
    if h is not None:
        if int(mm) > 59 or int(s) > 59:
            sec_overflow = True
        return {"ms": _to_ms(h, mm, s, ms), "sec_overflow": sec_overflow,
                "min_overflow": False}
    if mm2 is not None:
        if int(s2) > 59:
            sec_overflow = True
        if int(mm2) > 59:
            min_overflow = True   # 两段式分钟>59，疑似小时被当分
        return {"ms": _to_ms2(mm2, s2, ms2), "sec_overflow": sec_overflow,
                "min_overflow": min_overflow}
    return None


def parse_ts(raw):
    """解析 timestamp_raw → dict(start_ms,end_ms,is_point,sec_overflow,min_overflow)
    或 None(格式失败)。"""
    if not raw or not str(raw).strip():
        return None
    x = str(raw).strip()
    # 去外层全/半角括号
    x = x.replace('（', '(').replace('）', ')')
    x = re.sub(r'^\(+', '', x)
    x = re.sub(r'\)+$', '', x)
    x = re.sub(r'\s+', ' ', x).strip()
    # split 分隔符
    seps = SEP_RE.split(x)
    parts = [p.strip() for p in seps if p.strip()]
    if len(parts) > 2:
        return None  # 过多段，无法确定
    start = parse_single_token(parts[0])
    if start is None:
        return None
    end = start
    if len(parts) == 2:
        e = parse_single_token(parts[1])
        if e is None:
            return None
        end = e
    return {"start_ms": start["ms"], "end_ms": end["ms"],
            "is_point": start["ms"] == end["ms"],
            "sec_overflow": start["sec_overflow"] or end["sec_overflow"],
            "min_overflow": start["min_overflow"] or end["min_overflow"]}


def validate(raw, duration_ms=None):
    if not raw or not str(raw).strip():
        return _res("invalid_format", "空时间戳")
    x = str(raw).strip()
    p = parse_ts(x)
    if p is None:
        return _res("invalid_format", f"无法解析: {x!r}")
    if p["sec_overflow"]:
        return _res("unit_ambiguous", f"秒/分>59({x!r}) 不直接进位，疑毫秒/帧当秒")
    if p["min_overflow"]:
        return _res("unit_ambiguous", f"分>59({x!r}) 疑似小时被当分")
    start_ms, end_ms = p["start_ms"], p["end_ms"]
    if start_ms > end_ms:
        return _res("reversed", f"start>end: {x}")
    if duration_ms is not None and duration_ms > 0:
        if start_ms > duration_ms or end_ms > duration_ms:
            return _res("out_of_duration", f"超时长({duration_ms}ms): {x}")
    norm = _fmt_range(start_ms, end_ms)
    if _norm(x) != _norm(norm):
        return _res("normalized", f"规范化 {x} -> {norm}", start_ms, end_ms, norm)
    return _res("valid", "格式合法", start_ms, end_ms, norm)


def _res(status, reason, start_ms=None, end_ms=None, norm=None):
    return {"status": status, "start_ms": start_ms, "end_ms": end_ms,
            "normalized_ts": norm, "reason": reason}


def _norm(s):
    return re.sub(r'[\s()]', '', str(s))


def _fmt_range(start_ms, end_ms):
    def f(ms):
        h = ms // 3600000
        m = (ms % 3600000) // 60000
        s = (ms % 60000) // 1000
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{f(start_ms)}-{f(end_ms)}"


def load_duration_map():
    conn = sqlite3.connect(EV)
    cur = conn.cursor()
    dmap = {}
    for bv, mx in cur.execute(
            "SELECT raw_asset_id, MAX(end_ms) FROM transcript_segment GROUP BY raw_asset_id"):
        dmap[bv] = mx
    conn.close()
    return dmap


def main():
    dmap = load_duration_map()
    print(f"[dur] BV 时长映射 {len(dmap)} 条")
    conn = sqlite3.connect(QB)
    cur = conn.cursor()
    # 幂等：清掉上次的 timestamp 相关 issue（保留 resolve 的 MISSING_BV），保证与 provenance 一致
    cur.execute("DELETE FROM view_quality_issue WHERE issue_code LIKE 'TS_%' OR issue_code='INVALID_TS_FORMAT'")
    rows = cur.execute(
        "SELECT view_id, source_bv, timestamp_raw FROM view_raw").fetchall()

    stat = {}
    anchored = 0
    missing_dur = 0
    for view_id, source_bv, ts_raw in rows:
        dur = dmap.get(source_bv)
        if dur is None:
            missing_dur += 1
        r = validate(ts_raw, dur)
        st = r["status"]
        stat[st] = stat.get(st, 0) + 1
        anchor = "anchored" if (r["start_ms"] is not None and source_bv) else "unanchored"
        conf = "high" if st == "valid" else ("medium" if st == "normalized" else "low")
        cur.execute(
            """INSERT INTO view_provenance
               (view_id, bv_id, anchor_status, anchor_start_ms, anchor_end_ms,
                normalized_ts, anchor_confidence, duration_ms, notes)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(view_id) DO UPDATE SET
                 anchor_status=excluded.anchor_status,
                 anchor_start_ms=excluded.anchor_start_ms,
                 anchor_end_ms=excluded.anchor_end_ms,
                 normalized_ts=excluded.normalized_ts,
                 anchor_confidence=excluded.anchor_confidence,
                 duration_ms=excluded.duration_ms,
                 notes=excluded.notes""",
            (view_id, source_bv, anchor, r["start_ms"], r["end_ms"],
             r["normalized_ts"], conf, dur, r["reason"]))
        if anchor == "anchored":
            anchored += 1
        if st not in ("valid", "normalized"):
            cur.execute(
                """INSERT OR IGNORE INTO view_quality_issue
                   (view_id, issue_code, field, raw_value, reason, suggested_status)
                   VALUES (?,?,?,?,?,?)""",
                (view_id, _code_for(st), "timestamp", str(ts_raw)[:120],
                 r["reason"], st))
    conn.commit()

    print("\n=== timestamp 判定分布 ===")
    tot = sum(stat.values())
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print(f"  {k:20s} {v:6d}  ({v/tot*100:.1f}%)")
    print(f"\n  [skipped_duration] BV无transcript时长: {missing_dur}")
    print(f"  [effective] 可锚定: {anchored}/{tot}")
    conn.close()


def _code_for(status):
    return {"invalid_format": "INVALID_TS_FORMAT", "unit_ambiguous": "TS_UNIT_AMBIGUOUS",
            "unresolvable": "TS_UNRESOLVABLE", "reversed": "TS_REVERSED",
            "out_of_duration": "TS_OUT_OF_DURATION"}.get(status, "TS_ISSUE")


if __name__ == "__main__":
    main()
