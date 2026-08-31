#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qb_ru_watch.py — DB 轮询 watchdog：判断 ru_llm 归并进行/完成/停滞。

不依赖 Hermes 进程跟踪（ap 不可靠），只看证据库真实状态。
- 每 60s 查 reasoning_unit_window succeeded/pending + reasoning_unit 数
- pending==0 → 写完成标志文件并退出
- 连续 7 分钟 succeeded 无增长 → 写停滞标志文件并退出

用法: env -u PYTHONPATH python scripts/qb_ru_watch.py
"""
import sqlite3, time, datetime, os
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
# 2026-08-30 修：/c/tmp 是 MSYS 路径，Windows 原生 python 解析成 E:\c\tmp 不存在 → 写标志文件崩
TMP = Path("C:/tmp") if os.path.isdir("C:/tmp") else PROJ / "data"
WATCH = TMP / "qb_ru_watch.log"
DONE_FLAG = TMP / "qb_ru.done"
STALL_FLAG = TMP / "qb_ru.stalled"

last = -1
stall = 0
while True:
    try:
        q = sqlite3.connect(QB)
        c = q.cursor()
        done = c.execute("SELECT COUNT(*) FROM reasoning_unit_window WHERE status='succeeded'").fetchone()[0]
        pend = c.execute("SELECT COUNT(*) FROM reasoning_unit_window WHERE status='pending'").fetchone()[0]
        ru = c.execute("SELECT COUNT(*) FROM reasoning_unit WHERE status='active'").fetchone()[0]
        q.close()
    except Exception as e:
        done, pend, ru = -1, -1, -1
        print(f"[watch] DB 读取异常: {e}")
        time.sleep(60); continue

    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"{ts}  succeeded={done}  pending={pend}  reasoning_unit={ru}"
    print(line, flush=True)
    with open(WATCH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    if done >= 0 and pend == 0:
        with open(DONE_FLAG, "w", encoding="utf-8") as f:
            f.write(f"COMPLETE  succeeded={done} pending={pend} ru={ru}")
        print("[watch] ✅ 归并完成（pending=0）", flush=True)
        break

    if done == last:
        stall += 1
    else:
        stall = 0
    last = done
    if stall >= 7:  # 7 分钟无增长 → 疑似进程死亡
        with open(STALL_FLAG, "w", encoding="utf-8") as f:
            f.write(f"STALLED  succeeded={done} pending={pend} ru={ru}")
        print("[watch] ⚠️ 归并停滞（连续7分钟 succeeded 无增长），疑似进程死亡", flush=True)
        break
    time.sleep(60)
