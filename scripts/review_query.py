# -*- coding: utf-8 -*-
"""复盘查询: 决策库全景 + 到期未复盘决策"""
import sqlite3, sys, io, json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

db = sqlite3.connect(r"E:\qianboshi-agent\data\qianboshi_decision.db")
db.row_factory = sqlite3.Row
tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("TABLES:", tables)

for t in tables:
    if t.startswith("sqlite_"):
        continue
    print(f"\n===== {t} =====")
    cols = [d[1] for d in db.execute(f"PRAGMA table_info({t})")]
    rows = list(db.execute(f"SELECT * FROM {t}"))
    print("COLS:", cols)
    for r in rows:
        d = dict(zip(cols, r))
        # 截断超长字段
        for k, v in d.items():
            if isinstance(v, str) and len(v) > 120:
                d[k] = v[:120] + "..."
        print(json.dumps(d, ensure_ascii=False, default=str))
