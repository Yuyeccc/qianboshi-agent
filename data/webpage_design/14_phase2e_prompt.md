# Phase 2e 实现提示词 — 系统架构页（v1.0）

你是资深全栈工程师 + 数据可视化工程师。在"钱博士Agent 作品集网页"（E:\qianboshi-portfolio，Phase 0-2d 已完成实测）上实现 **Phase 2e：系统架构页**（暗色科技感：七层数据流 + 单条观点生命周期 + MCP 工具区 + 运行状态）。遵守现有架构，只改/新增本提示词列出的文件。

## 一、现有架构（必须遵守）

- Vite + React 18 + TS + Tailwind 3；`@/` = `frontend/src/`；三套 data-theme（product/architecture/terminal），CSS 变量在 styles/themes.css；组件用 Tailwind 映射类禁止硬编码色值；涨跌语义色：`market-positive`(#E05252 红=看多/涨)、`market-negative`(#26A269 绿=看空/跌)
- 数据层：DataProvider + ApiClient（snake_case→camelCase 显式映射，失败返回空结构）+ SnapshotClient + types/index.ts（**已有 ArchitectureSection/ArchitectureData 骨架类型，以本提示词为准替换**）；路由 app/router.tsx；i18n zh/en（`useTranslation`，非 useI18n）
- 后端：FastAPI（backend/，Python3.14），main.py 的 api_router（prefix=/api/v1），repositories 只读模式，路径常量在 schema_registry.py（DATA_ROOT = E:\qianboshi-agent\data）
- 现有页面：ArchitecturePage.tsx 是占位页（"Phase 1 实现"提示），本次重构
- 页面取数据：`useContext(DataContext)`（from `@/app/providers`）+ useEffect + loading/error/empty 三态（参照 OverviewPage 模式）；**不存在 useData/DataProvider 模块**
- ECharts MutationObserver 禁止 `subtree: true`；监听 documentElement 的 data-theme/class 属性即可
- 文件输出用 `<<<FILE: 路径>>> 内容 <<<END>>>` 标记，只输出清单内文件（白名单），禁止带 ``` 代码围栏

## 二、真实数据口径（已核实）

- `E:\qianboshi-agent\data\monitor_state.json`（实时读）：
  - `checked_at`："2026-08-22 22:39"（字符串）
  - `detected_new_today`：8
  - `processed`：数组，138 条 BV（累计处理数 = len）
  - `channels`：dict，uid→{last_bvid, last_check, total_videos}，6 个源 uid：
    - 179666921（深研一点聚合器）、480741488（钱博士直播）、1129838925（钱博士短视频）、11473291（笨笨的韭菜）、322005137（史诗级韭菜）、1372241958（趋势天哥）
- `E:\qianboshi-agent\data\pipeline_queue.json`：当前 `[]`（0 pending）
- MCP 工具清单（9 个，qianboshi_mcp.py 注册）：
  - pipeline_status（流水线状态）、queue_list（队列）、logs_tail（日志）、rag_stats（RAG统计）
  - get_asset_analysis_card（资产分析卡）、get_debate_card（多空对照卡）、get_evidence_pack（证据包）、get_decision_review（决策复盘）、list_user_decisions（决策日志）
- 知识库规模（复用 assets_repo 的指标）：structured_views 9727 / prediction_events 31320 / notes 987 / rag_chunks 11011 / analysts 11 / asset_cards 8

## 三、后端：新建 `backend/app/repositories/architecture_repo.py`

```python
def get_architecture_data() -> dict
```

返回：
```json
{
  "meta": {"generated_at": "ISO", "source": "live"},
  "summary_tags": ["Python-first", "GPU ASR", "RAG-enabled", "Event-driven Review", "Feishu Delivery"],
  "pipeline_status": {
    "scheduler": "active",
    "last_checked": "2026-08-22 22:39",
    "detected_today": 8,
    "processed_total": 138,
    "queue_pending": 0,
    "channels": [
      {"name": "钱博士直播", "uid": "480741488", "last_check": "2026-08-22 22:38", "total_videos": 50}
    ]
  },
  "layers": [
    {
      "layer_id": "source", "layer_name": "采集层", "layer_name_en": "Source Layer",
      "description": "从 B 站财经 UP 主持续采集直播与短视频",
      "nodes": [
        {"name": "B站财经UP主", "role": "6 个内容源：钱博士直播/短视频/深研一点/笨笨的韭菜/史诗级韭菜/趋势天哥", "tech": "Bilibili API"},
        {"name": "直播录像", "role": "全量收录直播回放", "tech": "monitor_bilibili"},
        {"name": "短视频", "role": "短视频观点补充", "tech": "Bilibili API"}
      ]
    },
    {
      "layer_id": "acquisition", "layer_name": "采集下载层", "layer_name_en": "Acquisition Layer",
      "description": "定时调度、下载与去重",
      "nodes": [
        {"name": "定时调度", "role": "工作日 22:00 cron 检测新视频", "tech": "Hermes cron"},
        {"name": "音视频下载", "role": "下载 wav 音频，失败重试", "tech": "yt-dlp"},
        {"name": "去重与记录", "role": "BV 去重，处理记录持久化", "tech": "pipeline_queue.json"}
      ]
    },
    {
      "layer_id": "speech", "layer_name": "语音转写层", "layer_name_en": "Speech Layer",
      "description": "GPU 加速语音转写，产出带时间戳的逐句文本",
      "nodes": [
        {"name": "GPU 转写", "role": "faster-whisper 时间戳级转写", "tech": "faster-whisper + CUDA"},
        {"name": "分段处理", "role": "长视频分片转写避免超时", "tech": "batch_transcribe_gpu"},
        {"name": "失败重试", "role": "转写失败自动重试，不阻塞队列", "tech": "drain_queue"}
      ]
    },
    {
      "layer_id": "understanding", "layer_name": "语义理解层", "layer_name_en": "Understanding Layer",
      "description": "ASR 纠错 + LLM 结构化抽取，把口语转成结构化观点",
      "nodes": [
        {"name": "ASR 纠错", "role": "两轮纠错：术语表/上下文修正", "tech": "batch_asr_fix"},
        {"name": "LLM 结构化", "role": "抽取观点/资产/多空方向/时间窗口/置信度", "tech": "DeepSeek LLM"},
        {"name": "观点入库", "role": "实体归一化 + 证据链保留（view_id/source/date/analyst）", "tech": "view_extractor"}
      ]
    },
    {
      "layer_id": "knowledge", "layer_name": "知识层", "layer_name_en": "Knowledge Layer",
      "description": "向量检索 + 结构化库，观点可追溯可检索",
      "nodes": [
        {"name": "结构化观点库", "role": "9727 条观点，实体/多空/周期索引", "tech": "structured_views.jsonl"},
        {"name": "向量检索", "role": "11011 chunks，新鲜度加权排序", "tech": "ChromaDB + MiniLM"},
        {"name": "笔记沉淀", "role": "987 篇 Markdown 笔记", "tech": "Obsidian vault"}
      ]
    },
    {
      "layer_id": "decision", "layer_name": "决策层", "layer_name_en": "Decision Layer",
      "description": "把研究资产组织成可复盘的决策产物",
      "nodes": [
        {"name": "盘前简报", "role": "8 章日报：大势/持仓/决策台/多空对照/资产卡", "tech": "agent.py"},
        {"name": "多空对照卡", "role": "多头/空头/分歧/共识，8 张资产卡", "tech": "debate_card_builder"},
        {"name": "预测事件", "role": "31320 个观点事件，回测命中率", "tech": "prediction_events"}
      ]
    },
    {
      "layer_id": "delivery", "layer_name": "交付复盘层", "layer_name_en": "Delivery & Review Layer",
      "description": "推送飞书 + 决策到期自动复盘，形成闭环",
      "nodes": [
        {"name": "飞书推送", "role": "简报/持仓/复盘推送到群", "tech": "Feishu API"},
        {"name": "决策复盘", "role": "到期自动回填收益并生成复盘", "tech": "decision_review_generator"},
        {"name": "MCP 工具", "role": "10 个工具暴露给 Agent 实时查询", "tech": "FastMCP"}
      ]
    }
  ],
  "view_lifecycle": [
    {"step": "视频片段", "detail": "B站直播回放/短视频"},
    {"step": "转写文本", "detail": "faster-whisper 带时间戳"},
    {"step": "ASR 修正", "detail": "术语表+上下文纠错"},
    {"step": "结构化观点", "detail": "资产/多空/周期/置信度"},
    {"step": "RAG chunk", "detail": "向量化入库，可检索"},
    {"step": "资产卡/多空卡", "detail": "进入投研资产"},
    {"step": "预测事件", "detail": "挂回测窗口"},
    {"step": "到期复盘", "detail": "收益回填+命中判定"}
  ],
  "mcp_tools": [
    {"name": "pipeline_status", "input": "无", "output": "流水线各环节实时状态", "purpose": "检查监控/队列/转写/RAG 是否健康"},
    {"name": "queue_list", "input": "limit", "output": "待处理任务列表", "purpose": "查看积压与处理进度"},
    {"name": "logs_tail", "input": "file/lines", "output": "日志尾部", "purpose": "排查流水线运行问题"},
    {"name": "rag_stats", "input": "无", "output": "向量库 chunk/笔记统计", "purpose": "核对知识库规模与健康"},
    {"name": "get_asset_analysis_card", "input": "asset_id", "output": "资产分析卡", "purpose": "驱动因素→状态→影响→证据"},
    {"name": "get_debate_card", "input": "entity/lookback_days", "output": "多空对照卡", "purpose": "多头/空头/分歧/共识一屏对照"},
    {"name": "get_evidence_pack", "input": "asset_id/horizon", "output": "证据包", "purpose": "10+1 字段聚合全证据"},
    {"name": "get_decision_review", "input": "asset_id/use_llm", "output": "决策复盘报告", "purpose": "判断→结果→认知修正"},
    {"name": "list_user_decisions", "input": "status", "output": "决策日志", "purpose": "用户拍板记录与状态"}
  ]
}
```
（mcp_tools 的 9 个工具如实列出，名称/输入/输出/用途用上面数据；渠道名映射：480741488=钱博士直播、1129838925=钱博士短视频、179666921=深研一点、11473291=笨笨的韭菜、322005137=史诗级韭菜、1372241958=趋势天哥，未知 uid 显示 uid 本身）

- monitor_state.json 读取失败时 pipeline_status 各字段给 null/0/[]，不抛错
- 全 try/except 兜底，单项失败返回空

## 四、后端 `backend/app/main.py` 加端点

`GET /api/v1/architecture` → `{"architecture_data": {...get_architecture_data()}}`（挂 api_router；注意已有 /overview /assets /decisions /briefs 端点，不要冲突）

## 五、前端

### 1. types/index.ts：替换 ArchitectureSection/ArchitectureData 为：

```ts
export interface ArchitectureNode {
  name: string;
  role: string;
  tech: string;
}
export interface ArchitectureLayer {
  layerId: string;
  layerName: string;
  layerNameEn: string;
  description: string;
  nodes: ArchitectureNode[];
}
export interface PipelineStatus {
  scheduler: string;
  lastChecked: string | null;
  detectedToday: number | null;
  processedTotal: number | null;
  queuePending: number | null;
  channels: { name: string; uid: string; lastCheck: string | null; totalVideos: number | null }[];
}
export interface LifecycleStep { step: string; detail: string }
export interface McpToolItem { name: string; input: string; output: string; purpose: string }
export interface ArchitectureData {
  meta: DataMeta;
  summaryTags: string[];
  pipelineStatus: PipelineStatus;
  layers: ArchitectureLayer[];
  viewLifecycle: LifecycleStep[];
  mcpTools: McpToolItem[];
}
```
（ArchitectureData 保留同名，字段全换；其他页面若引用旧字段需同步——目前无其他页面用 getArchitecture，安全）

### 2. api-client.ts：getArchitecture() 真实 fetch `/v1/architecture`，映射 `architecture_data` 下所有 snake_case→camelCase（summary_tags→summaryTags、pipeline_status→pipelineStatus、last_checked→lastChecked、detected_today→detectedToday、processed_total→processedTotal、queue_pending→queuePending、total_videos→totalVideos、view_lifecycle→viewLifecycle、mcp_tools→mcpTools、layer_id→layerId 等），失败返回全空结构

### 3. snapshot-client.ts：getArchitecture() 读 `/snapshots/architecture.json`，读不到返回空结构

### 4. 重构 `src/pages/ArchitecturePage.tsx`（暗色科技感，全屏深色）

页面整体用 `data-theme="architecture"` 视觉（可读 documentElement 的 theme，若为 product 也可正常渲染，用映射类即可）。区块结构（从上到下）：

**① 页面标题与工程摘要**
- 标题：`System Architecture`（h1，text-heading）+ 中文副题"从内容采集到决策复盘的自动化投研流水线"
- 工程摘要标签行：summaryTags 5 个 pill（Python-first / GPU ASR / RAG-enabled / Event-driven Review / Feishu Delivery），bg-surfaceSubtle 边框 border-line，等宽字体
- 右侧/下方运行状态卡（grid 2x2 或 4 列）：
  - Scheduler: Active（绿点 market-negative）
  - Last Checked: pipelineStatus.lastChecked
  - Queue: `{queuePending} pending`
  - Detected Today: `{detectedToday}` / Processed: `{processedTotal}`

**② 七层流水线图（主视觉）**
- 垂直 7 层，每层一张卡片：层名（中英）+ description + 横向节点卡片行
- 层卡片：bg-surface 深灰面板、border border-line rounded-lg，左侧层序号（01-07，等宽字体 text-brand），右侧节点 flex 排列
- 节点：小卡片 bg-surfaceSubtle rounded-md p-4，name 加粗 + tech 等宽小字 text-brand + role 小字 text-muted，节点之间用 → 或连线箭头衔接（CSS 伪元素/图标均可，不要引第三方库）
- 层与层之间用垂直连线或箭头（简单 CSS border 即可）
- 悬停：节点 hover 时 border-brand 高亮（简单过渡，160-360ms），不做复杂动画
- 数据从 layers 数组渲染（不要写死）

**③ 单条观点生命周期**
- 标题："单条观点的生命周期" + 副题"一条观点如何从视频变成可复盘的决策证据"
- 横向 8 步（可换行 flex-wrap）：viewLifecycle 每步一个小卡（step 名 + detail 小字），卡间用 → 箭头，首卡 text-brand 高亮，末卡 text-market-positive 绿
- 下方放一个"示例观点"代码块（mono 字体，bg-surface 深底）：展示 Asset/Direction/Horizon/Source/Published/Outcome 字段示例，示意一条真实观点字段（如 Gold / Bullish / 1-3 months / 钱博士直播 / 2026-xx-xx / Pending）

**④ MCP 工具区**
- 标题："MCP 工具" + 副题"把投研资产暴露给 Agent，9 个工具实时查询"
- 表格或卡片网格：每个工具 name（等宽 text-brand）+ purpose + 输入/输出（小字 text-muted），2 列网格即可，mcpTools 数组渲染

**⑤ 底部承接区块（浅色结果区，承接数据资产页）**
- 4 个计数卡：Raw videos（138 processed）→ Structured opinions（9727）→ Research assets（11 分析师 / 8 资产卡）→ Decision evidence（31320 事件）
- 底部一句话：`Architecture is useful only when every layer produces an inspectable artifact.`（斜体 text-muted）
- 计数卡从 architecture_data 外部拿不到则用 meta 空态兜底；如本页没有这些数据，可以直接静态写这些数字（已在数据口径核实）或复用 getOverview 的 metrics——**优先复用 overview metrics**：页面同时调 provider.getOverview() 拿 metrics（structuredViews/predictionEvents/notes/ragChunks/analysts/assetCards），与架构数据并列渲染

### 5. i18n：zh.ts/en.ts 补 `pages.architecture.*` 全部 key（页面结构标题、副题、区块标题、状态卡标签、生命周期标题等；技术名词/分析师名/工具名不翻译）

## 六、验收标准（必须全部满足）

1. `npm run build` 通过（frontend/）
2. 后端 8010 起服务后 `curl http://localhost:8010/api/v1/architecture` 返回完整 JSON（layers 7 层、mcp_tools 10 个、pipeline_status 实时）
3. 页面在 5173 渲染：标题/摘要标签/状态卡/七层流水线/生命周期/MCP 工具区/底部计数全部显示，数据非空
4. 断后端时页面不崩（api-client 返回空结构，页面显示 empty 态）
5. 无 console 报错（尤其 ECharts 无关，本页不用 ECharts）
6. 只输出清单内文件：backend/app/repositories/architecture_repo.py、backend/app/main.py、frontend/src/types/index.ts、frontend/src/data/api-client.ts、frontend/src/data/snapshot-client.ts、frontend/src/pages/ArchitecturePage.tsx、frontend/src/i18n/locales/zh.ts、frontend/src/i18n/locales/en.ts

## 七、输出格式

文件用 `<<<FILE: 相对路径>>> 内容 <<<END>>>` 标记，只输出清单内文件，禁止 ``` 代码围栏。
