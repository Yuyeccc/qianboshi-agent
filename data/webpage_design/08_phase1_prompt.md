# Phase 1 实现提示词 — 首页接真实数据（v1.0）

你是资深全栈工程师。在已有的"钱博士Agent 作品集网页"Phase 0 骨架上实现 **Phase 1：首页接入真实数据**。项目位于 `E:\qianboshi-portfolio`，Phase 0 已搭好 Vite+React+TS+Tailwind 前端骨架和 FastAPI 后端骨架（含 DataProvider 双模式接口、三套主题 CSS 变量、6页路由、中英 i18n）。本次只改以下文件，其余文件一律不动。

## 一、真实数据口径（已核实，写死为常量）
数据根目录 `DATA_DIR = E:\qianboshi-agent\data`，所有统计实时计算，禁止写死数字：

| 指标 | 统计方式 |
|---|---|
| 结构化观点数 | `DATA_DIR/views/structured_views.jsonl` 行数（当前约 9727） |
| 回测预测事件 | SQLite `qianboshi_decision.db`（只读 mode=ro）`prediction_events` 表 COUNT（当前 31320） |
| 研究笔记数 | `E:\obsidian-vault\学习\钱博士\` 下 `*.md` 文件数（当前 987） |
| RAG chunks | ChromaDB PersistentClient(path=`DATA_DIR/vector_db`).get_collection("qianboshi").count()（当前约 9400+；若 chromadb 导入或查询失败，返回 None 并在前端显示"—"） |
| 监控源数 | `DATA_DIR/monitor_state.json` 的 `channels` 键数量（当前 6） |
| 最近检查时间 | `monitor_state.json` 的 `checked_at` |
| 今日检测新视频 | `monitor_state.json` 的 `detected_new_today` |
| 最新简报 | `DATA_DIR/briefs/` 目录下 mtime 最新的 .md 文件名（当前 `日报_2026-08-22.md`） |

## 二、后端改动（E:\qianboshi-portfolio\backend）

### 1. 新建 `app/repositories/overview_repo.py`
- 函数 `get_overview_metrics() -> dict`：按上表统计口径返回全部指标，含 `generated_at`（当前 UTC ISO 时间）
- 函数 `get_system_status() -> dict`：读 monitor_state.json 返回 `{last_checked, detected_today, source_count, pipeline_running: bool}`（pipeline_running 用 `checked_at` 距今 < 6 小时判断）
- 函数 `get_latest_brief() -> dict`：返回 `{filename, generated_at(取文件mtime)}`
- 每个统计独立 try/except：单项失败返回 None 不拖垮整体；SQLite 用 `sqlite3.connect("file:...?mode=ro", uri=True)`；JSONL 用 `with open(encoding="utf-8")` 逐行计数；所有路径用常量模块顶部定义
- 注意：chromadb 的 collection.count() 调用可能慢或抛错，单独 try 包住

### 2. 改 `app/main.py`
新增两个端点（挂在现有 api_router 下，prefix=/api/v1）：
- `GET /api/v1/overview` → `{metrics: {...get_overview_metrics()}, status: {...get_system_status()}, latest_brief: {...get_latest_brief()}}`
- `GET /api/v1/overview/metrics` → `{metrics: {...}}`（兼容 Phase 0 架构文档）
- 端点函数直接调 overview_repo，返回 dict（FastAPI 自动转 JSON）

## 三、前端改动（E:\qianboshi-portfolio\frontend）

### 3. 完善 `src/types/index.ts`
OverviewData 类型补齐（保持与后端返回结构一致）：
```ts
export interface OverviewMetrics {
  structuredViews: number | null;
  predictionEvents: number | null;
  notes: number | null;
  ragChunks: number | null;
  sourceCount: number | null;
  generatedAt: string | null;
}
export interface SystemStatus {
  lastChecked: string | null;
  detectedToday: number | null;
  sourceCount: number | null;
  pipelineRunning: boolean | null;
}
export interface LatestBrief {
  filename: string | null;
  generatedAt: string | null;
}
export interface OverviewData {
  metrics: OverviewMetrics;
  status: SystemStatus;
  latestBrief: LatestBrief;
}
```
注意：现有类型文件里可能已有 OverviewData 骨架（字段不同），以本提示词为准替换。

### 4. 改 `src/data/api-client.ts`
`getOverview()` 实现真实 fetch：`fetch(`${apiBaseUrl}/v1/overview`)`，失败或返回非 2xx 时返回空结构（所有字段 null）而不是抛错。
**⚠️ 字段映射**：后端返回 snake_case（`structured_views`/`prediction_events`/`rag_chunks`/`source_count`/`last_checked`/`detected_today`/`pipeline_running`/`generated_at`/`latest_brief`/`filename`），前端 TS 类型用 camelCase（见第 3 条）——`getOverview()` 内必须做显式字段映射后再返回，禁止把后端 JSON 原样当 OverviewData 返回。其他方法保持 Phase 0 空骨架。

### 5. 新建 `src/components/data/MetricCard.tsx`
Props: `{ label: string; value: number | null; hint?: string }`。渲染：label 小字、value 大数字（千分位格式化 `toLocaleString('en-US')`，null 显示"—"）、hint 来源说明小字。样式用 CSS 变量（bg-surface、border-line、text-heading、text-muted），白底卡片、细边框、轻阴影（shadow-panel）、圆角 6px。

### 6. 改 `src/pages/OverviewPage.tsx`
- 用 `useContext(DataContext)` 拿 DataProvider，`useEffect` 调 `getOverview()`，loading/error/loaded 三态（loading 显示"加载中…"，error 或全 null 时数字显示"—"）
- 信任数据带：4 个 MetricCard——结构化观点(值=metrics.structuredViews, hint="结构化观点库 JSONL 行数")、回测预测事件(predictionEvents, hint="SQLite prediction_events 表，到期自动复盘")、研究笔记(notes, hint="Obsidian 笔记库")、知识库规模(ragChunks, hint="ChromaDB RAG 向量库 chunks")
- Hero 状态标签（"Phase 0 骨架/数据待接入"处）改为真实状态：`Pipeline 运行中/未运行`（status.pipelineRunning）+ 最近检查时间（status.lastChecked 格式化为本地时间）+ 今日检测 `detectedToday` 个新视频；数据未就绪时显示"—"
- 新增"最新简报"区块：latestBrief.filename + generatedAt，无数据时显示"—"
- 页面文案全部走 i18n（zh/en 两个文件补 key：overview.heroStatus、overview.lastChecked、overview.detectedToday、overview.latestBrief、overview.loading、metrics 四个 label 与 hint）
- 数字未接入时不允许出现虚假数字；所有 null 显示"—"

### 7. 改 `src/i18n/locales/zh.ts` 和 `en.ts`
补 Phase 1 新增文案 key（见第 6 条）。

### 8. 改 `backend/requirements.txt`
追加 `chromadb`（overview_repo 的 rag_chunks 统计需要；import 失败不影响其他指标）。

## 四、验收标准（必须全部满足）
1. 后端启动后 `curl http://localhost:8010/api/v1/overview` 返回真实数据：structuredViews≈9727、predictionEvents=31320、notes≈987、sourceCount=6、latest_brief 为 日报_2026-08-22.md
2. 前端 dev 下首页信任数据带显示真实数字（千分位），"—"只出现在后端确实没有的数据（如 ragChunks 失败时）
3. 停掉后端时前端页面不崩，数字显示"—"（降级验证）
4. `npm run build` TS 零错误
5. 中英切换后首页新文案都正确翻译
6. 不改动 Phase 0 已验收的其他页面/组件（Header/Footer/SiteShell/router/主题）——若必须微调需在代码注释标明原因

## 五、输出格式
按文件输出，每个文件用标记包裹：
```
<<<FILE: backend/app/repositories/overview_repo.py>>>
完整内容
<<<END>>>
```
只输出上述 7 个文件的代码，无解释性废话。
