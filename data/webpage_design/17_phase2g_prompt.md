# Phase 2g 实现提示词 — 简报行情区块（v1.0）

你是资深全栈工程师 + 数据可视化工程师。在"钱博士Agent 作品集网页"（E:\qianboshi-portfolio，Phase 0-2f 已完成实测）上实现 **Phase 2g：简报详情页全球市场行情区块**（美股三大指数卡 + 美股AI链 chips + 持仓代理 + 5日迷你走势图 + 数据时间戳）。遵守现有架构，只改/新增本提示词列出的文件。

## 一、现有架构（必须遵守）

- Vite + React 18 + TS + Tailwind 3；`@/` = `frontend/src/`；三套 data-theme（product/architecture/terminal），CSS 变量在 styles/themes.css；组件用 Tailwind 映射类禁止硬编码色值；涨跌语义色：`market-positive`(#E05252 红=涨/看多)、`market-negative`(#26A269 绿=跌/看空)
- 数据层：DataProvider + ApiClient（snake_case→camelCase 显式映射，失败返回空结构）+ SnapshotClient + types/index.ts；路由 app/router.tsx；i18n zh/en（`useTranslation`）
- 后端：FastAPI（backend/，Python3.14），main.py 的 api_router（prefix=/api/v1），repositories 只读模式，路径常量在 schema_registry.py（DATA_ROOT = E:\qianboshi-agent\data）
- 页面取数据：`useContext(DataContext)`（from `@/app/providers`）+ useEffect + loading/error/empty 三态（参照 OverviewPage/BriefDetailPage 模式）；**不存在 useData/DataProvider 模块**
- 文件输出用 `<<<FILE: 路径>>> 内容 <<<END>>>` 标记，只输出清单内文件（白名单），禁止带 ``` 代码围栏
- 本页不用 ECharts（迷你走势用纯 SVG 手写，避免引入图表库依赖）

## 二、真实数据口径（已核实，2026-08-23 12:44 刷新）

数据源 `E:\qianboshi-agent\data\market_cache.json`（最新价/change_pct/updated）+ `price_trends.json`（每标的日线 {date: {price, change_pct}}）：

**美股三大指数**（US_INDICES 常量）：
- ^DJI 道琼斯 53277.01 +0.98%
- ^IXIC 纳斯达克 26180.46 +0.43%
- ^GSPC 标普500 7674.37 +0.43%

**美股AI链 10 只**（US_STOCKS 常量，展示全部）：
- NVDA 英伟达 214.72 -0.98% / TSLA 特斯拉 362.86 +5.14% / AAPL 苹果 309.35 -0.63% / MSFT 微软 483.24 +0.43% / AMD 473.25 +0.81% / META 549.90 +0.75% / GOOGL 344.82 +1.22% / AVGO 博通 368.45 +1.21% / MRVL 迈威尔 237.04 -5.57% / SMCI 超微 37.24 +2.03%

**A股指数**（CN_INDICES 常量）：
- 000001.SS 上证指数 3905.20 +0.04% / 399001.SZ 深证成指 14094.17 +0.87% / 399006.SZ 创业板指 3545.58 +0.00%

**持仓代理（决策验证标的）**（PROXY_ASSETS 常量，标注"决策验证"）：
- 518880.SS 华安黄金ETF 9.39 +1.73%（关联：黄金 GOLD 决策 bullish/medium，待 08-26 复盘）
- 159992.SZ 创新药ETF 0.89 -5.32%（关联：创新药 INNOV_DRUG 决策 bullish/medium，待 08-26 复盘）
- 512480.SS 半导体ETF 1.04 +0.00%（关联：科技股 TECH 决策 bearish/short，已复盘 wrong）

**5日趋势**（price_trends.json 每标的最近 5 个交易日日期+价格，示例 ^DJI：[2026-08-08 54036.93, 08-10 53954.82, 08-11 54034.85, 08-12 53782.71, 08-23 53277.01]）——缺失时返回空数组

**统一数据时间戳**：market_cache.json 里 ^DJI 的 `updated` = "2026-08-23T12:44:22.562375"

## 三、后端：新建 `backend/app/repositories/market_repo.py`

```python
def get_market_data() -> dict
```

返回：
```json
{
  "meta": {"generated_at": "ISO", "data_as_of": "2026-08-23T12:44:22", "source": "yfinance"},
  "us_indices": [
    {"symbol": "^DJI", "name": "道琼斯", "name_en": "Dow Jones", "price": 53277.01, "change_pct": 0.98,
     "trend": [{"date": "2026-08-08", "price": 54036.93}, {"date": "2026-08-10", "price": 53954.82}]}
  ],
  "us_stocks": [
    {"symbol": "NVDA", "name": "英伟达", "name_en": "NVIDIA", "price": 214.72, "change_pct": -0.98, "trend": [...]}
  ],
  "cn_indices": [
    {"symbol": "000001.SS", "name": "上证指数", "name_en": "Shanghai Composite", "price": 3905.2, "change_pct": 0.04, "trend": [...]}
  ],
  "proxy_assets": [
    {"symbol": "518880.SS", "name": "华安黄金ETF", "name_en": "Gold ETF", "price": 9.39, "change_pct": 1.73,
     "trend": [...], "linked_decision": {"asset": "黄金", "direction": "bullish", "status": "open", "review_date": "2026-08-26"}}
  ]
}
```

实现要点：
- 从 market_cache.json 读 price/change_pct，从 price_trends.json 读最近 5 日 trend（按日期排序取最后 5 个）
- 符号→中文名映射常量：US_INDICES / US_STOCKS / CN_INDICES / PROXY_ASSETS 写死在 repo 里（如上数据口径）
- proxy_assets 的 linked_decision 从 SQLite `qianboshi_decision.db`（mode=ro，DATABASE_PATH 在 schema_registry.py）user_decision_logs 按 asset_id 关联：518880→GOLD、159992→INNOV_DRUG、512480→TECH，取 status/direction/review_date；查不到给 null 字段不报错
- 文件缺失/单标的缺失 → 该项跳过，不拖垮整体；全 try/except 兜底
- trend 每项只含 date/price 两字段（轻量，前端画 SVG 用）

## 四、后端 `backend/app/main.py` 加端点

`GET /api/v1/market` → `{"market_data": {...get_market_data()}}`（挂 api_router；注意已有 /overview /assets /decisions /briefs /architecture /discipline 端点，不要冲突）

## 五、前端

### 1. types/index.ts 新增：

```ts
export interface MarketTrendPoint { date: string; price: number }
export interface MarketQuote {
  symbol: string; name: string; nameEn: string;
  price: number | null; changePct: number | null; trend: MarketTrendPoint[];
}
export interface ProxyAssetDecision {
  asset: string | null; direction: string | null; status: string | null; reviewDate: string | null;
}
export interface MarketProxyAsset extends MarketQuote { linkedDecision: ProxyAssetDecision | null }
export interface MarketData {
  meta: DataMeta;
  dataAsOf: string | null;
  source: string | null;
  usIndices: MarketQuote[];
  usStocks: MarketQuote[];
  cnIndices: MarketQuote[];
  proxyAssets: MarketProxyAsset[];
}
```
（在 types/index.ts 合适位置追加，不动已有类型）

### 2. api-client.ts：
- 新增 `emptyMarket` 常量（全空结构）
- 新增 `mapMarketResponse(input: unknown): MarketData`（解 `market_data` 包壳，映射 data_as_of→dataAsOf、us_indices→usIndices、change_pct→changePct、name_en→nameEn、linked_decision→linkedDecision、review_date→reviewDate 等；trend 数组逐项 date/price；失败返回 emptyMarket）
- `ApiClient` 加 `getMarket(): Promise<MarketData>`（fetch `/v1/market`，失败返回 emptyMarket）

### 3. snapshot-client.ts：加 `getMarket()` 读 `/snapshots/market.json`，读不到返回 emptyMarket（沿用现有模式）

### 4. DataProvider 接口（frontend/src/data/provider.ts）：加 `getMarket(): Promise<MarketData>`（对照 getDiscipline 的位置加）

### 5. 新建 `src/components/brief/MarketSnapshot.tsx`（简报行情区块组件）

Props：`{ data: MarketData }`。白底产品风（跟简报详情页一致），区块结构：

**区块标题行**：左 "全球市场 · Global Markets"（text-sm font-medium text-heading）+ 右 数据时间（`数据更新 {formatDateTime(dataAsOf)} · {source}`，text-xs text-muted，formatDateTime 用 toLocaleString）

**① 美股三大指数卡（grid 3 列，sm:grid-cols-3 gap-3）**
每卡：白底 bg-surface border border-line rounded-lg p-4
- 名称（text-sm text-muted）+ name_en（text-xs text-muted/60）
- 价格（text-xl font-semibold，涨=market-positive 红/跌=market-negative 绿/平=text-heading）
- 涨跌幅（text-sm，同色，`+0.98%`）
- 迷你走势图：SVG 手写折线（宽 100% 高 32，5 个点，path 连线；涨=market-positive 色/跌=market-negative 色；trend 不足 2 点不画，画 "—"）

**② 美股 AI 链 chips（flex flex-wrap gap-2）**
每 chip：symbol（font-mono text-xs font-medium）+ change_pct（text-xs 红涨绿跌），bg-surfaceSubtle border border-line rounded-md px-2.5 py-1.5，hover:border-brand transition

**③ A股指数（3 列小卡，复用①卡片样式但更紧凑）**

**④ 持仓代理·决策验证（grid 3 列）**
每卡：白底卡 + 左上小标 "决策验证"（text-[10px] uppercase tracking-wide text-brand bg-surfaceBrand/20 rounded px-1.5 py-0.5）
- 名称 + symbol（text-sm）+ 价格/涨跌幅（同①配色）
- linkedDecision 存在时：底部一行小字（text-xs text-muted）`{asset} {direction==='bullish'?'看多':'看空'} · {status==='open'?'待复盘':'已复盘'} · {reviewDate}`（direction 映射：bullish 看多红/bearish 看空绿/neutral 中性灰）
- linkedDecision 为 null 时不显示这行

**空态**：usIndices/usStocks 全空时整区块显示 "暂无行情数据"（text-sm text-muted py-8 text-center），不崩

### 6. `src/pages/BriefDetailPage.tsx` 集成

- 页面加载时并行调 `provider.getMarket()`（和 getBrief/getBriefs 一起 Promise.all），存 state
- 在标题 header 之后、正文 markdown 之前插入 `<MarketSnapshot data={marketData} />`（上下留 gap）
- marketData 为 emptyMarket（meta.status 非 ready）时同样渲染空态提示，不阻断正文

### 7. i18n：zh.ts/en.ts 补 `market.*` 全部 key（标题/数据时间/来源/涨跌标签/决策验证/看多看空/待复盘已复盘/暂无行情数据/道琼斯纳斯达克标普等名称可走数据不翻译，但"全球市场/数据更新/决策验证/看多/看空/待复盘/已复盘/暂无行情数据"必须走 t()）

## 六、验收标准（必须全部满足）

1. `npm run build` 通过（frontend/）
2. 后端 8010 起服务后 `curl http://localhost:8010/api/v1/market` 返回完整 JSON：us_indices 3 / us_stocks 10 / cn_indices 3 / proxy_assets 3（各带 5 日 trend），proxy_assets 的 linked_decision 非 null（GOLD/INNOV_DRUG/TECH 关联正确）
3. 页面在 5173 `/zh/briefs/日报_2026-08-22` 渲染：标题行 + 时间戳 + 三大指数卡（价格/涨跌/迷你折线）+ AI 链 10 chips + A 股指数 + 3 张决策验证卡（带"决策验证"标签和关联行）
4. 断后端时页面不崩（emptyMarket → 空态提示，正文仍渲染）
5. 无 console 报错
6. 只输出清单内文件：backend/app/repositories/market_repo.py、backend/app/main.py、frontend/src/types/index.ts、frontend/src/data/api-client.ts、frontend/src/data/snapshot-client.ts、frontend/src/data/provider.ts、frontend/src/components/brief/MarketSnapshot.tsx、frontend/src/pages/BriefDetailPage.tsx、frontend/src/i18n/locales/zh.ts、frontend/src/i18n/locales/en.ts

## 七、输出格式

文件用 `<<<FILE: 相对路径>>> 内容 <<<END>>>` 标记，只输出清单内文件，禁止 ``` 代码围栏。
