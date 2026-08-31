# Phase 2d 实现提示词 — 决策台页（v1.0）

你是资深全栈工程师 + 数据可视化工程师。在"钱博士Agent 作品集网页"（E:\qianboshi-portfolio，Phase 0-2c 已完成实测）上实现 **Phase 2d：决策台页**（用户决策日志 + 资产卡 + 复盘闭环，深色终端外壳 + 白底资产卡）。遵守现有架构，只改/新增本提示词列出的文件。

## 一、现有架构（必须遵守）
- Vite + React 18 + TS + Tailwind 3；`@/` = `frontend/src/`；三套 data-theme；CSS 变量在 styles/themes.css（含 Phase 2b 加的 surfaceRaised/surfaceSubtle/surfaceBrand/borderStrong/brandStrong/shadow-card/cardHover）；组件用 Tailwind 映射类禁止硬编码色值；涨跌语义色：`market-positive`(#E05252 红=看多/涨)、`market-negative`(#26A269 绿=看空/跌)
- 数据层：DataProvider + ApiClient（snake_case→camelCase 显式映射，失败返回空结构）+ SnapshotClient + types/index.ts（**已有 DecisionSummary/DecisionItem 骨架类型，以本提示词为准替换**）；路由 app/router.tsx；i18n zh/en
- 后端：FastAPI（backend/，Python3.14），main.py 的 api_router（prefix=/api/v1），repositories 只读（SQLite mode=ro），复用 overview_repo/assets_repo 的路径常量模式
- 现有页面：DecisionDeskPage.tsx 是占位页（"Phase 1 实现"提示），本次重构

## 二、真实数据口径（已核实，后端实时计算）
SQLite `E:\qianboshi-agent\data\qianboshi_decision.db`（mode=ro）：
- **user_decision_logs**（5 条）：列 decision_id/user_id/asset_id/asset_name/asset_type/decision_date/horizon/direction/conviction/thesis/key_reasons/invalidation_conditions/action_note/asset_card_version/debate_card_id/market_snapshot/status/created_at/updated_at；现状：
  - dec_2026-08-06_GOLD_001 黄金 bullish 0.7 medium open
  - dec_2026-08-06_INNOV_DRUG_001 创新药 bullish 0.6 medium open
  - dec_2026-08-06_TECH_001 科技股 bearish 0.6 short **reviewed**
  - dec_2026-08-06_BAIJIU_001 白酒 bearish 0.7 short **reviewed**
  - dec_2026-08-06_ALUMINUM_001 铝 bullish 0.65 medium open
- **asset_cards**（8 张）：asset_id/asset_name/asset_type(commodity|sector|theme)/description/updated_at——GOLD黄金/SEMI半导体/AI AI应用/ROBOT机器人/BAIJIU白酒/ALUMINUM铝/INNOV_DRUG创新药/TECH科技
- **factor_states**（31 行）：asset_id/factor_name/current_state/impact_direction(positive|negative|neutral)/impact_strength(low|medium|high)/as_of_date——每资产 3-4 因子，取每资产 as_of_date 最新的 3 条
- **decision_reviews**（2 条）：decision_id/review_date/horizon_days/outcome_return/result_label('wrong'|'hit')/what_went_right/what_went_wrong/missed_factors/new_rule_learned——TECH/BAIJIU 已复盘 result_label='wrong'

## 三、后端：新建 `backend/app/repositories/decisions_repo.py`
```python
def get_decisions_data() -> dict
```
返回：
```json
{
  "stats": {"total": 5, "open": 3, "reviewed": 2, "hit": 0, "wrong": 2, "generated_at": "ISO"},
  "decisions": [
    {"decision_id": "...", "asset_name": "黄金", "asset_type": "commodity",
     "decision_date": "2026-08-06", "horizon": "medium", "direction": "bullish",
     "conviction": 0.7, "thesis": "核心逻辑前120字", "status": "open", "review_result": null}
  ],
  "asset_cards": [
    {"asset_id": "GOLD", "asset_name": "黄金", "asset_type": "commodity", "description": "...",
     "factors": [{"factor_name": "美元指数", "current_state": "近5日走弱-1.07%", "impact_direction": "positive", "impact_strength": "high"}]}
  ],
  "reviews": [
    {"decision_id": "...", "asset_name": "科技股", "direction": "bearish", "review_date": "2026-08-11",
     "result_label": "wrong", "outcome_return": 1.9048, "horizon_days": 5, "new_rule_learned": null}
  ]
}
```
- horizon 中英映射常量：short短期/medium中期/long长期（decision 展示用）
- reviews 需 JOIN user_decision_logs 拿 asset_name/direction
- 全 try/except 兜底，单项失败返回空

## 四、后端 `backend/app/main.py` 加端点
`GET /api/v1/decisions` → `{"decisions_data": {...get_decisions_data()}}`（挂 api_router；注意已有 /overview 等端点，不要冲突）

## 五、前端

### 1. types/index.ts：替换 DecisionSummary/DecisionItem 为：
```ts
export interface DecisionItem {
  decisionId: string; assetName: string; assetType: string;
  decisionDate: string | null; horizon: string; direction: string;
  conviction: number | null; thesis: string; status: string;
  reviewResult: string | null;
}
export interface AssetCardFactor { factorName: string; currentState: string; impactDirection: string; impactStrength: string }
export interface AssetCardItem { assetId: string; assetName: string; assetType: string; description: string; factors: AssetCardFactor[] }
export interface DecisionReviewItem { decisionId: string; assetName: string; direction: string; reviewDate: string | null; resultLabel: string; outcomeReturn: number | null; horizonDays: number | null; newRuleLearned: string | null }
export interface DecisionStats { total: number; open: number; reviewed: number; hit: number; wrong: number; generatedAt: string | null }
export interface DecisionSummary { stats: DecisionStats; decisions: DecisionItem[]; assetCards: AssetCardItem[]; reviews: DecisionReviewItem[] }
```
（DecisionSummary 保留同名，字段全换；其他页面若引用旧字段需同步——目前无其他页面用 getDecisions，安全）

### 2. api-client.ts：getDecisions() 真实 fetch `/v1/decisions`，映射 `decisions_data` 下所有 snake_case→camelCase（decision_id→decisionId、result_label→resultLabel、factor_name→factorName 等），失败返回全空结构

### 3. snapshot-client.ts：getDecisions() 读 `/snapshots/decision-desk.json`，读不到返回空结构

### 4. 新建 `src/components/decision/AssetCardView.tsx`（白底产品卡，展示感强）
Props `{ card: AssetCardItem }`。设计：
- 白底卡片：bg-surface border border-line rounded-lg shadow-card p-6，hover:shadow-cardHover hover:border-brand transition
- 顶部：资产名（text-lg font-medium text-heading）+ 类型标签（commodity=商品/sector=板块/theme=主题，小 pill：bg-surfaceSubtle text-muted 或按类型着色——commodity 琥珀/sector 蓝/info 色）
- 描述（text-sm text-muted line-clamp-2）
- 因子速览：3 行（factor_name 左 text-sm text-muted + current_state 中 truncate + impact 色点右：positive=market-positive 红/negative=market-negative 绿/neutral=灰，加 tooltip title=impact_strength）
- 每行 impact_direction 用色点 + current_state 文本

### 5. 新建 `src/components/decision/DecisionCard.tsx`
Props `{ decision: DecisionItem }`。设计（深色终端风格）：
- 面板：bg-surface border border-line rounded-lg p-5，左侧 2px 方向色条（bullish=market-positive 红 / bearish=market-negative 绿 / neutral 灰）
- 顶部行：资产名（font-medium text-heading）+ 方向 pill（看多红底/看空绿底/中性灰底，小圆角）+ 状态 badge（待复盘=warning 琥珀 / 已复盘=info 蓝 / 复盘结果 wrong=market-negative 绿（失误）/ hit=market-positive 红（命中））
- 第二行：决策日期 + 周期（short短期/medium中期）+ 信心度（tabular-nums，如 70%）
- 核心逻辑 thesis（text-sm text-muted line-clamp-2）
- 信心度可视化：细进度条（h-1 rounded bg-surfaceSubtle，内层宽度=conviction*100%，颜色同方向色）

### 6. 重构 `src/pages/DecisionDeskPage.tsx`（深色终端外壳 + 白底资产卡）
页面结构（自上而下）：
1. 页面头：eyebrow（"DECISION DESK"）+ H1（决策台 decisions.title）+ 描述（decisions.description）
2. **统计条**（grid border-y sm:grid-cols-5）：决策总数 / 待复盘 / 已复盘 / 命中 / 失误（label 小字 + value tabular-nums；命中/失误用语义色）
3. **决策日志**（decisions.logTitle）：DecisionCard 列表（决策数组，按 decision_date 降序）
4. **资产卡墙**（decisions.cardsTitle）：grid sm:grid-cols-2 xl:grid-cols-4 的 AssetCardView（8 张白底卡）
5. **复盘闭环**（decisions.reviewsTitle）：reviews 列表——每条：资产名 + 方向 pill + 复盘日期 + result_label（命中/失误 badge）+ 收益 outcome_return（+1.90%，market-positive 红）+ 周期天数；new_rule_learned 有则展示（引用块样式）
6. 底部数据时效注脚（generated_at）
- loading/error/空态与其他页一致
- 文案全走 i18n

### 7. i18n zh/en 新增 key
- decisions.title（决策台 / Decision Desk）、decisions.description（"基于结构化观点库的用户决策记录、资产卡因子状态与到期自动复盘闭环。" / "User decisions, asset card factor states, and the automatic review loop."）
- decisions.statTotal（决策总数 / Decisions）、statOpen（待复盘 / Pending review）、statReviewed（已复盘 / Reviewed）、statHit（命中 / Hit）、statWrong（失误 / Miss）
- decisions.logTitle（决策日志 / Decision log）、cardsTitle（资产卡 / Asset cards）、reviewsTitle（复盘闭环 / Review loop）
- decisions.directionBullish（看多 / Bullish）、directionBearish（看空 / Bearish）、directionNeutral（中性 / Neutral）
- decisions.statusOpen（待复盘 / Pending）、statusReviewed（已复盘 / Reviewed）、resultHit（命中 / Hit）、resultWrong（失误 / Miss）
- decisions.horizonShort（短期 / Short-term）、horizonMedium（中期 / Medium-term）、horizonLong（长期 / Long-term）
- decisions.conviction（信心度 / Conviction）、decisions.reviewDate（复盘 / Reviewed on）、decisions.outcomeReturn（收益 / Return）、decisions.horizonDays（{count} 日窗口 / {count}-day window）
- 类型标签直接显示 asset_name 原文；assetType 显示 decisions.assetType{commodity|sector|theme}（商品/板块/主题 / Commodity/Sector/Theme）

## 六、验收标准
1. `curl http://localhost:8010/api/v1/decisions` 返回 stats{5,3,2,0,2}、5 条决策（3 open 2 reviewed）、8 张资产卡各带 3 因子、2 条复盘（wrong）
2. 前端 /zh/decisions：统计条 5 项、决策日志 5 卡（方向色条+pill+信心度进度条+状态 badge）、资产卡墙 8 张白底卡（因子速览带色点）、复盘区 2 条（失误 badge + 收益显示）
3. 三套主题切换配色正常（白底资产卡在深色主题下仍可读）
4. 停后端：空态不崩
5. `npm run build` TS 零错误
6. 中英切换正常
7. 不破坏其他页面

## 七、输出格式
按文件输出，每个文件用标记包裹：
```
<<<FILE: backend/app/repositories/decisions_repo.py>>>
完整内容
<<<END>>>
```
新建：backend/app/repositories/decisions_repo.py、frontend/src/components/decision/AssetCardView.tsx、frontend/src/components/decision/DecisionCard.tsx
修改：backend/app/main.py、frontend/src/types/index.ts、frontend/src/data/api-client.ts、frontend/src/data/snapshot-client.ts、frontend/src/pages/DecisionDeskPage.tsx、frontend/src/i18n/locales/zh.ts、frontend/src/i18n/locales/en.ts
只输出这些文件的代码，无解释废话。
