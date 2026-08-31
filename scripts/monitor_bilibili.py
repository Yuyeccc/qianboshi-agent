#!/usr/bin/env python3
"""
B站自动监控 — 检测新视频 + 触发流水线 (v3.0 多源统一监控)

监控源 (6个):
  - 深研一点 (179666921):   聚合10+分析师直播录像 (标题需匹配分析师)
  - 笨笨的韭菜 (11473291):  独立UP主
  - 史诗级韭菜 (322005137): 独立UP主
  - 趋势天哥 (1372241958):  独立UP主
  - 钱博士直播 (480741488): 钱博士直播回放
  - 钱博士短视频 (1129838925): 钱博士短视频

用法:
    python monitor_bilibili.py                  # 检测新视频 → 存队列
    python monitor_bilibili.py --dry-run        # 检测但不存队列
    python monitor_bilibili.py --pipeline       # 检测并自动下载转写
    python monitor_bilibili.py --pipeline --limit 3   # 最多处理3个
    python monitor_bilibili.py --list 10        # 列出最近视频
"""
import json
import os
import re
import sys
import time
import argparse
import subprocess
import io
from contextlib import redirect_stderr
from pathlib import Path
from datetime import datetime, date, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config

# ─── 监控源 ───────────────────────────────────────────────

MONITOR_SOURCES = [
    {"uid": "179666921",  "name": "深研一点",     "type": "aggregator"},
    {"uid": "11473291",   "name": "笨笨的韭菜",   "type": "individual"},
    {"uid": "322005137",  "name": "史诗级韭菜",   "type": "individual"},
    {"uid": "1372241958", "name": "趋势天哥",     "type": "individual"},
    {"uid": "480741488",  "name": "钱博士直播",   "type": "individual"},
    {"uid": "1129838925", "name": "钱博士短视频", "type": "individual"},
]

PROJ = Path(__file__).parent.parent
STATE_FILE = PROJ / "data" / "monitor_state.json"
QUEUE_FILE = PROJ / "data" / "pipeline_queue.json"

# 项目依赖的 Python 解释器：优先项目主 Python（有 yt_dlp/faster_whisper），
# 避免 Hermes 桌面运行时 venv python（无这些包）截胡 PATH
_PY_CANDIDATES = [
    r"C:\Python314\python.exe",
    r"C:\Python312\python.exe",
    r"C:\Python311\python.exe",
]
PYTHON_EXE = next((p for p in _PY_CANDIDATES if Path(p).exists()), "python")

# cookie 优先用项目内文件，fallback 到 skill 目录（Windows 原生路径）
_COOKIE_CANDIDATES = [
    PROJ / "data" / "bilibili_cookies.txt",
    Path(r"C:\Users\1\AppData\Local\hermes\skills\media\bilibili-browser\references\bilibili_cookies.txt"),
]

def find_cookie():
    for p in _COOKIE_CANDIDATES:
        if p.exists():
            return p
    return None

# 历史BV锚点文件（首次运行用最新BV去重，防止把历史视频全当新视频）
_BV_ANCHOR_FILES = {
    "179666921": PROJ / "data" / "shenyan_bvs.json",
    "480741488": PROJ / "data" / "qianboshi_live_bvs.json",
    "1129838925": PROJ / "data" / "qianboshi_short_bvs.json",
}

# 匹配标题中的日期和分析师
TITLE_DATE_RE = re.compile(r'(\d{4})[-.](\d{1,2})[-.](\d{1,2})')
ANALYST_KEYWORDS = [
    "钱博士", "李一恩", "旗帜鲜明", "任泽平", "投机大拿", "马安强",
    "柏年说", "财联社", "笨笨的韭菜", "史诗级韭菜", "趋势天哥",
]
BANNED_ANALYST_KEYWORDS = ["主力行为学", "汤山老王", "马跑跑", "邻居大爷", "八叔不啰嗦"]


# ─── 视频列表获取 (yt-dlp) ───────────────────────────────

def _ytdlp(args_list, timeout=30):
    """执行 yt-dlp 命令，返回 (returncode, stdout)"""
    cookie = find_cookie()
    cmd = [PYTHON_EXE, "-m", "yt_dlp", "--no-warnings", "--ignore-errors"]
    if cookie:
        cmd += ["--cookies", str(cookie)]
    cmd += args_list
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, r.stdout.strip()
    except Exception as e:
        print(f"  yt-dlp: {e}", file=sys.stderr)
        return 1, ""


def fetch_channel_videos(uid, max_videos=50, stop_bvid=None, max_titles=10):
    """
    用 yt-dlp --flat-playlist + cookies 获取频道BV列表。
    stop_bvid: 提供时只给"该BV之前"的新视频fetch标题（深研一点聚合频道需要标题匹配分析师）
    max_titles: 最多fetch多少个标题（单个fetch约2-5秒）
    """
    url = f"https://space.bilibili.com/{uid}/video"

    # Stage 1: 获取BV列表 (flat playlist)
    rc, out = _ytdlp(["--flat-playlist", "--print", "%(id)s",
                      "--playlist-end", str(max_videos), url])
    if rc != 0 or not out:
        return []
    bvids = [line.strip() for line in out.split('\n')
             if line.strip() and not line.startswith("ERROR")]
    if not bvids:
        return []
    videos = [{"bvid": b, "title": ""} for b in bvids]

    # Stage 2: 决定哪些视频需要fetch标题
    if stop_bvid:
        need_title = []
        for v in videos:
            if v["bvid"] == stop_bvid:
                break
            need_title.append(v)
        need_title = need_title[:max_titles]
    else:
        need_title = videos[:min(3, max_titles)]

    for v in need_title:
        rc, title = _ytdlp(["--print", "%(title)s",
                            f"https://www.bilibili.com/video/{v['bvid']}"], timeout=15)
        if rc == 0 and title and title != "NA":
            v["title"] = title
    return videos


def match_analyst(title):
    for kw in BANNED_ANALYST_KEYWORDS:
        if kw in title:
            return None
    for kw in ANALYST_KEYWORDS:
        if kw in title:
            return kw
    return None


# ─── 状态管理 ─────────────────────────────────────────────

def load_state():
    state = {"channels": {}, "processed": [], "checked_at": ""}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    state.setdefault("channels", {})
    state.setdefault("processed", [])

    # 首次运行锚点初始化：用历史BVS文件最新BV，防止历史视频被当新视频
    # 只填缺失的频道，不覆盖已有记录
    for uid, bv_file in _BV_ANCHOR_FILES.items():
        if uid in state["channels"]:
            continue
        # 兼容旧格式：深研一点用顶层 last_bvid
        if uid == "179666921" and state.get("last_bvid"):
            state["channels"][uid] = {
                "last_bvid": state["last_bvid"],
                "last_check": "legacy",
                "anchor": True,
            }
            continue
        if bv_file.exists():
            try:
                bvs = json.loads(bv_file.read_text(encoding="utf-8"))
                if bvs:
                    state["channels"][uid] = {
                        "last_bvid": bvs[0],
                        "last_check": "anchor",
                        "anchor": True,
                    }
            except Exception:
                pass
    return state


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── 主逻辑 ───────────────────────────────────────────────

def check_all_sources(state, verbose=True, dry_run=False):
    """检查所有监控源，返回新视频列表。dry_run=True 时不更新状态（纯预览）"""
    all_new = []

    for src in MONITOR_SOURCES:
        uid = src["uid"]
        name = src["name"]
        if verbose:
            print(f"  [{name}] 检查中...", end=" ", file=sys.stderr)

        ch = state["channels"].get(uid, {})
        stop_bvid = ch.get("last_bvid")
        videos = fetch_channel_videos(uid, stop_bvid=stop_bvid,
                                      max_titles=10 if src["type"] == "aggregator" else 3)
        if not videos:
            print("无数据", file=sys.stderr)
            continue
        if verbose:
            print(f"{len(videos)}个视频", file=sys.stderr)

        # 找新视频（直到上次最新BV为止）
        channel_new = []
        for v in videos:
            if v["bvid"] == stop_bvid:
                break
            if v["bvid"] in state.get("processed", []):
                continue
            if stop_bvid is None:
                # 首次无锚点：只收标题可识别分析师的（防历史洪水）
                analyst = match_analyst(v["title"])
                if not analyst and src["type"] == "aggregator":
                    continue
                if not analyst:
                    analyst = name
                channel_new.append({**v, "uid": uid, "channel": name, "analyst": analyst})
                if len(channel_new) >= 10:
                    break
            else:
                analyst = match_analyst(v["title"]) if src["type"] == "aggregator" else name
                if analyst or src["type"] == "individual":
                    channel_new.append({**v, "uid": uid, "channel": name,
                                        "analyst": analyst or name})

        if channel_new:
            all_new.extend(channel_new)

        # 更新状态（dry-run 不更新，保持可重复预览）
        if videos and not dry_run:
            state["channels"][uid] = {
                "last_bvid": videos[0]["bvid"],
                "last_check": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "total_videos": len(videos),
            }
            # 兼容字段：深研一点额外写顶层（旧 cron / 其他脚本读取）
            if uid == "179666921":
                state["last_bvid"] = videos[0]["bvid"]
                state["last_title"] = videos[0]["title"] if videos[0]["title"] else state.get("last_title", "")
                state["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    return all_new


def load_queue():
    """读取待处理队列"""
    if QUEUE_FILE.exists():
        try:
            queue = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
            if not isinstance(queue, list):
                return []
            for item in queue:
                if not isinstance(item, dict):
                    continue
                item.setdefault("status", "queued")
                item.setdefault("retry_count", 0)
            return queue
        except Exception:
            pass
    return []


def _write_queue(queue):
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_queue_item(bvid, status, error=None, retry_count=None):
    """更新队列任务状态，失败任务保留在队列中供重试。"""
    queue = load_queue()
    changed = False
    for item in queue:
        if item.get("bvid") != bvid:
            continue
        item["status"] = status
        item["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if error is not None:
            item["last_error"] = str(error)[:200]
        elif status in {"running", "done"}:
            item.pop("last_error", None)
        if retry_count is not None:
            item["retry_count"] = retry_count
        else:
            item.setdefault("retry_count", 0)
        changed = True
        break
    if changed:
        _write_queue(queue)
    return changed


def remove_from_queue(bvid):
    """从队列移除一个任务（处理过后调用）"""
    queue = load_queue()
    newq = [x for x in queue if x["bvid"] != bvid]
    if len(newq) != len(queue):
        _write_queue(newq)
        return True
    return False


def pop_latest(n=3):
    """取队列中最新（发布日期最晚）的n个任务，不删除。返回list"""
    return load_queue()[:n]


# 发布日期缓存（cron 维护的 BV→pubdate 映射）
_PUBDATES_CACHE = {}
try:
    _pd_file = PROJ / "data" / "bv_pubdates.json"
    if _pd_file.exists():
        _PUBDATES_CACHE = json.loads(_pd_file.read_text(encoding="utf-8"))
except Exception:
    pass


def _guess_pubdate(item):
    """推断发布日期：bv_pubdates缓存 → 标题日期正则。返回 date 或 None"""
    bv = item["bvid"]
    pd = _PUBDATES_CACHE.get(bv)
    if pd:
        if isinstance(pd, (int, float)) and pd > 0:
            return datetime.fromtimestamp(pd).date()
        if isinstance(pd, str) and pd[:4] == "20":
            try:
                return datetime.strptime(pd[:10], "%Y-%m-%d").date()
            except Exception:
                pass
    m = TITLE_DATE_RE.search(item.get("title") or "")
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
    return None


def _queue_sort_key(item):
    """队列排序键：优先发布日期，其次入队时间"""
    pd = item.get("pubdate")
    if pd:
        try:
            return datetime.strptime(pd[:10], "%Y-%m-%d").date()
        except Exception:
            pass
    try:
        return datetime.strptime(item.get("added_at", "")[:10], "%Y-%m-%d").date()
    except Exception:
        return date(1970, 1, 1)


def save_queue(new_videos):
    """保存待处理队列：
    - 半年外的视频直接丢弃（RAG freshness权重0.6，不会检索到，处理=浪费）
    - 按发布日期降序（最新优先处理）
    """
    queue = load_queue()
    existing_bvids = {q["bvid"] for q in queue}
    cutoff = date.today() - timedelta(days=180)

    for v in new_videos:
        if v["bvid"] in existing_bvids:
            continue
        item = {
            "bvid": v["bvid"],
            "title": v["title"],
            "analyst": v.get("analyst", v.get("channel", "")),
            "channel": v["channel"],
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "status": "queued",
            "retry_count": 0,
        }
        pd = _guess_pubdate(item)
        if pd:
            item["pubdate"] = pd.isoformat()
            if pd < cutoff:
                print(f"  ⏭ 跳过半年外视频: {v['bvid']} ({pd}) — RAG不会检索到，不入队",
                      file=sys.stderr)
                continue
        else:
            item["pubdate"] = None
        queue.append(item)
        existing_bvids.add(v["bvid"])

    # 最新优先（降序）
    queue.sort(key=_queue_sort_key, reverse=True)
    _write_queue(queue)
    return queue


def _run_pipeline(bvid, title, analyst):
    """
    单视频处理流水线:
    1. yt-dlp 下载音频 → audio/
    2. faster-whisper GPU转写 → transcripts/ (PATH方式加载CUDA DLL)
    3. batch_asr_fix.py 纠错
    4. transcribe_to_note.py LLM结构化 → obsidian
    5. build_vector_db.py --scan → RAG增量入库
    """
    proj = Path(__file__).parent.parent
    url = f"https://www.bilibili.com/video/{bvid}"

    print(f"\n{'='*50}")
    print(f"  处理: [{analyst}] {(title or bvid)[:50]}")
    print(f"  BV: {bvid}")
    print(f"{'='*50}")

    # Step 1: 下载音频
    print("\n[1/5] 下载音频...")
    audio_dir = proj / "audio"
    audio_dir.mkdir(exist_ok=True)

    dl_cmd = [PYTHON_EXE, "-m", "yt_dlp", "-x", "--audio-format", "wav",
              "-o", str(audio_dir / f"{bvid}.%(ext)s"),
              "--no-playlist", "--no-warnings"]
    cookie = find_cookie()
    if cookie:
        dl_cmd += ["--cookies", str(cookie)]
    dl_cmd.append(url)

    result = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"  ❌ 下载失败: {result.stderr[-200:]}")
        return False
    print("  ✅ 下载完成")

    # Step 2: GPU转写 (PATH方式, 与 batch_transcribe_gpu.py 一致)
    print("\n[2/5] GPU转写 (faster-whisper base)...")
    wav_path = audio_dir / f"{bvid}.wav"
    if not wav_path.exists():
        wavs = list(audio_dir.glob(f"{bvid}.*"))
        if not wavs:
            print("  ❌ 找不到音频文件")
            return False
        wav_path = wavs[0]

    txt_dir = proj / "transcripts"
    txt_dir.mkdir(exist_ok=True)
    txt_path = txt_dir / f"{bvid}_transcript.txt"

    transcribe_cmd = [
        PYTHON_EXE, "-c", f"""
import os, sys
_cuda_base = r'C:\\Users\\1\\AppData\\Roaming\\Python\\Python314\\site-packages\\nvidia'
for _sub in ['cublas/bin', 'cuda_nvrtc/bin', 'cudnn/bin']:
    _p = os.path.join(_cuda_base, _sub)
    if os.path.isdir(_p):
        os.environ['PATH'] = _p + os.pathsep + os.environ.get('PATH', '')

from faster_whisper import WhisperModel
model = WhisperModel("small", device="cuda", compute_type="float16")
segments, info = model.transcribe(r"{wav_path}", language="zh", beam_size=3, vad_filter=False)
with open(r"{txt_path}", "w", encoding="utf-8", buffering=1) as f:
    for seg in segments:
        f.write(f"[{{seg.start:.2f}}s -> {{seg.end:.2f}}s] {{seg.text}}\\n")
        f.flush()
print(f"OK {{info.duration:.0f}}s")
"""
    ]
    result = subprocess.run(transcribe_cmd, capture_output=True, text=True, timeout=1200)
    if result.returncode != 0:
        print(f"  ❌ 转写失败: {result.stderr[-200:]}")
        return False
    print(f"  ✅ 转写完成 → {txt_path.name}")

    # Step 3: ASR纠错（全量增量，幂等）
    print("\n[3/5] ASR纠错...")
    fix_result = subprocess.run(
        [PYTHON_EXE, str(proj / "scripts" / "batch_asr_fix.py")],
        capture_output=True, text=True, timeout=60,
    )
    print("  ✅ 纠错完成")

    # Step 4: LLM结构化
    print("\n[4/5] LLM结构化...")
    struct_result = subprocess.run(
        [PYTHON_EXE, str(proj / "scripts" / "transcribe_to_note.py"),
         "--file", f"{bvid}_transcript_corrected.txt"],
        capture_output=True, text=True, timeout=600,
    )
    if struct_result.returncode != 0:
        print(f"  ⚠️ 结构化可能失败: {struct_result.stderr[-200:]}")
    else:
        print("  ✅ 结构化完成")

    # Step 5: RAG增量入库
    print("\n[5/5] RAG增量入库...")
    subprocess.run(
        [PYTHON_EXE, str(proj / "scripts" / "build_vector_db.py"), "--scan"],
        capture_output=True, text=True, timeout=120,
    )
    print("  ✅ RAG更新完成")

    return True


def run_pipeline_step(bvid, title, analyst):
    """
    处理单个视频（包装 _run_pipeline）。
    成功才从队列移除并记录 processed；失败保留在队列中供重试。
    """
    queue = load_queue()
    current = next((item for item in queue if item.get("bvid") == bvid), {})
    retry_count = int(current.get("retry_count") or 0)
    mark_queue_item(bvid, "running", retry_count=retry_count)
    stderr_buffer = io.StringIO()
    try:
        with redirect_stderr(stderr_buffer):
            ok = _run_pipeline(bvid, title, analyst)
    except Exception as e:
        ok = False
        stderr_buffer.write(str(e))

    if ok:
        state = load_state()
        processed = state.setdefault("processed", [])
        if bvid not in processed:
            processed.append(bvid)
        save_state(state)
        remove_from_queue(bvid)
        return True

    last_error = (stderr_buffer.getvalue().strip() or "pipeline returned False")[:200]
    mark_queue_item(bvid, "failed", error=last_error, retry_count=retry_count + 1)
    print(f"  失败：任务仍在队列，可重试（retry_count={retry_count + 1}）")
    return False


# ─── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="B站多源监控+流水线")
    parser.add_argument("--list", type=int, default=0, help="列出最近N个视频")
    parser.add_argument("--pipeline", action="store_true", help="检测新视频并自动处理")
    parser.add_argument("--limit", type=int, default=3, help="--pipeline时最多处理N个")
    parser.add_argument("--dry-run", action="store_true", help="只检测，不存队列")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.list:
        for src in MONITOR_SOURCES:
            print(f"\n{'='*50}")
            print(f"  {src['name']} (UID={src['uid']})")
            print(f"{'='*50}")
            videos = fetch_channel_videos(src["uid"], args.list, max_titles=3)
            for v in videos[:args.list]:
                t = f"  {v['bvid']}"
                if v["title"]:
                    t += f"  {v['title'][:60]}"
                print(t)
        sys.exit(0)

    print("=" * 50)
    print("  B站多源监控 — 深研一点 + 钱博士直播/短视频 + 3独立UP主")
    print("=" * 50)

    state = load_state()

    # 检测新视频
    new_videos = check_all_sources(state, verbose=True, dry_run=args.dry_run)

    if not new_videos:
        print("\n✅ 无新视频")
    else:
        print(f"\n🆕 发现 {len(new_videos)} 个新视频:")
        for v in new_videos:
            print(f"  [{v.get('analyst', v['channel'])}] {(v['title'] or '(无标题)')[:50]}")
            print(f"  BV: {v['bvid']}  ({v['channel']})")
            print()

        if not args.dry_run:
            queue = save_queue(new_videos)
            print(f"📋 队列: {len(queue)} 个待处理")

        if args.pipeline:
            print(f"\n🚀 开始自动流水线 (最多 {args.limit} 个)...")
            done = 0
            for v in new_videos:
                if done >= args.limit:
                    print(f"\n⏭ 已达上限，剩余 {len(new_videos) - done} 个留在队列")
                    break
                ok = run_pipeline_step(v["bvid"], v["title"],
                                       v.get("analyst", v["channel"]))
                if ok:
                    done += 1
            print(f"\n✅ 流水线完成: 成功处理 {done} 个")

    # 刷新行情缓存（幂等，失败不阻塞；A股收盘后价格落库，供次日日报用）
    # 2026-08-06: 从 --pipeline 分支移出——cron agent 只跑 monitor 不跑 pipeline 时也要刷新
    if not args.dry_run:
        try:
            import importlib
            mc = importlib.import_module("market_cache")
            mc.refresh_all()
            print("  ✅ 行情缓存已刷新")
        except Exception as e:
            print(f"  ⚠️ 行情刷新失败: {e}")

        # 港股行情（2026-08-06 并入：3069.HK 翰森/1801.HK 信达等创新药港股，供决策台港股因子）
        try:
            import subprocess
            hk = subprocess.run(
                [r"C:\Python314\python.exe", "scripts/fetch_hk.py",
                 "--symbols", "3069.HK,1801.HK", "--days", "90"],
                capture_output=True, text=True, timeout=180,
                cwd=str(Path(__file__).resolve().parents[1]),
            )
            tail = (hk.stdout or "").strip().splitlines()[-3:]
            print(f"  ✅ 港股行情已刷新: {' | '.join(tail)}" if hk.returncode == 0 else f"  ⚠️ 港股刷新失败({hk.returncode}): {hk.stderr[-200:]}")
        except Exception as e:
            print(f"  ⚠️ 港股刷新失败: {e}")

        # 结构化观点提取（2026-08-27 并入：笔记→structured_views.jsonl，修复观点断流）
        # merge 模式幂等：新笔记才追加，旧数据不动；失败不阻塞主流程
        try:
            import subprocess
            ve = subprocess.run(
                [r"C:\Python314\python.exe", "scripts/view_extractor.py", "--since", (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")],
                capture_output=True, text=True, timeout=300,
                cwd=str(Path(__file__).resolve().parents[1]),
            )
            if ve.returncode == 0:
                import json as _json
                try:
                    rep = _json.loads((ve.stdout or "{}").split("{", 1)[1].rsplit("}", 1)[0].join(["{", "}"]))
                    print(f"  ✅ 观点提取: +{rep.get('views_added', '?')} 条 (共 {rep.get('views_written', '?')})")
                except Exception:
                    print("  ✅ 观点提取完成")
            else:
                print(f"  ⚠️ 观点提取失败({ve.returncode}): {ve.stderr[-200:]}")
        except Exception as e:
            print(f"  ⚠️ 观点提取失败: {e}")

    # 保存状态
    state["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_state(state)
    print(f"\n✅ 检查完成: {state['checked_at']}")
