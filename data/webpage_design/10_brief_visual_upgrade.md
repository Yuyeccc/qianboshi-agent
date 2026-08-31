我先快速核对现有简报页面、主题变量和 Markdown 渲染入口，确保方案里的组件命名、路由数据和 Tailwind/CSS 变量能直接落到当前项目，而不是脱离代码库的概念稿。重点会确认三件事：现有页面是否已经有统一的 `Card`/按钮模式、简报数据目前以什么形态提供、以及深色主题对 surface/border/text 的变量约定。随后我会按“可拆组件 + 页面 JSX 骨架 + 必要 CSS”给出完整方案。下面是一套可直接落地到 Vite + React + TS + Tailwind 项目的简报视觉升级方案。整体方向是：**把简报从“文件列表”升级成真实投研系统的可读产物**，但仍保持白底、克制、信息密度高、无营销式装饰。

假设现有简报数据最终可以统一成：

```ts
export interface BriefMeta {
  filename: string
  date: string // YYYY-MM-DD
  generatedAt?: string
  size?: number
  content?: string
  summary?: string
}
```

建议补充主题变量：

```css
:root {
  --color-surface: #ffffff;
  --color-surface-raised: #ffffff;
  --color-surface-subtle: #f7f9fc;
  --color-surface-brand: #f1f6ff;

  --color-border: #e4e9f0;
  --color-border-strong: #cbd5e1;

  --color-heading: #182230;
  --color-text: #405064;
  --color-muted: #8491a3;
  --color-brand: #3267d6;
  --color-brand-strong: #2455bd;

  --color-up: #e05252;
  --color-down: #26a269;

  --shadow-card: 0 8px 24px rgb(30 64 175 / 0.06);
  --shadow-card-hover: 0 14px 34px rgb(30 64 175 / 0.11);
}

[data-theme="dark"] {
  --color-surface: #111827;
  --color-surface-raised: #172133;
  --color-surface-subtle: #0d1420;
  --color-surface-brand: #17284a;

  --color-border: #2a3950;
  --color-border-strong: #40516b;

  --color-heading: #f3f6fb;
  --color-text: #c7d1df;
  --color-muted: #8493a8;
  --color-brand: #79a7ff;
  --color-brand-strong: #a9c5ff;

  --color-up: #ff8585;
  --color-down: #53c995;

  --shadow-card: 0 8px 28px rgb(0 0 0 / 0.18);
  --shadow-card-hover: 0 14px 34px rgb(0 0 0 / 0.28);
}
```

如果已有三套主题，只需要将以上语义变量映射到现有主题变量即可。

---

## 1. 首页最新简报卡片

### 设计目标

首页不再展示一行文件名，而是展示一张“最新投研产物预览卡”：

- 顶部：`最新简报` + `REAL-TIME OUTPUT`
- 主体：日期徽章、简报标题、摘要
- 底部：章节数量、生成时间、状态标签
- 右侧：箭头入口
- 整张卡片可点击
- 保持 `4px ~ 8px` 圆角，不使用大面积渐变

### 组件树

```txt
LatestBriefSection
├── SectionHeader
└── LatestBriefCard
    ├── BriefDateBadge
    ├── BriefCardMain
    │   ├── BriefCardMeta
    │   ├── BriefCardTitle
    │   ├── BriefCardSummary
    │   └── BriefCardStats
    └── BriefArrowButton
```

### JSX

```tsx
import { ArrowUpRight, FileText, Clock3, Layers3 } from 'lucide-react'
import { Link } from 'react-router-dom'

function LatestBriefSection({ brief }: { brief: BriefMeta }) {
  const sectionCount = brief.content
    ? (brief.content.match(/^##\s+/gm) ?? []).length
    : 8

  return (
    <section className="mt-20" aria-labelledby="latest-brief-title">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-brand)]">
            Latest output
          </p>

          <h2
            id="latest-brief-title"
            className="text-2xl font-medium tracking-[-0.02em] text-[var(--color-heading)]"
          >
            最新简报
          </h2>
        </div>

        <Link
          to="/zh/briefs"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--color-muted)] transition-colors duration-200 hover:text-[var(--color-brand)]"
        >
          查看全部
          <ArrowUpRight size={15} strokeWidth={1.8} />
        </Link>
      </div>

      <Link
        to={`/zh/briefs/${encodeURIComponent(brief.filename)}`}
        className="
          group relative block overflow-hidden rounded-lg
          border border-[var(--color-border)]
          bg-[var(--color-surface-raised)]
          shadow-[var(--shadow-card)]
          transition-[border-color,box-shadow,transform]
          duration-200 ease-out
          hover:-translate-y-0.5
          hover:border-[var(--color-brand)]
          hover:shadow-[var(--shadow-card-hover)]
          focus-visible:outline-none
          focus-visible:ring-2
          focus-visible:ring-[var(--color-brand)]
          focus-visible:ring-offset-2
          focus-visible:ring-offset-[var(--color-surface)]
        "
      >
        <div className="grid gap-7 p-6 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-center sm:p-8">
          <BriefDateBadge date={brief.date} size="large" />

          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-subtle)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-muted)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-down)]" />
                已生成
              </span>

              <span className="text-xs text-[var(--color-muted)]">
                {brief.generatedAt ?? '每日盘前产出'}
              </span>
            </div>

            <h3 className="truncate text-xl font-medium tracking-[-0.015em] text-[var(--color-heading)] transition-colors duration-200 group-hover:text-[var(--color-brand)]">
              {brief.title ?? '每日市场投研简报'}
            </h3>

            <p className="mt-2 line-clamp-2 max-w-2xl text-sm leading-6 text-[var(--color-text)]">
              {brief.summary ?? '汇总市场大势、持仓诊断、标的异动与风险提示，形成每日盘前决策参考。'}
            </p>

            <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-[var(--color-muted)]">
              <span className="inline-flex items-center gap-1.5">
                <Layers3 size={14} />
                {sectionCount} 个章节
              </span>

              {brief.size && (
                <span className="inline-flex items-center gap-1.5">
                  <FileText size={14} />
                  {formatFileSize(brief.size)}
                </span>
              )}
            </div>
          </div>

          <span
            className="
              flex h-11 w-11 shrink-0 items-center justify-center self-start
              rounded-full border border-[var(--color-border)]
              text-[var(--color-brand)]
              transition-[background-color,border-color,transform]
              duration-200
              group-hover:border-[var(--color-brand)]
              group-hover:bg-[var(--color-surface-brand)]
              group-hover:translate-x-0.5
              sm:self-center
            "
            aria-hidden="true"
          >
            <ArrowUpRight size={19} strokeWidth={1.7} />
          </span>
        </div>

        <div className="h-0.5 w-0 bg-[var(--color-brand)] transition-all duration-300 group-hover:w-full" />
      </Link>
    </section>
  )
}
```

日期徽章：

```tsx
function BriefDateBadge({
  date,
  size = 'default',
}: {
  date: string
  size?: 'default' | 'large'
}) {
  const parsed = new Date(`${date}T00:00:00`)
  const day = parsed.getDate()
  const month = parsed
    .toLocaleDateString('en-US', { month: 'short' })
    .toUpperCase()

  return (
    <div
      className={[
        'flex shrink-0 flex-col items-center justify-center border border-[var(--color-border)]',
        'bg-[var(--color-surface-brand)] text-[var(--color-brand)]',
        size === 'large'
          ? 'h-20 w-20 rounded-lg'
          : 'h-14 w-14 rounded-md',
      ].join(' ')}
    >
      <span
        className={[
          'font-semibold leading-none tabular-nums tracking-[-0.04em]',
          size === 'large' ? 'text-3xl' : 'text-xl',
        ].join(' ')}
      >
        {String(day).padStart(2, '0')}
      </span>
      <span className="mt-1 text-[10px] font-semibold tracking-[0.12em]">
        {month}
      </span>
    </div>
  )
}
```

---

## 2. 简报列表页

### 页面区块顺序

```txt
BriefsPage
├── Breadcrumb
├── PageHeader
│   ├── eyebrow
│   ├── H1
│   └── description
├── BriefStatsBar
├── MonthGroup[]
│   ├── MonthGroupHeader
│   └── BriefListRow[]
└── EmptyState / LoadingState
```

页面整体保持窄一些，建议：

```tsx
<main className="mx-auto max-w-5xl px-5 py-12 sm:px-8 lg:py-16">
```

### 顶部标题和统计条

```tsx
function BriefsPage({ briefs, loading }: {
  briefs: BriefMeta[]
  loading: boolean
}) {
  if (loading) return <BriefsLoadingState />
  if (!briefs.length) return <BriefsEmptyState />

  const grouped = groupBriefsByMonth(briefs)
  const sorted = [...briefs].sort((a, b) => b.date.localeCompare(a.date))

  return (
    <main className="mx-auto max-w-5xl px-5 py-12 sm:px-8 lg:py-16">
      <nav className="mb-10 text-xs text-[var(--color-muted)]">
        <Link
          to="/zh"
          className="transition-colors hover:text-[var(--color-brand)]"
        >
          首页
        </Link>
        <span className="mx-2">/</span>
        <span className="text-[var(--color-text)]">简报</span>
      </nav>

      <header className="mb-9 max-w-2xl">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-brand)]">
          Daily research output
        </p>

        <h1 className="text-4xl font-medium tracking-[-0.035em] text-[var(--color-heading)] sm:text-5xl">
          简报
        </h1>

        <p className="mt-4 text-sm leading-7 text-[var(--color-text)]">
          由内容采集、GPU 转写、结构化分析与 RAG 流程持续生成的每日盘前投研产物。
        </p>
      </header>

      <BriefStatsBar
        total={briefs.length}
        latest={sorted[0]?.date}
        earliest={sorted.at(-1)?.date}
      />

      <div className="mt-12 space-y-10">
        {Object.entries(grouped).map(([month, monthBriefs]) => (
          <BriefMonthGroup
            key={month}
            month={month}
            briefs={monthBriefs}
          />
        ))}
      </div>
    </main>
  )
}
```

统计条不做成后台表格，而是做成一条低干扰的横向信息带：

```tsx
function BriefStatsBar({
  total,
  latest,
  earliest,
}: {
  total: number
  latest?: string
  earliest?: string
}) {
  return (
    <div className="grid border-y border-[var(--color-border)] sm:grid-cols-3">
      <BriefStat label="累计简报" value={`${total} 篇`} />
      <BriefStat label="最近更新" value={latest ? formatShortDate(latest) : '--'} />
      <BriefStat label="覆盖时间" value={earliest ? formatShortDate(earliest) : '--'} />
    </div>
  )
}

function BriefStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-[var(--color-border)] py-4 last:border-b-0 sm:border-b-0 sm:border-r sm:px-5 sm:first:pl-0 sm:last:border-r-0">
      <span className="text-xs text-[var(--color-muted)]">{label}</span>
      <span className="text-sm font-medium tabular-nums text-[var(--color-heading)]">
        {value}
      </span>
    </div>
  )
}
```

### 按月分组和列表行

```tsx
function BriefMonthGroup({
  month,
  briefs,
}: {
  month: string
  briefs: BriefMeta[]
}) {
  const [year, monthNumber] = month.split('-')

  return (
    <section aria-labelledby={`month-${month}`}>
      <div className="mb-3 flex items-baseline gap-3">
        <h2
          id={`month-${month}`}
          className="text-base font-medium text-[var(--color-heading)]"
        >
          {year} 年 {Number(monthNumber)} 月
        </h2>

        <span className="text-xs tabular-nums text-[var(--color-muted)]">
          {briefs.length} 篇
        </span>
      </div>

      <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] shadow-[var(--shadow-card)]">
        {briefs.map((brief, index) => (
          <BriefListRow
            key={brief.filename}
            brief={brief}
            isLast={index === briefs.length - 1}
          />
        ))}
      </div>
    </section>
  )
}

function BriefListRow({
  brief,
  isLast,
}: {
  brief: BriefMeta
  isLast: boolean
}) {
  return (
    <Link
      to={`/zh/briefs/${encodeURIComponent(brief.filename)}`}
      className={[
        'group flex min-h-24 items-center gap-4 px-4 py-4 sm:px-5',
        'transition-colors duration-200',
        'hover:bg-[var(--color-surface-subtle)]',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-brand)]',
        !isLast ? 'border-b border-[var(--color-border)]' : '',
      ].join(' ')}
    >
      <BriefDateBadge date={brief.date} />

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="truncate text-sm font-medium text-[var(--color-heading)] transition-colors duration-200 group-hover:text-[var(--color-brand)]">
            {brief.title ?? brief.filename}
          </h3>

          <span className="rounded-full border border-[var(--color-border)] px-2 py-0.5 text-[10px] text-[var(--color-muted)]">
            已生成
          </span>
        </div>

        <p className="mt-1 truncate text-xs text-[var(--color-muted)]">
          {brief.filename}
        </p>
      </div>

      <div className="hidden shrink-0 text-right sm:block">
        <p className="text-xs tabular-nums text-[var(--color-muted)]">
          {brief.generatedAt ?? '盘前'}
        </p>
        {brief.size && (
          <p className="mt-1 text-[11px] tabular-nums text-[var(--color-muted)]">
            {formatFileSize(brief.size)}
          </p>
        )}
      </div>

      <ArrowUpRight
        size={18}
        strokeWidth={1.7}
        className="shrink-0 text-[var(--color-muted)] transition-[color,transform] duration-200 group-hover:translate-x-0.5 group-hover:text-[var(--color-brand)]"
      />
    </Link>
  )
}
```

这里文件大小降级为辅助信息，只在桌面端显示。主视觉信息是：

1. 日期；
2. 简报标题；
3. 文件名；
4. 生成状态；
5. 进入详情的箭头。

### 加载态

加载态需要保留页面结构，避免内容加载后布局跳动：

```tsx
function BriefsLoadingState() {
  return (
    <main className="mx-auto max-w-5xl px-5 py-12 sm:px-8">
      <div className="h-3 w-20 animate-pulse rounded bg-[var(--color-surface-subtle)]" />
      <div className="mt-10 h-12 w-32 animate-pulse rounded bg-[var(--color-surface-subtle)]" />

      <div className="mt-12 space-y-8">
        {[1, 2].map((group) => (
          <div key={group}>
            <div className="mb-3 h-5 w-32 animate-pulse rounded bg-[var(--color-surface-subtle)]" />
            <div className="overflow-hidden rounded-lg border border-[var(--color-border)]">
              {[1, 2, 3].map((row) => (
                <div
                  key={row}
                  className="h-24 animate-pulse border-b border-[var(--color-border)] bg-[var(--color-surface-subtle)] last:border-b-0"
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </main>
  )
}
```

### 空态

```tsx
function BriefsEmptyState() {
  return (
    <main className="mx-auto max-w-5xl px-5 py-12 sm:px-8">
      <div className="border-y border-[var(--color-border)] py-20 text-center">
        <FileText
          size={28}
          strokeWidth={1.4}
          className="mx-auto text-[var(--color-muted)]"
        />
        <h1 className="mt-5 text-xl font-medium text-[var(--color-heading)]">
          暂无简报
        </h1>
        <p className="mt-2 text-sm text-[var(--color-muted)]">
          运行产物将在生成后显示在这里。
        </p>
      </div>
    </main>
  )
}
```

---

## 3. 简报详情页

### 页面结构

```txt
BriefDetailPage
├── ReadingProgressBar
├── Breadcrumb
├── BriefDetailHeader
│   ├── BackButton
│   ├── BriefDateBadge
│   ├── Filename / title
│   ├── GeneratedAt
│   ├── RealOutputBadge
│   └── CopyLinkButton
├── ContentLayout
│   ├── Article
│   │   └── MarkdownRenderer
│   └── BriefToc
└── BriefPagination
```

桌面端采用：

```txt
左侧正文 max-w-prose
右侧 TOC sticky
```

正文不建议无限加宽。中文表格较多时，可以让文章主体整体达到 `max-w-6xl`，但正文段落仍保持 `max-w-prose`。

### 详情页 JSX

```tsx
function BriefDetailPage({
  brief,
  previous,
  next,
}: {
  brief: BriefMeta
  previous?: BriefMeta
  next?: BriefMeta
}) {
  const headings = extractBriefHeadings(brief.content ?? '')

  return (
    <>
      <ReadingProgressBar />

      <main className="mx-auto max-w-6xl px-5 py-8 sm:px-8 lg:py-12">
        <nav className="mb-8 flex items-center gap-2 text-xs text-[var(--color-muted)]">
          <Link
            to="/zh"
            className="transition-colors hover:text-[var(--color-brand)]"
          >
            首页
          </Link>
          <span>/</span>
          <Link
            to="/zh/briefs"
            className="transition-colors hover:text-[var(--color-brand)]"
          >
            简报
          </Link>
          <span>/</span>
          <span className="max-w-48 truncate text-[var(--color-text)]">
            {brief.date}
          </span>
        </nav>

        <BriefDetailHeader brief={brief} />

        <div className="mt-14 grid gap-12 lg:grid-cols-[minmax(0,760px)_180px] lg:items-start">
          <article className="min-w-0">
            <div className="prose-brief">
              <MarkdownRenderer content={brief.content ?? ''} />
            </div>
          </article>

          <BriefToc headings={headings} />
        </div>

        <BriefPagination previous={previous} next={next} />
      </main>
    </>
  )
}
```

### 顶部 Meta 区

```tsx
function BriefDetailHeader({ brief }: { brief: BriefMeta }) {
  async function copyLink() {
    await navigator.clipboard.writeText(window.location.href)
  }

  return (
    <header className="border-b border-[var(--color-border)] pb-9">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-4 sm:gap-5">
          <BriefDateBadge date={brief.date} size="large" />

          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-brand)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-brand)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-down)]" />
                真实运行产出
              </span>

              <span className="text-xs text-[var(--color-muted)]">
                Daily research brief
              </span>
            </div>

            <h1 className="break-words text-2xl font-medium leading-tight tracking-[-0.025em] text-[var(--color-heading)] sm:text-3xl">
              {brief.title ?? brief.filename}
            </h1>

            <p className="mt-3 break-all text-xs leading-5 text-[var(--color-muted)]">
              {brief.filename}
            </p>

            <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-[var(--color-muted)]">
              <span>生成于 {brief.generatedAt ?? `${brief.date} 盘前`}</span>
              {brief.size && <span>{formatFileSize(brief.size)}</span>}
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={copyLink}
          className="
            inline-flex h-9 shrink-0 items-center gap-2 self-start
            rounded-md border border-[var(--color-border)]
            px-3 text-xs font-medium text-[var(--color-text)]
            transition-colors duration-200
            hover:border-[var(--color-brand)]
            hover:bg-[var(--color-surface-brand)]
            hover:text-[var(--color-brand)]
          "
        >
          <Link2 size={14} />
          复制链接
        </button>
      </div>
    </header>
  )
}
```

返回按钮建议放在 Breadcrumb 旁边，使用图标 + 文本，避免只使用不明确的箭头：

```tsx
<Link
  to="/zh/briefs"
  className="mb-5 inline-flex items-center gap-1.5 text-sm text-[var(--color-muted)] transition-colors hover:text-[var(--color-brand)]"
>
  <ArrowLeft size={15} />
  返回简报列表
</Link>
```

---

## 4. TOC 提取和章节导航

### 提取逻辑

只从 Markdown 中提取二级标题：

```tsx
export interface BriefHeading {
  id: string
  text: string
}

export function extractBriefHeadings(content: string): BriefHeading[] {
  const headings: BriefHeading[] = []
  const usedIds = new Map<string, number>()

  for (const line of content.split('\n')) {
    const match = line.match(/^##\s+(.+?)\s*$/)
    if (!match) continue

    const text = match[1]
      .replace(/\*\*/g, '')
      .replace(/[`*_]/g, '')
      .trim()

    const baseId =
      text
        .toLowerCase()
        .replace(/[^\w\u4e00-\u9fff]+/g, '-')
        .replace(/^-+|-+$/g, '') || 'section'

    const count = usedIds.get(baseId) ?? 0
    usedIds.set(baseId, count + 1)

    headings.push({
      text,
      id: count === 0 ? baseId : `${baseId}-${count}`,
    })
  }

  return headings
}
```

注意：Markdown 渲染器必须使用同样的 ID 生成规则，否则 TOC 锚点会失效。更稳妥的方式是将 `headings` 传给 Markdown renderer，根据标题文本按顺序消费 ID。

### TOC 组件

```tsx
function BriefToc({ headings }: { headings: BriefHeading[] }) {
  if (!headings.length) return null

  return (
    <aside className="hidden lg:block">
      <div className="sticky top-24">
        <p className="mb-4 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-muted)]">
          Contents
        </p>

        <nav aria-label="简报章节">
          <ol className="space-y-2 border-l border-[var(--color-border)]">
            {headings.map((heading, index) => (
              <li key={heading.id}>
                <a
                  href={`#${heading.id}`}
                  className="
                    relative block border-l border-transparent
                    py-0.5 pl-4 text-xs leading-5
                    text-[var(--color-muted)]
                    transition-[color,border-color] duration-200
                    hover:border-[var(--color-brand)]
                    hover:text-[var(--color-brand)]
                  "
                >
                  <span className="mr-2 tabular-nums text-[var(--color-muted)]">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  {heading.text}
                </a>
              </li>
            ))}
          </ol>
        </nav>
      </div>
    </aside>
  )
}
```

移动端可以在正文前渲染为横向滚动导航：

```tsx
<div className="mb-8 flex gap-2 overflow-x-auto pb-1 lg:hidden">
  {headings.map((heading) => (
    <a
      key={heading.id}
      href={`#${heading.id}`}
      className="shrink-0 rounded-md border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text)]"
    >
      {heading.text}
    </a>
  ))}
</div>
```

---

## 5. Markdown 正文样式

建议不要只依赖 Tailwind Typography 的默认样式，单独维护 `.prose-brief`，以便控制金融表格、标题、指标数字和涨跌色。

### Markdown renderer

如果使用 `react-markdown`：

```tsx
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function MarkdownRenderer({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        table: ({ children }) => (
          <div className="brief-table-wrap">
            <table>{children}</table>
          </div>
        ),
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
```

### CSS

```css
.prose-brief {
  color: var(--color-text);
  font-size: 15px;
  line-height: 1.9;
}

.prose-brief > p,
.prose-brief > ul,
.prose-brief > ol,
.prose-brief > blockquote {
  max-width: 68ch;
}

.prose-brief h2 {
  scroll-margin-top: 96px;
  margin: 3.5rem 0 1rem;
  padding-top: 0.25rem;
  border-top: 1px solid var(--color-border);
  color: var(--color-heading);
  font-size: 1.35rem;
  font-weight: 550;
  line-height: 1.35;
  letter-spacing: -0.015em;
}

.prose-brief h3 {
  scroll-margin-top: 96px;
  margin: 2.25rem 0 0.75rem;
  color: var(--color-heading);
  font-size: 1.05rem;
  font-weight: 550;
}

.prose-brief p {
  margin: 1rem 0;
}

.prose-brief strong {
  color: var(--color-heading);
  font-weight: 650;
}

.prose-brief ul,
.prose-brief ol {
  padding-left: 1.4rem;
}

.prose-brief li::marker {
  color: var(--color-brand);
}

.prose-brief blockquote {
  margin: 1.5rem 0;
  border-left: 3px solid var(--color-brand);
  padding: 0.75rem 1rem;
  background: var(--color-surface-brand);
  color: var(--color-text);
}

.prose-brief code {
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-surface-subtle);
  padding: 0.12em 0.3em;
  color: var(--color-brand-strong);
  font-size: 0.9em;
}

.brief-table-wrap {
  width: 100%;
  margin: 1.5rem 0;
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-raised);
}

.prose-brief table {
  width: 100%;
  min-width: 560px;
  border-collapse: collapse;
  font-size: 13px;
  line-height: 1.6;
}

.prose-brief thead {
  background: var(--color-surface-brand);
  color: var(--color-heading);
}

.prose-brief th {
  white-space: nowrap;
  border-bottom: 1px solid var(--color-border-strong);
  padding: 0.7rem 0.9rem;
  text-align: left;
  font-size: 11px;
  font-weight: 650;
}

.prose-brief td {
  border-bottom: 1px solid var(--color-border);
  padding: 0.7rem 0.9rem;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.prose-brief tbody tr:nth-child(even) {
  background: var(--color-surface-subtle);
}

.prose-brief tbody tr:last-child td {
  border-bottom: 0;
}

.prose-brief td:first-child {
  color: var(--color-heading);
  font-weight: 550;
}

/* Markdown 中可通过 className 或统一解析规则标记涨跌值 */
.prose-brief .is-up,
.prose-brief .rise {
  color: var(--color-up);
}

.prose-brief .is-down,
.prose-brief .fall {
  color: var(--color-down);
}
```

涨跌颜色建议不要直接写死 `#E05252` 和 `#26A269`，而是把它们放到 `--color-up` / `--color-down`，这样三套主题可以分别控制对比度。

---

## 6. 阅读进度条

页面顶部固定一条极细进度条，使用品牌色，不增加额外面板。

```tsx
function ReadingProgressBar() {
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    const updateProgress = () => {
      const scrollTop = window.scrollY
      const scrollable =
        document.documentElement.scrollHeight - window.innerHeight

      setProgress(scrollable > 0 ? (scrollTop / scrollable) * 100 : 0)
    }

    updateProgress()
    window.addEventListener('scroll', updateProgress, { passive: true })

    return () => window.removeEventListener('scroll', updateProgress)
  }, [])

  return (
    <div
      className="fixed inset-x-0 top-0 z-50 h-0.5 bg-transparent"
      aria-hidden="true"
    >
      <div
        className="h-full origin-left bg-[var(--color-brand)] transition-[width] duration-100"
        style={{ width: `${progress}%` }}
      />
    </div>
  )
}
```

建议只保留 `100ms` 左右的 width transition，避免滚动时有明显拖尾。

---

## 7. 上一篇 / 下一篇导航

按日期排序，详情页底部采用左右两列的导航，不使用大卡片嵌套：

```tsx
function BriefPagination({
  previous,
  next,
}: {
  previous?: BriefMeta
  next?: BriefMeta
}) {
  return (
    <nav className="mt-16 grid border-y border-[var(--color-border)] sm:grid-cols-2">
      <BriefPaginationLink
        direction="previous"
        brief={previous}
      />
      <BriefPaginationLink
        direction="next"
        brief={next}
      />
    </nav>
  )
}

function BriefPaginationLink({
  direction,
  brief,
}: {
  direction: 'previous' | 'next'
  brief?: BriefMeta
}) {
  if (!brief) {
    return <div className="hidden sm:block" />
  }

  const isPrevious = direction === 'previous'

  return (
    <Link
      to={`/zh/briefs/${encodeURIComponent(brief.filename)}`}
      className={[
        'group flex min-h-24 items-center gap-3 py-5',
        isPrevious ? 'sm:border-r sm:pr-8' : 'justify-end text-right sm:pl-8',
        'border-[var(--color-border)]',
      ].join(' ')}
    >
      {isPrevious && <ArrowLeft size={17} className="text-[var(--color-muted)]" />}

      <div>
        <p className="text-[11px] text-[var(--color-muted)]">
          {isPrevious ? '上一篇' : '下一篇'}
        </p>
        <p className="mt-1 text-sm font-medium text-[var(--color-heading)] transition-colors group-hover:text-[var(--color-brand)]">
          {brief.date}
        </p>
      </div>

      {!isPrevious && (
        <ArrowRight size={17} className="text-[var(--color-muted)]" />
      )}
    </Link>
  )
}
```

---

## 8. 统一设计语言

### 卡片规格

所有简报相关卡片统一使用：

```txt
圆角：rounded-md 或 rounded-lg
边框：border border-[var(--color-border)]
背景：bg-[var(--color-surface-raised)]
阴影：shadow-[var(--shadow-card)]
hover：border-brand + shadow-card-hover + translate-y(-2px)
过渡：duration-200 ease-out
```

不要在列表页继续使用传统后台表格的粗表头、固定列宽和大面积灰色 hover。列表中的“行”可以保留结构化感，但视觉上应更接近作品集里的案例索引。

### 标题层级

```txt
页面 H1：text-4xl / sm:text-5xl，font-medium，tracking-[-0.035em]
页面 H2：text-2xl，font-medium
列表月份：text-base，font-medium
列表标题：text-sm，font-medium
详情文章 H2：text-xl 左右，带顶部边界
辅助信息：text-xs，text-muted
```

不建议使用特别粗的 `font-bold` 作为主标题，细字重更接近 Stripe / Linear 的产品界面风格。

### 日期徽章

日期徽章应成为三个区域的共同识别元素：

```txt
背景：var(--color-surface-brand)
边框：var(--color-border)
日期数字：var(--color-brand)
月份：uppercase + tracking-[0.12em]
数字：tabular-nums
```

它既是时间信息，也能让简报列表不再像文件管理器。

### Hover 和微动效

统一控制在以下范围内：

```txt
卡片上移：-translate-y-0.5
箭头位移：translate-x-0.5
标题颜色：muted/heading -> brand
底部强调线：width 0 -> width 100%
过渡时长：duration-200
强调线进入：duration-300
```

避免使用大幅缩放、强烈阴影、闪烁或渐变动画。

### 深色主题兼容

所有组件的颜色都通过变量使用：

```tsx
text-[var(--color-heading)]
text-[var(--color-text)]
text-[var(--color-muted)]
text-[var(--color-brand)]
bg-[var(--color-surface)]
bg-[var(--color-surface-raised)]
bg-[var(--color-surface-subtle)]
bg-[var(--color-surface-brand)]
border-[var(--color-border)]
```

不要在 JSX 中直接写：

```tsx
text-[#182230]
bg-white
border-gray-200
text-blue-600
```

这样白底产品主题、架构暗色主题、终端深色主题可以复用同一套 JSX。终端主题如果有更强烈的等宽字体设定，只建议作用于文件名、时间、数据和表格数字，标题仍保持正常 UI 字体，避免详情页变成纯终端界面。

---

## 9. 必要工具函数

```tsx
function formatShortDate(date: string) {
  const [year, month, day] = date.split('-')
  return `${year.slice(2)}.${month}.${day}`
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function groupBriefsByMonth(briefs: BriefMeta[]) {
  return briefs
    .slice()
    .sort((a, b) => b.date.localeCompare(a.date))
    .reduce<Record<string, BriefMeta[]>>((groups, brief) => {
      const month = brief.date.slice(0, 7)
      groups[month] ??= []
      groups[month].push(brief)
      return groups
    }, {})
}
```

最终三页会形成一致的阅读路径：

```txt
首页：最新简报视觉预览
  ↓
列表页：按月份浏览全部真实产物
  ↓
详情页：带章节导航和金融表格排版的完整阅读体验
```

这样首页负责建立“系统确实在持续运行”的第一印象，列表页负责展示产物规模与连续性，详情页负责证明数据产品和投研分析的真实完成度。