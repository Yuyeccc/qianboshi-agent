#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evidence_tagger.py — task2 文本证据命中率真实化 + 维度增补

对已锚定观点：确定性预筛时间窗候选段 → gpt-5.6-sol 选 quote + 标维度
（evidence_authority/inference_type/topic/支持判定）→ 落 view_evidence_annotation。

qianboshi 证据权威四档（直播证据）：
  A 直接原话 / B 近距转述 / C 二手概括 / D 推断(非分析师原话)

用法:
  env -u PYTHONPATH python scripts/evidence_tagger.py [--limit N] [--offset N]
"""
import os, re, json, sys, sqlite3, time, argparse
import requests, yaml
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
EV = PROJ / "data" / "evidence" / "qianboshi_evidence.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS view_evidence_annotation (
  view_id TEXT PRIMARY KEY,
  quote_text TEXT,
  segment_id TEXT,
  anchor_start_ms INTEGER, anchor_end_ms INTEGER,
  evidence_authority TEXT, inference_type TEXT, topic TEXT,
  match_quality REAL, supported INTEGER, reason TEXT,
  model TEXT, created_at TEXT DEFAULT (datetime('now'))
);
"""

SYSTEM = "你是分析师直播观点证据标注员。只输出JSON，不要其他文字。"


def stream_chat(prompt, system=SYSTEM, retries=3):
    """fluxionai stream 调用（非流式必 524）。返回 content 或 None。
    重试（2026-08-30 加）：非200/异常/空内容 → 指数退避 15s/30s/60s，
    治 fluxionai 网关偶发 524/限流（与 ru_llm 同款教训）。"""
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    p = cfg["llm"]["premium"]
    key = open(p["api_key_file"]).read().strip()
    url = f"{p['api_base'].rstrip('/')}/chat/completions"
    body = {"model": p["model"],
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "temperature": 0.3, "max_tokens": p.get("max_tokens", 3500),
            "stream": True}
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {key}",
                                            "Content-Type": "application/json"},
                              json=body, stream=True, timeout=200)
            if r.status_code != 200:
                print(f"  [resp {r.status_code}]（attempt {attempt}/{retries}）", flush=True)
                time.sleep(15 * attempt)
                continue
            content = ""
            # 必须手动 utf-8 解码：decode_unicode=True 会被 ISO-8859-1 误解码导致中文乱码
            for line in r.iter_lines():
                if not line or not line.startswith(b"data:"):
                    continue
                pl = line[5:].strip()
                if pl == b"[DONE]":
                    break
                try:
                    delta = json.loads(pl.decode("utf-8"))["choices"][0]["delta"].get("content", "")
                    if delta:
                        content += delta
                except Exception:
                    pass
            if content and content.strip():
                return content
            print(f"  [resp 200] 空内容（attempt {attempt}/{retries}）", flush=True)
        except Exception as e:
            print(f"  [resp EXC] {e}（attempt {attempt}/{retries}）", flush=True)
        time.sleep(15 * attempt)
    return None


def _parse_json(content):
    """鲁棒提取 JSON：剥围栏，取首个{到末个}。失败返回 None。"""
    if not content:
        return None
    c = re.sub(r'```(?:json)?', '', content).strip()
    s = c.find('{'); e = c.rfind('}')
    if s == -1 or e == -1:
        return None
    try:
        return json.loads(c[s:e + 1])
    except Exception:
        return None


def extract_topics(claim, entities):
    """从实体里挑主题词（因果主线候选）。"""
    kws = []
    if isinstance(entities, dict):
        for key in ("sectors", "themes"):
            for v in (entities.get(key) or []):
                s = str(v)
                if 2 <= len(s) <= 8:
                    kws.append(s)
    return kws[:6]


def prefilter_segments(bv, start_ms, end_ms, topics, ev):
    """确定性预筛：时间窗 ±10s 内候选段；候选过多则按主题词过滤。"""
    lo, hi = max(0, start_ms - 10000), end_ms + 10000
    segs = list(ev.execute(
        "SELECT start_ms,end_ms,text FROM transcript_segment "
        "WHERE raw_asset_id=? AND start_ms IS NOT NULL AND end_ms BETWEEN ? AND ?",
        (bv, lo, hi)))
    if len(segs) > 8 and topics:
        key_segs = [s for s in segs if any(t in s[2] for t in topics)]
        if key_segs:
            segs = key_segs[:8]
    return segs[:12] if len(segs) > 12 else segs


def build_prompt(claim, evidence, entities, segs):
    seg_block = "\n".join(f"[{s[0]}-{s[1]}] {s[2]}" for s in segs)
    ent = json.dumps(entities, ensure_ascii=False) if isinstance(entities, dict) else ""
    tmpl = """【任务-只输出这个JSON】
{
 "quote": "候选段中最能支撑观点的逐字原文(没有则给最接近的,完全无则空字符串)",
 "segment_start_ms": 数字,
 "segment_end_ms": 数字,
 "evidence_authority": "A或B或C或D",
 "inference_type": "fact或interpretation或correlation或hypothesis或causal_claim或forecast",
 "topic": "因果主线必填(1-2个中文词,如半导体/存储/算力/光模块/铝/电池/港股/机器人,无明确主线给'其他')",
 "match_quality": 0到1,
 "supported": true或false,
 "reason": "一句话理由"
}"""
    head = f"""给一条分析师直播观点 + 候选原文段（带时间戳），选出最能支撑观点的 quote 并标维度。
【观点】
claim: {claim}
evidence原文(可能含原始引用): {str(evidence)[:500]}
实体: {ent}
【候选原文段】
{seg_block}"""
    return head + "\n" + tmpl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--since-days", type=int, default=31,
                    help="只看最近N天内的观点（默认31=最近1个月）")
    ap.add_argument("--asc", action="store_true",
                    help="按日期从旧到新(默认最新优先)")
    args = ap.parse_args()

    qb = sqlite3.connect(QB, timeout=60); qc = qb.cursor()  # 60s 锁超时：支持多进程并发标注
    ev = sqlite3.connect(EV); ec = ev.cursor()
    qb.executescript(SCHEMA)  # annotation 表属观点层库
    qb.commit()

    # 取锚定观点：anchor_start_ms 非空 + 最近 N 天内的观点（日期在 raw_json.date）
    import datetime
    since = (datetime.date.today() - datetime.timedelta(days=args.since_days)).isoformat()
    order = "ASC" if args.asc else "DESC"
    rows = qc.execute(
        """SELECT v.view_id, v.claim, v.evidence, v.raw_json, p.bv_id,
                  p.anchor_start_ms, p.anchor_end_ms
           FROM view_raw v JOIN view_provenance p ON p.view_id=v.view_id
           WHERE p.anchor_start_ms IS NOT NULL
             AND COALESCE(json_extract(v.raw_json,'$.date'),'') >= ?
             AND NOT EXISTS (SELECT 1 FROM view_evidence_annotation a WHERE a.view_id = v.view_id)
           ORDER BY json_extract(v.raw_json,'$.date') %s LIMIT ? OFFSET ?""" % order,
        (since, args.limit, args.offset)).fetchall()
    print(f"[tagger] 处理 {len(rows)} 条未标注锚定观点（date>={since}）\n")

    for i, (view_id, claim, evidence, raw_json, bv, s, e) in enumerate(rows, 1):
        try:
            d = json.loads(raw_json)
        except Exception:
            d = {}
        topics = extract_topics(claim, d.get("entities"))
        segs = prefilter_segments(bv, s, e, topics, ec)
        if not segs:
            print(f"  [{i}] {view_id}: 窗口内无候选段，跳过")
            continue
        prompt = build_prompt(claim, evidence, d.get("entities"), segs)
        content = stream_chat(prompt)
        if content is None:
            print(f"  [{i}] {view_id}: premium 失败，跳过")
            continue
        obj = _parse_json(content)
        if obj is None:
            print(f"  [{i}] {view_id}: JSON解析失败: {content[:120]}")
            continue
        st = time.strftime("%Y-%m-%d %H:%M:%S")
        qc.execute(
            """INSERT OR REPLACE INTO view_evidence_annotation
               (view_id, quote_text, segment_id, anchor_start_ms, anchor_end_ms,
                evidence_authority, inference_type, topic, match_quality,
                supported, reason, model, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (view_id, obj.get("quote"), f"{bv}:{obj.get('segment_start_ms')}",
             obj.get("segment_start_ms"), obj.get("segment_end_ms"),
             obj.get("evidence_authority"), obj.get("inference_type"),
             obj.get("topic"), float(obj.get("match_quality") or 0),
             1 if obj.get("supported") else 0, obj.get("reason", ""),
             "gpt-5.6-sol", st))
        qb.commit()
        print(f"  [{i}] {view_id}: auth={obj.get('evidence_authority')} "
              f"inf={obj.get('inference_type')} topic={obj.get('topic')} "
              f"mq={obj.get('match_quality')} supported={obj.get('supported')}")

    # 汇总
    n = qc.execute("SELECT COUNT(*) FROM view_evidence_annotation").fetchone()[0]
    print(f"\n[tagger] 已标注 {n} 条")
    qb.close(); ev.close()


if __name__ == "__main__":
    main()
