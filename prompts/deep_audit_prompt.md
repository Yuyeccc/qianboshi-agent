# 任务：深度分析钱博士Agent的可优化点

你是资深AI系统架构师 + 量化投研系统专家。请深度分析下面这个金融内容Agent系统，找出所有可优化的点，**必须适配下述真实业务需求**。输出要具体、可落地，禁止泛泛而谈（"加强缓存""优化提示词"这种不算方案，必须给出怎么做）。

## 一、系统现状

钱博士Agent：B站财经直播自动处理系统，四层架构：

【采集层】monitor_bilibili.py(365行) — 监控B站频道→检测新直播→yt-dlp下载音频；monitor_state.json做断点续传(last_bvid/跳过列表下次优先)
【转写层】batch_transcribe_gpu.py(106行) — faster-whisper(base, CUDA, RTX4060 8GB)转写；batch_asr_fix.py(293行) — 109条正则纠错表(ASR易错词/公司名/术语)；transcribe_to_note.py(371行) — LLM结构化→Obsidian笔记.md；batch_note_asr_fix.py(321行) — 对笔记二次纠错
【知识层】build_vector_db.py(465行) — 笔记切chunk→Chroma向量库增量upsert(9483 chunks)；query_rag.py(403行) — RAG查询(带banned source过滤/keyword overlap)；view_extractor.py(382行) — 从笔记抽结构化观点→structured_views.jsonl(观点类型/方向/时间跨度/质量分)；view_store.py(298行) — 观点库查询打分
【产出层】agent.py(529行, QianboshiAgent类, 工具注册表tool_registry.py 666行) — 日报生成；daily_brief.py(541行) — 盘前简报(实时行情+RAG观点)；brief_renderer.py(781行) — 简报渲染；brief_hybrid.py(304行)/brief_dual.py(170行)/brief_schema.py(190行)/post_check.py(170行) — 简报变体+后置质检；advice.py(281行) — 投资建议生成；validate.py(387行) — 10位分析师观点vs市场实际走势回测验证
【支撑】config_loader.py(226行) — 统一配置；market_data_sources.py(448行) — A股(akshare/baostock)/港股美股(yfinance)三源行情+缓存；entity_normalizer.py(218行) — 实体别名匹配；latest_digest.py(130行) — 最近观点digest(绕开embedding的轻量检索)

数据资产：864篇结构化笔记；9483向量chunks；structured_views.jsonl观点库；ASR纠错后转写稿(115MB)；entity_aliases.yaml别名库；行情多源缓存。
技术栈：Python, Chroma, faster-whisper, yt-dlp, DeepSeek官方API(deepseek-v4-flash), Obsidian。
已知问题：audio/占326GB无清理策略；测试覆盖薄(2个测试文件276行)；监控未覆盖钱博士自己频道；LLM API故障切换手动。

## 二、真实业务需求（最重要，所有优化建议必须围绕它）

用户实盘炒股，用本系统辅助决策。实践发现的核心痛点：

1. **观点必须带完整例证链**：日报要把每个观点、每个支撑例证都完整分析出来，不能只给"看好XX/看空XX"的结论。例证来源包括ASR转写原文、二次理解后的内容。
2. **日报可以长、可以复杂**：允许调用大量ASR内容或二次理解内容，长度和复杂度不是约束，信息完整性和可追溯性才是。
3. **分析师历史判断回测**：对每个分析师(KOL)的历史判断必须逐一列举正误——"他之前对这个板块/标的说过什么，后来市场走势证明对/错"，把历史准确率作为当前判断的可信度参考。现有validate.py(10分析师vs市场)只是雏形，需评估如何升级为完整体系。

## 三、输出要求

按维度组织，每条优化建议必须包含：**问题现状 → 根因 → 具体方案(怎么改/新模块怎么设计) → 预期收益 → 工作量/成本估算**：

1. 日报生成架构：怎么支撑"长日报+完整例证链+历史回测引用"
2. 分析师历史判断回测体系：数据从哪来、怎么结构化存储、怎么计算准确率、怎么在日报中呈现
3. RAG/检索层优化
4. 数据管线优化（采集/转写/纠错/结构化）
5. 代码工程（测试/配置/错误处理/监控）
6. 成本优化

最后给一个"最高价值优先"的落地路线图（先做什么、后做什么，每步的预期效果）。
