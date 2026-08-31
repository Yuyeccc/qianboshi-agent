# Phase 2b 实现提示词 — 简报视觉升级（v1.0）

你是资深前端工程师 + 设计系统工程师。在"钱博士Agent 作品集网页"（E:\qianboshi-portfolio，Phase 0/1/2a 已完成实测）上实现 **Phase 2b：简报功能视觉升级**（首页最新简报卡片、列表页、详情页三处美化）。遵守现有架构，只改/新增本提示词列出的文件。

## 一、现有架构（必须遵守）
- Vite + React 18 + TS + Tailwind 3；`@/` = `frontend/src/`
- 三套主题 `data-theme="product|architecture|terminal"`，CSS 变量在 `src/styles/themes.css`，Tailwind 映射在 `tailwind.config.ts`（现有映射：page/surface/line/heading/text/muted/brand/market-positive/market-negative/warning/info + shadow-panel）；**组件一律用 Tailwind 映射类，禁止直写 var(--xxx) 或硬编码色值**
- 数据：`BriefItem {filename, date, generatedAt, sizeBytes}`、`BriefDetail {filename, content, generatedAt}`（src/types/index.ts）；`getBriefs()`/`getBrief()` 在 DataProvider/ApiClient/SnapshotClient
- 路由：`/:locale/briefs`、`/:locale/briefs/:filename`
- i18n：zh.ts/en.ts；现有 key：briefs.title/empty/notFound/back/all/date/size/generatedAt
- 现有页面：OverviewPage（最新简报区块=文件名链接+"全部简报"）、BriefListPage（表格）、BriefDetailPage（返回+H1+时间+prose-brief 全文）
- **新增依赖已装**：react-markdown ^9 + remark-gfm ^4（详情页在用）

## 二、设计规格（已由 gpt-5.6 设计方案定稿，10_brief_visual_upgrade.md）

### A. themes.css 扩展（三套主题各补 7 个 token）
每套主题新增（务必加到对应 data-theme 块里）：

product：
```css
--color-surface-raised: #FFFFFF;
--color-surface-subtle: #F7F9FC;
--color-surface-brand: #E6F5F3;
--color-border-strong: #C9D4DE;
--color-brand-strong: #09635F;
--shadow-card: 0 8px 24px rgba(50, 50, 93, 0.06);
--shadow-card-hover: 0 14px 34px rgba(50, 50, 93, 0.11);
```
architecture：
```css
--color-surface-raised: #17232E;
--color-surface-subtle: #111A23;
--color-surface-brand: #123B38;
--color-border-strong: #385263;
--color-brand-strong: #7DE8D8;
--shadow-card: 0 8px 28px rgba(0, 0, 0, 0.25);
--shadow-card-hover: 0 14px 38px rgba(0, 0, 0, 0.35);
```
terminal：
```css
--color-surface-raised: #1B2530;
--color-surface-subtle: #141B23;
--color-surface-brand: #153A3A;
--color-border-strong: #3A4B59;
--color-brand-strong: #35B8AE;
--shadow-card: 0 8px 28px rgba(0, 0, 0, 0.3);
--shadow-card-hover: 0 14px 38px rgba(0, 0, 0, 0.4);
```

### B. tailwind.config.ts 扩展映射
extend.colors 增加：`surfaceRaised/surfaceSubtle/surfaceBrand/borderStrong/brandStrong`（映射对应 var）；extend.boxShadow 增加：`card/cardHover`。

### C. 新建 `src/utils/brief.ts`（工具函数，纯函数无依赖）
```ts
export function slugify(text: string): string
// 生成锚点 id：中文保留，空白/标点换 -，小写，去重由调用方处理
export function extractBriefHeadings(content: string): Array<{ id: string; text: string }>
// 正则 /^##\s+(.+)$/gm 提取二级标题；id = slugify(文本)，重名加 -2/-3 后缀
export function extractBriefSummary(content: string, maxLen = 90): string
// 取第一个非空正文段落：去掉行首 ==== 分隔线、# 标题行、markdown 符号（# * > ` []( )），截 maxLen 字加 …
export function countBriefSections(content: string): number  // /^##\s+/gm 计数
export function groupBriefsByMonth(items: BriefItem[]): Array<{ month: string; label: string; items: BriefItem[] }>
// month="2026-08"，label="2026 年 8 月"，按月降序
export function formatShortDate(date: string | null): string  // "2026-08-22" -> "8月22日"
export function formatFileSize(bytes: number | null): string  // "9 KB"
```

### C2. 后端补充（首页卡片需要摘要/章节数）
改 `backend/app/repositories/overview_repo.py` 的 `get_latest_brief()`：返回增加 `summary`（文件内容提取首段，逻辑同前端 extractBriefSummary：去分隔线/标题/markdown 符号，截 90 字）和 `section_count`（`^##\s+` 计数，正则用 re.MULTILINE）；文件读取失败时 summary/section_count 为 None/0。改 `frontend/src/types/index.ts`：LatestBrief 类型增加 `summary: string | null` 和 `sectionCount: number | null`；api-client 的 getOverview 映射相应字段。

### D. 新建组件（放 src/components/brief/ 下，5 个文件）
1. **BriefDateBadge.tsx** `({ date, size = "large" })`：日期徽章——large：上"22"大字(2xl,tabular-nums,text-heading)+下"AUG 2026"(11px uppercase,text-muted) 竖排，正方形圆角 8px，border-line + bg-surface-subtle 内衬；small：紧凑横排"8.22"。date 为 null 时显示"—"
2. **ReadingProgressBar.tsx**：顶部 fixed（top-0 left-0 z-50 h-[3px]），内部品牌色宽度 = 滚动百分比（scrollY / (scrollHeight - innerHeight)），useEffect 监听 scroll + resize，无数据时隐藏
3. **BriefToc.tsx** `({ headings })`：右侧 sticky（lg:sticky lg:top-16），"本页目录"小标题 + 标题列表（text-sm，hover:text-brand，当前高亮可选但非必须——Phase 2b 不做滚动监听高亮，纯锚点跳转）；headings 空则不渲染；点击 `document.getElementById(id)?.scrollIntoView({behavior:"smooth"})`，每个正文标题要加 `scroll-mt-24` class（在 MarkdownRenderer 的 h2 自定义渲染里加）
4. **BriefPagination.tsx** `({ previous, next, locale })`：底部双栏——上一篇（left, ArrowLeft 图标）/下一篇（right, ArrowRight），各自 Link 到对应 briefs/:filename，无则 disabled 样式（text-muted 不可点）
5. **LatestBriefCard.tsx** `({ brief, locale })`：首页最新简报卡片（整卡 Link）：
   - 外层：group relative block rounded-lg border border-line bg-surfaceRaised shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:border-brand hover:shadow-cardHover
   - 内层 grid：`sm:grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-5 p-6 sm:p-8`——BriefDateBadge(large) + 主区 + 箭头按钮（ArrowUpRight，圆角方块 border-line group-hover:bg-brand group-hover:text-surface）
   - 主区：状态行（绿点+已生成标签，text-brand 用 surface-brand 底 pill）+ 标题（truncate text-xl font-medium text-heading group-hover:text-brand）+ 摘要（line-clamp-2 text-sm text-text）+ 底部 meta 行（章节数 Layers3 图标+生成时间 Clock3 图标，text-xs text-muted）
   - 所有文案走 t()（i18n key 见 F）

### E. 页面改造（3 个）
1. **OverviewPage.tsx**：最新简报区块改为——区块头（eyebrow 小标签 uppercase tracking text-brand + H2 标题 + 右侧"全部简报"链接带 ArrowUpRight）+ LatestBriefCard（数据来自已有 overview.latestBrief，注意映射：filename/date(从 filename 提取 YYYY-MM-DD 正则，取不到用 generatedAt)/generatedAt）；latestBrief.filename 为 null 时保持"—"不渲染卡片
2. **BriefListPage.tsx**：重构——
   - 容器 `mx-auto max-w-5xl`（页面级，SiteShell 已有 max-w-7xl，此页内容内部再加 max-w-5xl 容器）
   - 面包屑（首页 / 简报，text-xs text-muted，hover:text-brand）
   - 头部：eyebrow（"Daily research output"）+ H1 简报（text-4xl sm:text-5xl font-medium tracking-tight）+ 描述（briefs.description，text-sm text-muted）
   - 统计条：`grid border-y border-line sm:grid-cols-3`，三项：累计简报 X 篇 / 最近更新 formatShortDate / 覆盖时间 formatShortDate（label 小字 text-muted + value tabular-nums text-heading）
   - 按月分组：每组 MonthGroupHeader（"2026 年 8 月" text-base font-medium + 组内数量 text-xs text-muted）→ 组内行列表（卡片：rounded-lg border border-line bg-surface shadow-card hover:border-brand hover:shadow-cardHover transition，行内 grid `sm:grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-4 px-5 py-4`：BriefDateBadge(small) + 文件名（truncate font-medium text-heading group-hover:text-brand）+ 大小（text-xs text-muted）+ 右侧 ArrowUpRight）
   - loading/空态保持现有 i18n key
3. **BriefDetailPage.tsx**：重构——
   - ReadingProgressBar 顶部
   - 容器 max-w-6xl + 面包屑（首页 / 简报 / date）+ 返回按钮（ArrowLeft + briefs.backToList）
   - Meta 区（header border-b）：BriefDateBadge(large) + 右侧：状态 pill（绿点+真实运行产出 briefs.realOutput，bg-surfaceBrand text-brand）+ 标题（H1 brief.filename 去掉 .md 后缀作标题？保留文件名，text-2xl sm:text-3xl font-medium）+ 文件名小字 + 生成时间 + 大小；右上复制链接按钮（Link2 图标 + briefs.copyLink，navigator.clipboard.writeText(location.href)，点击后短暂显示"已复制"——可用 useState 3 秒切换文案）
   - 内容区双栏：`mt-10 grid gap-10 lg:grid-cols-[minmax(0,1fr)_200px] lg:items-start`——左 article（ReactMarkdown 自定义 h2 渲染：加 id=slug + scroll-mt-24 class，其余默认）+ 右 BriefToc
   - 底部 BriefPagination：需要 prev/next——页面同时调 getBriefs()（排序按 date 降序）定位当前 filename 的相邻项
   - 详情页还需要加载中/未找到状态（保持现有）

### F. i18n 新增 key（zh/en 都要）
- briefs.description（"由内容采集、GPU 转写、结构化分析与 RAG 流程持续生成的每日盘前投研产物。" / "Daily pre-market research briefs generated by the content pipeline: acquisition, GPU transcription, structured analysis and RAG."）
- briefs.statTotal（累计简报 / Total briefs）、briefs.statLatest（最近更新 / Latest）、briefs.statCoverage（覆盖时间 / Coverage）
- briefs.pieces（篇 / briefs）——统计条单位
- briefs.generated（已生成 / Generated）、briefs.realOutput（真实运行产出 / Real system output）
- briefs.sections（章节 / sections）、briefs.backToList（返回简报列表 / Back to briefs）、briefs.copyLink（复制链接 / Copy link）、briefs.copied（已复制 / Copied）
- briefs.prev（上一篇 / Previous）、briefs.next（下一篇 / Next）
- briefs.toc（本页目录 / Contents）
- briefs.preview（内容预览 / Preview）

## 三、文件清单
新建：frontend/src/utils/brief.ts、frontend/src/components/brief/BriefDateBadge.tsx、frontend/src/components/brief/ReadingProgressBar.tsx、frontend/src/components/brief/BriefToc.tsx、frontend/src/components/brief/BriefPagination.tsx、frontend/src/components/brief/LatestBriefCard.tsx
修改：frontend/src/styles/themes.css、frontend/tailwind.config.ts、frontend/src/pages/OverviewPage.tsx、frontend/src/pages/BriefListPage.tsx、frontend/src/pages/BriefDetailPage.tsx、frontend/src/i18n/locales/zh.ts、frontend/src/i18n/locales/en.ts
（BriefDetailPage 里 ReactMarkdown 的 h2 自定义渲染：components={{ h2: ({children}) => <h2 id={slug(children)} className="scroll-mt-24">{children}</h2> }}，slug 用 utils 里的提取逻辑）

## 四、验收标准
1. 首页最新简报卡片：日期徽章+标题+2行摘要+章节数+生成时间+hover 上浮品牌色边框；"全部简报"链接带箭头
2. 列表页：面包屑+eyebrow+H1+描述+统计条（3 项）+按月分组卡片行（hover 效果）
3. 详情页：顶部进度条滚动增长；Meta 区含日期徽章/真实产出标签/复制链接（点击复制+3秒"已复制"）；双栏（左正文右 sticky 目录，点目录平滑滚动到对应章节）；底部上一篇/下一篇可点击跳转
4. 三套主题切换后所有新组件配色正常（深色主题下卡片/徽章/进度条可见性 OK）
5. 中英切换全部新文案正确
6. `npm run build` TS 零错误
7. 停后端：首页不渲染卡片显示"—"、列表空态、详情"未找到"，页面不崩
8. 不破坏 Phase 0-2a 已有功能（导航/主题切换/首页数据/简报基础跳转）

## 五、输出格式
按文件输出，每个文件用标记包裹：
```
<<<FILE: frontend/src/utils/brief.ts>>>
完整内容
<<<END>>>
```
只输出文件清单里的文件，无解释废话。
