#!/usr/bin/env python3
"""
B站自动监控 — 检测新视频 + 触发流水线

监控源:
  - 深研一点 (UID=179666921): 聚合10+分析师直播录像
  - 笨笨的韭菜 (UID=11473291)
  - 史诗级韭菜 (UID=322005137)
  - 趋势天哥 (UID=1372241958)

用法:
    python monitor_bilibili.py              # 检测新视频
    python monitor_bilibili.py --pipeline   # 检测并自动下载转写
    python monitor_bilibili.py --list 10    # 列出最近视频
"""
import json
import os
import re
import sys
import time
import argparse
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config

# ─── 监控源 ───────────────────────────────────────────────

MONITOR_SOURCES = [
    {"uid": "179666921", "name": "深研一点", "type": "aggregator"},
    {"uid": "11473291",  "name": "笨笨的韭菜", "type": "individual"},
    {"uid": "322005137", "name": "史诗级韭菜", "type": "individual"},
    {"uid": "1372241958","name": "趋势天哥", "type": "individual"},
]

STATE_FILE = Path(__file__).parent.parent / "data" / "monitor_state.json"
QUEUE_FILE = Path(__file__).parent.parent / "data" / "pipeline_queue.json"

# 匹配标题中的日期和分析师
TITLE_DATE_RE = re.compile(r'(\d{4})[-.](\d{1,2})[-.](\d{1,2})')
ANALYST_KEYWORDS = [
    "钱博士", "李一恩", "旗帜鲜明", "任泽平", "投机大拿",
    "柏年说", "主力行为学", "汤山老王", "马跑跑", "财联社",
    "邻居大爷", "八叔不啰嗦", "笨笨的韭菜", "史诗级韭菜", "趋势天哥",
]


# ─── 视频列表获取 (yt-dlp) ───────────────────────────────

def fetch_channel_videos(uid, max_videos=50):
    """
    用 yt-dlp --flat-playlist + cookies 获取频道BV列表。
    """
    cookie_file = Path("/c/Users/1/AppData/Local/hermes/skills/media/bilibili-browser/references/bilibili_cookies.txt")
    url = f"https://space.bilibili.com/{uid}/video"

    cmd = [
        "python", "-m", "yt_dlp",
        "--cookies", str(cookie_file),
        "--flat-playlist", "--dump-json",
        "--playlist-end", str(max_videos),
        "--no-warnings", "--ignore-errors",
        url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                                encoding="utf-8", errors="replace")
        videos = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            try:
                v = json.loads(line)
                bvid = v.get("id", "")
                if bvid:
                    videos.append({"bvid": bvid})
            except json.JSONDecodeError:
                pass
        return videos
    except subprocess.TimeoutExpired:
        return []
    except Exception as e:
        print(f"  yt-dlp: {e}", file=sys.stderr)
        return []


def match_analyst(title):
    for kw in ANALYST_KEYWORDS:
        if kw in title:
            return kw
    return None


# ─── 状态管理 ─────────────────────────────────────────────

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"channels": {}, "processed": []}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── 主逻辑 ───────────────────────────────────────────────

def check_all_sources(state, verbose=True):
    """检查所有监控源，返回新视频列表"""
    all_new = []

    for src in MONITOR_SOURCES:
        uid = src["uid"]
        name = src["name"]
        if verbose:
            print(f"  [{name}] 检查中...", end=" ", file=sys.stderr)

        videos = fetch_channel_videos(uid)
        if not videos:
            print(f"无数据", file=sys.stderr)
            continue

        if verbose:
            print(f"{len(videos)}个视频", file=sys.stderr)

        # 获取该频道的上次最新BV
        last_bvid = state.get("channels", {}).get(uid, {}).get("last_bvid")

        # 找新视频
        channel_new = []
        for v in videos:
            if v["bvid"] == last_bvid:
                break
            if v["bvid"] in state.get("processed", []):
                continue
            analyst = match_analyst(v["title"])
            if analyst or src["type"] == "individual":
                channel_new.append({**v, "uid": uid, "channel": name,
                                    "analyst": analyst or name})

        if channel_new:
            all_new.extend(channel_new)

        # 更新状态
        if videos:
            state.setdefault("channels", {})[uid] = {
                "last_bvid": videos[0]["bvid"],
                "last_check": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "total_videos": len(videos),
            }

    return all_new


def save_queue(new_videos):
    """保存待处理队列"""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    queue = []
    if QUEUE_FILE.exists():
        queue = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))

    # 去重
    existing_bvids = {q["bvid"] for q in queue}
    for v in new_videos:
        if v["bvid"] not in existing_bvids:
            queue.append({
                "bvid": v["bvid"],
                "title": v["title"],
                "analyst": v.get("analyst", v.get("channel", "")),
                "channel": v["channel"],
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })

    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    return queue


def run_pipeline_step(bvid, title, analyst):
    """
    单视频处理流水线:
    1. yt-dlp 下载音频 → audio/
    2. faster-whisper GPU转写 → transcripts/
    3. batch_asr_fix.py 纠错
    4. transcribe_to_note.py LLM结构化 → obsidian
    5. build_vector_db.py --upsert → RAG
    """
    proj = Path(__file__).parent.parent
    url = f"https://www.bilibili.com/video/{bvid}"

    print(f"\n{'='*50}")
    print(f"  处理: [{analyst}] {title[:50]}")
    print(f"  BV: {bvid}")
    print(f"{'='*50}")

    # Step 1: 下载音频
    print("\n[1/5] 下载音频...")
    audio_dir = proj / "audio"
    audio_dir.mkdir(exist_ok=True)

    cookie_file = proj / "data" / "bilibili_cookies.txt"
    dl_cmd = [
        "yt-dlp", "-x", "--audio-format", "wav",
        "-o", str(audio_dir / f"{bvid}.%(ext)s"),
        "--no-playlist", "--no-warnings",
    ]
    if cookie_file.exists():
        dl_cmd.insert(2, "--cookies")
        dl_cmd.insert(3, str(cookie_file))
    dl_cmd.append(url)

    result = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"  ❌ 下载失败: {result.stderr[:200]}")
        return False
    print(f"  ✅ 下载完成")

    # Step 2: GPU转写
    print("\n[2/5] GPU转写 (faster-whisper base)...")
    wav_path = audio_dir / f"{bvid}.wav"
    if not wav_path.exists():
        wav_path = list(audio_dir.glob(f"{bvid}.*"))
        if not wav_path:
            print("  ❌ 找不到音频文件")
            return False
        wav_path = wav_path[0]

    txt_dir = proj / "transcripts"
    txt_dir.mkdir(exist_ok=True)
    txt_path = txt_dir / f"{bvid}_transcript.txt"

    transcribe_cmd = [
        "python", "-c", f"""
import os, sys
base = r'C:\\Users\\1\\AppData\\Roaming\\Python\\Python314\\site-packages\\nvidia'
for sub in ['cublas/bin','cuda_nvrtc/bin','cudnn/bin']:
    p = os.path.join(base, sub)
    if os.path.isdir(p): os.add_dll_directory(p)

from faster_whisper import WhisperModel
model = WhisperModel("base", device="cuda", compute_type="float16")
segments, info = model.transcribe(r"{wav_path}", language="zh", beam_size=3, vad_filter=False)
with open(r"{txt_path}", "w", encoding="utf-8", buffering=1) as f:
    for seg in segments:
        f.write(f"[{{seg.start:.2f}}s -> {{seg.end:.2f}}s] {{seg.text}}\\n")
        f.flush()
print(f"OK {{len(list(segments))}} segments")
"""
    ]
    result = subprocess.run(transcribe_cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"  ❌ 转写失败: {result.stderr[:200]}")
        return False
    print(f"  ✅ 转写完成 → {txt_path.name}")

    # Step 3: ASR纠错
    print("\n[3/5] ASR纠错...")
    fix_result = subprocess.run(
        ["python", str(proj / "scripts" / "batch_asr_fix.py")],
        capture_output=True, text=True, timeout=30,
    )
    print(f"  ✅ 纠错完成")

    # Step 4: LLM结构化
    print("\n[4/5] LLM结构化...")
    struct_result = subprocess.run(
        ["python", str(proj / "scripts" / "transcribe_to_note.py"),
         "--file", f"{bvid}_transcript_corrected.txt"],
        capture_output=True, text=True, timeout=300,
    )
    if struct_result.returncode != 0:
        print(f"  ⚠️ 结构化可能失败: {struct_result.stderr[:200]}")
    else:
        print(f"  ✅ 结构化完成")

    # Step 5: RAG upsert
    print("\n[5/5] RAG增量入库...")
    # 找到生成的文件名
    obsidian_path = proj.parent.parent / "obsidian-vault" / "学习" / "钱博士"
    # 实际上应该从 transcribe_to_note 输出解析文件名
    # 暂时用 --scan
    subprocess.run(
        ["python", str(proj / "scripts" / "build_vector_db.py"), "--scan"],
        capture_output=True, text=True, timeout=30,
    )
    print(f"  ✅ RAG更新完成")

    return True


# ─── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="B站监控+流水线")
    parser.add_argument("--list", type=int, default=0, help="列出最近N个视频")
    parser.add_argument("--pipeline", action="store_true", help="检测新视频并自动处理")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.list:
        for src in MONITOR_SOURCES:
            print(f"\n{'='*50}")
            print(f"  {src['name']} (UID={src['uid']})")
            print(f"{'='*50}")
            videos = fetch_channel_videos(src["uid"], args.list)
            for v in videos[:args.list]:
                print(f"  {v['bvid']}")
        sys.exit(0)

    print("=" * 50)
    print("  B站多源监控 — 深研一点+3独立UP主")
    print("=" * 50)

    state = load_state()

    # 检测新视频
    new_videos = check_all_sources(state, verbose=True)

    if not new_videos:
        print("\n✅ 无新视频")
    else:
        print(f"\n🆕 发现 {len(new_videos)} 个新视频:")
        for v in new_videos:
            print(f"  [{v.get('analyst', v['channel'])}] {v['title'][:50]}")
            print(f"  BV: {v['bvid']}  {v['channel']}")
            print()

        # 保存到队列
        queue = save_queue(new_videos)
        print(f"📋 队列: {len(queue)} 个待处理")

        if args.pipeline:
            print(f"\n🚀 开始自动流水线...")
            for v in new_videos:
                run_pipeline_step(v["bvid"], v["title"],
                                  v.get("analyst", v["channel"]))

    # 保存状态
    state["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_state(state)
    print(f"\n✅ 检查完成: {state['checked_at']}")
