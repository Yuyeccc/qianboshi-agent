# Phase 2f 实现提示词 — 实盘纪律页（v1.0）

你是资深全栈工程师 + 数据可视化工程师。在"钱博士Agent 作品集网页"（E:\qianboshi-portfolio，Phase 0-2e 已完成实测）上实现 **Phase 2f：实盘纪律页**（白底运营复盘风，局部深色 KPI 带；决策日志/到期复盘/纪律规则/时间线）。遵守现有架构，只改/新增本提示词列出的文件。

## 一、现有架构（必须遵守）

- Vite + React 18 + TS + Tailwind 3；`@/` = `frontend/src/`；三套 data-theme（product/architecture/terminal），CSS 变量在 styles/themes.css；组件用 Tailwind 映射类禁止硬编码色值；涨跌语义色：`market-positive`(#E05252 红=看多/涨)、`market-negative`(#26A269 绿=看空/跌)
- 数据层：DataProvider + ApiClient（snake_case→camelCase 显式映射，失败返回空结构）+ SnapshotClient + types/index.ts（**已有 DisciplineRule/DisciplineData 骨架类型，以本提示词为准替换**）；路由 app/router.tsx；i18n zh/en（`useTranslation`）
- 后端：FastAPI（backend/，Python3.14），main.py 的 api_router（prefix=/api/v1），repositories 只读模式（SQLite mode=ro），路径常量在 schema_registry.py（DATA_ROOT = E:\qianboshi-agent\data）
- 现有页面：DisciplinePage.tsx 是占位页（"Phase 1 实现"提示），本次重构
- 页面取数据：`useContext(DataContext)`（from `@/app/providers`）+ useEffect + loading/error/empty 三态（参照 OverviewPage 模式）；**不存在 useData/DataProvider 模块**
- 文件输出用 `<<<FILE: 路径>>> 内容 <<<END>>>` 标记，只输出清单内文件（白名单），禁止带 ``` 代码围栏

## 二、⚠️ 脱敏红线（最高优先级，违反 = 返工）

实盘纪律页是求职作品集，**绝不展示**：
- 具体金额（买入价/卖出价/加仓金额/市值/盈亏金额）
- 持仓明细（持仓标的代码/数量/成本价，如 000217/159992/成本0.8991）
- 收益率具体数值可展示（如 outcome_return 2.33%）但**金额/成本/代码一律不展示**
- 用户的真实姓名/ID（user_id 字段不展示）

后端在组装数据时**必须剔除** thesis/key_reasons/action_note 中的持仓与金额表述（action_note 字段整体不返回；thesis 截取前 120 字并去掉"持仓XXX/成本XXX/投XXX元"类表述——简单做法：thesis 只返回前 100 字，且后端做一次关键词清洗：出现 "持仓" "成本" "000217" "159992" "元" 等即截断到该词之前）。

## 三、真实数据口径（已核实）

SQLite `E:\qianboshi-agent\data\qianboshi_decision.db`（mode=ro）：
- **user_decision_logs**（5 条）：dec_2026-08-06_GOLD_001 黄金 bullish 0.7 medium open / dec_2026-08-06_INNOV_DRUG_001 创新药 bullish 0.6 medium open / dec_2026-08-06_TECH_001 科技股 bearish 0.6 short **reviewed** / dec_2026-08-06_BAIJIU_001 白酒 bearish 0.7 short **reviewed** / dec_2026-08-06_ALUMINUM_001 铝 bullish 0.65 medium open
- **decision_reviews**（2 条）：TECH/BAIJIU 已复盘，review_date 2026-08-11，horizon_days 5，result_label='wrong'，outcome_return 1.9048（TECH）/ 2.3256（BAIJIU）
- 统计：total 5 / open 3 / reviewed 2 / hit 0 / wrong 2

策略框架（静态配置，来自用户实盘理念"情绪定方向+纪律定仓位+止损定退出"）：
- r1 情绪定方向：市场情绪（恐慌/贪婪）决定多空方向，不追涨杀跌
- r2 纪律定仓位：按计划分批建仓（如黄金：涨投/大跌投/小跌投三档），仓位由纪律决定不由感觉决定
- r3 止损定退出：设定失效条件（跌破关键支撑/逻辑证伪），触达即执行退出
- r4 到期必复盘：每个判断挂时间窗口，到期自动复盘并记录结果

纪律原则（页面标题区，绑定系统字段）：
- 观点必须有来源（view 记录 analyst/source/date）
- 预测必须有时间窗口（prediction_event 挂 maturity）
- 到期后必须记录结果（decision_review 回填 outcome）

## 四、后端：新建 `backend/app/repositories/discipline_repo.py`

```python
def get_discipline_data() -> dict
```

返回：
```json
{
  "meta": {"generated_at": "ISO", "source": "live"},
  "principles": [
    {"id": "p1", "title": "观点必须有来源", "description": "每条观点记录分析师/来源/日期"},
    {"id": "p2", "title": "预测必须有时间窗口", "description": "每个判断挂 maturity，到期自动复盘"},
    {"id": "p3", "title": "到期后必须记录结果", "description": "复盘回填收益并判定 hit/wrong"}
  ],
  "stats": {
    "total_decisions": 5, "open": 3, "reviewed": 2, "hit": 0, "wrong": 2,
    "review_coverage_pct": 40, "generated_at": "ISO"
  },
  "framework": [
    {"rule_id": "r1", "title": "情绪定方向", "description": "恐慌贪婪定多空，不追涨杀跌", "status": "active"},
    {"rule_id": "r2", "title": "纪律定仓位", "description": "按档位计划分批建仓，仓位不由感觉决定", "status": "active"},
    {"rule_id": "r3", "title": "止损定退出", "description": "预设失效条件，触达即退出", "status": "active"},
    {"rule_id": "r4", "title": "到期必复盘", "description": "判断挂时间窗口，到期自动复盘", "status": "active"}
  ],
  "timeline": [
    {"date": "2026-08-06", "action_type": "decision", "summary": "建立 5 条决策日志：黄金/创新药看多，科技股/白酒看空，铝看多", "rule_ids": ["r1", "r2"]},
    {"date": "2026-08-11", "action_type": "review", "summary": "科技股/白酒到期复盘，均判定 wrong，各记录收益与修正", "rule_ids": ["r4"]}
  ],
  "decision_logs": [
    {"decision_id": "dec_2026-08-06_GOLD_001", "date": "2026-08-06", "asset_name": "黄金",
     "direction": "bullish", "horizon": "medium", "conviction": 0.7,
     "thesis": "黄金强相关于美元加息降息，8月已兑现9月加息趋势，该跌的已跌得差不多；预计再震荡一段时间后，9月开始往上走。",
     "key_reasons": ["8月已兑现9月加息预期，利空出尽", "美元加息周期末端，黄金压力释放", "该跌的已经跌得差不多"],
     "status": "open", "review": null},
    {"decision_id": "dec_2026-08-06_TECH_001", "date": "2026-08-06", "asset_name": "科技股",
     "direction": "bearish", "horizon": "short", "conviction": 0.6,
     "thesis": "科技股周二周三已大涨，位置偏高不敢进，预计回调：光模块相对还好，其他半导体周四可能下跌套人。",
     "key_reasons": ["科技股短期涨幅过大", "半导体位置偏高", "不愿承担套牢风险"],
     "status": "reviewed", "review": {"review_date": "2026-08-11", "result_label": "wrong", "outcome_return": 1.9048, "horizon_days": 5}}
  ]
}
```
（decision_logs 如实返回 5 条，review 只挂在 reviewed 的 2 条上；thesis 按脱敏红线截断清洗；key_reasons 原样返回前 3 条；action_note 不返回）

- horizon 中英映射常量：short短期/medium中期/long长期
- reviews JOIN user_decision_logs 拿 asset_name/direction
- 全 try/except 兜底，单项失败返回空

## 五、后端 `backend/app/main.py` 加端点

`GET /api/v1/discipline` → `{"discipline_data": {...get_discipline_data()}}`（挂 api_router；注意已有 /overview /assets /decisions /briefs /architecture 端点，不要冲突）

## 六、前端

### 1. types/index.ts：替换 DisciplineRule/DisciplineData 为：

```ts
export interface DisciplinePrinciple { id: string; title: string; description: string }
export interface DisciplineStats {
  totalDecisions: number | null; open: number | null; reviewed: number | null;
  hit: number | null; wrong: number | null; reviewCoveragePct: number | null;
  generatedAt: string | null;
}
export interface DisciplineFrameworkRule { ruleId: string; title: string; description: string; status: string }
export interface DisciplineTimelineItem { date: string | null; actionType: string; summary: string; ruleIds: string[] }
export interface DisciplineReview { reviewDate: string | null; resultLabel: string; outcomeReturn: number | null; horizonDays: number | null }
export interface DisciplineLogItem {
  decisionId: string; date: string | null; assetName: string;
  direction: string; horizon: string; conviction: number | null;
  thesis: string; keyReasons: string[]; status: string; review: DisciplineReview | null;
}
export interface DisciplineData {
  meta: DataMeta;
  principles: DisciplinePrinciple[];
  stats: DisciplineStats;
  framework: DisciplineFrameworkRule[];
  timeline: DisciplineTimelineItem[];
  decisionLogs: DisciplineLogItem[];
}
```
（DisciplineData 保留同名，字段全换；其他页面若引用旧字段需同步——目前无其他页面用 getDiscipline，安全）

### 2. api-client.ts：getDiscipline() 真实 fetch `/v1/discipline`，映射 `discipline_data` 下所有 snake_case→camelCase（total_decisions→totalDecisions、review_coverage_pct→reviewCoveragePct、rule_id→ruleId、action_type→actionType、decision_id→decisionId、asset_name→assetName、result_label→resultLabel、outcome_return→outcomeReturn、horizon_days→horizonDays、key_reasons→keyReasons、decision_logs→decisionLogs 等），失败返回全空结构

### 3. snapshot-client.ts：getDiscipline() 读 `/snapshots/discipline.json`，读不到返回空结构

### 4. 重构 `src/pages/DisciplinePage.tsx`（白底产品风，局部深色 KPI 带）

页面整体用 product 主题视觉（用映射类即可，跟 Header 当前主题走）。区块结构（从上到下）：

**① 页面标题与纪律原则**
- 标题：`Trading Discipline`（h1 text-heading）+ 中文副题"记录观点，不追逐结果；到期复盘，不修改历史"
- 三条纪律原则：principles 渲染为 3 个横向卡片（icon：来源=BookMarked / 时间窗口=Timer / 结果=ClipboardCheck，lucide 图标），白底卡片 bg-surface border border-line rounded-lg shadow-card p-6，title 加粗 + description 小字 text-muted

**② 复盘 KPI 带（深色横条）**
- 深色背景条（bg-surface 深色面板或直接用 architecture 主题色块，border border-line rounded-lg p-6，内部文字浅色）
- 5 个指标格：总决策 totalDecisions / 待到期 open / 已复盘 reviewed / 命中 hit / 未命中 wrong
- 命中/未命中用语义色（hit=market-positive 红、wrong=market-negative 绿），其余用 text-heading
- 附加一行小字：`复盘覆盖率 {reviewCoveragePct}% · 数据口径：user_decision_logs + decision_reviews`（text-muted）

**③ 策略框架**
- 标题"实盘纪律框架" + 副题"情绪定方向 · 纪律定仓位 · 止损定退出"
- framework 渲染 4 个卡片（2x2 网格）：ruleId 小标（mono text-brand）+ title + description + status pill（active=绿色圆点 "生效中"）

**④ 决策日志**
- 标题"决策日志" + 副题"保留当时的判断，不展示事后结论；持仓与金额已脱敏"
- 纵向列表（每条一个白底卡）：日期 + 资产名 + 方向 pill（bullish 红/bearish 绿/neutral 灰）+ horizon 标签 + 置信度（conviction 百分比）+ 状态 pill（open=待到期 / reviewed=已复盘）
- thesis 全文（text-sm text-text leading-6）
- key_reasons 前 3 条：小字列表（• 前缀 text-muted）
- 若有 review：底部一条复盘行（border-t）：`复盘 {review.reviewDate} · 结果 wrong · 区间收益 {outcomeReturn}% · 窗口 {horizonDays}天`（wrong 用 market-negative，hit 用 market-positive）

**⑤ 纪律时间线（底部浅色收束）**
- 标题"纪律时间线"
- timeline 纵向时间线：左侧日期（mono text-brand），右侧 summary + ruleIds 关联（小 pill 显示对应规则 r1/r2...），节点用圆点（border-brand bg-surface）

### 5. i18n：zh.ts/en.ts 补 `pages.discipline.*` 全部 key（标题/副题/原则/指标标签/框架/日志/时间线/状态词等；资产名/规则内容不翻译）

## 七、验收标准（必须全部满足）

1. `npm run build` 通过（frontend/）
2. 后端 8010 起服务后 `curl http://localhost:8010/api/v1/discipline` 返回完整 JSON（principles 3 / stats / framework 4 / timeline 2 / decision_logs 5，其中 2 条带 review）
3. **脱敏检查**：响应中绝无 "000217" "159992" "成本" "持仓" "100元" "500元" "200元" 等字样
4. 页面在 5173 渲染：原则/深色 KPI 带/框架 4 卡/决策日志 5 条（2 条带复盘行）/时间线全部显示，数据非空
5. 断后端时页面不崩（api-client 返回空结构，页面显示 empty 态）
6. 无 console 报错
7. 只输出清单内文件：backend/app/repositories/discipline_repo.py、backend/app/main.py、frontend/src/types/index.ts、frontend/src/data/api-client.ts、frontend/src/data/snapshot-client.ts、frontend/src/pages/DisciplinePage.tsx、frontend/src/i18n/locales/zh.ts、frontend/src/i18n/locales/en.ts

## 八、输出格式

文件用 `<<<FILE: 相对路径>>> 内容 <<<END>>>` 标记，只输出清单内文件，禁止 ``` 代码围栏。
