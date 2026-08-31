#!/usr/bin/env python3
"""
批量GPU转写 — 处理最新的N个未转写音频文件

用法:
    python scripts/batch_transcribe_gpu.py              # 处理最新10个
    python scripts/batch_transcribe_gpu.py --count 20   # 处理最新20个
    python scripts/batch_transcribe_gpu.py --all        # 处理全部
"""
import os
import sys
import argparse
import time
from pathlib import Path

# CUDA DLL path fix — must use PATH, not add_dll_directory
_cuda_base = r'C:\Users\1\AppData\Roaming\Python\Python314\site-packages\nvidia'
_cuda_paths = [
    os.path.join(_cuda_base, 'cublas/bin'),
    os.path.join(_cuda_base, 'cuda_nvrtc/bin'),
    os.path.join(_cuda_base, 'cudnn/bin'),
]
for _p in _cuda_paths:
    if os.path.isdir(_p):
        os.environ['PATH'] = _p + os.pathsep + os.environ.get('PATH', '')

from faster_whisper import WhisperModel

PROJ = Path(__file__).parent.parent
AUDIO_DIR = PROJ / "audio"
TRANS_DIR = PROJ / "transcripts"
TRANS_DIR.mkdir(exist_ok=True)


def get_pending_files(max_size_mb=0):
    """获取已下载但未转写的音频文件，按修改时间从新到旧。
    max_size_mb: 跳过大于此大小的文件（0=不限制）"""
    pending = []
    for f in sorted(AUDIO_DIR.glob("*.wav"), key=lambda x: x.stat().st_mtime, reverse=True):
        bv = f.stem
        txt_path = TRANS_DIR / f"{bv}_transcript.txt"
        if txt_path.exists():
            continue
        if max_size_mb > 0 and f.stat().st_size > max_size_mb * 1024 * 1024:
            continue
        pending.append(f)
    return pending


def transcribe_file(model, wav_path, txt_path):
    """转写单个文件"""
    print(f"  🎤 {wav_path.name} ...", end=" ", flush=True)
    try:
        segments, info = model.transcribe(
            str(wav_path), language="zh", beam_size=3, vad_filter=False
        )
        lines = []
        for seg in segments:
            lines.append(f"[{seg.start:.2f}s -> {seg.end:.2f}s] {seg.text.strip()}")
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"✅ {len(lines)} segments ({info.duration:.0f}s)")
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10, help="处理数量")
    parser.add_argument("--all", action="store_true", help="处理全部")
    parser.add_argument("--model", default="small", help="Whisper模型")
    parser.add_argument("--max-size-mb", type=int, default=500, help="跳过大于此MB的文件（0=不限制，默认500）")
    args = parser.parse_args()

    pending = get_pending_files(max_size_mb=args.max_size_mb)
    if args.all:
        count = len(pending)
    else:
        count = min(args.count, len(pending))

    if not pending:
        print("✅ 全部已转写，无待处理文件")
        return

    print(f"📋 待转写: {len(pending)} 个，本次处理 {count} 个")
    print(f"🔧 加载模型: {args.model} (CUDA float16)...")
    model = WhisperModel(args.model, device="cuda", compute_type="float16")
    print(f"🚀 开始转写...\n")

    success = 0
    for i, wav_path in enumerate(pending[:count], 1):
        bv = wav_path.stem
        txt_path = TRANS_DIR / f"{bv}_transcript.txt"
        size_mb = wav_path.stat().st_size / 1024 / 1024
        print(f"[{i}/{count}] {size_mb:.0f}MB", end=" ")
        if transcribe_file(model, wav_path, txt_path):
            success += 1

    print(f"\n{'='*50}")
    print(f"✅ 完成: {success}/{count} 成功")
    print(f"📁 转录输出: {TRANS_DIR}")


if __name__ == "__main__":
    main()
