#!/usr/bin/env python3
"""
转录→结构化笔记 批处理脚本

用DeepSeek API将ASR纠错后的转录文本转为Obsidian结构化笔记。

用法:
    python transcribe_to_note.py                          # 处理全部未处理的转录
    python transcribe_to_note.py --file BV1xxx.md         # 处理单个
    python transcribe_to_note.py --dry-run                # 预览但不保存
"""
import json
import os
import re
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_llm_config, get_obsidian_path

# ─── Prompt模板 ───────────────────────────────────────────

STRUCTURE_PROMPT = """你是钱博士（B站金融主播）的内容整理助手。请将以下直播转录整理为结构化笔记。

## 要求
1. **忠实还原**: 只整理钱博士实际说过的话，不添加原文没有的信息
2. **标注时间戳**: 每条观点标注原文时间戳（HH:MM格式）
3. **区分确定性与推测**: 明确标注钱博士说"一定/肯定"vs"可能/也许"
4. **提取通用知识**: 把不依赖当日行情的市场规律/分析框架单独列出
5. **忽略闲聊**: 跳过观众互动、打赏、与投资无关的闲聊

## 输出格式

```markdown
---
date: YYYY-MM-DD
type: livestream
source: BV号
---

# 钱博士直播复盘 YYYY.M.D

## 精炼总结
> 用1-2句话总结本场核心观点

## 大盘判断
| 维度 | 判断 | 证据/逻辑 |
|------|------|----------|
| 市场状态 | 牛市/熊市/震荡？ | 引用原文 |
| 短期走势 | 看涨/看跌/横盘？ | 引用原文 |
| 核心矛盾 | 当前市场主要矛盾 | 引用原文 |

## 板块观点
### 板块名1
- **时间**: HH:MM-HH:MM
- **方向**: 看多/看空/中性
- **时限**: 短期/中期/长期
- **核心逻辑**: 用钱博士原话概括
- **确定性**: 高/中/低
- **涉及标的**: 提到的个股/ETF

### 板块名2
（同上）

## 个股/ETF速览
| 标的 | 方向 | 时限 | 核心逻辑 |
|------|------|------|---------|

## 逃顶信号检查
- 放量滞涨: 是否提及 / 具体判断
- 龙头破位: 是否提及 / 具体判断
- 情绪过热: 是否提及 / 具体判断
- 宏观转向: 是否提及 / 具体判断

## 通用知识（不依赖时间的规律/框架）
- 

## 经典语录
- 

## 风险提示
- 本笔记基于直播转录整理，可能有ASR错误
```

如果某部分直播中没有涉及，写"本场未涉及"即可。

以下是直播转录：

{transcript}"""


# ─── 转录预处理 ───────────────────────────────────────────

def clean_transcript(text):
    """清洗转录文本：转时间戳为HH:MM格式，去掉噪声"""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 转换时间戳: [1234.56s -> 1235.78s] → 20:34-20:35
        m = re.match(r'^\[([\d.]+)s\s*[-–>]\s*([\d.]+)s\]\s*(.*)', line)
        if m:
            start_sec = float(m.group(1))
            end_sec = float(m.group(2))
            content = m.group(3).strip()

            # 如果只有时间戳没有内容，跳过
            if not content:
                continue

            # 转秒为 HH:MM:SS（直播通常2h内，从0开始）
            def sec_to_time(s):
                h = int(s // 3600)
                m = int((s % 3600) // 60)
                sec = int(s % 60)
                if h > 0:
                    return f"{h}:{m:02d}:{sec:02d}"
                return f"{m}:{sec:02d}"

            ts = f"[{sec_to_time(start_sec)}]"
            cleaned.append(f"{ts} {content}")
        else:
            cleaned.append(line)

    text = '\n'.join(cleaned)

    # 如果太长，保留前后各40K
    if len(text) > 80000:
        text = text[:40000] + "\n\n... (中间省略) ...\n\n" + text[-40000:]

    return text


def extract_date_from_filename(fname):
    """从文件名提取日期。支持 BVxxx 和 YYYY.M.D 格式"""
    # 格式1: 2026.6.25_transcript_corrected.txt
    m = re.search(r'(\d{4})\.(\d{1,2})\.(\d{1,2})', fname)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # 格式2: 从文件内容提取
    return datetime.now().strftime("%Y-%m-%d")


# ─── API调用 ──────────────────────────────────────────────

def call_deepseek(prompt, llm_config, max_tokens=8000):
    """调用DeepSeek API"""
    import requests

    headers = {
        "Authorization": f"Bearer {llm_config['api_key']}",
        "Content-Type": "application/json",
    }

    body = {
        "model": llm_config["analysis_model"],
        "messages": [
            {"role": "system", "content": "你是专业金融内容整理助手，擅长从直播转录中提取结构化信息。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }

    url = f"{llm_config['api_base']}/chat/completions"
    resp = requests.post(url, headers=headers, json=body, timeout=300)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ─── 主处理 ───────────────────────────────────────────────

def process_one(txt_path, llm_config, obsidian_dir, dry_run=False):
    """处理单个转录文件"""
    fname = txt_path.name
    basename = fname.replace("_transcript_corrected.txt", "").replace("_corrected.txt", "")

    # 检查是否已处理：匹配包含相同日期/BV号的已有笔记
    # 提取标识符：日期(YYYY.M.D) 或 BV号
    date_match = re.search(r'(\d{4}\.\d{1,2}\.\d{1,2})', basename)
    bv_match = re.search(r'(BV[\w]+)', basename)
    identifier = date_match.group(1) if date_match else (bv_match.group(1) if bv_match else basename)

    out_name = f"钱博士直播复盘 {basename}.md"

    # 检查obsidian目录中是否有包含相同标识符的文件
    existing = list(obsidian_dir.glob("*.md"))
    skip = False
    for ex in existing:
        ex_name = ex.name
        if identifier and identifier in ex_name:
            skip = True
            break
        # 也检查BV号匹配（处理带BV和不带BV的命名）
        if bv_match:
            bv = bv_match.group(1)
            if bv in ex_name:
                skip = True
                break

    if skip and not dry_run:
        print(f"  ⏭ 跳过(已存在匹配): {out_name}", file=sys.stderr)
        return True

    out_path = obsidian_dir / out_name
    if out_path.exists() and not dry_run:
        print(f"  ⏭ 跳过(已存在): {out_name}")
        return True

    print(f"  📝 处理: {fname}...")

    # 读取+清洗
    raw = txt_path.read_text(encoding="utf-8")
    transcript = clean_transcript(raw)

    if len(transcript) < 500:
        print(f"  ⚠️ 内容太短({len(transcript)}字)，跳过")
        return False

    print(f"    转录长度: {len(raw)} → 清洗后 {len(transcript)} 字")

    # 调用LLM
    prompt = STRUCTURE_PROMPT.replace("{transcript}", transcript)
    try:
        result = call_deepseek(prompt, llm_config)
    except Exception as e:
        print(f"  ❌ API调用失败: {e}")
        return False

    if dry_run:
        print(f"  [DRY RUN] 生成 {len(result)} 字")
        print(result[:500])
        return True

    # 保存
    out_path.write_text(result, encoding="utf-8")
    print(f"  ✅ → {out_path.name} ({len(result)} 字)")
    return True


def process_all(llm_config, obsidian_dir, transcripts_dir, dry_run=False, limit=0):
    """处理所有未处理的转录"""
    txt_files = sorted(Path(transcripts_dir).glob("*_corrected.txt"))
    total = len(txt_files)
    success = 0

    print(f"共 {total} 份转录\n")

    for i, txt_path in enumerate(txt_files):
        if limit and i >= limit:
            break
        print(f"[{i+1}/{min(total, limit or total)}]", end=" ")
        if process_one(txt_path, llm_config, obsidian_dir, dry_run):
            success += 1
        # 控制频率：每篇等3秒
        if not dry_run:
            time.sleep(3)

    print(f"\n完成: {success}/{min(total, limit or total)} 成功")


# ─── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="转录→结构化笔记")
    parser.add_argument("--file", help="处理单个转录文件")
    parser.add_argument("--dry-run", action="store_true", help="预览不保存")
    parser.add_argument("--limit", type=int, default=0, help="最多处理N份")
    parser.add_argument("--config", help="config.yaml路径")
    args = parser.parse_args()

    config = load_config(args.config)
    llm = get_llm_config(config)

    if not llm["api_key"]:
        print("❌ API key未配置")
        sys.exit(1)

    obsidian_dir = get_obsidian_path(config)
    transcripts_dir = config.get("paths", {}).get("transcripts_dir", "./transcripts")
    if not Path(transcripts_dir).is_absolute():
        transcripts_dir = str(Path(__file__).parent.parent / transcripts_dir)
    transcripts_dir = Path(transcripts_dir)

    print(f"📂 转录: {transcripts_dir}")
    print(f"📂 输出: {obsidian_dir}")
    print(f"🤖 模型: {llm['analysis_model']}")
    print()

    if args.file:
        process_one(transcripts_dir / args.file, llm, obsidian_dir, args.dry_run)
    else:
        process_all(llm, obsidian_dir, transcripts_dir, args.dry_run, args.limit)
