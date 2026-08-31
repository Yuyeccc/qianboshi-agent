​我先快速确认当前工作区的项目结构与已有样式约定，再把这套设计系统落到可直接使用的 token、组件规格和页面主题规则上，避免和现有实现冲突。这次任务核心是设计规范输出，但我会先检查是否已有前端入口、全局 CSS 或主题变量；如果已有实现，会按现有技术栈组织成能直接迁移的命名与数值。我正在读取工作区文件，重点看 `package.json`、全局样式和路由结构，以确定最终规范是写成独立设计文档，还是同步进现有 token 文件。# 钱博士 Agent 作品集设计系统

## 1. 设计定位

整体体验定位为：

> **真实运行中的 AI 金融投研基础设施，而不是概念型 AI Demo。**

视觉策略采用三种状态：

| 页面 | 视觉主题 | 使用目的 |
|---|---|---|
| 首页、系统概览、关于 | 白底产品官网风 | 建立可信度、突出产品结构 |
| 系统架构 | 暗色科技感 | 表达数据管道、自动化和工程能力 |
| 数据资产、决策台、实盘纪律 | 深色金融终端风 | 强调数据密度、时间序列和交易纪律 |
| 决策台资产卡 | 白底产品卡 | 让复杂资产信息更易扫描、展示感更强 |

建议使用以下主题切换：

```css
[data-theme="light"]
[data-theme="architecture"]
[data-theme="terminal"]
```

不要使用渐变作为主要视觉语言。渐变只用于极少量数据流动画或背景光效。

---

# 2. 色彩系统

## 2.1 品牌主色

品牌主色使用偏蓝的青色，表达数据、智能和工程系统，同时避免典型紫色 AI 风格。

```css
--brand-500: #0B7A75;
--brand-600: #09635F;
--brand-700: #084E4B;
--brand-100: #DDF5F1;
--brand-50:  #F0FBF9;
```

使用原则：

- `brand-500`：主要 CTA、激活态、重点链接
- `brand-600`：hover、深色背景上的品牌色
- `brand-100`：品牌标签、浅色背景、选中态底色
- 不建议大面积使用品牌色填充页面

## 2.2 中性色

### 浅色产品官网色板

```css
--light-bg:           #F7F8FA;
--light-surface:      #FFFFFF;
--light-surface-muted:#F1F3F5;

--light-border:       #E5E7EB;
--light-border-strong:#D1D5DB;

--light-text:         #111827;
--light-text-secondary:#4B5563;
--light-text-tertiary:#8A94A6;
--light-text-disabled:#B8C0CC;
```

### 架构页暗色科技色板

架构页不要使用纯黑，采用带轻微蓝灰倾向的深色底。

```css
--arch-bg:             #0B1117;
--arch-surface:        #111A23;
--arch-surface-raised: #17232E;
--arch-surface-hover:  #1D2C38;

--arch-border:         #263746;
--arch-border-strong:  #385263;

--arch-text:           #F4F7FA;
--arch-text-secondary: #AAB8C5;
--arch-text-tertiary:  #718292;
--arch-text-disabled:  #506170;
```

架构页专用高亮色：

```css
--arch-cyan:       #5DE2D0;
--arch-cyan-muted: #1D5F5A;
--arch-blue:       #6EA8FE;
--arch-violet:     #A78BFA;
--arch-amber:      #F4C46B;
```

其中：

- 青色：实时数据流、运行状态、Pipeline 主路径
- 蓝色：模型、向量库、API
- 紫色：LLM、Embedding、智能处理
- 琥珀色：定时任务、预警、待处理状态

## 2.3 深色金融终端色板

```css
--terminal-bg:             #0D1218;
--terminal-surface:        #141B23;
--terminal-surface-raised: #1B2530;
--terminal-surface-hover:  #222F3B;

--terminal-border:         #293642;
--terminal-border-strong:  #3A4B59;

--terminal-text:           #F3F6F8;
--terminal-text-secondary: #B4C0C9;
--terminal-text-tertiary:  #7D8B96;
--terminal-text-disabled:  #56636E;

--terminal-grid:           #202B35;
```

## 2.4 涨跌语义色

采用中国金融市场习惯：红涨、绿跌。

```css
--up-500:       #E05252;
--up-400:       #F06B6B;
--up-100:       #FDE8E8;
--up-muted:     #54272B;

--down-500:     #26A269;
--down-400:     #42C58A;
--down-100:     #DDF7E9;
--down-muted:   #183D31;

--warning-500:  #D99A2B;
--warning-100:  #FFF3D6;
--warning-muted:#4A381B;

--info-500:     #4D91E8;
--info-100:     #E5F0FF;
--info-muted:   #203B5A;

--neutral-500:  #8793A0;
```

建议增加颜色语义别名，避免业务代码直接依赖具体颜色：

```css
--market-positive: var(--up-500);
--market-negative: var(--down-500);
--market-neutral:  var(--neutral-500);
--status-success:  var(--down-500);
--status-warning:  var(--warning-500);
--status-error:    var(--up-500);
--status-info:     var(--info-500);
```

涨跌色只用于：

- 数值变化
- K 线、柱状图、走势线
- 看多 / 看空标签
- 命中 / 失误统计
- 风险警示

不要把整块页面背景做成红色或绿色。

---

# 3. 字体系统

## 3.1 中文字体

优先使用系统字体，避免加载过大的中文 Web Font：

```css
font-family:
  "Inter",
  "SF Pro Display",
  "SF Pro Text",
  "PingFang SC",
  "Microsoft YaHei",
  Arial,
  sans-serif;
```

Windows 环境下建议：

```css
font-family:
  "Inter",
  "PingFang SC",
  "Microsoft YaHei",
  sans-serif;
```

## 3.2 英文与数字字体

英文标题、数字和指标使用 `Inter`：

```css
font-family: "Inter", sans-serif;
font-feature-settings: "tnum" 1, "cv11" 1;
```

金融数字建议使用等宽数字：

```css
font-variant-numeric: tabular-nums;
```

如果需要更强的终端感，可以用于数据区域：

```css
font-family:
  "IBM Plex Mono",
  "SFMono-Regular",
  Consolas,
  monospace;
```

适用场景：

- 事件 ID
- 时间戳
- 数据源编号
- Pipeline 节点状态
- 任务日志
- 回测样本数

不建议整站使用等宽字体。

## 3.3 字号层级

```css
--text-xs:   11px;
--text-sm:   12px;
--text-md:   14px;
--text-base: 16px;
--text-lg:   18px;
--text-xl:   20px;
--text-2xl:  24px;
--text-3xl:  32px;
--text-4xl:  44px;
--text-5xl:  56px;
```

页面推荐使用：

| 用途 | 字号 | 行高 | 字重 |
|---|---:|---:|---:|
| 页面主标题 | 44px | 1.1 | 650 |
| 页面副标题 | 20px | 1.45 | 450 |
| 区块标题 | 24px | 1.25 | 650 |
| 卡片标题 | 16px | 1.35 | 600 |
| 正文 | 14px | 1.6 | 400 |
| 辅助文本 | 12px | 1.5 | 450 |
| 大型指标 | 36px | 1.0 | 650 |
| 表格数字 | 14px | 1.2 | 550 |

首页主标题建议：

```css
font-size: clamp(36px, 5vw, 56px);
line-height: 1.08;
font-weight: 650;
letter-spacing: 0;
```

不要使用负字间距。

---

# 4. 间距与尺寸

采用 4px 基础网格：

```css
--space-1:  4px;
--space-2:  8px;
--space-3:  12px;
--space-4:  16px;
--space-5:  20px;
--space-6:  24px;
--space-8:  32px;
--space-10: 40px;
--space-12: 48px;
--space-16: 64px;
--space-20: 80px;
--space-24: 96px;
```

## 页面布局

```css
--page-max-width: 1200px;
--page-padding-desktop: 32px;
--page-padding-tablet: 24px;
--page-padding-mobile: 16px;

--section-gap-desktop: 96px;
--section-gap-mobile: 56px;
```

首页及浅色页面内容宽度：

```css
max-width: 1200px;
margin-inline: auto;
padding-inline: 32px;
```

数据资产和决策台建议最大宽度扩大至：

```css
max-width: 1440px;
padding-inline: 24px;
```

## 控件尺寸

```css
--control-height-sm: 28px;
--control-height-md: 36px;
--control-height-lg: 44px;

--icon-button-size-sm: 28px;
--icon-button-size-md: 36px;
--icon-button-size-lg: 44px;
```

---

# 5. 圆角系统

整体圆角要克制，体现真实产品而非营销页面。

```css
--radius-none: 0;
--radius-sm:   4px;
--radius-md:   6px;
--radius-lg:   8px;
--radius-xl:   12px;
--radius-full: 999px;
```

使用规则：

| 元素 | 圆角 |
|---|---:|
| 输入框、按钮 | 6px |
| 普通卡片 | 8px |
| 资产卡 | 8px |
| 弹窗 | 12px |
| 标签、状态点 | 999px |
| 图表容器 | 8px |
| 架构节点 | 6px |
| 数据表格 | 6px |

避免 16px、20px、24px 大圆角，除非用于首页非常大的展示模块。

---

# 6. 阴影与边框

## 浅色页面

```css
--shadow-sm:
  0 1px 2px rgba(17, 24, 39, 0.04);

--shadow-md:
  0 6px 20px rgba(17, 24, 39, 0.07);

--shadow-lg:
  0 16px 40px rgba(17, 24, 39, 0.10);

--focus-ring:
  0 0 0 3px rgba(11, 122, 117, 0.18);
```

白底产品页优先使用边框，阴影只用于：

- 悬浮卡片
- 弹窗
- 导航下拉菜单
- 首页重点展示模块

## 深色页面

深色终端页面不使用明显阴影，而使用边框和内高光：

```css
--terminal-inner-highlight:
  inset 0 1px 0 rgba(255, 255, 255, 0.035);

--terminal-panel-shadow:
  0 12px 32px rgba(0, 0, 0, 0.18);
```

面板推荐：

```css
background: var(--terminal-surface);
border: 1px solid var(--terminal-border);
box-shadow: var(--terminal-inner-highlight);
```

---

# 7. 导航设计

## 桌面端

高度：

```css
height: 68px;
```

结构：

```text
[钱博士 Agent]    [概览] [系统架构] [数据资产] [决策台] [实盘纪律] [关于]    [中 / EN]
```

导航样式：

- 背景：`rgba(255,255,255,0.88)`
- 底部边框：`#E5E7EB`
- `backdrop-filter: blur(12px)`
- 页面内容最大宽度：`1200px`
- Logo 使用文字 + 小型数据流图标，不要做复杂插画

激活状态：

```css
color: var(--brand-600);
font-weight: 600;
```

激活底部指示条：

```css
height: 2px;
background: var(--brand-500);
border-radius: 2px;
```

## 深色页面导航

进入架构页、数据资产页和决策台时，导航同步变为深色：

```css
background: rgba(13, 18, 24, 0.88);
border-color: var(--terminal-border);
color: var(--terminal-text);
```

不要让导航固定使用浅色，否则跨页面切换会产生割裂感。

## 移动端

移动端使用：

```text
[Logo]                         [菜单]
```

菜单打开后使用全屏或右侧抽屉，不建议将 6 个页面压缩成一排小字。

---

# 8. 按钮系统

## Primary Button

```css
height: 36px;
padding-inline: 16px;
border-radius: 6px;
background: var(--brand-600);
color: #FFFFFF;
font-size: 14px;
font-weight: 600;
```

Hover：

```css
background: var(--brand-700);
```

适用：

- 查看系统架构
- 查看决策台
- 打开某条研究笔记
- 查看完整复盘

## Secondary Button

```css
background: transparent;
color: var(--light-text);
border: 1px solid var(--light-border-strong);
```

Hover：

```css
background: var(--light-surface-muted);
border-color: var(--brand-500);
```

## Terminal Button

```css
background: var(--terminal-surface-raised);
color: var(--terminal-text);
border: 1px solid var(--terminal-border-strong);
```

激活或执行态：

```css
background: var(--brand-600);
border-color: var(--brand-500);
color: #FFFFFF;
```

## 图标按钮

图标按钮必须有 tooltip 和 `aria-label`：

```css
width: 36px;
height: 36px;
border-radius: 6px;
```

适用图标：

- `ArrowUpRight`：打开详情
- `ExternalLink`：查看原始来源
- `Download`：下载报告
- `RefreshCw`：重新运行
- `Search`：搜索
- `Filter`：筛选
- `CalendarDays`：按日期筛选
- `ChevronDown`：下拉选择
- `PanelRight`：展开详情面板

按钮文字只用于明确动作，不要把图标按钮做成带文字的长胶囊。

---

# 9. 卡片系统

## 9.1 普通产品卡

```css
background: var(--light-surface);
border: 1px solid var(--light-border);
border-radius: 8px;
padding: 24px;
```

Hover：

```css
border-color: #C9D3D9;
box-shadow: var(--shadow-md);
transform: translateY(-1px);
```

动效：

```css
transition:
  border-color 160ms ease,
  box-shadow 160ms ease,
  transform 160ms ease;
```

不要使用大面积浮动卡片堆叠。页面区块应保持平整、连续、可扫描。

## 9.2 资产卡

资产卡是决策台中的白底展示组件，与外层深色终端形成对比。

```css
background: #FFFFFF;
border: 1px solid #DDE3E8;
border-radius: 8px;
padding: 20px;
color: #111827;
box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
```

结构：

```text
[资产图标] 黄金                         [看多]
XAU / GOLD

当前观点
★★★★☆

核心逻辑
美元走弱、实际利率回落，短期保持偏多。

[来源数] [置信度] [最近更新]
```

资产卡上方建议使用：

```css
display: grid;
grid-template-columns: repeat(5, minmax(180px, 1fr));
gap: 12px;
```

移动端改为横向滚动或单列，不要压缩卡片宽度。

## 9.3 数据指标卡

深色数据页面的指标卡采用高密度布局：

```css
background: var(--terminal-surface);
border: 1px solid var(--terminal-border);
border-radius: 6px;
padding: 16px;
min-height: 116px;
```

结构：

```text
9473
结构化观点
↑ 12.4% 近30天
```

数字：

```css
font-size: 30px;
font-weight: 650;
font-variant-numeric: tabular-nums;
```

辅助标签：

```css
font-size: 12px;
color: var(--terminal-text-tertiary);
```

---

# 10. 标签与状态

## 通用标签

```css
height: 24px;
padding-inline: 8px;
border-radius: 999px;
font-size: 12px;
font-weight: 550;
display: inline-flex;
align-items: center;
gap: 4px;
```

### 标签颜色

```css
.tag-brand {
  color: var(--brand-700);
  background: var(--brand-100);
}

.tag-positive {
  color: #A93636;
  background: var(--up-100);
}

.tag-negative {
  color: #16734A;
  background: var(--down-100);
}

.tag-warning {
  color: #8A6114;
  background: var(--warning-100);
}

.tag-neutral {
  color: var(--light-text-secondary);
  background: var(--light-surface-muted);
}
```

深色终端中使用 muted 背景：

```css
.tag-positive {
  color: var(--up-400);
  background: var(--up-muted);
}

.tag-negative {
  color: var(--down-400);
  background: var(--down-muted);
}
```

## Pipeline 状态

```text
已完成       绿色点 + 绿色文字
运行中       青色点 + 呼吸动画
等待处理     琥珀色点
失败         红色点
已跳过       灰色点
```

状态点：

```css
width: 6px;
height: 6px;
border-radius: 50%;
```

运行中动画：

```css
animation: pulse 1.8s ease-in-out infinite;
```

动画只用于实时运行状态，不要广泛使用。

---

# 11. 图表系统

## 通用图表规则

- 图表背景与所在容器一致
- 不使用厚重坐标轴
- 网格线使用低对比度
- 主要数据线最多 2 至 3 条
- tooltip 采用实体面板，不使用浏览器原生 tooltip
- 数值必须使用等宽数字或 tabular numbers
- 图表必须有清晰的时间范围和单位

## 颜色分配

```css
--chart-primary:   #4D91E8;
--chart-secondary: #5DE2D0;
--chart-positive:  #E05252;
--chart-negative:  #26A269;
--chart-warning:   #D99A2B;
--chart-muted:     #718292;
```

## 推荐图表类型

### 数据资产页

- 观点累计数量：面积折线图
- 观点来源分布：横向条形图
- 观点类型分布：分组条形图
- 笔记生成趋势：柱线组合图
- RAG chunks：单值指标 + 时间趋势

### 决策台

- 看多 / 看空命中率：分组柱状图
- 预测事件状态：状态分布条
- 资产观点变化：时间序列折线图
- 多空对照：左右对比列表
- 决策到期复盘：时间线

### 终端图表样式

```css
.chart-grid {
  stroke: var(--terminal-grid);
  stroke-width: 1;
}

.chart-axis {
  fill: var(--terminal-text-tertiary);
  font-size: 11px;
}

.chart-tooltip {
  background: #202B35;
  border: 1px solid #3A4B59;
  border-radius: 6px;
  color: #F3F6F8;
  padding: 10px 12px;
}
```

---

# 12. 表格系统

数据资产页和决策台需要表格表达真实数据量。

```css
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

thead {
  background: var(--terminal-surface-raised);
  color: var(--terminal-text-tertiary);
}

th {
  height: 36px;
  padding: 0 12px;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

td {
  height: 48px;
  padding: 0 12px;
  border-top: 1px solid var(--terminal-border);
  color: var(--terminal-text-secondary);
}
```

表格行 hover：

```css
background: rgba(255, 255, 255, 0.025);
```

适合展示的字段：

```text
时间
来源
资产
观点方向
置信度
预测区间
当前状态
复盘结果
```

长文本不直接塞进表格，应显示摘要并支持展开详情。

---

# 13. 架构页专项风格

架构页是工程能力的核心展示区域。

## 视觉结构

背景：

```css
background: #0B1117;
```

建议使用：

```css
background-image:
  linear-gradient(#1B2833 1px, transparent 1px),
  linear-gradient(90deg, #1B2833 1px, transparent 1px);
background-size: 32px 32px;
```

网格透明度控制在约 `0.35`，不能喧宾夺主。

## 节点样式

```css
.arch-node {
  background: #111A23;
  border: 1px solid #385263;
  border-radius: 6px;
  padding: 16px;
}
```

节点顶部显示：

```text
● RUNNING
```

节点内容：

```text
faster-whisper
GPU ASR 转写
```

## 数据流连线

- 主流程：`#5DE2D0`
- 模型流：`#A78BFA`
- 外部 API：`#6EA8FE`
- 定时触发：`#F4C46B`
- 异常路径：`#F06B6B`

连线宽度：

```css
stroke-width: 1.5px;
```

激活数据流：

```css
stroke-width: 2px;
stroke-dasharray: 5 5;
animation: flow 1.2s linear infinite;
```

架构图应能体现：

```text
B站源
  ↓
yt-dlp
  ↓
faster-whisper GPU
  ↓
ASR纠错
  ↓
DeepSeek 结构化笔记
  ↓
ChromaDB RAG
  ↓
盘前简报
  ↓
飞书推送
```

底部可补充：

```text
cron / SQLite / MCP Tools
```

---

# 14. 数据资产页专项风格

页面背景：

```css
background: var(--terminal-bg);
```

顶部使用指标带：

```text
9,473 结构化观点
9,400+ RAG chunks
900+ 研究笔记
30,000+ 回测事件
```

指标之间使用细边框分隔，而不是四个大圆角营销卡片。

推荐布局：

```text
顶部：资产总览指标带

第二行：
[观点趋势图  2fr] [来源分布 1fr]

第三行：
[笔记产出趋势 1fr] [回测预测统计 1fr]

底部：
[观点明细表]
```

页面中使用较高的信息密度：

- 标题与内容间距：16px
- 图表内边距：16px
- 行高：44 至 48px
- 关键指标与辅助说明明显分层

---

# 15. 决策台专项风格

决策台不是传统 Dashboard 营销页面，应模拟一个真实的研究工作台。

## 页面结构

```text
[市场状态] [数据更新时间] [盘前简报状态] [筛选]

资产卡横向区域
黄金 | 创新药 | 科技 | 白酒 | 铝

多空对照区域
看多观点                         看空观点

预测事件区域
待到期 | 已命中 | 未命中 | 待复盘

决策日志区域
时间线 + 原始观点 + 当时判断 + 当前结果
```

## 市场状态

```css
.market-status {
  color: var(--down-400);
  background: var(--down-muted);
  border: 1px solid rgba(66, 197, 138, 0.3);
}
```

文案示例：

```text
盘前准备完成
最近更新 08:42:16
```

## 多空对照卡

外层保持终端风格，左右内容使用细微色彩区分：

```css
.long-panel {
  border-top: 2px solid var(--up-500);
}

.short-panel {
  border-top: 2px solid var(--down-500);
}
```

注意中国市场红涨绿跌，因此：

- 多 / 涨：红色
- 空 / 跌：绿色

在页面上同时使用文字“看多”“看空”，不要只依赖颜色表达。

---

# 16. 实盘纪律页专项风格

实盘纪律页要表达“系统如何约束决策”，不是只展示收益率。

推荐视觉元素：

- 决策日志时间线
- 到期自动复盘状态
- 原始观点与最终结果对照
- 预测区间与实际结果
- 看多 / 看空命中率对照
- 系统自动推送记录

## 关键数据展示

```text
看空命中率       59.6%
看多命中率       39.1%
样本总量         30,000+
已完成复盘       12,840
```

59.6% 和 39.1% 使用对比柱形图或双 KPI，不建议只用两个孤立数字。

文案要明确：

```text
历史回测结果，不构成投资建议
```

这句话放在数据模块底部，以 11px 辅助文字展示。

---

# 17. 中英双语规范

## 文案切换

导航切换按钮建议使用：

```text
中 / EN
```

或：

```text
中文
English
```

不要使用国旗图标表示语言。

## 中文文案

中文应短、明确、偏产品化：

```text
结构化观点
研究笔记
预测事件
到期复盘
数据来源
系统状态
```

## 英文文案

英文使用 sentence case：

```text
Structured opinions
Research notes
Prediction events
Review due
Data sources
System status
```

不要使用全大写标题。只有表格字段、状态标签、技术标识可以使用小型大写或全大写。

## 中英文布局注意事项

- 中文标签建议预留英文状态下 1.3 倍宽度
- 数字指标不随语言变化布局
- 卡片标题设置 `min-height`，避免切换语言时页面跳动
- 按钮不要依赖固定宽度
- 移动端语言切换后检查长英文溢出

---

# 18. 动效规范

动效整体克制，重点表现“系统在运行”。

```css
--ease-standard: cubic-bezier(0.2, 0.8, 0.2, 1);
--duration-fast: 120ms;
--duration-base: 180ms;
--duration-slow: 280ms;
```

允许：

- 导航激活切换
- 卡片 hover
- 架构数据流动画
- Pipeline 运行状态呼吸
- 图表进入时的轻微绘制动画
- 页面主题切换

避免：

- 大幅滚动视差
- 无限旋转装饰
- 大面积漂浮元素
- 每个卡片同时出现的复杂动画
- 依赖动画才能理解数据的交互

尊重系统设置：

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

---

# 19. 推荐 Token 总表

```css
:root {
  --brand-500: #0B7A75;
  --brand-600: #09635F;
  --brand-700: #084E4B;
  --brand-100: #DDF5F1;
  --brand-50: #F0FBF9;

  --up-500: #E05252;
  --up-400: #F06B6B;
  --up-100: #FDE8E8;
  --up-muted: #54272B;

  --down-500: #26A269;
  --down-400: #42C58A;
  --down-100: #DDF7E9;
  --down-muted: #183D31;

  --warning-500: #D99A2B;
  --info-500: #4D91E8;

  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --radius-xl: 12px;
  --radius-full: 999px;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;
  --space-16: 64px;
  --space-20: 80px;
  --space-24: 96px;

  --page-max-width: 1200px;
  --terminal-max-width: 1440px;

  --font-sans:
    "Inter",
    "SF Pro Display",
    "PingFang SC",
    "Microsoft YaHei",
    Arial,
    sans-serif;

  --font-mono:
    "IBM Plex Mono",
    "SFMono-Regular",
    Consolas,
    monospace;

  --ease-standard: cubic-bezier(0.2, 0.8, 0.2, 1);
  --duration-fast: 120ms;
  --duration-base: 180ms;
  --duration-slow: 280ms;
}

[data-theme="light"] {
  --page-bg: #F7F8FA;
  --surface: #FFFFFF;
  --surface-muted: #F1F3F5;
  --border: #E5E7EB;
  --border-strong: #D1D5DB;
  --text: #111827;
  --text-secondary: #4B5563;
  --text-tertiary: #8A94A6;
}

[data-theme="architecture"] {
  --page-bg: #0B1117;
  --surface: #111A23;
  --surface-raised: #17232E;
  --border: #263746;
  --border-strong: #385263;
  --text: #F4F7FA;
  --text-secondary: #AAB8C5;
  --text-tertiary: #718292;
}

[data-theme="terminal"] {
  --page-bg: #0D1218;
  --surface: #141B23;
  --surface-raised: #1B2530;
  --border: #293642;
  --border-strong: #3A4B59;
  --text: #F3F6F8;
  --text-secondary: #B4C0C9;
  --text-tertiary: #7D8B96;
}
```

这套系统的核心识别点是：浅色页面建立产品可信度，架构页展示自动化工程链路，终端页面承载真实数据密度，白底资产卡负责把复杂投研信息重新变成可读、可展示的产品模块。