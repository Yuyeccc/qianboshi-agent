# Phase 0 实现提示词 — 钱博士Agent 作品集网页（v1.0）

你是资深前端工程师 + Python 后端工程师。按以下要求实现"钱博士Agent 求职作品集网页"的 **Phase 0 项目骨架**。严格遵守设计约束，输出可直接运行的代码。

## 一、项目背景（一句话）
钱博士Agent：真实运行的 AI 金融投研系统（B站多UP主采集 → GPU转写 → ASR纠错 → LLM结构化 → ChromaDB RAG → 盘前简报 → 飞书推送）。本网页是其求职作品集展示站，6页多页面，中英双语，三套主题。

## 二、技术栈（已定稿，不得更换）
- 前端：Vite + React 18 + TypeScript + Tailwind CSS 3 + react-router-dom ^6.28.0 + ECharts（按需引入，Phase 0 暂不装图表代码）+ lucide-react
- 后端：FastAPI（只读 API，Python 3.14，标准库 sqlite3）
- 双语：Phase 0 只搭 i18n 结构（react-i18next 资源文件骨架），不要求完整翻译
- 数据访问：DataProvider 接口 + 两个实现（api-client / snapshot-client），VITE_DATA_MODE 环境变量切换

## 三、设计约束（必须遵守，组件不得硬编码颜色）
三套主题通过 `data-theme` 属性切换（product / architecture / terminal），CSS 变量定义在 `frontend/src/styles/themes.css`：

```css
:root, [data-theme="product"] {
  --color-bg: #F7F8FA; --color-surface: #FFFFFF; --color-border: #E5E7EB;
  --color-heading: #111827; --color-text: #4B5563; --color-muted: #6B7280;
  --color-brand: #0B7A75; --color-brand-hover: #08635F;
  --color-market-positive: #E05252; --color-market-negative: #26A269;
  --color-warning: #D99A2B; --color-info: #4D91E8;
  --shadow-panel: 0 12px 30px rgba(50,50,93,0.12), 0 3px 8px rgba(0,0,0,0.08);
}
[data-theme="architecture"] {
  --color-bg: #0B1117; --color-surface: #111A23; --color-border: #263542;
  --color-heading: #F4F7FB; --color-text: #C9D5DF; --color-muted: #8293A3;
  --color-brand: #5DE2D0; --color-data-flow: #5DE2D0; --color-model: #6EA8FE;
  --color-llm: #A78BFA; --color-scheduled: #F4C46B;
}
[data-theme="terminal"] {
  --color-bg: #0D1218; --color-surface: #141B23; --color-border: #293642;
  --color-heading: #F1F5F9; --color-text: #CBD5E1; --color-muted: #81909D;
  --color-brand: #0B7A75;
  --color-market-positive: #E05252; --color-market-negative: #26A269;
  --color-warning: #D99A2B; --color-info: #4D91E8;
}
```

- 字体：`Inter, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif`；数字/指标用 `font-variant-numeric: tabular-nums`
- 标题细字重：`.display-title { font-weight: 300; letter-spacing: -0.02em; }`
- 圆角克制（4-8px），不用胶囊圆角；品牌青 #0B7A75 为主色，禁止紫色
- 禁止 AI 味：不用全屏渐变、不用"图标+标题+三行文案"卡片三连堆满页面、不造假数据
- Tailwind 通过 `tailwind.config.ts` 的 `extend.colors` 映射到 CSS 变量（page/surface/line/heading/text/muted/brand/market-positive/market-negative/warning/info）

## 四、Phase 0 交付物（严格按此目录结构）

项目根目录：**`E:\qianboshi-portfolio`**（与 qianboshi-agent 平级的独立目录/独立 git 仓库，方便以后推 GitHub Pages）。

```
qianboshi-portfolio/
├── README.md                    # 项目说明：双模式、启动命令、目录结构
├── package.json                 # workspace 根：frontend 的依赖放 frontend/，根只放脚本
├── docs/
│   └── architecture.md          # 从 E:\qianboshi-agent\data\webpage_design\04_tech_architecture_v2.md 复制
├── frontend/
│   ├── index.html               # lang 占位、引入 /src/main.tsx
│   ├── package.json             # 依赖：react, react-dom, react-router-dom@^6.28.0, i18next, react-i18next, lucide-react; dev: vite, @vitejs/plugin-react, typescript, tailwindcss@^3, postcss, autoprefixer, @types/react, @types/react-dom; scripts: dev=vite, build=vite build, preview=vite preview, build:snapshot=vite build --mode snapshot
│   ├── tsconfig.json            # strict, jsx react-jsx, paths: @/* -> src/*
│   ├── vite.config.ts           # plugin-react, resolve.alias @, server.proxy /api -> http://localhost:8000
│   ├── tailwind.config.ts       # extend.colors 映射 CSS 变量（见设计约束）
│   ├── postcss.config.js
│   ├── .env.local               # VITE_DATA_MODE=live, VITE_API_BASE_URL=/api
│   ├── .env.snapshot            # VITE_DATA_MODE=snapshot, VITE_API_BASE_URL=/snapshots
│   ├── public/snapshots/.gitkeep
│   └── src/
│       ├── main.tsx             # 挂载 App，引入 themes.css + index.css
│       ├── App.tsx              # RouterProvider / 语言路由外层
│       ├── vite-env.d.ts
│       ├── index.css            # @tailwind base/components/utilities + 基础样式（字体、tabular-nums、.display-title）
│       ├── styles/themes.css    # 三套主题 CSS 变量（见设计约束）
│       ├── app/
│       │   ├── router.tsx       # createBrowserRouter, 路由: /:locale, /:locale/architecture, /:locale/assets, /:locale/decisions, /:locale/discipline, /:locale/about; 兜底 redirect / -> /zh
│       │   ├── providers.tsx    # I18nextProvider + DataProvider context
│       │   └── config.ts        # runtimeMode = import.meta.env.VITE_DATA_MODE === 'snapshot' ? 'snapshot' : 'live'; apiBaseUrl
│       ├── data/
│       │   ├── provider.ts      # DataProvider 接口 + getDataProvider() 工厂（按 config.runtimeMode 返回 live/snapshot 实现）
│       │   ├── api-client.ts    # ApiClient implements DataProvider：fetch 实现，每个方法返回空骨架数据（Phase 0 不接真实数据，方法体返回 Promise.resolve({...空结构}))
│       │   └── snapshot-client.ts # SnapshotClient implements DataProvider：读 public/snapshots/*.json，缺失文件返回空结构
│       ├── types/
│       │   └── index.ts         # OverviewData/ArchitectureData/AssetsData/DecisionSummary/DisciplineData/AboutData 等骨架类型 + DataMeta/Metric/DataMode
│       ├── i18n/
│       │   ├── index.ts         # i18next 初始化：zh/en 资源，lng 从路由参数取
│       │   └── locales/zh.ts    # nav 6项 + 首页 hero 文案骨架（中）
│       │   └── locales/en.ts    # 同上（英）
│       ├── components/layout/
│       │   ├── SiteShell.tsx    # 布局壳：Header + Outlet + Footer，读取 useParams locale
│       │   ├── Header.tsx       # 顶部导航：6页链接（前缀 locale）、语言切换（中/EN）、滚动吸顶
│       │   └── Footer.tsx       # 底部：GitHub 链接占位 + 数据时效提示占位
│       └── pages/
│           ├── OverviewPage.tsx       # 首页骨架：Hero（项目名+一句话定位+状态标签占位）+ 信任数据带（4个 MetricCard 占位数字）+ 流水线预告（横向步骤条）
│           ├── ArchitecturePage.tsx   # 架构页占位：页面标题 + "Phase 1 实现"提示
│           ├── DataAssetsPage.tsx     # 占位
│           ├── DecisionDeskPage.tsx   # 占位
│           ├── DisciplinePage.tsx     # 占位
│           └── AboutPage.tsx          # 占位
├── backend/
│   ├── requirements.txt         # fastapi, uvicorn, pydantic
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app：CORS 允许 localhost:5173；GET /health 返回 {status:"ok", version:"0.1.0"}；挂载 api/v1 路由（Phase 0 只留 /api/v1/meta 返回数据模式说明）
│   │   └── repositories/
│   │       ├── __init__.py
│   │       └── schema_registry.py  # DATA_PATHS 常量（数据目录、DB路径）+ KNOWN_TABLES 占位（Phase 1 由 inspect 填充）
│   └── scripts/
│       └── inspect_sqlite.py    # 数据路径写死：DB = E:\qianboshi-agent\data\qianboshi_decision.db（只读 mode=ro），JSONL = E:\qianboshi-agent\data\views\structured_views.jsonl；打印每张表 表名/列名/行数/前2行样本 + JSONL 前3条原始记录与顶层字段枚举；报告写入 E:\qianboshi-agent\data\webpage_design\07_schema_report.md（同时 stdout 打印）
```

## 五、验收标准（Phase 0 完成必须全部通过）
1. `cd frontend && npm install && npm run dev` 成功，localhost:5173 打开无报错
2. `/` 重定向 `/zh`，六个语言路由可切换，404 兜底
3. 导航 6 项 + 中/EN 切换按钮可用（i18n 生效）
4. `data-theme` 在 `<html>` 或 `<body>` 上切换时三套主题色生效（可在 Header 加临时主题切换按钮，标注 TODO 移除）
5. 首页显示 Hero + 数据带 + 流水线预告骨架，无 AI 味（无渐变堆砌、无假数据暗示——占位数字用 "—" 或明确 "待接入" 标注）
6. `cd backend && pip install -r requirements.txt && uvicorn app.main:app` 启动成功，`/health` 返回 200
7. `python backend/scripts/inspect_sqlite.py` 运行成功，输出 07_schema_report.md（记录实际表结构）
8. `npm run build` 通过（TS 无错误）
9. 代码无 BOM、无缩进混乱；所有组件颜色来自 CSS 变量，无硬编码色值

## 六、输出要求
按文件逐个输出代码，每个文件用以下标记包裹：
```
<<<FILE: relative/path/to/file>>>
文件完整内容
<<<END>>>
```
不要输出解释性废话，不要输出未要求的文件。无法确定真实 schema 时用占位并注明 TODO。

## 七、禁止事项
- 不实现 Phase 1+ 内容（真实数据接入、图表、快照生成、GitHub Actions）
- 不改动 E:\qianboshi-agent 下任何现有文件（只新增 qianboshi-portfolio/ 和 webpage_design/ 下文件）
- 不引入 Next.js、不引入 axios、不引入 UI 组件库（shadcn 等）
