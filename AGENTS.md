# qianboshi-agent

将钱博士直播回放内容转化为可检索的知识库，搭建金融分析Agent。

## 任务分工
- **Mac**: 轻量任务（问答、资料收集、文字分析）
- **Windows（机械革命笔记本 172.16.2.145）**: 重型任务（视频下载、转写、批量处理）

## 快速开始

```bash
# 1. 下载直播回放音频
python3 -m yt_dlp --cookies /tmp/bilibili_cookies.txt -x --audio-format m4a -o "/tmp/qianboshi_%(date)s.%(ext)s" "BV号"

# 2. Mac转WAV
afconvert input.m4a output.wav -f WAVE -d LEI16@16000 -c 1

# 3. 转写
python3 -c "from faster_whisper import WhisperModel; model=WhisperModel('small',device='cpu',compute_type='int8'); segs,_=model.transcribe('input.wav',language='zh'); [print(f'[{s.start:.0f}s]\t{s.text}') for s in segs]"
```

## 注意事项
- B站下载需先登录获取cookies（playwright扫码）
- HuggingFace被墙时设置 `export HF_ENDPOINT=https://hf-mirror.com`
- 代理SSL冲突时先 `unset http_proxy https_proxy`
