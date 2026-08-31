# -*- coding: utf-8 -*-
"""一次性脚本：拉队列中 pubdate=null 的 BV 的发布日期，写入 bv_pubdates.json
key 必须带 BV 前缀（血泪坑）。失败走 Clash 代理，礼貌请求 sleep 1.2s。"""
import json, os, sys, time, urllib.request

DATA = r"E:\qianboshi-agent\data"
QUEUE = os.path.join(DATA, "pipeline_queue.json")
PUBDATES = os.path.join(DATA, "bv_pubdates.json")

def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def save_json(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)

def fetch_pubdate(bvid, proxies=None):
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    if proxies:
        handler = urllib.request.ProxyHandler(proxies)
        opener = urllib.request.build_opener(handler)
    else:
        opener = urllib.request.build_opener()
    with opener.open(req, timeout=15) as r:
        j = json.loads(r.read().decode("utf-8"))
    if j.get("code") != 0:
        return None, f"code={j.get('code')} msg={j.get('message')}"
    d = j["data"]
    return d.get("pubdate"), d.get("title")

def main():
    q = load_json(QUEUE)
    items = q if isinstance(q, list) else q.get("items", q.get("queue", []))
    missing = [it for it in items if it.get("bvid") and not it.get("pubdate")]
    if not missing:
        print("队列中没有 pubdate=null 的任务")
        return

    pubdates = load_json(PUBDATES)
    print(f"待补 {len(missing)} 个 BV")

    proxy_env = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
    ok = 0
    for i, it in enumerate(missing, 1):
        bvid = it["bvid"]
        # 已存在则跳过
        if bvid in pubdates and isinstance(pubdates[bvid], dict) and pubdates[bvid].get("pubdate"):
            print(f"  [{i}/{len(missing)}] {bvid} 已有 pubdate，跳过")
            continue
        pubdate, title = None, None
        for attempt, proxies in enumerate([None, proxy_env]):
            try:
                pubdate, title = fetch_pubdate(bvid, proxies)
                if pubdate:
                    break
            except Exception as e:
                last_err = str(e)[:80]
        if pubdate:
            import datetime
            ds = datetime.datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d")
            pubdates[bvid] = {"pubdate": ds, "title": title or it.get("title") or ""}
            # 同步回队列，让 drain 后续步骤能读到
            it["pubdate"] = ds
            print(f"  [{i}/{len(missing)}] {bvid} -> {ds} | {(title or '')[:30]}")
            ok += 1
        else:
            print(f"  [{i}/{len(missing)}] {bvid} 拉取失败: {last_err}")
        time.sleep(1.2)

    save_json(PUBDATES, pubdates)
    # 队列也同步 pubdate
    with open(QUEUE, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=1)
    print(f"\n完成: 成功 {ok}/{len(missing)}，bv_pubdates.json 现有 {len(pubdates)} 条")

if __name__ == "__main__":
    main()
