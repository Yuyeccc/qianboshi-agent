​我会先确认当前工作区的仓库形态与是否已有前后端约定，再把文档写入一个明确的架构文档文件。内容会按可执行交付设计，包含目录、接口、类型、命令和验收标准，而不是只列概念选型。接下来我会以现有代码库为约束核对目录和依赖；若当前仓库尚无前端骨架，则文档会给出从零创建 `frontend/`、`backend/` 的完整路径和初始化命令，并把真实数据字段映射标注为需要在实现阶段由 SQLite schema 校准的边界。我将把交付物定位为仓库内的 `docs/architecture.md`，并同时覆盖静态 GitHub Pages 与本地 FastAPI 的运行契约。后续实现可以直接按该文档逐阶段验收。我现在检查工作区文件，避免文档目录或现有命名与项目冲突。# 钱博士 Agent 求职作品集网页技术栈架构文档

版本：`v0.2`  
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



---

### 路由库版本修订

前端路由统一使用 `react-router-dom ^6.28.0`，不使用 `react-router-dom ^7.0.2`。选择 v6 的原因是其 API、生态集成方案和中文资料均已稳定，能够满足本作品集的嵌套路由、动态路由、懒加载和错误边界需求；v7 在本项目中没有带来必须采用的功能收益。安装依赖示例：

```bash
npm install react-router-dom@^6.28.0
```

路由实现应使用 v6 规范，包括 `createBrowserRouter`、`RouterProvider`、`Outlet`、`useLoaderData` 和路由级 `lazy`；不得混用 v7 专属 API 或迁移期兼容写法。
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



---

### 实盘纪律页脱敏 API 契约

实盘纪律页不得向浏览器输出 `portfolio.json` 中的原始持仓、账户金额、成本价、单笔盈亏、累计盈亏、可反推真实仓位的持仓明细或任何其他敏感字段。后端必须在服务端读取原始数据后生成脱敏视图，前端只能调用脱敏后的接口；禁止将原始 `portfolio.json` 作为静态资源放入 `public/`，禁止通过下载接口、调试接口或错误响应泄露原始内容。

新增只读接口 `GET /api/discipline/overview`，响应字段固定如下：

```ts
type DisciplineOverviewResponse = {
  dataMode: "anonymized" | "demo";
  disclaimer: string;
  allocationByAssetClass: Array<{
    assetClass: "equity" | "bond" | "commodity" | "crypto" | "cash" | "other";
    weightPct: number; // 仅展示按资产类别聚合后的百分比，四舍五入至整数
  }>;
  strategyFramework: Array<{
    ruleId: string;
    title: string;
    description: string;
    status: "active" | "paused";
  }>;
  executionTimeline: Array<{
    date: string; // YYYY-MM-DD
    actionType: "rebalance" | "risk_check" | "rule_review" | "exit" | "other";
    summary: string;
    ruleIds: string[];
  }>;
  asOfDate: string; // YYYY-MM-DD
};
```

`allocationByAssetClass` 只能由服务端按资产类别汇总，并仅保留整数百分比；若任一类别的展示仍可结合其他公开信息反推单一标的，则合并到 `other`。`executionTimeline` 只允许输出纪律动作、规则编号和日期，不得包含金额、价格、数量、代码、收益率或具体持仓名称。若当前数据不能稳定完成上述脱敏聚合，则该接口必须返回 `dataMode: "demo"` 的固定演示数据，页面顶部必须显示“演示数据，非真实账户持仓”，且不得与真实数据混用。
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
| `GET` | `/api/v1/discipline` | 纪律总览(脱敏)：策略框架、纪律时间线、风险提示 | `market_cache.json`、SQLite、服务端脱敏聚合 |
| `GET` | `/api/v1/discipline/overview` | 资产类别占比(脱敏)、策略规则、执行时间线 | `portfolio.json`(仅服务端聚合)、`price_trends.json` |
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
| 实盘组合(脱敏) | `portfolio.json`(仅服务端聚合) | `discipline.json` |
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



---

### 数据口径表

首页、架构页和决策台的所有展示数字必须由可复跑的统计任务生成，并在构建时写入 `data-manifest.json`。页面不得手写“9473”“9400+”“3万+”等数字。每项数据必须同时保存统计值、统计命令或 SQL、数据源、统计执行时间和截止日期字段；当来源没有可用日期字段时，统一使用统计任务执行时间 `generatedAt` 作为截止时间，并在页面或数据说明中标注“截至构建时间”。

| 展示数字 | 精确统计方式 | 数据来源 | 截止日期字段 |
| --- | --- | --- | --- |
| 结构化观点数 | 在 Phase 0 确认实际表和字段后执行：`SELECT COUNT(*) FROM <structured_view_table> WHERE <view_id> IS NOT NULL;`；如观点存于 JSONL，则执行 `jq -s 'map(select(.<view_id> != null)) \| length' structured_views.jsonl` | SQLite 结构化观点表或 `structured_views.jsonl` | `<published_at>`；缺失时 `generatedAt` |
| RAG chunks 数 | 对实际 Chroma collection 执行 `collection.count()`，命令封装为 `python scripts/count_chroma.py --collection <confirmed_collection>` | Chroma 向量库 | chunk 元数据 `<created_at>` 或 `<source_published_at>`；缺失时 `generatedAt` |
| 笔记数 | `find notes -type f \( -name '*.md' -o -name '*.mdx' \) -print \| wc -l`；排除模板目录、隐藏目录和构建产物 | `notes/` | 文件修改时间 `mtime`，或笔记 frontmatter `date` |
| 回测预测事件数 | `SELECT COUNT(*) FROM <prediction_event_table> WHERE <event_type> IN ('prediction','forecast','backtest_prediction');`，事件类型枚举必须以实际 schema 为准 | SQLite 预测/回测事件表 | `<event_at>` 或 `<created_at>` |
| 分析师命中率 | 仅统计已结算且方向可判定的事件：`SUM(CASE WHEN <predicted_direction>=<realized_direction> THEN 1 ELSE 0 END) * 1.0 / COUNT(*)`；同时输出样本数 `COUNT(*)`，样本数小于 30 时页面显示“样本不足”而非百分比 | SQLite 预测结果表 | `<settled_at>` |
| 多空比 | 在同一有效时间窗内计算：`bullish_count / bearish_count`；`neutral` 不计入分母，若空头数为 0 则展示 `N/A` 而非无穷大 | 结构化观点表或 JSONL | `<published_at>` |
| 资产卡数 | `SELECT COUNT(DISTINCT <asset_identifier>) FROM <asset_or_view_table> WHERE <asset_identifier> IS NOT NULL;` | SQLite 资产/观点表 | `<published_at>` 或 `<updated_at>` |
| MCP 工具数 | `node scripts/count-mcp-tools.mjs`，脚本读取 MCP server 的实际工具注册表并统计唯一工具名；不统计未注册的源码文件或示例工具 | MCP server 工具注册模块 | 代码版本提交时间或 `generatedAt` |
| 最近简报时间 | `find briefs -type f -name '*.md' -printf '%T@ %p\n' \| sort -nr \| head -1`；若简报含 frontmatter，则优先取最新有效 `published_at` | `briefs/` 或简报数据库表 | `published_at`，无该字段时文件 `mtime` |
| 监控源数 | `SELECT COUNT(DISTINCT <source_id>) FROM <source_registry_table> WHERE <enabled>=1;`；若来源由配置文件维护，则读取配置并统计 `enabled: true` 的唯一 `sourceId` | 监控源注册表或 sources 配置 | `<updated_at>`，无该字段时 `generatedAt` |

`data-manifest.json` 中每项指标的最小结构如下，前端只读取该文件或其对应 API，不得自行重新计算导致页面口径漂移：

```ts
type MetricManifestItem = {
  key: string;
  value: number | string | null;
  unit: "count" | "ratio" | "datetime";
  query: string;
  source: string;
  cutoffField: string;
  cutoffValue: string;
  generatedAt: string;
  status: "verified" | "demo" | "unavailable";
};
```

当某项统计无法在真实数据上复跑时，必须将 `status` 标记为 `demo` 或 `unavailable`。`demo` 数据必须在对应页面邻近位置标注“演示数据”；`unavailable` 不展示虚构数字。


---

### 实盘纪律页数据源与脱敏映射

`portfolio.json` 仅作为服务端受限输入源，不得被前端、静态站点构建产物或通用数据查询接口直接访问。数据映射表中应新增以下约束：

| 页面模块 | 原始数据源 | 服务端允许读取字段类别 | API 可输出字段 | 明确禁止输出字段 |
| --- | --- | --- | --- | --- |
| 实盘纪律页：资产配置 | `portfolio.json` | 资产类别、内部权重计算所需字段 | 按资产类别聚合的整数仓位占比 | 标的代码、标的名称、数量、成本价、市值、现金额、账户总额、单一持仓占比 |
| 实盘纪律页：策略框架 | 策略规则配置或人工维护规则清单 | 规则名称、触发条件、风控原则、启停状态 | 通用策略规则框架和启停状态 | 与真实账户绑定的阈值、资金规模、具体下单参数 |
| 实盘纪律页：纪律时间线 | 交易/复盘日志或人工维护事件 | 日期、纪律动作类型、关联规则编号、脱敏摘要 | 无金额的纪律执行时间线 | 买卖标的、成交价、成交量、盈亏金额、收益率、订单号 |

服务端应将原始持仓解析、类别聚合和字段白名单控制封装在独立的 `disciplineView` 映射层中。除 `GET /api/discipline/overview` 外，其他 API 不得依赖或返回 `portfolio.json` 数据；日志、异常追踪和开发调试输出同样不得记录原始持仓对象。
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



---

### 区块级主题作用域

全局 `data-theme` 只负责应用默认主题，页面内的终端面板、数据密集区、浅色内容区等局部深浅过渡必须通过 `ThemeScope` 实现。`ThemeScope` 在 DOM 上创建局部主题边界，使 CSS 自定义属性在该区块及其子树内覆盖，而不会改变页面其他区域或全局用户偏好。组件签名如下：

```tsx
type ThemeName = "light" | "dark" | "terminal";

type ThemeScopeProps = React.PropsWithChildren<{
  theme: ThemeName;
  className?: string;
  transition?: boolean;
}>;

export function ThemeScope({
  theme,
  className,
  transition = true,
  children,
}: ThemeScopeProps): JSX.Element;
```

使用方式如下。页面可以嵌套多个主题区块，内层主题优先级高于外层主题；不允许通过直接修改 `document.documentElement.dataset.theme` 实现页面局部效果。

```tsx
<main data-theme={appTheme}>
  <HeroSection />
  <ThemeScope theme="terminal" className="decision-terminal">
    <DecisionTimeline />
    <SignalTable />
  </ThemeScope>
  <ThemeScope theme="light">
    <ResearchArchive />
  </ThemeScope>
</main>
```

`ThemeScope` 应输出 `data-theme-scope="<theme>"` 和可选的 `data-theme-transition="true"` 属性。CSS 使用变量覆盖而非为每个组件复制颜色定义，例如 `[data-theme-scope="terminal"] { --surface: #101614; --text-primary: #e8f0ea; --accent: #53d18a; }`。主题切换采用 `background-color`、`color`、`border-color`、`fill` 和 `stroke` 的 CSS `transition`，建议时长 `180ms` 至 `240ms`；当用户启用 `prefers-reduced-motion: reduce` 时必须禁用过渡动画。

对于随滚动进入视口的区块，使用 `IntersectionObserver` 为区块添加 `data-in-view="true"`，仅触发一次进入动画和主题过渡，不得在用户反复滚动时持续闪烁。观察阈值建议为 `0.2`，并在组件卸载时断开 observer。主题本身必须在首屏渲染时确定，滚动事件只控制视觉过渡，不得延迟或异步替换主题值。
### 双语数据文本策略

界面导航、按钮、筛选器、状态标签、空状态和说明文案属于 UI 文案，必须使用 i18n 字典提供中英文版本。分析师姓名、原始观点、研报摘要、笔记正文和原始资产名称属于数据内容，默认保持原文，不进行机器翻译、不因界面语言切换而改写，以避免语义失真和来源不可追溯。

UI 层维护一份受控的关键名词中英映射表，用于标签、筛选项、图例和辅助说明，不修改原始数据字段。映射至少覆盖分析师显示名别名、资产标准名称/代码和方向词：

```ts
type DataTermMap = {
  analystAliases: Record<string, { zh: string; en: string }>;
  assets: Record<string, { zh: string; en: string; symbol?: string }>;
  directions: {
    bullish: { zh: "看多"; en: "Bullish" };
    bearish: { zh: "看空"; en: "Bearish" };
    neutral: { zh: "中性"; en: "Neutral" };
  };
};
```

页面展示时，原始字段应保留为 `originalText` 或 `originalName`，映射后的字段仅作为 `displayLabel` 使用。观点卡、观点详情和引用区域必须固定显示“观点内容为原文”/“Opinion content is shown in its original language”；当映射不存在时，直接回退显示原始值，不得显示空白、猜测性翻译或英文占位符。
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



---


### 架构页流水线图实现

架构页的下载、转写、结构化和 RAG 流水线图不使用 ECharts Graph。该图使用自定义 React 节点和 SVG 连线实现，组件职责固定如下：

```tsx
type PipelineDiagramProps = {
  stages: PipelineStage[];
  activeStageId?: string;
};

function PipelineDiagram(props: PipelineDiagramProps): JSX.Element;
function PipelineNode(props: {
  stage: PipelineStage;
  index: number;
  total: number;
}): JSX.Element;
function SvgEdge(props: {
  from: DOMRect;
  to: DOMRect;
  status: "idle" | "active" | "complete" | "blocked";
}): JSX.Element;
```

`PipelineDiagram` 负责读取节点布局、响应断点和协调连线；`PipelineNode` 负责显示阶段名称、输入输出、已验证数据量和状态；`SvgEdge` 使用覆盖在节点容器上的 SVG 绘制连接路径、箭头和状态色。桌面端采用横向流程布局，移动端切换为纵向布局，连线方向随布局变化。节点位置应由 CSS Grid 或 Flexbox 管理，SVG 仅根据节点 `getBoundingClientRect()` 计算路径，不能以固定像素坐标硬编码。

采用该方案的原因是流水线节点数量有限且布局语义明确，自定义节点可以精确控制信息密度、主题切换、悬停状态和移动端重排；ECharts Graph 的自动布局在小屏幕和内容长度变化时不可预测，且会增加不必要的运行时体积。节点中的累计量必须读取已验证的 `data-manifest.json`；尚未验证的量显示“待核对”或“演示数据”，不得显示未经统计确认的数字。
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

### 决策台时间线聚合与降采样

决策台时间线不得将全部“3万+”预测/回测事件以单点散点图直接渲染。服务端或构建期数据任务必须先按时间粒度和资产维度聚合，默认查询窗口为最近 6 个月，默认时间粒度为月；用户可切换资产过滤条件，并在数据量较低时切换为周粒度。单次接口响应只返回当前筛选条件下的聚合桶，不返回未筛选的全量事件明细。

建议聚合结构如下：

```ts
type TimelineAggregate = {
  periodStart: string; // YYYY-MM-DD，按月或周的桶起点
  granularity: "month" | "week";
  assetId: string;
  eventCount: number;
  bullishCount: number;
  bearishCount: number;
  neutralCount: number;
  hitRate: number | null;
  settledCount: number;
};
```

聚合 SQL 应以实际 schema 核对后的字段替换占位符，逻辑如下：

```sql
SELECT
  date(<event_at>, 'start of month') AS period_start,
  <asset_id> AS asset_id,
  COUNT(*) AS event_count,
  SUM(CASE WHEN <direction> = 'bullish' THEN 1 ELSE 0 END) AS bullish_count,
  SUM(CASE WHEN <direction> = 'bearish' THEN 1 ELSE 0 END) AS bearish_count,
  SUM(CASE WHEN <direction> = 'neutral' THEN 1 ELSE 0 END) AS neutral_count,
  SUM(CASE WHEN <predicted_direction> = <realized_direction> THEN 1 ELSE 0 END) * 1.0
    / NULLIF(SUM(CASE WHEN <realized_direction> IS NOT NULL THEN 1 ELSE 0 END), 0) AS hit_rate,
  SUM(CASE WHEN <realized_direction> IS NOT NULL THEN 1 ELSE 0 END) AS settled_count
FROM <prediction_event_table>
WHERE <event_at> >= date('now', '-6 months')
  AND (:asset_id IS NULL OR <asset_id> = :asset_id)
GROUP BY period_start, asset_id
ORDER BY period_start ASC;
```

量级目标为：全量原始事件约 `30,000+` 条；若按最近 6 个月、约 20 个资产、月粒度聚合，最大约为 `6 × 20 = 120` 个桶；切换周粒度时最大约为 `26 × 20 = 520` 个桶。前端图表每次渲染应控制在 `600` 个聚合点以内。点击聚合桶时可打开侧边栏展示该桶的摘要、事件数量和方向分布；只有在用户继续点击“查看事件”后，才按分页请求该桶内原始事件，单页上限为 `50` 条。

| 资产价格趋势 | 多序列 `LineChart` | `/discipline/price-trends` |
| 资产类别配置 | 环形图/分段条 | `/discipline/overview` |
| 纪律执行状态 | 状态标签+时间轴 | `/discipline/overview` |
| 风险事件 | `ScatterChart` / 时间轴 | `/discipline/risk-events` |

### 实盘纪律页

| 区块 | ECharts 类型 | 数据 |
|---|---|---|
| 当前组合净值 | `LineChart` | `/discipline/price-trends` |
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



---

### Phase 0：实际 Schema 核对与类型冻结

在编写业务 TypeScript 类型、SQL 查询、API DTO 或前端 mock 数据之前，必须完成真实数据源核对。Phase 0 的唯一产出是《实际 schema 核对报告》，未经该报告确认不得冻结 `NormalizedView`、预测事件、资产、分析师或 RAG 元数据等类型定义，也不得将 v0.2 中的假设字段写入生产接口。

执行步骤如下：

1. 运行 `inspect_sqlite.py`，目标 SQLite 文件路径由环境变量或命令参数明确传入，例如：`python scripts/inspect_sqlite.py --db ./data/<actual-db>.sqlite --sample-limit 3`。
2. 对 `structured_views.jsonl` 执行原始记录抽样和字段枚举，例如：`head -n 3 data/structured_views.jsonl` 与 `jq -s 'map(keys) | add | unique' data/structured_views.jsonl`。
3. 将脚本输出、JSONL 原始样本、字段差异、主键候选、时间字段和可空性结论写入 `docs/actual-schema-report.md`。
4. 依据报告生成 `src/types/generated-data.ts` 或等效类型文件；每个字段必须标记来源表/JSONL 路径、可空性和转换规则。`NormalizedView` 只能作为经报告确认后的映射类型，不得作为原始数据 schema 的替代品。

`inspect_sqlite.py` 对每张实际存在的表必须打印以下内容，输出顺序按表名排序，样本行数量固定为前 3 条或由 `--sample-limit` 指定：

```text
数据库路径与文件哈希
SQLite 版本
表名
建表 SQL（sqlite_master.sql）
列名、声明类型、NOT NULL、默认值、主键顺序
索引名及索引列
总行数（SELECT COUNT(*)）
样本行（SELECT * LIMIT 3，字段名和值均完整输出）
候选时间字段及最小值/最大值
```

对于 `structured_views.jsonl`，报告必须原样保留前 3 条记录，不得在展示前进行字段删除、重命名或格式化；随后输出顶层字段并集、每个字段出现次数、字段值类型集合、可为空字段和嵌套对象字段路径。若 SQLite 与 JSONL 表示同一业务实体但字段名或语义不一致，报告必须列出映射关系和无法映射的字段，待人工确认后再冻结类型。
### Phase 1.5：数据可行性验证与数据清单

在架构页、首页信任数据和决策台开始前端实现前，新增 Phase 1.5“数据可行性验证”。该阶段必须用真实数据对每个计划展示的累计量执行一次可复跑聚合，并输出 `docs/data-inventory.md` 与 `public/data-manifest.json`。`data-inventory.md` 至少记录指标名称、统计命令或 SQL、原始结果、数据源路径/表名、时间范围、截止字段、执行时间、负责人和验证状态。

架构页阶段量的建议统计口径如下：

| 流水线阶段 | 验证统计方式 | 备注 |
| --- | --- | --- |
| 下载 | `find <downloads_dir> -type f -print \| wc -l` | 仅统计有效下载产物；排除临时文件、`.DS_Store`、日志和重复缓存 |
| 转写 | `find <transcripts_dir> -type f \( -name '*.txt' -o -name '*.json' -o -name '*.srt' \) -print \| wc -l` | 需明确一个源文件对应一个转写任务还是一个转写文件 |
| 结构化 | `SELECT COUNT(*) FROM <confirmed_structured_table>;` 或 `jq -s 'length' structured_views.jsonl` | 表名与 JSONL 路径必须以 Phase 0 报告为准 |
| 笔记 | `find notes -type f \( -name '*.md' -o -name '*.mdx' \) -print \| wc -l` | 排除模板和构建目录 |
| 预测/回测事件 | `SELECT COUNT(*) FROM <confirmed_prediction_event_table>;` | 必须在报告中注明事件类型筛选条件 |
| RAG chunks | `python scripts/count_chroma.py --collection <confirmed_collection>`，内部调用 `collection.count()` | 必须记录 collection 名称、持久化目录和 collection 元数据 |
| 监控源 | 读取真实 source registry，统计唯一且 `enabled=true` 的 `sourceId` | 禁止按配置文件行数统计 |

每个展示数字必须先通过真实数据验证，再进入页面文案和图表实现。统计任务无法运行、数据源不存在、字段语义不明确或结果无法解释时，前端必须将对应项目标记为“演示数据”，并在紧邻数字或图例的位置显示该标记；不得以估算值、历史截图或手工填写数字替代真实统计结果。只有 `data-manifest.json` 中 `status: "verified"` 的指标可以作为作品集的真实能力证明展示。
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