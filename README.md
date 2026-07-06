# 钱博士金融分析Agent 🤖💰

基于钱博士直播回放内容构建的金融分析Agent。自动从B站获取直播回放，转写为文字稿，整理成结构化知识库，并通过RAG实现金融问答。

## 架构

```
B站直播回放 → yt-dlp → 音频下载 → afconvert → WAV → faster-whisper → 文字稿
    → LLM整理 → Obsidian知识库 → ChromaDB向量化 → RAG检索 → 钱博士Agent
```

## 功能

- ✅ **B站直播回放下载** — 自动登录、下载音频
- ✅ **语音转文字** — faster-whisper中文转写
- ✅ **结构化笔记整理** — LLM自动分类归档到Obsidian
- ✅ **RAG问答Agent** — 基于钱博士分析框架的金融问答
- 🔄 **Windows/Mac双平台** — Mac做轻量任务，Windows做重型转写

## 安装

```bash
# 依赖
pip install yt-dlp faster-whisper sentence-transformers chromadb
# Mac用户：无需ffmpeg，使用系统自带afconvert
# Windows用户：需安装ffmpeg
```

## 使用

```python
from qianboshi_agent import QianboshiAgent

agent = QianboshiAgent()
answer = agent.ask("机器人板块现在怎么看？")
print(answer)
# → 使用钱博士的分析框架回答...
```

## 项目结构

```
├── assets/          # 已整理的Obsidian笔记
├── data/            # 音频/文字稿临时文件
├── src/
│   ├── downloader.py    # B站下载
│   ├── transcriber.py   # 语音转文字
│   ├── organizer.py     # LLM笔记整理
│   └── agent.py         # RAG问答Agent
├── config.yaml      # 配置文件
└── README.md
```

## 当前进度

| 日期 | 状态 | 笔记 |
|------|------|------|
| 2026.7.5 | ✅ 已完成 | [查看](assets/) |
| 2026.7.2 | ✅ 已完成 | [查看](assets/) |
| 2026.6.30 | ⏳ 待转写 | — |
| 2026.6.28 | ⏳ 待转写 | — |
| 2026.6.25 | ⏳ 待转写 | — |

## 技术栈

- **下载**: yt-dlp + playwright (B站登录)
- **语音转写**: faster-whisper (small模型)
- **音频处理**: afconvert (Mac) / ffmpeg (Win)
- **向量存储**: ChromaDB + sentence-transformers
- **LLM**: DeepSeek / Claude
- **笔记**: Obsidian Markdown
