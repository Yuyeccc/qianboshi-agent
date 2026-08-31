#!/usr/bin/env python3
"""
清积压队列 — 从 pipeline_queue.json 取最新 N 个任务逐个跑完整管道。

用法:
    python scripts/drain_queue.py --limit 3      # 处理最新3个（推荐先小批量验证）
    python scripts/drain_queue.py --limit 20     # 处理最新20个
    python scripts/drain_queue.py --all          # 处理全部积压
    python scripts/drain_queue.py --status       # 只查看队列状态
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from monitor_bilibili import load_queue, mark_queue_item, run_pipeline_step


def _retryable_tasks(queue, retry_failed=False):
    tasks = []
    skipped = []
    for item in queue:
        status = item.get("status", "queued")
        retry_count = int(item.get("retry_count") or 0)
        if status == "failed" and retry_failed:
            tasks.append(item)
        elif status in ("queued", "failed") and retry_count < 3:
            tasks.append(item)
        elif status == "failed" and retry_count >= 3:
            skipped.append(item)
    return tasks, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3, help="处理数量（默认3）")
    parser.add_argument("--all", action="store_true", help="处理全部积压")
    parser.add_argument("--status", action="store_true", help="只查看队列状态")
    parser.add_argument("--retry-failed", action="store_true", help="强制重试失败任务（忽略3次上限）")
    parser.add_argument("--skip-failed", help="跳过指定失败任务 BVID")
    args = parser.parse_args()

    queue = load_queue()
    if not queue:
        print("✅ 队列为空")
        return

    if args.skip_failed:
        if mark_queue_item(args.skip_failed, "done"):
            print(f"已跳过失败任务: {args.skip_failed}")
        else:
            print(f"未找到任务: {args.skip_failed}")
        return

    print(f"📋 队列共 {len(queue)} 个任务（按发布日期最新优先）")
    for i, item in enumerate(queue[:10], 1):
        pd = item.get("pubdate") or "日期未知"
        status = item.get("status", "queued")
        retry_count = int(item.get("retry_count") or 0)
        print(f"  {i}. [{item.get('analyst', item.get('channel', ''))}] "
              f"{(item.get('title') or item['bvid'])[:45]} ({pd}) "
              f"status={status} retry={retry_count}")

    if args.status:
        return

    available, skipped = _retryable_tasks(queue, retry_failed=args.retry_failed)
    for item in skipped:
        print(f"跳过失败超过3次任务: {item.get('bvid')}，可用 --retry-failed 强制重试")
    tasks = available if args.all else available[:args.limit]
    if not tasks:
        print("没有可处理任务")
        return
    print(f"\n🚀 开始处理 {len(tasks)} 个任务...")

    ok = fail = 0
    for item in tasks:
        bvid = item["bvid"]
        title = item.get("title", "")
        analyst = item.get("analyst", item.get("channel", ""))
        success = run_pipeline_step(bvid, title, analyst)
        if success:
            ok += 1
        else:
            fail += 1

    remaining = len(load_queue())
    print(f"\n✅ 本轮完成: 成功 {ok} / 失败 {fail}，剩余队列 {remaining} 个")
    if remaining:
        print("失败任务仍在队列，可重试")


if __name__ == "__main__":
    main()
