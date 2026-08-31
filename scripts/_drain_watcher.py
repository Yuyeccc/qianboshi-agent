
import json, pathlib, time, datetime

proj = pathlib.Path(r"E:\qianboshi-agent")
queue_file = proj / "data" / "pipeline_queue.json"
prog = proj / "data" / "drain_progress.txt"

while True:
    try:
        q = json.loads(queue_file.read_text(encoding="utf-8"))
        pending = len([x for x in q if x.get("status") in ("queued","running","failed")])
        failed = [x for x in q if x.get("status") == "failed"]
    except Exception as e:
        pending, failed = -1, []
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] 待处理:{pending} 失败:{len(failed)}"
    if failed:
        line += " -> " + ",".join(x["bvid"] for x in failed[:3])
    with open(prog, "a", encoding="utf-8") as f:
        f.write(line + "\n"); f.flush()
    if pending == 0:
        with open(prog, "a", encoding="utf-8") as f:
            f.write("ALL_DONE\n"); f.flush()
        break
    time.sleep(120)
