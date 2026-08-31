​<<<INSERT_AFTER: 1.技术选型总表>>>
### 路由库版本修订

前端路由统一使用 `react-router-dom ^6.28.0`，不使用 `react-router-dom ^7.0.2`。选择 v6 的原因是其 API、生态集成方案和中文资料均已稳定，能够满足本作品集的嵌套路由、动态路由、懒加载和错误边界需求；v7 在本项目中没有带来必须采用的功能收益。安装依赖示例：

```bash
npm install react-router-dom@^6.28.0
```

路由实现应使用 v6 规范，包括 `createBrowserRouter`、`RouterProvider`、`Outlet`、`useLoaderData` 和路由级 `lazy`；不得混用 v7 专属 API 或迁移期兼容写法。
<<<END>>>

<<<INSERT_AFTER: 3.后端 API 设计>>>
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
<<<END>>>

<<<INSERT_AFTER: 4.数据源映射表>>>
### 实盘纪律页数据源与脱敏映射

`portfolio.json` 仅作为服务端受限输入源，不得被前端、静态站点构建产物或通用数据查询接口直接访问。数据映射表中应新增以下约束：

| 页面模块 | 原始数据源 | 服务端允许读取字段类别 | API 可输出字段 | 明确禁止输出字段 |
| --- | --- | --- | --- | --- |
| 实盘纪律页：资产配置 | `portfolio.json` | 资产类别、内部权重计算所需字段 | 按资产类别聚合的整数仓位占比 | 标的代码、标的名称、数量、成本价、市值、现金额、账户总额、单一持仓占比 |
| 实盘纪律页：策略框架 | 策略规则配置或人工维护规则清单 | 规则名称、触发条件、风控原则、启停状态 | 通用策略规则框架和启停状态 | 与真实账户绑定的阈值、资金规模、具体下单参数 |
| 实盘纪律页：纪律时间线 | 交易/复盘日志或人工维护事件 | 日期、纪律动作类型、关联规则编号、脱敏摘要 | 无金额的纪律执行时间线 | 买卖标的、成交价、成交量、盈亏金额、收益率、订单号 |

服务端应将原始持仓解析、类别聚合和字段白名单控制封装在独立的 `disciplineView` 映射层中。除 `GET /api/discipline/overview` 外，其他 API 不得依赖或返回 `portfolio.json` 数据；日志、异常追踪和开发调试输出同样不得记录原始持仓对象。
<<<END>>>

<<<INSERT_AFTER: 4.数据源映射表>>>
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
<<<END>>>

<<<INSERT_AFTER: 6.主题与双语方案>>>
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
<<<END>>>

<<<INSERT_AFTER: 7.图表方案>>>
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
<<<END>>>

<<<INSERT_AFTER: 8.分阶段实施计划>>>
### Phase 0：实际 Schema 核对与类型冻结

在编写业务 TypeScript 类型、SQL 查询、API DTO 或前端 mock 数据之前，必须完成真实数据源核对。Phase 0 的唯一产出是《实际 schema 核对报告》，未经该报告确认不得冻结 `NormalizedView`、预测事件、资产、分析师或 RAG 元数据等类型定义，也不得将 v0.1 中的假设字段写入生产接口。

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
<<<END>>>