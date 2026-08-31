#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topic_normalize.py — 蓝图#7 因果主线收敛（确定性，零 LLM）

1. 别名归一：topic → 主线词（半导体/光模块/算力/存储/港股/黄金/...）
2. "其他"/空 topic 回填：用 entities.sectors[0]（结构化字段，非猜测）
3. 同步更新 claim.topic + view_evidence_annotation.topic
4. 输出主线分布 + 正负对称（每主线 bullish/bearish/neutral 多空对照）

用法:
  env -u PYTHONPATH python scripts/topic_normalize.py            # dry-run
  env -u PYTHONPATH python scripts/topic_normalize.py --apply    # 落库
"""
import sqlite3, json, sys
from pathlib import Path
from collections import Counter, defaultdict

PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
APPLY = "--apply" in sys.argv

# 别名表：子词 → 主线（前缀匹配，越长的越先匹配）
ALIASES = [
    ("人形机器人", "机器人"), ("商业航天", "商业航天"), ("光模块", "光模块"), ("CPO", "光模块"),
    ("光通信", "光模块"), ("先进制程", "半导体"), ("半导体", "半导体"), ("芯片", "半导体"),
    ("晶圆", "半导体"), ("存储", "存储"), ("内存", "存储"), ("闪存", "存储"), ("DRAM", "存储"),
    ("液冷", "算力"), ("算力", "算力"), ("服务器", "算力"), ("恒生科技", "港股"), ("恒指", "港股"),
    ("港股", "港股"), ("黄金", "黄金"), ("贵金属", "黄金"), ("金价", "黄金"), ("有色", "资源品"),
    ("资源品", "资源品"), ("铝", "铝"), ("铜", "铜"), ("创新药", "医药"), ("医药", "医药"),
    ("生物医药", "医药"), ("大金融", "大金融"), ("证券", "大金融"), ("券商", "大金融"),
    ("银行", "大金融"), ("保险", "大金融"), ("机器人", "机器人"), ("机器狗", "机器人"),
    ("航天", "商业航天"), ("卫星", "商业航天"), ("大消费", "大消费"), ("消费", "大消费"),
    ("白酒", "大消费"), ("茶饮", "大消费"), ("房地产", "房地产"), ("地产", "房地产"),
    ("军工", "军工"), ("国防", "军工"), ("汽车", "汽车"), ("新能源车", "汽车"),
    ("PCB", "PCB"), ("软件", "软件"), ("量化", "量化"), ("创业板", "大盘"), ("A股", "大盘"),
    ("股市", "大盘"), ("大盘", "大盘"), ("指数", "大盘"), ("美股", "美股"), ("科技", "科技"),
    ("能源", "能源"), ("油气", "能源"), ("铀矿", "能源"), ("通胀", "通胀"),
]


def normalize(topic):
    if not topic or topic.strip() in ("", "其他"):
        return None
    t = topic.strip()
    for sub, main in ALIASES:
        if t == sub or t.startswith(sub) or sub in t:
            return main
    return t


def main():
    conn = sqlite3.connect(QB)
    cur = conn.cursor()
    # 取 claim topic + entities
    rows = cur.execute("""SELECT c.view_id, c.topic, v.raw_json FROM claim c
                          JOIN view_raw v ON v.view_id=c.view_id""").fetchall()
    updates = []  # (view_id, new_topic, old_topic)
    stats = Counter()
    backfill = 0
    for vid, topic, raw in rows:
        new_t = normalize(topic)
        if new_t is None:
            # 回填：entities.sectors[0]
            try:
                d = json.loads(raw)
            except Exception:
                d = {}
            s = (d.get("entities") or {}).get("sectors") or []
            if s:
                new_t = normalize(s[0])
            if new_t is None:
                new_t = "其他"
            backfill += 1
        if new_t != topic:
            updates.append((vid, new_t, topic))
        stats[new_t] += 1
    print(f"归一前 topic 去重: {len(set(r[1] for r in rows))} | 归一后: {len(stats)}")
    print(f"需更新 {len(updates)} 条（其中 '其他'/空 回填 {backfill}）")
    print("\n=== 主线分布 top20 ===")
    for k, v in stats.most_common(20):
        print(f"  {k}: {v}")
    if not APPLY:
        print("\n[dry-run] 未落库。--apply 后同步 claim + annotation 的 topic")
        conn.close()
        return
    # 落库 claim + annotation
    n1 = n2 = 0
    for vid, new_t, old_t in updates:
        n1 += cur.execute("UPDATE claim SET topic=?, updated_at=datetime('now') WHERE view_id=?", (new_t, vid)).rowcount
        n2 += cur.execute("UPDATE view_evidence_annotation SET topic=? WHERE view_id=?", (new_t, vid)).rowcount
    conn.commit()
    print(f"\n✅ 更新 claim {n1} 条 / annotation {n2} 条")
    # 多空对称报告
    print("\n=== 主线多空对称（top10）===")
    st = defaultdict(Counter)
    upd_map = {u[0]: u[1] for u in updates}
    for vid, topic, raw in rows:
        nt = upd_map.get(vid, topic)
        strow = cur.execute("SELECT stance FROM claim WHERE view_id=?", (vid,)).fetchone()
        st[nt][strow[0] if strow else 'neutral'] += 1
    for k in [x[0] for x in stats.most_common(10)]:
        c = st[k]
        print(f"  {k}: 多 {c['bullish']} / 空 {c['bearish']} / 中 {c['neutral']} / risk {c['risk']} / watch {c['watch']}")
    conn.close()


if __name__ == "__main__":
    main()
