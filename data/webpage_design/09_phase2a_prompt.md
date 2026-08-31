# Phase 2a 实现提示词 — 简报列表页 + 详情页（v1.0）

你是资深全栈工程师。在"钱博士Agent 作品集网页"（E:\qianboshi-portfolio，Phase 0/1 已完成并实测通过）上实现 **Phase 2a：简报列表页与详情页**。遵守现有架构约束，只改/新增本提示词列出的文件。

## 一、现有架构（必须遵守）
- 前端：Vite + React 18 + TS + Tailwind 3 + react-router-dom v6 + i18next；`@/` 别名 = `frontend/src/`；样式全走 CSS 变量（`bg-surface`/`border-line`/`text-heading`/`text-muted`/`text-brand` 等 Tailwind 映射，禁止硬编码色值）；`data-theme` 三套主题
- 数据层：`DataProvider` 接口（`src/data/provider.ts`），`ApiClient`（`src/data/api-client.ts`，fetch 失败返回空结构不抛错）、`SnapshotClient`（`src/data/snapshot-client.ts`）；类型在 `src/types/index.ts`
- 路由：`src/app/router.tsx`（createBrowserRouter，`:locale` 前缀：zh/en），页面组件 default export
- i18n：`src/i18n/locales/zh.ts`、`en.ts`，所有 UI 文案走 t()
- 后端：FastAPI（backend/，Python 3.14），`app/main.py` 里 `api_router = APIRouter(prefix="/api/v1")`，repositories 在 `app/repositories/`，只读（SQLite mode=ro），每项独立 try/except
- 现有页面：OverviewPage 已接真实数据（9727 观点/31320 事件/987 笔记/11011 chunks/最新简报文件名）
- **重要**：简报数据目录 `DATA_DIR = E:\qianboshi-agent\data\briefs`，里面是中文 md 文件（如 `日报_2026-08-22.md`）

## 二、后端改动

### 1. 新建 `backend/app/repositories/brief_repo.py`
- `BRIEFS_DIR = Path(r"E:\qianboshi-agent\data\briefs")`
- `list_briefs() -> list[dict]`：扫描目录 `*.md`，按 mtime 降序，返回 `[{filename, date(文件名里提取 YYYY-MM-DD 或取 mtime 日期), generated_at(ISO), size_bytes}]`；空目录返回 `[]`
- `get_brief(filename: str) -> dict | None`：**安全校验**——`filename` 必须匹配 `^[\w\u4e00-\u9fa5\-\.]+\.md$` 且 `(BRIEFS_DIR / filename).resolve().parent == BRIEFS_DIR.resolve()`，防路径穿越；文件存在返回 `{filename, content(原文), generated_at}`，否则 None
- 全部 try/except，异常返回 None/空

### 2. 改 `backend/app/main.py`
新增（挂在 api_router 下）：
- `GET /api/v1/briefs` → `{"briefs": [...list_briefs()]}`
- `GET /api/v1/briefs/{filename}` → `{"brief": {...}}` 或 404 `{"error": "not found"}`（filename 用 path 参数）

## 三、前端改动

### 3. 改 `src/types/index.ts` 增加：
```ts
export interface BriefItem {
  filename: string;
  date: string | null;
  generatedAt: string | null;
  sizeBytes: number | null;
}
export interface BriefDetail {
  filename: string;
  content: string;
  generatedAt: string | null;
}
```

### 4. 改 `src/data/provider.ts` 接口增加：
```ts
getBriefs(): Promise<BriefItem[]>;
getBrief(filename: string): Promise<BriefDetail | null>;
```
### 5. 改 `src/data/api-client.ts`：
- `getBriefs()`：fetch `/v1/briefs`，映射 `data.briefs`，失败返回 `[]`
- `getBrief(filename)`：fetch `/v1/briefs/${encodeURIComponent(filename)}`，失败/404 返回 null
### 6. 改 `src/data/snapshot-client.ts`：
- 对应方法读 `/snapshots/briefs.json`（Phase 5 才真正生成文件，现在读不到返回 `[]`/null 即可，结构先对齐）

### 7. 新建 `src/pages/BriefListPage.tsx`
- 路由 `/zh/briefs`（及 /en/briefs），default export
- 从 DataContext 拿 provider，`getBriefs()` 加载；loading/error/空 三态
- 列表：每行 = 文件名 + 日期 + 大小（KB，千分位），整行是 Link 到 `/briefs/${encodeURIComponent(filename)}`（locale 前缀），hover 高亮；白底产品风（bg-surface 卡片、border-line、圆角 6px）
- 页面标题走 i18n（`briefs.title`）
- 空数据时显示"—"或"暂无简报"（i18n key）

### 8. 新建 `src/pages/BriefDetailPage.tsx`
- 路由 `/zh/briefs/:filename`（及 /en），default export；`useParams` 拿 filename，`getBrief(filename)` 加载
- 渲染：返回按钮（Link 到 `/:locale/briefs`）+ 标题（文件名）+ 生成时间 + markdown 正文
- markdown 渲染：用 `react-markdown` + `remark-gfm`（表格/任务列表支持）。**新增依赖**：`react-markdown`、`remark-gfm`（package.json dependencies，版本用 ^9 和 ^4 最新稳定）
- 样式：`.prose-brief` 自定义样式（写在 `src/index.css`）——标题层级（h1/h2/h3）、表格（边框 border-line、表头 bg-surface-muted）、列表、引用块、代码块、加粗；正文白底阅读风（bg-surface、text-heading/text-muted）；表格中的涨跌色文本（红 #E05252 / 绿 #26A269 语义）原样保留
- 不存在的简报显示"未找到"（i18n key）+ 返回按钮
- loading 显示"加载中…"

### 9. 改 `src/pages/OverviewPage.tsx`
- "最新简报"区块：文件名从纯文本改为 `Link` 到 `/:locale/briefs/{encodeURIComponent(filename)}`（带图标或样式提示可点击，如 hover:text-brand + 箭头）；旁边加"全部简报"链接（Link 到 `/:locale/briefs`）
- 文件名为 null 时保持"—"不可点

### 10. 改 `src/app/router.tsx`
- 在 localeRoute children 增加：`{ path: "briefs", element: <BriefListPage /> }`、`{ path: "briefs/:filename", element: <BriefDetailPage /> }`

### 11. 改 `src/i18n/locales/zh.ts`、`en.ts`
新增 key：`briefs.title`（简报/Reports）、`briefs.empty`（暂无简报/No briefs yet）、`briefs.notFound`（未找到该简报/Brief not found）、`briefs.back`（返回/Back）、`briefs.all`（全部简报/All briefs）、`briefs.date`（日期/Date）、`briefs.size`（大小/Size）、`briefs.generatedAt`（生成时间/Generated at）

## 四、验收标准
1. `curl http://localhost:8010/api/v1/briefs` 返回简报列表（含 日报_2026-08-22.md，20 个左右）
2. `curl "http://localhost:8010/api/v1/briefs/日报_2026-08-22.md"` 返回 md 原文（URL 编码中文）；`curl ".../../../etc/passwd"` 类路径穿越返回 404/None 不崩
3. 前端 `/zh/briefs` 列表正常显示，点条目进详情页，markdown 表格/标题渲染正常
4. 首页最新简报可点击跳详情；"全部简报"链接可用
5. 中英切换正常（UI 文案翻译，简报正文保持中文）
6. `npm run build` TS 零错误
7. 停后端：列表页空态、详情页"未找到"、首页不可点，页面不崩
8. 不改动 Phase 0/1 已验收的其他行为（导航/主题/OverviewPage 数据）

## 五、输出格式
按文件输出，每个文件用标记包裹：
```
<<<FILE: backend/app/repositories/brief_repo.py>>>
完整内容
<<<END>>>
```
需要新建的文件：backend/app/repositories/brief_repo.py、frontend/src/pages/BriefListPage.tsx、frontend/src/pages/BriefDetailPage.tsx
需要修改的文件：backend/app/main.py、frontend/src/types/index.ts、frontend/src/data/provider.ts、frontend/src/data/api-client.ts、frontend/src/data/snapshot-client.ts、frontend/src/pages/OverviewPage.tsx、frontend/src/app/router.tsx、frontend/src/i18n/locales/zh.ts、frontend/src/i18n/locales/en.ts、frontend/package.json（加 react-markdown/remark-gfm）、frontend/src/index.css（加 .prose-brief）
只输出这些文件的代码，无解释废话。
