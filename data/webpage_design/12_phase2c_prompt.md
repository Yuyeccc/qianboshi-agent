# Phase 2c 实现提示词 — 数据资产页（v1.0）

你是资深全栈工程师 + 数据可视化工程师。在"钱博士Agent 作品集网页"（E:\qianboshi-portfolio，Phase 0/1/2a/2b 已完成实测）上实现 **Phase 2c：数据资产页**（观点库统计/分析师命中率/来源分布，深色金融终端风 + ECharts 图表）。遵守现有架构，只改/新增本提示词列出的文件。

## 一、现有架构（必须遵守）
- Vite + React 18 + TS + Tailwind 3；`@/` = `frontend/src/`；三套 data-theme（product/architecture/terminal），CSS 变量在 styles/themes.css，Tailwind 映射在 tailwind.config.ts（含 surfaceRaised/surfaceSubtle/surfaceBrand/borderStrong/brandStrong/shadow-card/cardHover，Phase 2b 已加）；组件用 Tailwind 映射类，禁止硬编码色值
- 数据层：DataProvider（provider.ts）+ ApiClient（api-client.ts，失败降级空结构）+ SnapshotClient + 类型 types/index.ts；路由 app/router.tsx（`:locale` 前缀）；i18n zh.ts/en.ts
- 后端：FastAPI（backend/，Python 3.14），main.py 的 api_router（prefix=/api/v1）；repositories 只读（SQLite mode=ro，JSONL 逐行读）；overview_repo.py 已有：_count_structured_views（JSONL 行数 9727）/ _count_prediction_events（31320）/ _count_notes（987）/ _count_rag_chunks（snapshot.json 11011）/ get_system_status / get_latest_brief
- 现有页面：OverviewPage/BriefListPage/BriefDetailPage/ArchitecturePage（占位）/DataAssetsPage（占位）/DecisionDeskPage（占位）/DisciplinePage（占位）/AboutPage（占位）
- **DataAssetsPage 现状**：纯占位页（"Phase 1 实现"提示），本次重构为完整数据资产页

## 二、真实数据口径（已核实，后端实时计算）
数据目录 `DATA_DIR = E:\qianboshi-agent\data`：
- 观点库：`views/structured_views.jsonl`（9727 行），字段：analyst/claim/confidence/date/entities/evidence/horizon/logic/quality_flags/risk/section/source_bv/source_file/source_type/stance/timestamp/version/view_id/view_type；**stance 取值**：bullish 2465/neutral 4791/bearish 1793/watch 303/risk 375；**horizon**：intraday 1756/unknown 4098/short 2308/medium 1319/long 246；**source_type**：livestream 8475/short_video 1180/news 72
- 分析师 top10（按观点数）：钱博士直播 4441/钱博士短视频 1180/笨笨的韭菜 752/史诗级韭菜 737/趋势天哥 655/旗帜鲜明 572/李一恩 469/投机大拿 322/柏年说 274/任泽平 253
- SQLite analyst_scores（335 行）：列 analyst/entity/horizon/window_days/sample_count/hit_rate/avg_return/score/updated_at——按 analyst 分组取 sample_count 最大一行的 hit_rate 作为该分析师命中率
- SQLite asset_cards（8 张）：GOLD黄金/SEMI半导体/AI AI应用/ROBOT机器人/BAIJIU白酒/ALUMINUM铝/INNOV_DRUG创新药/TECH科技
- SQLite debate_cards（163 张）：列 card_id/entity_id/entity_name/entity_type/horizon/window_start/window_end/bullish_count/bearish_count/neutral_count/risk_count/watch_count/consensus_direction/disagreement_level/confidence_level/novelty_level/summary/created_at/updated_at——取 updated_at 最新 8 张做"多空对照速览"
- 最新观点样例：JSONL 读取时记录最后 5 条有效记录（文件尾部最新）

## 三、后端：新建 `backend/app/repositories/assets_repo.py`
```python
def get_assets_data() -> dict
```
返回结构（全部 try/except 兜底，单项失败返回空/None）：
```json
{
  "metrics": {"structured_views": 9727, "prediction_events": 31320, "notes": 987,
              "rag_chunks": 11011, "analysts": 12, "asset_cards": 8, "generated_at": "ISO"},
  "stance_dist": [{"name": "bullish", "label_zh": "看多", "value": 2465}, ...5项],
  "horizon_dist": [{"name": "short", "label_zh": "短期", "value": 2308}, ...5项(unknown→"未标注")],
  "source_contrib": [{"name": "钱博士直播", "views": 4441}, ...top10 降序],
  "analyst_rank": [{"name": "钱博士直播", "hit_rate": 0.53, "samples": 74}, ...按 hit_rate 降序 top8],
  "debate_cards": [{"entity": "半导体", "bullish": 77, "bearish": 53, "neutral": 95, "consensus": "neutral", "disagreement": 0.46, "updated": "..."}, ...最新8张],
  "sample_views": [{"analyst": "...", "date": "...", "stance": "...", "claim": "前80字"}, ...5条]
}
```
- metrics 直接复用 overview_repo 的计数函数 + 新增：analysts = JSONL 去重分析师数、asset_cards = SQLite asset_cards COUNT
- JSONL 只扫一遍：同时统计 stance/horizon/source_contrib/analysts/样例（循环内累加，不重复读文件）
- analyst_rank：SQLite `SELECT analyst, sample_count, hit_rate FROM analyst_scores` 全读，Python 按 analyst 分组取 sample_count 最大行，hit_rate 保留 4 位小数，按 hit_rate 降序取 8
- debate_cards：`SELECT entity_name, bullish_count, bearish_count, neutral_count, consensus_direction, disagreement_level, updated_at FROM debate_cards ORDER BY updated_at DESC LIMIT 8`
- 中文 label 映射常量放 repo 内（stance: bullish看多/bearish看空/neutral中性/watch观察/risk风险；horizon: intraday日内/short短期/medium中期/long长期/unknown未标注）

## 四、后端 `backend/app/main.py` 加端点
`GET /api/v1/assets` → `{"assets": {...get_assets_data()}}`（挂 api_router）

## 五、前端

### 1. 装依赖
`npm install echarts`（全量引入即可，Phase 2c 不追求按需裁剪，后续优化）

### 2. types/index.ts 增加
```ts
export interface DistItem { name: string; labelZh: string; value: number }
export interface SourceContribItem { name: string; views: number }
export interface AnalystRankItem { name: string; hitRate: number | null; samples: number | null }
export interface DebateCardItem { entity: string; bullish: number; bearish: number; neutral: number; consensus: string; disagreement: number | null; updated: string | null }
export interface SampleViewItem { analyst: string; date: string | null; stance: string; claim: string }
export interface AssetsData {
  metrics: { structuredViews: number|null; predictionEvents: number|null; notes: number|null; ragChunks: number|null; analysts: number|null; assetCards: number|null; generatedAt: string|null };
  stanceDist: DistItem[]; horizonDist: DistItem[]; sourceContrib: SourceContribItem[];
  analystRank: AnalystRankItem[]; debateCards: DebateCardItem[]; sampleViews: SampleViewItem[];
}
```
（注意：AssetsData 类型已存在但结构不同，以本提示词为准替换；api-client/snapshot-client 里 getAssets() 返回类型同步调整）

### 3. api-client.ts 的 getAssets()
fetch `/v1/assets`，映射 snake_case→camelCase（metrics 字段名、stance_dist→stanceDist、hit_rate→hitRate 等），失败返回全空结构

### 4. snapshot-client.ts 的 getAssets()
读 `/snapshots/data-assets.json`，读不到返回空结构

### 5. 新建 `src/components/charts/ChartFrame.tsx`
通用图表容器：`({ title, subtitle?, children, className? })`——终端风格面板：rounded-lg border border-line bg-surface p-5，标题（text-sm font-medium text-heading）+ 副标题（text-xs text-muted）+ 内容区（h-64 或自定义）

### 6. 重构 `src/pages/DataAssetsPage.tsx`（深色终端风）
页面结构（自上而下）：
1. 页面头：eyebrow（"DATA ASSETS"）+ H1（数据资产 dataAssets.title）+ 描述（dataAssets.description）
2. **指标墙**（grid 2/3/6 列）：6 个终端指标卡（复用 MetricCard 或自定义：数字 tabular-nums 大字号 + label + hint）：结构化观点/回测事件/研究笔记/知识库规模/分析师数/资产卡
3. **观点方向分布 + 周期分布**（grid lg:grid-cols-2）：两个 ChartFrame 内嵌 ECharts——环形图（stance_dist，颜色：bullish=红#E05252/bearish=绿#26A269/neutral=灰#8793A0/watch=琥珀#D99A2B/risk=蓝#4D91E8，tooltip 显示 label_zh+数量+占比）+ 横向条形图（horizon_dist，brand 青色 #0B7A75）
4. **来源贡献**（ChartFrame）：横向条形图 top10（钱博士直播等，渐变蓝或单色 #0B7A75，条长=views）
5. **分析师命中率**（ChartFrame）：横向条形图 analyst_rank（hit_rate×100% 显示，红涨绿跌语义——这里命中率越高越"准"，用品牌色；tooltip 显示样本数 samples；hitRate 为 null 时条为 0 显示"—"）
6. **多空对照速览**（ChartFrame 或表格）：debate_cards 表格——实体/看多(红)/看空(绿)/中性(灰)/共识方向(标签)/分歧度(百分比)；consensus 用语义色标签
7. **观点样例**（终端风格区块）：sample_views 5 条——每条：分析师名 + 日期 + stance 标签（红/绿/灰 pill）+ claim 前 80 字（截断加…）
8. 底部数据时效注脚：generated_at + "统计口径见项目说明"
- 整页深色终端观感：页面容器用 terminal 主题的变量（bg-surface 面板 + border-line + text-heading/text-muted），但**不强制给页面套 data-theme**（跟随全局主题切换，Phase 4 再精细控制页面级主题）
- loading/error/空态：loading 显示"加载中…"，error 显示"—"，空数组显示"暂无数据"
- ECharts 用法：`import * as echarts from "echarts"` + useRef + useEffect 初始化/dispose（或 echarts-for-react 均可，二选一保持简单）；图表 resize 监听（window resize 时 chart.resize()）；图表颜色取 CSS 变量（getComputedStyle 读取 --color-heading/--color-muted 等，深色主题下图表也好看）
- 页面文案走 i18n（见下）

### 7. i18n zh/en 新增 key
- dataAssets.title（数据资产 / Data Assets）、dataAssets.description（"观点库、分析师命中率与来源分布的结构化快照。" / "Structured snapshot of the view database, analyst hit rates and source distribution."）
- dataAssets.metricsStructured（结构化观点 / Structured views）、metricsEvents（回测事件 / Prediction events）、metricsNotes（研究笔记 / Notes）、metricsChunks（知识库规模 / RAG chunks）、metricsAnalysts（分析师 / Analysts）、metricsCards（资产卡 / Asset cards）
- dataAssets.stanceTitle（观点方向分布 / View direction）、dataAssets.horizonTitle（观点周期分布 / Time horizon）、dataAssets.sourceTitle（来源贡献 Top10 / Source contribution Top 10）、dataAssets.rankTitle（分析师命中率 Top8 / Analyst hit rate Top 8）、dataAssets.debateTitle（多空对照速览 / Debate cards）、dataAssets.samplesTitle（最新观点样例 / Recent views）
- dataAssets.debateCols：entity 实体/Entity、bullish 看多/Bullish、bearish 看空/Bearish、neutral 中性/Neutral、consensus 共识/Consensus、disagreement 分歧度/Disagreement
- dataAssets.updatedAt（数据更新于 / Data updated at）
- 复用已有 overview.loading；stance/horizon 的 label 由后端返回（label_zh），前端按 locale 显示（zh 用 labelZh，en 用 name 或英文映射——en 下显示 name 原值即可）

## 六、验收标准
1. `curl http://localhost:8010/api/v1/assets` 返回全部字段，stance_dist 5 项合计 9727，analyst_rank 8 条带 hitRate/samples，debate_cards 8 条，sample_views 5 条
2. 前端 /zh/assets：指标墙 6 卡真实数字；4 个 ECharts 图表渲染（环形图/条形图×3）无控制台报错；多空表 + 观点样例正常
3. 三套主题切换后图表和面板配色正常（图表颜色随 CSS 变量变化）
4. 停后端：页面空态不崩
5. `npm run build` TS 零错误
6. 中英切换正常
7. 不破坏其他页面

## 七、输出格式
按文件输出，每个文件用标记包裹：
```
<<<FILE: backend/app/repositories/assets_repo.py>>>
完整内容
<<<END>>>
```
新建：backend/app/repositories/assets_repo.py、frontend/src/components/charts/ChartFrame.tsx
修改：backend/app/main.py、frontend/src/types/index.ts、frontend/src/data/api-client.ts、frontend/src/data/snapshot-client.ts、frontend/src/pages/DataAssetsPage.tsx、frontend/src/i18n/locales/zh.ts、frontend/src/i18n/locales/en.ts
（ECharts 依赖我自己装，package.json 不用输出）
只输出这些文件的代码，无解释废话。
