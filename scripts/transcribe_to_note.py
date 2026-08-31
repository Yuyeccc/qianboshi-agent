#!/usr/bin/env python3
"""
转录→结构化笔记 批处理脚本 v2.0 (深研一点风格)

用DeepSeek API将ASR纠错后的转录文本转为结构化笔记。
段落+时间戳引用格式，支持多空标注、证据分类、知识分离。

用法:
    python transcribe_to_note.py                          # 处理全部未处理的转录
    python transcribe_to_note.py --file BV1xxx            # 处理单个
    python transcribe_to_note.py --limit 20               # 限制数量
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

STRUCTURE_PROMPT = """你是财经直播内容的结构化整理助手。请将以下直播转录整理为段落+时间戳引用的结构化笔记。

## 核心原则
1. **忠实还原**: 只整理主播实际说过的话，不添加原文没有的信息
2. **段落+证据**: 每个观点先用自己的话概括为一段，然后附上时间戳引用作为证据
3. **多空清晰**: 涉及行情判断时，标注短线/中长线方向（看多🐂📈 / 看空🐻📉 / 中性🦀➡️）
4. **证据分类**: 每条涉及资产/板块的信息，标注依据类型（事实数据 / 逻辑推演 / 陈述观点）
5. **知识分离**: 不依赖当日行情的通用规律、交易技巧、分析框架，归入「内容」部分
6. **忽略闲聊**: 跳过观众互动、打赏、与投资无关的闲聊

## 输出格式

```markdown
---
date: YYYY-MM-DD
source: BV号
---

> 本文基于直播转录整理，可能有ASR错误。总结可能存在遗漏或错误，不能完全反映原视频观点，请以原视频及引用部分为准。

## 精华总结
今日市场：（用1-2段概括当日大盘状态、核心矛盾、主要观点）
宏观事件：（如有外部事件影响市场，简述）
后市观点：（主播对未来走势的判断）
仓位建议：（如有明确仓位管理建议）

## 观点分析

### 板块/资产名1
短线：看多/看空/中性 🐂📈/🐻📉/🦀➡️
逻辑：（用主播原话概括核心逻辑，1-2句）
(00:00:00-00:00:00) 引用原文
(00:00:00-00:00:00) 引用原文

中长线：看多/看空/中性 🐂📈/🐻📉/🦀➡️
逻辑：（1-2句）
(00:00:00-00:00:00) 引用原文

涉及资产：具体标的名称
影响与结果：该资产发生了什么变化
逻辑：原因分析
依据类型：事实数据 / 逻辑推演 / 陈述观点
(00:00:00-00:00:00) 引用原文

### 板块/资产名2
（同上结构，没有涉及的部分就跳过）

## 市场知识
内容：（通用规律、分析框架、交易技巧——即不依赖当日行情的知识）
(00:00:00-00:00:00) 引用原文
```

## 格式规则
- 每个观点必须先概括为一段自然语言，再附时间戳引用
- 观点之间用空行分隔
- 引用格式严格为 `(00:00:00-00:00:00) 原文内容`
- 如果某部分直播中没有涉及，直接跳过不写
- 不要用表格，全部用段落+列表
- 主播说"一定/肯定"的标注确定性高，说"可能/也许"的标注确定性低
- 涉及具体股票代码或名称时，如实保留，不要脱敏

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

    # 如果太长，保留前后各30K
    if len(text) > 60000:
        text = text[:30000] + "\n\n... (中间省略) ...\n\n" + text[-30000:]

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
        # 转写后结构化总结是高频批量任务，用 routine_model(flash) 即可，pro 留给日报/复盘等高质量产出
        "model": llm_config["routine_model"],
        "messages": [
            {"role": "system", "content": "你是专业金融内容整理助手，擅长从直播转录中提取结构化信息。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    # deepseek-v4-flash 是推理模型，默认 reasoning 会吃光 max_tokens 导致 content 为空
    # 智谱glm系列不支持thinking参数（400），仅对deepseek模型附加
    if "deepseek" in str(llm_config.get("routine_model", "")):
        body["thinking"] = {"type": "disabled"}

    url = f"{llm_config['api_base']}/chat/completions"
    resp = requests.post(url, headers=headers, json=body, timeout=600)
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

    # 从BV→来源映射表获取正确名称
    _BV_SOURCE_MAP = None
    def _get_source(bv):
        nonlocal _BV_SOURCE_MAP
        if _BV_SOURCE_MAP is None:
            map_path = Path(__file__).parent.parent / "data" / "bv_source_map.json"
            if map_path.exists():
                import json
                _BV_SOURCE_MAP = json.loads(map_path.read_text(encoding="utf-8"))
            else:
                _BV_SOURCE_MAP = {}
        return _BV_SOURCE_MAP.get(bv, "钱博士")

    out_name = f"{_get_source(basename)} {basename}.md"

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
    
    # 修正 date 字段（从B站API获取准确日期）
    _BV_PUBDATES = None
    def _get_pubdate(bv):
        nonlocal _BV_PUBDATES
        if _BV_PUBDATES is None:
            _BV_PUBDATES = {}
            for p in [Path(__file__).parent.parent / "data" / "bv_pubdates.json",
                      Path(__file__).parent.parent / "data" / "shenyan_video_meta.json"]:
                if p.exists():
                    import json
                    data = json.loads(p.read_text(encoding="utf-8"))
                    for k, v in data.items():
                        if isinstance(v, dict) and "pubdate" in v:
                            _BV_PUBDATES[k] = v["pubdate"]
                        elif isinstance(v, (int, float)) and v > 0:
                            # 兼容裸时间戳格式
                            _BV_PUBDATES[k] = v
        return _BV_PUBDATES.get(bv)
    
    pubdate = _get_pubdate(bv_match.group(1) if bv_match else basename)
    if pubdate:
        from datetime import datetime
        correct_date = datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d")
        text = out_path.read_text(encoding="utf-8")
        dm = re.search(r'^date:\s*(.+)$', text, re.MULTILINE)
        # XX/未知/空 等占位符一律替换为真实日期
        if dm and ("XX" in dm.group(1) or dm.group(1).strip() in ("", "未知", "未提供", "unknown", "无", "未知日期")):
            text = re.sub(r'^date:\s*(.+)$', f"date: {correct_date}", text, count=1, flags=re.MULTILINE)
            out_path.write_text(text, encoding="utf-8")
    
    print(f"  ✅ → {out_path.name} ({len(result)} 字)")
    return True


def process_all(llm_config, obsidian_dir, transcripts_dir, dry_run=False, limit=0, after_date=None):
    """处理所有未处理的转录"""
    txt_files = sorted(Path(transcripts_dir).glob("*_corrected.txt"))
    
    # 按日期过滤（如果指定了 after_date）
    if after_date:
        from datetime import datetime, timezone
        cutoff = datetime.fromisoformat(after_date).replace(tzinfo=timezone.utc) if 'T' in after_date else datetime.strptime(after_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        
        # 加载 pubdate 缓存
        _pubdates = {}
        for p in [Path(__file__).parent.parent / "data" / "bv_pubdates.json",
                  Path(__file__).parent.parent / "data" / "shenyan_video_meta.json"]:
            if p.exists():
                import json
                data = json.loads(p.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if isinstance(v, dict) and "pubdate" in v:
                        _pubdates[k] = v["pubdate"]
                    elif isinstance(v, (int, float)):
                        _pubdates[k] = v
        
        filtered = []
        for cp in txt_files:
            fname = cp.name
            import re as _re
            bv_match = _re.search(r'(BV[0-9A-Za-z]+)', fname)
            bv = bv_match.group(1) if bv_match else None
            pubdate = _pubdates.get(bv) if bv else None
            if pubdate:
                dt = datetime.fromtimestamp(pubdate, tz=timezone.utc)
                if dt >= cutoff:
                    filtered.append(cp)
        txt_files = filtered
    
    total = len(txt_files)
    success = 0

    print(f"共 {total} 份转录\n")

    for i, txt_path in enumerate(txt_files):
        if limit and i >= limit:
            break
        print(f"[{i+1}/{min(total, limit or total)}]", end=" ")
        if process_one(txt_path, llm_config, obsidian_dir, dry_run):
            success += 1
        # 控制频率：每篇等0.3秒（之前0.5秒，降低减少等待）
        if not dry_run:
            time.sleep(0.3)

    print(f"\n完成: {success}/{min(total, limit or total)} 成功")


# ─── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="转录→结构化笔记")
    parser.add_argument("--file", help="处理单个转录文件")
    parser.add_argument("--dry-run", action="store_true", help="预览不保存")
    parser.add_argument("--limit", type=int, default=0, help="最多处理N份")
    parser.add_argument("--config", help="config.yaml路径")
    parser.add_argument("--after-date", help="只处理指定日期后的数据，格式 YYYY-MM-DD（如 2026-01-20）")
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
    print(f"🤖 模型: {llm['routine_model']}（转写总结）")
    print()

    if args.file:
        process_one(transcripts_dir / args.file, llm, obsidian_dir, args.dry_run)
    else:
        process_all(llm, obsidian_dir, transcripts_dir, args.dry_run, args.limit, args.after_date)
