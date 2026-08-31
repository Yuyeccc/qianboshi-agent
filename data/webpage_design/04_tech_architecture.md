​我会先确认当前工作区的仓库形态与是否已有前后端约定，再把文档写入一个明确的架构文档文件。内容会按可执行交付设计，包含目录、接口、类型、命令和验收标准，而不是只列概念选型。接下来我会以现有代码库为约束核对目录和依赖；若当前仓库尚无前端骨架，则文档会给出从零创建 `frontend/`、`backend/` 的完整路径和初始化命令，并把真实数据字段映射标注为需要在实现阶段由 SQLite schema 校准的边界。我将把交付物定位为仓库内的 `docs/architecture.md`，并同时覆盖静态 GitHub Pages 与本地 FastAPI 的运行契约。后续实现可以直接按该文档逐阶段验收。我现在检查工作区文件，避免文档目录或现有命名与项目冲突。# 钱博士 Agent 求职作品集网页技术栈架构文档

版本：`v0.1`  
定位：真实运行的 AI 金融投研系统作品集  
部署模式：

- 本地动态版：React 前端 + FastAPI 只读 API + 本地真实数据
- GitHub Pages 静态版：React 静态构建 + 预生成 JSON 快照
- 两种模式共用同一套页面、组件和 `DataProvider` 接口

---

## 1. 技术选型总表

| 层级 | 选型 | 版本策略 | 选择理由 |
|---|---|---:|---|
| 前端框架 | React | `^18.3.1` | 生态成熟，适合构建多页面数据型作品集 |
| 开发语言 | TypeScript | `^5.6.3` | 为数据接口、图表模型和双模式数据源提供类型约束 |
| 构建工具 | Vite | `^6.0.0` | 启动快、配置简单、可直接输出 GitHub Pages 静态资源 |
| 样式 | Tailwind CSS | `^3.4.16` | 适合统一 spacing、响应式布局和主题变量映射 |
| 图表 | ECharts + `echarts-for-react` | `^5.5.1` / `^3.0.2` | 金融时间序列、热力图、散点图和仪表盘能力完整 |
| 图标 | lucide-react | `^0.468.0` | 线性图标风格统一，避免手写 SVG |
| 路由 | react-router-dom | `^7.0.2` | 支持 `/zh`、`/en` 语言路由及六个页面 |
| 双语 | react-i18next + i18next | `^15.1.3` / `^23.16.8` | 资源文件清晰，支持语言路由和插值 |
| HTTP 客户端 | 原生 `fetch` | 浏览器内置 | 项目为只读数据访问，不引入 Axios 体积和抽象成本 |
| 后端 | FastAPI | `>=0.115,<1.0` | Python 数据生态兼容，适合只读 API |
| 数据校验 | Pydantic | `>=2.9,<3.0` | 将 SQLite/JSON 原始数据转换成稳定 API 契约 |
| SQLite 访问 | Python `sqlite3` | 标准库 | 只读查询，无额外 ORM 成本 |
| 部署 | GitHub Pages | - | 适合静态快照模式，成本低且可公开展示 |
| API 本地代理 | Vite proxy | - | 本地开发时避免 CORS，并保持前端 API 路径稳定 |

### Vite vs Next.js 结论

本项目采用 Vite，不采用 Next.js。

原因：

1. GitHub Pages 是核心部署目标，Vite 的静态输出是原生能力。
2. 本项目不需要 SSR、服务端组件、登录鉴权或服务端表单操作。
3. 后端已经由 FastAPI 负责动态数据访问，Next.js 的服务端能力会与现有架构重复。
4. Vite 构建产物简单，适合面试时解释“同一套前端通过 DataProvider 切换数据源”。
5. React Router 已足够处理六个页面和语言路由。

---

## 2. 仓库目录结构

```text
qianboshi-portfolio/
├── README.md
├── package.json
├── package-lock.json
├── .gitignore
├── docs/
│   └── architecture.md
│
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── public/
│   │   ├── favicon.svg
│   │   └── snapshots/
│   │       ├── overview.json
│   │       ├── architecture.json
│   │       ├── data-assets.json
│   │       ├── decision-desk.json
│   │       ├── discipline.json
│   │       └── about.json
│   │
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── vite-env.d.ts
│       │
│       ├── app/
│       │   ├── router.tsx
│       │   ├── providers.tsx
│       │   └── config.ts
│       │
│       ├── pages/
│       │   ├── OverviewPage.tsx
│       │   ├── ArchitecturePage.tsx
│       │   ├── DataAssetsPage.tsx
│       │   ├── DecisionDeskPage.tsx
│       │   ├── DisciplinePage.tsx
│       │   └── AboutPage.tsx
│       │
│       ├── components/
│       │   ├── layout/
│       │   │   ├── SiteShell.tsx
│       │   │   ├── Header.tsx
│       │   │   ├── Footer.tsx
│       │   │   └── PageTransition.tsx
│       │   ├── navigation/
│       │   │   ├── LocaleSwitcher.tsx
│       │   │   └── PageNav.tsx
│       │   ├── data/
│       │   │   ├── MetricCard.tsx
│       │   │   ├── DataStatus.tsx
│       │   │   ├── SourceBadge.tsx
│       │   │   └── AssetCard.tsx
│       │   ├── charts/
│       │   │   ├── ChartFrame.tsx
│       │   │   ├── TrendChart.tsx
│       │   │   ├── HeatmapChart.tsx
│       │   │   └── EventScatterChart.tsx
│       │   └── architecture/
│       │       ├── PipelineDiagram.tsx
│       │       └── PipelineNode.tsx
│       │
│       ├── data/
│       │   ├── provider.ts
│       │   ├── api-client.ts
│       │   ├── snapshot-client.ts
│       │   └── query-keys.ts
│       │
│       ├── types/
│       │   ├── common.ts
│       │   ├── overview.ts
│       │   ├── architecture.ts
│       │   ├── assets.ts
│       │   ├── decisions.ts
│       │   ├── discipline.ts
│       │   └── about.ts
│       │
│       ├── i18n/
│       │   ├── index.ts
│       │   └── locales/
│       │       ├── zh.ts
│       │       └── en.ts
│       │
│       ├── styles/
│       │   ├── index.css
│       │   ├── tokens.css
│       │   ├── themes.css
│       │   └── utilities.css
│       │
│       └── lib/
│           ├── format.ts
│           ├── dates.ts
│           └── echarts.ts
│
├── backend/
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── .env.example
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   ├── api/
│   │   │   ├── overview.py
│   │   │   ├── architecture.py
│   │   │   ├── assets.py
│   │   │   ├── decisions.py
│   │   │   ├── discipline.py
│   │   │   └── about.py
│   │   ├── schemas/
│   │   │   ├── common.py
│   │   │   ├── overview.py
│   │   │   ├── architecture.py
│   │   │   ├── assets.py
│   │   │   ├── decisions.py
│   │   │   └── discipline.py
│   │   ├── repositories/
│   │   │   ├── json_repository.py
│   │   │   ├── sqlite_repository.py
│   │   │   ├── source_repository.py
│   │   │   └── schema_registry.py
│   │   └── services/
│   │       ├── overview_service.py
│   │       ├── asset_service.py
│   │       ├── decision_service.py
│   │       └── snapshot_service.py
│   └── scripts/
│       ├── inspect_sqlite.py
│       └── generate_snapshots.py
│
└── .github/
    └── workflows/
        └── deploy-pages.yml
```

### 关键职责

- `frontend/src/data/provider.ts`：定义前端唯一数据访问接口。
- `api-client.ts`：请求本地 FastAPI。
- `snapshot-client.ts`：请求 `public/snapshots/*.json`。
- `frontend/src/types/`：前后端共享的数据结构在前端侧的类型定义。
- `backend/app/repositories/`：封装真实数据文件和 SQLite 查询，页面 API 不直接操作文件。
- `backend/app/services/`：将原始数据转换为页面所需的聚合结构。
- `backend/scripts/generate_snapshots.py`：调用服务层生成静态快照。
- `schema_registry.py`：记录 SQLite 实际表名和逻辑数据集之间的映射，避免将表名散落在业务代码中。

---

## 3. 后端 API 设计

API 前缀统一为 `/api/v1`。

所有 API 返回统一包装：

```python
from datetime import datetime
from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    data: T
    generated_at: datetime
    source: str  # "live" | "snapshot-compatible"
```

### 通用端点

| Method | Path | 返回内容 | 数据来源 |
|---|---|---|---|
| `GET` | `/health` | 服务状态、数据目录、最近数据时间 | 文件系统、SQLite |
| `GET` | `/api/v1/meta` | 系统版本、快照时间、数据统计、运行模式 | JSON 文件、SQLite |

### 首页概览

| Method | Path | 返回内容 | 数据来源 |
|---|---|---|---|
| `GET` | `/api/v1/overview` | 系统简介、核心指标、流水线状态、最新简报摘要 | 多源聚合 |
| `GET` | `/api/v1/overview/metrics` | 9473 条观点、9400+ RAG chunks、900+ 笔记、回测事件数、MCP 工具数 | `structured_views.jsonl`、SQLite、Chroma 统计、配置/状态文件 |
| `GET` | `/api/v1/overview/recent-briefs` | 最近盘前简报列表 | `market_cache.json`、SQLite 决策库或简报记录表 |

### 系统架构页

| Method | Path | 返回内容 | 数据来源 |
|---|---|---|---|
| `GET` | `/api/v1/architecture` | 六阶段流水线节点、边、运行状态、延迟/产出统计 | `monitor_state.json`、`pipeline_queue.json`、配置文件 |
| `GET` | `/api/v1/architecture/pipeline` | 采集、下载、转写、纠错、结构化、RAG、简报、推送节点详情 | 状态 JSON、SQLite |
| `GET` | `/api/v1/architecture/mcp-tools` | 6 个 MCP 工具名称、用途、输入输出说明 | MCP 配置或后端静态注册表 |

### 数据资产页

| Method | Path | 返回内容 | 数据来源 |
|---|---|---|---|
| `GET` | `/api/v1/assets` | 资产总览、观点分类、数据更新时间 | `structured_views.jsonl`、SQLite |
| `GET` | `/api/v1/assets/summary` | 观点、笔记、RAG chunks、预测事件、资产卡汇总 | JSONL、SQLite、Chroma 统计 |
| `GET` | `/api/v1/assets/views` | 结构化观点分页列表 | `views/structured_views.jsonl` |
| `GET` | `/api/v1/assets/asset-cards` | 5 张资产卡及其最新状态 | `portfolio.json`、资产卡 JSON 或 SQLite |
| `GET` | `/api/v1/assets/coverage` | UP 主来源覆盖、观点数量、时间分布 | `structured_views.jsonl` |
| `GET` | `/api/v1/assets/rag` | RAG chunk 总数、来源分布、嵌入索引状态 | Chroma 目录或其统计文件 |

建议分页参数：

```text
GET /api/v1/assets/views?page=1&page_size=50&source=xxx&symbol=xxx
```

### 决策台

| Method | Path | 返回内容 | 数据来源 |
|---|---|---|---|
| `GET` | `/api/v1/decisions` | 决策事件分页列表 | SQLite 决策库 |
| `GET` | `/api/v1/decisions/summary` | 预测总数、命中率、按资产/方向/时间聚合 | SQLite |
| `GET` | `/api/v1/decisions/timeline` | 预测事件时间序列 | SQLite |
| `GET` | `/api/v1/decisions/distribution` | 方向、置信度、周期、结果分布 | SQLite |
| `GET` | `/api/v1/decisions/latest` | 最新决策及解释 | SQLite、`market_cache.json` |
| `GET` | `/api/v1/decisions/{decision_id}` | 单条决策详情、关联观点、结果 | SQLite、JSONL |

建议过滤参数：

```text
GET /api/v1/decisions?page=1&page_size=100
  &asset=沪深300
  &direction=bullish
  &from=2024-01-01
  &to=2025-01-01
```

### 实盘纪律页

| Method | Path | 返回内容 | 数据来源 |
|---|---|---|---|
| `GET` | `/api/v1/discipline` | 纪律总览、当前组合状态、风险提示 | `portfolio.json`、`market_cache.json`、SQLite |
| `GET` | `/api/v1/discipline/portfolio` | 资产卡、仓位、成本、当前价格、盈亏 | `portfolio.json`、`price_trends.json` |
| `GET` | `/api/v1/discipline/risk-events` | 风险事件、止损/止盈/超限记录 | SQLite 决策库、`monitor_state.json` |
| `GET` | `/api/v1/discipline/price-trends` | 资产价格和组合净值时间序列 | `price_trends.json` |
| `GET` | `/api/v1/discipline/rules` | 系统执行纪律和风控规则 | 后端静态配置文件 |

### 关于 / 技术栈页

| Method | Path | 返回内容 | 数据来源 |
|---|---|---|---|
| `GET` | `/api/v1/about` | 技术栈、系统边界、项目指标、工具列表 | 后端静态配置、`meta` |
| `GET` | `/api/v1/about/stack` | Python、FastAPI、Whisper、LLM、Chroma、SQLite、MCP | 后端静态配置 |
| `GET` | `/api/v1/about/limitations` | 数据时效、模型局限、非投资建议说明 | 后端静态配置 |

### 动态版专属端点

以下端点仅在本地动态版提供：

- `/api/v1/decisions/{decision_id}`
- `/api/v1/assets/views`
- 带分页、过滤、排序的所有 API
- `/health`
- `/api/v1/meta` 中的实时数据状态
- SQLite 和本地文件的实时聚合查询

GitHub Pages 不提供 API。静态版会将页面首屏和图表所需的数据提前打包到快照 JSON 中。

### SQLite 表名校准

当前已知 SQLite 包含 12 张表，但未在需求中提供实际表名。实现后端前必须执行：

```bash
cd backend
python scripts/inspect_sqlite.py \
  --db "E:/qianboshi-agent/data/qianboshi_decision.db"
```

脚本输出每张表的：

- 表名
- 字段名和字段类型
- 主键
- 行数
- 最早/最新时间字段候选

然后将实际表名登记到：

```python
# backend/app/repositories/schema_registry.py
TABLES = {
    "decision_events": "实际表名",
    "prediction_results": "实际表名",
    "asset_cards": "实际表名",
    "risk_events": "实际表名",
}
```

页面和服务层只使用逻辑名称，不直接依赖 SQLite 实际表名。

---

## 4. 数据源映射表

| 页面区块 | 数据文件 / SQLite 逻辑表 | 快照文件 |
|---|---|---|
| 首页系统状态 | `monitor_state.json`、`pipeline_queue.json` | `overview.json` |
| 首页核心数字 | `structured_views.jsonl`、SQLite 决策事件表、Chroma 统计 | `overview.json` |
| 首页最新简报 | `market_cache.json`、SQLite 简报表 | `overview.json` |
| 首页流水线预告 | `monitor_state.json`、`pipeline_queue.json` | `overview.json` |
| 架构流水线 | 状态文件、管线配置、日志聚合 | `architecture.json` |
| 架构数据流 | `structured_views.jsonl`、Chroma、SQLite | `architecture.json` |
| 架构 MCP 工具 | MCP 配置或注册表 | `architecture.json` |
| 数据资产总量 | `structured_views.jsonl`、SQLite | `data-assets.json` |
| 结构化观点列表 | `views/structured_views.jsonl` | `data-assets.json` |
| UP 主覆盖 | `structured_views.jsonl` | `data-assets.json` |
| RAG chunks | Chroma collection 统计 | `data-assets.json` |
| 资产卡 | `portfolio.json`、资产卡数据 | `data-assets.json` |
| 决策台统计 | SQLite 决策事件、结果表 | `decision-desk.json` |
| 决策时间线 | SQLite 预测/结果表 | `decision-desk.json` |
| 决策详情 | SQLite + 关联观点 JSONL | 动态版专属，静态版摘要进入 `decision-desk.json` |
| 实盘组合 | `portfolio.json` | `discipline.json` |
| 价格趋势 | `price_trends.json` | `discipline.json` |
| 风险事件 | `monitor_state.json`、SQLite 风险表 | `discipline.json` |
| 纪律规则 | 后端静态配置 | `discipline.json` |
| 关于技术栈 | 后端静态配置 | `about.json` |
| 关于数据规模 | 以上数据源聚合 | `about.json` |

快照 JSON 必须带有元数据：

```json
{
  "generated_at": "2025-01-15T08:30:00Z",
  "data_as_of": "2025-01-15T08:00:00Z",
  "mode": "snapshot",
  "version": "2025.01.15",
  "data": {}
}
```

---

## 5. 双模式架构

### 5.1 DataProvider 接口

```ts
// frontend/src/data/provider.ts

import type { OverviewData } from "../types/overview";
import type { ArchitectureData } from "../types/architecture";
import type { AssetsData, ViewQuery, ViewPage } from "../types/assets";
import type {
  DecisionDetail,
  DecisionQuery,
  DecisionSummary,
  DecisionTimeline,
} from "../types/decisions";
import type { DisciplineData } from "../types/discipline";
import type { AboutData } from "../types/about";

export interface DataProvider {
  getOverview(): Promise<OverviewData>;
  getArchitecture(): Promise<ArchitectureData>;
  getAssets(): Promise<AssetsData>;
  getAssetViews(query?: ViewQuery): Promise<ViewPage>;

  getDecisionSummary(): Promise<DecisionSummary>;
  getDecisionTimeline(): Promise<DecisionTimeline>;
  getDecisions(query?: DecisionQuery): Promise<ViewPage>;
  getDecision(id: string): Promise<DecisionDetail>;

  getDiscipline(): Promise<DisciplineData>;
  getAbout(): Promise<AboutData>;
}
```

### 5.2 通用类型

```ts
// frontend/src/types/common.ts

export type MarketDirection = "up" | "down" | "flat";
export type DataMode = "live" | "snapshot";

export interface DataMeta {
  generatedAt: string;
  dataAsOf: string;
  mode: DataMode;
  version: string;
}

export interface Metric {
  key: string;
  label: string;
  value: number;
  displayValue: string;
  unit?: string;
  trend?: number;
}

export interface Paginated<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}
```

### 5.3 前端切换机制

```ts
// frontend/src/app/config.ts

export type RuntimeMode = "live" | "snapshot";

export const runtimeMode: RuntimeMode =
  import.meta.env.VITE_DATA_MODE === "snapshot"
    ? "snapshot"
    : "live";

export const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ?? "/api";
```

```ts
// frontend/src/data/provider.ts

import { ApiClient } from "./api-client";
import { SnapshotClient } from "./snapshot-client";
import { runtimeMode } from "../app/config";

export const dataProvider =
  runtimeMode === "snapshot"
    ? new SnapshotClient("/snapshots")
    : new ApiClient("/api/v1");
```

### 5.4 环境变量

```dotenv
# frontend/.env.local
VITE_DATA_MODE=live
VITE_API_BASE_URL=/api
```

```dotenv
# frontend/.env.snapshot
VITE_DATA_MODE=snapshot
VITE_API_BASE_URL=
VITE_BASE_PATH=/qianboshi-portfolio/
```

Vite 配置中的 `base`：

```ts
// frontend/vite.config.ts

export default defineConfig({
  base: process.env.VITE_BASE_PATH ?? "/",
});
```

### 5.5 快照生成方案

快照生成脚本直接调用后端 service 层，而不是通过 HTTP 请求本地 API：

```bash
cd backend

python scripts/generate_snapshots.py \
  --data-dir "E:/qianboshi-agent/data" \
  --db "E:/qianboshi-agent/data/qianboshi_decision.db" \
  --output "../frontend/public/snapshots"
```

脚本要求：

1. 读取 JSON 和 JSONL。
2. 只读连接 SQLite。
3. 通过 Pydantic schema 校验聚合结果。
4. 对列表数据进行截断，避免页面首包过大。
5. 输出六个页面快照。
6. 输出失败时返回非零退出码，不覆盖上一次有效快照。
7. 在每个快照中写入 `generated_at` 和 `data_as_of`。

建议快照策略：

- 首页：只保留最新 10 条简报和统计数据。
- 数据资产：保留聚合统计、最新 100 条观点、Top 来源。
- 决策台：保留聚合统计、完整时间线和最新 100 条决策摘要。
- 实盘纪律：保留组合当前状态和最近 180 天价格序列。
- 单条详情：静态版只支持快照中已包含的事件，不支持任意历史 ID 查询。

---

## 6. 主题与双语方案

### 6.1 页面与主题对应

| 页面 | `data-theme` |
|---|---|
| 首页 | `product` |
| 系统架构 | `architecture` |
| 数据资产 | `terminal` |
| 决策台 | `terminal` |
| 实盘纪律 | `product` |
| 关于 / 技术栈 | `product` |

资产卡内部允许使用产品风格：

```tsx
<section data-theme="terminal">
  <AssetCard data-theme="product" />
</section>
```

### 6.2 CSS Variables

```css
/* frontend/src/styles/themes.css */

:root,
[data-theme="product"] {
  --color-bg: #f7f8fa;
  --color-surface: #ffffff;
  --color-border: #e5e7eb;
  --color-heading: #061b31;
  --color-text: #374151;
  --color-muted: #6b7280;
  --color-brand: #0b7a75;
  --color-brand-hover: #08635f;
  --color-market-positive: #e05252;
  --color-market-negative: #26a269;
  --color-warning: #d99a2b;
  --color-info: #4d91e8;
  --shadow-panel: 0 12px 30px rgba(50, 50, 93, 0.12),
    0 3px 8px rgba(0, 0, 0, 0.08);
}

[data-theme="architecture"] {
  --color-bg: #0b1117;
  --color-surface: #111a23;
  --color-border: #263542;
  --color-heading: #f4f7fb;
  --color-text: #c9d5df;
  --color-muted: #8293a3;
  --color-brand: #5de2d0;
  --color-data-flow: #5de2d0;
  --color-model: #6ea8fe;
  --color-llm: #a78bfa;
  --color-scheduled: #f4c46b;
}

[data-theme="terminal"] {
  --color-bg: #0d1218;
  --color-surface: #141b23;
  --color-border: #293642;
  --color-heading: #f1f5f9;
  --color-text: #cbd5e1;
  --color-muted: #81909d;
  --color-brand: #0b7a75;
  --color-market-positive: #e05252;
  --color-market-negative: #26a269;
  --color-warning: #d99a2b;
  --color-info: #4d91e8;
}
```

颜色不得直接写进组件。组件只使用：

```css
color: var(--color-heading);
background: var(--color-surface);
border-color: var(--color-border);
```

### 6.3 Tailwind 映射

```ts
// frontend/tailwind.config.ts

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        page: "var(--color-bg)",
        surface: "var(--color-surface)",
        line: "var(--color-border)",
        heading: "var(--color-heading)",
        brand: "var(--color-brand)",
        muted: "var(--color-muted)",
        "market-positive": "var(--color-market-positive)",
        "market-negative": "var(--color-market-negative)",
        warning: "var(--color-warning)",
        info: "var(--color-info)",
      },
      boxShadow: {
        panel: "var(--shadow-panel)",
      },
      borderRadius: {
        panel: "6px",
      },
    },
  },
};
```

### 6.4 字体和数字

```css
:root {
  font-family:
    Inter,
    "PingFang SC",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    system-ui,
    sans-serif;
  font-variant-numeric: tabular-nums;
}

.metric-value,
.price,
.timestamp,
.code-value {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum";
}
```

标题使用细字重：

```css
.display-title {
  font-size: clamp(2.5rem, 5vw, 3.5rem);
  line-height: 1.08;
  font-weight: 300;
  letter-spacing: -0.02em;
}
```

### 6.5 语言路由

路由结构：

```text
/zh
/zh/architecture
/zh/assets
/zh/decisions
/zh/discipline
/zh/about

/en
/en/architecture
/en/assets
/en/decisions
/en/discipline
/en/about
```

```ts
// frontend/src/app/router.tsx

const routes = [
  { path: "/:locale", element: <OverviewPage /> },
  { path: "/:locale/architecture", element: <ArchitecturePage /> },
  { path: "/:locale/assets", element: <DataAssetsPage /> },
  { path: "/:locale/decisions", element: <DecisionDeskPage /> },
  { path: "/:locale/discipline", element: <DisciplinePage /> },
  { path: "/:locale/about", element: <AboutPage /> },
];
```

语言资源：

```ts
// frontend/src/i18n/locales/zh.ts

export default {
  nav: {
    overview: "概览",
    architecture: "系统架构",
    assets: "数据资产",
    decisions: "决策台",
    discipline: "实盘纪律",
    about: "关于",
  },
  metrics: {
    structuredViews: "结构化观点",
    ragChunks: "RAG Chunks",
    notes: "研究笔记",
    predictions: "回测预测事件",
  },
};
```

所有用户可见文本必须来自 i18n，不在组件中硬编码中文或英文。

---

## 7. 图表方案

### 首页

| 区块 | ECharts 类型 | 数据 |
|---|---|---|
| 核心指标 | 自定义 MetricCard，不使用图表 | `/overview/metrics` |
| 系统运行状态 | `Gauge` 或环形进度图 | `/overview` |
| 数据增长趋势 | `LineChart` | `/overview` |
| 深色系统预告 | 自定义流水线节点图 | `/architecture/pipeline` |

### 系统架构页

| 区块 | ECharts / 组件 | 数据 |
|---|---|---|
| 端到端流水线 | 自定义 React 节点 + SVG 连线或 ECharts `Graph` | `/architecture/pipeline` |
| 各阶段产出量 | `BarChart` | `/architecture` |
| 运行状态 | 状态标签和时间轴 | `/architecture` |
| MCP 工具 | 工具列表组件 | `/architecture/mcp-tools` |

架构页的数据流线使用 `#5DE2D0`，模型节点使用 `#6EA8FE`，LLM 节点使用 `#A78BFA`，定时任务使用 `#F4C46B`。

### 数据资产页

| 区块 | ECharts 类型 | 数据 |
|---|---|---|
| 资产数量 | MetricCard | `/assets/summary` |
| 来源覆盖 | 横向 `BarChart` | `/assets/coverage` |
| 观点时间分布 | `LineChart` 或 `BarChart` | `/assets` |
| 观点类别分布 | `Treemap` 或 `PieChart` | `/assets/summary` |
| RAG 分块分布 | `BarChart` | `/assets/rag` |
| 资产卡 | 自定义白底 `AssetCard` | `/assets/asset-cards` |

### 决策台

| 区块 | ECharts 类型 | 数据 |
|---|---|---|
| 预测事件时间线 | `ScatterChart` | `/decisions/timeline` |
| 命中率变化 | `LineChart` | `/decisions/timeline` |
| 方向分布 | `PieChart` | `/decisions/distribution` |
| 置信度分布 | `BarChart` | `/decisions/distribution` |
| 资产 × 方向 | `HeatmapChart` | `/decisions/distribution` |
| 决策列表 | 表格 | `/decisions` |

中国市场颜色语义：

- 上涨 / 看多：`market-positive`，实际颜色 `#E05252`
- 下跌 / 看空：`market-negative`，实际颜色 `#26A269`
- 警告：`warning`
- 信息：`info`

### 实盘纪律页

| 区块 | ECharts 类型 | 数据 |
|---|---|---|
| 当前组合净值 | `LineChart` | `/discipline/price-trends` |
| 资产价格趋势 | 多序列 `LineChart` | `/discipline/price-trends` |
| 当前仓位 | `BarChart` | `/discipline/portfolio` |
| 盈亏状态 | `Gauge` 或分段条 | `/discipline/portfolio` |
| 风险事件 | `ScatterChart` / 时间轴 | `/discipline/risk-events` |

### 按需引入 ECharts

```ts
// frontend/src/lib/echarts.ts

import * as echarts from "echarts/core";
import {
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  HeatmapChart,
  GraphChart,
  GaugeChart,
} from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DatasetComponent,
  VisualMapComponent,
  DataZoomComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  HeatmapChart,
  GraphChart,
  GaugeChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DatasetComponent,
  VisualMapComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

export { echarts };
```

图表组件只接收已经转换好的 `option`：

```ts
export interface ChartFrameProps {
  option: echarts.EChartsOption;
  height?: number;
  ariaLabel: string;
}
```

---

## 8. 分阶段实施计划

### Phase 0：项目骨架和数据契约

交付物：

- `frontend/` Vite React TypeScript 项目
- `backend/` FastAPI 项目
- 路由、主题变量、DataProvider 接口
- `schema_registry.py`
- SQLite 检查脚本
- `/health` API

验证方式：

```bash
cd frontend
npm install
npm run dev
```

浏览器可以打开 `/zh`，页面显示基础布局。

```bash
cd backend
uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/health
```

验收标准：

- 前端能启动
- 后端能启动
- `/health` 返回 `200`
- 语言路由和主题属性正常切换

### Phase 1：完成首页单页

交付物：

- 首页导航
- Hero 概览
- 核心指标
- 系统流水线预告区
- 最新简报摘要
- 白底产品风和深色预告模块

验证方式：

- 使用本地 mock provider
- 1440px、768px、390px 三种宽度手工检查
- 无横向滚动
- 首屏 10 秒内能看到系统真实规模和运行链路

### Phase 2：接入真实数据和后端 API

交付物：

- `overview.py`
- `assets.py`
- `decisions.py`
- `discipline.py`
- SQLite schema 检查结果
- JSON/JSONL repository
- Pydantic 响应模型
- 首页和数据资产页真实数据

验证方式：

```bash
curl http://localhost:8000/api/v1/overview
curl http://localhost:8000/api/v1/assets/summary
curl http://localhost:8000/api/v1/decisions/summary
curl http://localhost:8000/api/v1/discipline
```

验收标准：

- API 不写入 SQLite
- 缺失文件时返回结构化错误或空数据
- 所有数值和页面展示口径一致
- JSONL 不因一次性加载过大导致明显卡顿

### Phase 3：完成六页和图表

交付物：

- 架构页
- 数据资产页
- 决策台
- 实盘纪律页
- 关于页
- ECharts 图表
- 响应式布局

验证方式：

- 每个页面至少有真实数据区块
- 图表空数据、异常数据和加载状态可展示
- 通过浏览器检查 Console 无错误
- 图表在移动端不溢出

### Phase 4：双语和三套主题

交付物：

- `/zh`、`/en`
- `zh.ts`、`en.ts`
- `data-theme="product|architecture|terminal"`
- 主题化图表颜色
- 中英文长度适配

验证方式：

- 逐页切换中文和英文
- 刷新后语言保持
- 中英文 URL 可直接访问
- 不存在紫色 AI 主色污染
- 深色页文字对比度达到可读标准

### Phase 5：静态快照、部署和打磨

交付物：

- `generate_snapshots.py`
- `snapshot-client.ts`
- GitHub Actions
- GitHub Pages 部署
- SEO 基础信息和 404 页面
- 数据时效标识
- 性能和视觉检查报告

验证方式：

```bash
cd backend
python scripts/generate_snapshots.py \
  --data-dir "E:/qianboshi-agent/data" \
  --db "E:/qianboshi-agent/data/qianboshi_decision.db" \
  --output "../frontend/public/snapshots"

cd ../frontend
npm run build:snapshot
npm run preview
```

验收标准：

- 无 FastAPI 时静态版完整可用
- 刷新深层路径后不出现空白页
- GitHub Pages 子路径资源加载正常
- 页面明确显示数据生成时间
- 动态版和静态版组件视觉一致

---

## 9. 环境与依赖

### Node.js

要求：

```text
Node.js >= 20.18.0
npm >= 10
```

建议使用：

```bash
nvm install 20
nvm use 20
```

### 前端依赖

```json
{
  "dependencies": {
    "@vitejs/plugin-react": "^4.3.4",
    "echarts": "^5.5.1",
    "echarts-for-react": "^3.0.2",
    "i18next": "^23.16.8",
    "lucide-react": "^0.468.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-i18next": "^15.1.3",
    "react-router-dom": "^7.0.2"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@typescript-eslint/eslint-plugin": "^8.18.0",
    "@typescript-eslint/parser": "^8.18.0",
    "@vitejs/plugin-react": "^4.3.4",
    "autoprefixer": "^10.4.20",
    "eslint": "^9.16.0",
    "postcss": "^8.4.49",
    "prettier": "^3.4.2",
    "tailwindcss": "^3.4.16",
    "typescript": "^5.6.3",
    "vite": "^6.0.0"
  }
}
```

版本原则：

- 应用依赖使用兼容范围 `^`
- 部署和 CI 必须提交 `package-lock.json`
- CI 使用 `npm ci`
- ECharts 不引入完整 `echarts` 组件集合

### Python 依赖

```text
fastapi>=0.115,<1.0
uvicorn[standard]>=0.32,<1.0
pydantic>=2.9,<3.0
pydantic-settings>=2.6,<3.0
python-dotenv>=1.0,<2.0
orjson>=3.10,<4.0
```

说明：

- SQLite 使用 Python 标准库 `sqlite3`
- 不在作品集 API 中直接加载 Whisper、LLM 或 Chroma 推理模型
- Chroma 只读取统计信息；若生产环境不方便直接打开 Chroma，可在快照生成阶段读取统计后写入 JSON

### 初始化和启动命令

```bash
git clone <repository-url>
cd qianboshi-portfolio

cd frontend
npm install
npm run dev
```

本地动态后端：

```bash
cd backend

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Linux/macOS 激活命令：

```bash
source .venv/bin/activate
```

前端 Vite 代理：

```ts
// frontend/vite.config.ts

server: {
  proxy: {
    "/api": {
      target: "http://localhost:8000",
      changeOrigin: true,
    },
  },
}
```

推荐 scripts：

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "build:snapshot": "vite --mode snapshot build",
    "preview": "vite preview",
    "lint": "eslint .",
    "format": "prettier --write ."
  }
}
```

---

## 10. 风险与坑

### GitHub Pages 没有后端 API

GitHub Pages 只能托管静态资源。必须：

- 在部署前执行快照生成
- 构建时使用 `VITE_DATA_MODE=snapshot`
- 禁止静态页面调用 `/api/v1`
- 快照文件放在 `frontend/public/snapshots/`

### GitHub Pages 路由刷新

GitHub Pages 默认没有 SPA 服务端回退。需要同时处理：

1. Vite 配置正确 `base`。
2. 提供 `404.html`。
3. 将构建后的 `index.html` 复制为 `404.html`。
4. 页面内部使用 React Router 的 BrowserRouter 或 HashRouter。

推荐保持干净 URL，并在构建后执行：

```bash
cp dist/index.html dist/404.html
```

Windows PowerShell：

```powershell
Copy-Item dist/index.html dist/404.html
```

### GitHub Pages 资源路径

不能硬编码：

```text
/assets/logo.svg
```

应通过 Vite 处理资源，或使用：

```ts
const assetUrl = `${import.meta.env.BASE_URL}assets/logo.svg`;
```

### ECharts 体积

不能直接：

```ts
import * as echarts from "echarts";
```

必须使用 `echarts/core` 和按需注册组件。图表容器必须指定稳定高度：

```tsx
<div className="h-[320px] w-full">
  <ReactECharts option={option} style={{ height: "100%" }} />
</div>
```

### JSONL 读取和性能

`structured_views.jsonl` 不应在浏览器端直接读取。后端和快照脚本负责：

- 逐行解析
- 聚合统计
- 分页
- 截断返回
- 清理异常字段

### 中文数字对齐

金融页面需要稳定的数字宽度：

- 所有金额、数量、百分比使用 `font-variant-numeric: tabular-nums`
- 价格字段统一格式化函数
- 不使用依赖字体宽度的手工空格对齐
- 表格列设置最小宽度，避免数据变化导致布局抖动

### 快照数据时效性

静态页面必须显示：

```text
数据更新于 2025-01-15 08:30
运行模式：静态快照
```

快照顶部统一展示 `generated_at` 和 `data_as_of`。不得让用户误以为 GitHub Pages 展示的是实时行情。

### 深浅主题对比度

需要分别检查：

- `--color-muted` 在深色背景上的可读性
- 图表 tooltip 和 legend 的对比度
- 红涨绿跌在深色和白底上的区分度
- 架构页节点文本不使用过低透明度
- 边框不能只依靠颜色表达状态

状态应同时使用颜色、文字或图标表达，避免色觉差异导致信息丢失。

### 只读边界

FastAPI 必须：

- SQLite 使用只读 URI 或文件系统只读约束
- 不执行 `INSERT`、`UPDATE`、`DELETE`
- 不修改原始 JSON
- 不暴露任意文件路径参数
- 只允许配置文件中的固定数据目录
- 对异常字段进行 Pydantic 校验和降级处理

SQLite 只读连接示例：

```python
sqlite3.connect(
    f"file:{db_path}?mode=ro",
    uri=True,
)
```

### 真实数据字段不稳定

原始数据可能存在字段名称、时间格式和空值差异。必须在 repository 层做归一化：

```python
class NormalizedView(BaseModel):
    id: str
    source: str
    title: str
    symbol: str | None = None
    direction: str | None = None
    confidence: float | None = None
    published_at: datetime | None = None
```

页面不得直接依赖原始 JSONL 字段。

---

## 首批落地顺序

第一步执行：

```bash
mkdir -p frontend backend docs
```

随后完成：

1. `backend/scripts/inspect_sqlite.py`
2. `backend/app/repositories/schema_registry.py`
3. `frontend/src/data/provider.ts`
4. `frontend/src/types/`
5. `frontend/src/app/router.tsx`
6. 三套主题 CSS 变量
7. `/zh` 首页骨架
8. `/health` API

第一阶段验收通过后，再接入真实聚合数据和图表。这样可以先验证路由、主题、数据契约和双模式边界，再逐页增加业务展示内容。