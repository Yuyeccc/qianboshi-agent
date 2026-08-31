#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ru_llm.py — #6 reasoning_unit LLM 归并（第一阶段·锚点窗口）

对每个 reasoning_unit_window，调 gpt-5.6-sol 把窗口内 candidate_sentence
归并为 reasoning_unit（unit 类型/topic/inference_type/core_proposition/spans），
服务端拼 source_text（不信 LLM 文本），落 reasoning_unit + source + claim_reasoning_unit。

试点: --limit N（先小样本评估质量）
用法:
  env -u PYTHONPATH python scripts/ru_llm.py --limit 5
"""
import os, re, json, sqlite3, argparse, time, datetime, traceback
import requests, yaml
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
EV = PROJ / "data" / "evidence" / "qianboshi_evidence.db"

SYSTEM = "你是财经直播文本语义归并专家。只输出JSON。"


def stream_chat(prompt, system=SYSTEM, retries=3):
    """调 fluxionai gpt-5.6-sol，走 /v1/responses（Codex wire，不触发 524）。
    chat/completions 在 fluxionai 上报 524 超时会杀进程；responses 接口稳定、输出更长。
    非流式一次读全（responses 接口无需流式）。max_output_tokens 控制长度。

    重试（2026-08-30 加）：524/非200/空内容/异常 都是 fluxionai 服务端偶发限流，
    指数退避重试 retries 次（15s/30s/60s）。另外网关偶发返回 200+错误JSON，
    resp.text 可能是 dict → 强制类型校验，非 str 一律丢弃。"""
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    p = cfg["llm"]["premium"]
    key = open(p["api_key_file"]).read().strip()
    url = f"{p['api_base'].rstrip('/')}/responses"
    body = {"model": p["model"],
            "input": [{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            "max_output_tokens": p.get("max_tokens", 3500),
            "store": False}
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {key}",
                                            "Content-Type": "application/json"},
                              json=body, timeout=600)
            if r.status_code != 200:
                print(f"  [resp {r.status_code}] {r.text[:200]}（attempt {attempt}/{retries}）", flush=True)
                time.sleep(15 * attempt)
                continue
            resp = r.json()
            parts = []
            for o in resp.get("output", []):
                for c in o.get("content", []):
                    if isinstance(c, dict) and c.get("type") == "output_text":
                        t = c.get("text", "")
                        if isinstance(t, str):
                            parts.append(t)
            content = "\n".join(parts)
            if not content:
                t = resp.get("text", "")
                content = t if isinstance(t, str) else ""
            if content and content.strip():
                return content
            print(f"  [resp 200] 空内容（attempt {attempt}/{retries}）", flush=True)
        except Exception as e:
            print(f"  [resp EXC] {e}（attempt {attempt}/{retries}）", flush=True)
        time.sleep(15 * attempt)
    return None


def parse_json(content):
    if not content:
        return None
    if not isinstance(content, str):
        content = str(content)  # 防 200+错误JSON 把 dict 塞进来（w159/w169 根因）
    c = re.sub(r'```(?:json)?', '', content).strip()
    s, e = c.find('{'), c.rfind('}')
    if s == -1 or e == -1:
        return None
    try:
        return json.loads(c[s:e + 1])
    except Exception:
        return None


def build_prompt(cs_list, anno_texts):
    """cs_list: [{id,text,start,end}], anno_texts: 锚点观点摘要。"""
    lines = "\n".join(f"({c['id']}) [{c['start']}-{c['end']}] {c['text']}" for c in cs_list)
    tmpl = """【任务】把窗口内候选句子归并为 reasoning_unit（语义推理单元）。
只输出这个JSON：
{
 "units": [
   {
    "unit_key": "u1",
    "spans": [{"candidate_sentence_id":"cs_xx","char_start":0,"char_end":N}, ...],
    "unit_type": "assertion或reason或evidence或qualification",
    "topic": "主线词",
    "inference_type": "fact|interpretation|correlation|hypothesis|causal_claim|forecast",
    "core_proposition": "该unit的一句话核心判断",
    "support_role": "core_claim|supporting_evidence|reason|qualification|counterpoint",
    "confidence": 0到1
   }, ...
 ],
 "unassigned_candidate_sentence_ids": []
}
规则：1.spans必须连续且引用给定id;2.一个unit一个主要推理中心;3.独立判断/转折/不同inference拆;4.同标的不自动合;5.不确定拆不merge;6.不属于观点的句子放unassigned。"""
    head = f"""给一段直播文本的候选句子序列 + 其锚点观点，归并为 reasoning_unit。
【窗口候选句子】
{lines}
【锚点观点】{anno_texts}
"""
    return head + "\n" + tmpl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--retry-failed", action="store_true",
                    help="先把 failed 窗重置为 pending 再跑（524/空响应 重试）")
    args = ap.parse_args()
    conn = sqlite3.connect(QB); cur = conn.cursor()
    ev = sqlite3.connect(EV); ec = ev.cursor()

    if args.retry_failed:
        n = cur.execute(
            "UPDATE reasoning_unit_window SET status='pending', error_message=NULL, "
            "attempt_count=0 WHERE status='failed'").rowcount
        conn.commit()
        print(f"[ru_llm] --retry-failed: 重置 {n} 个 failed 窗为 pending")

    rows = cur.execute(
        "SELECT window_id,asset_id,start_ms,end_ms,annotation_ids FROM reasoning_unit_window "
        "WHERE status='pending' ORDER BY window_id" + (f" LIMIT {args.limit}" if args.limit else "")).fetchall()
    print(f"[ru_llm] 待归并窗口 {len(rows)}")

    for i, (wid, bv, w_s, w_e, ann_ids) in enumerate(rows, 1):
        try:
            cs = list(ec.execute(
                "SELECT id,start_ms,end_ms,text FROM candidate_sentence "
                "WHERE raw_asset_id=? AND start_ms>=? AND start_ms<=? ORDER BY start_ms",
                (bv, w_s, w_e)))
            cs_list = [{"id": f"cs_{r[0]}", "start": r[1], "end": r[2], "text": r[3]} for r in cs]
            if not cs_list:
                cur.execute("UPDATE reasoning_unit_window SET status='needs_review', error_message='no cs' WHERE window_id=?", (wid,)); conn.commit()
                continue
            # 锚点观点文本
            try:
                ann_ids_list = json.loads(ann_ids) if ann_ids else []
            except Exception:
                ann_ids_list = []
            if not ann_ids_list:
                cur.execute("UPDATE reasoning_unit_window SET status='failed', error_message='no ann', attempt_count=attempt_count+1 WHERE window_id=?", (wid,)); conn.commit()
                print(f"  [{i}] {wid}: 无锚点观点")
                continue
            anno_ts = " | ".join(
                r[0] for r in cur.execute(
                    "SELECT claim FROM view_raw WHERE view_id IN (%s) LIMIT 6" % ",".join("?"*len(ann_ids_list)),
                    ann_ids_list))
            prompt = build_prompt(cs_list, anno_ts[:800])
            content = stream_chat(prompt)
            obj = parse_json(content) if content else None
            if obj is None:
                cur.execute("UPDATE reasoning_unit_window SET status='failed', error_message=?, attempt_count=attempt_count+1 WHERE window_id=?", (str(content)[:200] if content else 'none', wid)); conn.commit()
                print(f"  [{i}] {wid}: JSON失败")
                continue
            # 落库：对每个 unit 生成 reasoning_unit + source
            ru_ids = []
            for u in obj.get("units", []):
                # 收集 span 文本（服务端拼 source_text）
                src_text_bits = []
                order = 0
                # 先插 reasoning_unit 拿到 id
                cid = cur.execute(
                    """INSERT INTO reasoning_unit (asset_id,start_ms,end_ms,source_text,unit_type,topic,
                       inference_type,normalized_proposition,primary_role,authority_level,
                       grouping_confidence,grouping_method,grouping_model,status)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'active')""",
                    (bv, _span_start(u, cs_list), _span_end(u, cs_list), "", u.get("unit_type"),
                     u.get("topic"), u.get("inference_type"), u.get("core_proposition"),
                     u.get("support_role"), "A", u.get("confidence", 0.5), "anchor_llm", "gpt-5.6-sol"))
                ru_id = cid.lastrowid
                for sp in u.get("spans", []):
                    cur.execute(
                        "INSERT INTO reasoning_unit_source (reasoning_unit_id,candidate_sentence_id,char_start,char_end,sentence_order) VALUES (?,?,?,?,?)",
                        (ru_id, sp.get("candidate_sentence_id"), sp.get("char_start", 0), sp.get("char_end", 0), order))
                    order += 1
                # 服务端拼 source_text
                src_text = _splice_text(u, cs_list)
                cur.execute("UPDATE reasoning_unit SET source_text=? WHERE reasoning_unit_id=?", (src_text, ru_id))
                ru_ids.append(ru_id)
                if ru_ids:
                    pass
                # claim_reasoning_unit
                for cid_claim in ann_ids_list:
                    cur.execute(
                        "INSERT OR IGNORE INTO claim_reasoning_unit (claim_id,reasoning_unit_id,relation_role,relation_type,relation_confidence,annotation_id,authority_level,inference_type) VALUES (?,?,?,?,?,?,?,?)",
                        (cid_claim, ru_id, u.get("support_role", "core_claim"), "supports", u.get("confidence", 0.5), cid_claim, "A", u.get("inference_type")))
            cur.execute("UPDATE reasoning_unit_window SET status='succeeded', completed_at=?, attempt_count=attempt_count+1 WHERE window_id=?", (datetime.datetime.now().isoformat(), wid))
            conn.commit()
            print(f"  [{i}] {wid}: {len(obj.get('units', []))} units, {len(ru_ids)} ru")
        except Exception as e:
            try:
                cur.execute("UPDATE reasoning_unit_window SET status='failed', error_message=?, attempt_count=attempt_count+1 WHERE window_id=?", (str(e)[:500], wid)); conn.commit()
            except Exception:
                pass
            traceback.print_exc()
            print(f"  [{i}] {wid}: 异常 {e}")
            continue
    conn.close(); ev.close()


def _span_start(u, cs_list):
    sp = u.get("spans", [])
    if not sp:
        return 0
    csid = sp[0].get("candidate_sentence_id", "")
    for c in cs_list:
        if c["id"] == csid:
            return c["start"]
    return 0


def _span_end(u, cs_list):
    sp = u.get("spans", [])
    if not sp:
        return 0
    csid = sp[-1].get("candidate_sentence_id", "")
    for c in cs_list:
        if c["id"] == csid:
            return c["end"]
    return 0


def _splice_text(u, cs_list):
    """服务端按 spans 拼 source_text（不信 LLM 文本）。第一版用整句拼（char级clause切分后续做）。"""
    parts = []
    seen = set()
    for sp in u.get("spans", []):
        csid = sp.get("candidate_sentence_id", "")
        if csid in seen:
            continue
        seen.add(csid)
        for c in cs_list:
            if c["id"] == csid:
                parts.append(c["text"])
                break
    return "".join(parts)


if __name__ == "__main__":
    main()
