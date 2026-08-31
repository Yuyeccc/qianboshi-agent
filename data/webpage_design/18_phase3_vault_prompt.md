# Phase 3 实现提示词 — 研究档案库（Research Vault）（v1.0）

你是资深全栈工程师 + 数据产品工程师。在"钱博士Agent 作品集网页"（E:\qianboshi-portfolio，Phase 0-2g 已完成实测）上实现 **Phase 3：研究档案库**（按需加载：Obsidian 笔记浏览 + 资产卡详情 + RAG 检索，三模式工作台）。遵守现有架构，只改/新增本提示词列出的文件。

## 一、现有架构（必须遵守）

- Vite + React 18 + TS + Tailwind 3；`@/` = `frontend/src/`；三套 data-theme（product/architecture/terminal），CSS 变量在 styles/themes.css；组件用 Tailwind 映射类禁止硬编码色值；涨跌语义色：`market-positive`(#E05252 红=涨/看多)、`market-negative`(#26A269 绿=跌/看空)
- 数据层：DataProvider + ApiClient（snake_case→camelCase 显式映射，失败返回空结构）+ SnapshotClient + types/index.ts；路由 app/router.tsx（createHashRouter）；i18n zh/en（`useTranslation`）
- 后端：FastAPI（backend/，Python3.14），main.py 的 api_router（prefix=/api/v1），repositories 只读模式，路径常量在 schema_registry.py（DATA_ROOT = E:\qianboshi-agent\data，DATABASE_PATH = data/qianboshi_decision.db）
- 页面取数据：`useContext(DataContext)`（from `@/app/providers`）+ useEffect + loading/error/empty 三态；**不存在 useData/DataProvider 模块**
- 文件输出用 `<<<FILE: 路径>>> 内容 <<<END>>>` 标记，只输出清单内文件（白名单），禁止带 ``` 代码围栏
- **主项目复用**：后端可 `sys.path.insert(0, r"E:\qianboshi-agent\scripts")` 后 import `evidence_pack_builder`（build_evidence_pack(asset_id, horizon) 返回 11 模块 dict）和 `query_rag`（QianboshiRAG().query(text, top_k, score_threshold, max_days) 返回 [{"content","source","section","score","raw_score","type"}]）——两者自带配置加载，**不要重新实现**
- 参考现有 repo 写法：assets_repo.py（_database_uri/mode=ro）、brief_repo.py（目录扫描）、market_repo.py（读 JSON + SQLite 关联）

## 二、真实数据口径（已核实）

**笔记**（E:\obsidian-vault\学习\钱博士\，987 篇 .md）：
- 命名：`日期 标题.md`，如 `2026.7.2 钱博士直播复盘.md`、`2026.6.25 半导体再次进入逼空行情 短视频解读.md`
- YAML frontmatter：`date` / `created` / `tags`（数组）/ `source`（如 `B站BV1Z4T76AE9y 钱博士直播回放 2026.7.2`）
- 正文：markdown，含视频时间戳引用 `(00:15:17-00:15:20)`、表格、代码块
- 文件名日期解析：`2026.7.2` → `2026-07-02`（正则 `(\d{4})\.(\d{1,2})\.(\d{1,2})`）

**结构化观点**（structured_views.jsonl 9727 条）：view_id/analyst/claim/confidence/date/entities{etfs,sectors,stocks,themes,us_mapping}/evidence/horizon/logic/quality_flags/risk/section/source_bv/source_file/source_path/source_type/stance/timestamp/version/view_type
- **source_path 指向笔记绝对路径**（如 E:\obsidian-vault\学习\钱博士\任泽平 2026.06.27 BV1Zz7W6yEHo.md）——观点↔笔记联动键：source_path 的文件名部分 == 笔记文件名
- 关联观点数 = 按 source_path 文件名统计

**资产卡**（SQLite asset_cards 8 张）：asset_id(GOLD/SEMI/AI/ROBOT/BAIJIU/ALUMINUM/INNOV_DRUG/TECH)/asset_name/asset_type/description/version/default_horizon/updated_at
**因子**（factor_states 31 行）：asset_id/factor_name/current_state/impact_direction/impact_strength/evidence_refs/as_of_date
**多空**（debate_cards）：entity_name/bullish_count/bearish_count/neutral_count/consensus_direction/disagreement_level
**证据包**：build_evidence_pack(asset_id, horizon) → {asset_id, asset_name, as_of_date, asset_card, factor_states, debate_card, latest_views, analyst_scores, market_snapshot, user_decision_history, rag_evidence, summary}

## 三、页面与路由

- `#/vault` → `ResearchVaultPage.tsx`（default export）：三模式工作台
- `#/vault/assets/:assetId` → `AssetResearchDetailPage.tsx`（default export）：单资产研究详情
- 导航加"研究档案库"（Header 里，zh=研究档案库 / en=Research Vault；路由路径 vault）

## 四、后端

### 新建 `backend/app/repositories/vault_repo.py`

```python
NOTE_DIR = Path(r"E:\obsidian-vault\学习\钱博士")
VIEWS_PATH = DATA_ROOT / "views" / "structured_views.jsonl"
def _note_id_from_filename(filename: str) -> str  # sha256(filename) 前 12 位
def _parse_frontmatter(content: str) -> dict      # YAML date/created/tags/source，解析失败给 {}
def _parse_title(filename: str) -> str            # 去掉日期前缀和 .md
def _parse_note_date(filename: str) -> str | None # 2026.7.2 → 2026-07-02
def _scan_notes() -> list[dict]                   # 全量扫描 NOTE_DIR：note_id/filename/title/note_date/created_at/tags/source/excerpt(正文前160字)/size_bytes/file_mtime
def _views_index() -> dict[str, int]              # 文件名→观点数（structured_views.jsonl 单遍扫描，source_path 取 basename）
def get_vault_summary() -> dict
def list_notes(page: int, page_size: int, query: str | None, date_from: str | None, date_to: str | None, tags: list[str] | None, source: str | None, sort: str) -> dict
def get_note_detail(note_id: str) -> dict | None  # 校验 note_id 存在于扫描结果，返回全文+frontmatter+关联观点(最近5条)
```

返回结构：
- `get_vault_summary()` → `{"meta": {"generated_at","source"}, "notes_count": 987, "views_count": 9727, "chunks_count": 11011, "assets_count": 8, "latest_note_date": "2026-08-22", "modes": ["notes","search","assets"]}`
- `list_notes()` → `{"data": [{note_id,filename,title,note_date,created_at,tags,source,excerpt,structured_view_count,size_bytes}], "pagination": {"page","page_size","total","has_more"}}`
  - 筛选：query 匹配标题/正文关键词；date_from/date_to 过滤 note_date；tags 任一匹配；source 包含；sort 支持 date_desc/date_asc/title
- `get_note_detail(note_id)` → `{"note_id","filename","title","note_date","created_at","tags","source","content","related_views":[view_id,analyst,claim,date,stance,confidence,section,evidence(前200字)]}`
  - **绝不返回 source_path 绝对路径**；note_id 白名单校验（不存在返回 None）
- `POST /api/vault/notes/{note_id}/open-local`（仅本地 dev）：校验 note_id 在扫描结果 → 返回 `{"opened": true, "note_id"}`；非 dev 环境返回 403。用 `subprocess.Popen(["open", path])`（macOS）或 `os.startfile`（Windows，需 platform 判断）；路径必须是 NOTE_DIR 下 resolved 后的真实文件（防穿越）

### 新建 `backend/app/repositories/asset_vault_repo.py`

```python
def get_assets_index() -> dict        # 8 资产卡摘要 + 各卡因子数/观点倾向汇总
def get_asset_evidence_pack(asset_id: str, horizon: str = "medium") -> dict  # sys.path 注入后调 build_evidence_pack；失败返回 {"error": ...} 或空结构
def get_asset_views(asset_id: str, page: int, page_size: int) -> dict        # 按 entities 匹配 structured_views（stocks/sectors/themes/etfs 里含该资产相关代码/词），分页
```

### 新建 `backend/app/repositories/rag_vault_repo.py`

```python
def rag_query(text: str, top_k: int = 10, score_threshold: float = 0.0, max_days: int | None = None, page: int = 1, page_size: int = 10) -> dict
def rag_suggestions() -> list[dict]   # 静态快捷词：如 黄金 美元指数 / 半导体 回调 / 光模块 新易盛 / AI 应用 商业化 等 8-12 条
```
- rag_query：调 QianboshiRAG().query()，返回 `{"data": [{rank,content,source,section,score,raw_score,type}], "pagination": {...}}`；ChromaDB 不可用时返回空 data + `{"degraded": true, "reason": "chromadb unavailable"}`，**不抛错**
- 注意：query_rag 导入可能依赖 chromadb 版本（主项目是 1.5.9），导入失败/查询异常全部 try/except 兜底

### main.py 加端点（挂 api_router）

| Method | Path | 返回 |
|---|---|---|
| GET | /api/v1/vault/summary | `{"vault_summary": {...}}` |
| GET | /api/v1/notes | `{"notes_data": {...list_notes()}}`（query/date_from/date_to/tags/source/sort/page/page_size 作 query params） |
| GET | /api/v1/notes/{note_id} | `{"note": {...}}` 或 404 |
| POST | /api/v1/notes/{note_id}/open-local | `{"opened": true, "note_id": ...}` 或 403 |
| GET | /api/v1/vault/assets | `{"assets_index": {...}}` |
| GET | /api/v1/vault/assets/{asset_id}/evidence-pack | `{"evidence_pack": {...}}`（horizon query param，默认 medium） |
| GET | /api/v1/vault/assets/{asset_id}/views | `{"views_data": {...}}` |
| POST | /api/v1/rag/query | body `{"text","top_k","score_threshold","max_days","page","page_size"}` → `{"rag_data": {...}}` |
| GET | /api/v1/rag/suggestions | `{"suggestions": [...]}` |

## 五、前端

### 1. types/index.ts 新增（不动已有类型）：

```ts
export interface VaultNoteItem { noteId: string; filename: string; title: string; noteDate: string | null; createdAt: string | null; tags: string[]; source: string | null; excerpt: string; structuredViewCount: number | null; sizeBytes: number | null }
export interface VaultNoteDetail extends VaultNoteItem { content: string; relatedViews: RelatedViewItem[] }
export interface RelatedViewItem { viewId: string; analyst: string; claim: string; date: string | null; stance: string; confidence: number | null; section: string | null; evidence: string }
export interface Pagination { page: number; pageSize: number; total: number; hasMore: boolean }
export interface VaultSummary { meta: DataMeta; notesCount: number | null; viewsCount: number | null; chunksCount: number | null; assetsCount: number | null; latestNoteDate: string | null; modes: string[] }
export interface RagHitItem { rank: number; content: string; source: string; section: string | null; score: number; rawScore: number; type: string }
export interface RagSuggestionItem { label: string; query: string; assetId?: string | null }
```

### 2. api-client.ts / snapshot-client.ts / provider.ts：
- 新增 emptyVaultSummary / emptyNotesData / emptyEvidencePack / emptyRagData 常量
- 新增 mapVaultSummaryResponse / mapNotesResponse / mapNoteDetailResponse / mapEvidencePackResponse（evidence_pack 字段复杂，**顶层字段直接透传 camelCase 映射**：asset_card→assetCard、factor_states→factorStates、debate_card→debateCard、latest_views→latestViews、analyst_scores→analystScores、market_snapshot→marketSnapshot、user_decision_history→userDecisionHistory、rag_evidence→ragEvidence）/ mapRagResponse / mapAssetsIndexResponse
- DataProvider 加：getVaultSummary() / listNotes(params) / getNoteDetail(noteId) / getVaultAssets() / getAssetEvidencePack(assetId, horizon?) / getAssetViews(assetId, page?) / ragQuery(params) / getRagSuggestions() / openNoteLocal(noteId)
- **listNotes/ragQuery 带参数**：ApiClient 拼 query string；SnapshotClient 读快照分片（notes/index-page-{page}.json、rag/presets/…）

### 3. 新建 `src/pages/ResearchVaultPage.tsx`（default export，白底产品风为主）

**① 标题区**：`研究档案库 / Research Vault` + 副题 + 右侧数据条（notes/views/chunks 计数 + 快照/API 模式标）
**② 模式切换 Tabs**：`笔记浏览 | RAG 检索 | 资产研究`（localStorage 记忆上次模式，URL ?mode= 同步）
**③ 笔记浏览模式**（默认）：
- 左筛选栏：关键词/日期范围/标签/来源（从 summary 或首屏拉取可用 tags）；右侧列表分页（每页 20，加载更多或页码）
- 笔记卡片：title + note_date + tags chips + excerpt + 关联观点数 badge；点击 → 右侧详情面板（或新路由 `#/vault/note/:noteId`）
- 详情面板：frontmatter（date/created/tags/source）+ 正文 markdown 渲染（react-markdown + remark-gfm，**不要 dangerouslySetInnerHTML 原始 HTML**）+ 关联观点列表（claim/analyst/date/stance/confidence/evidence 截断）
**④ RAG 检索模式**：
- 输入框（Enter 触发）+ top_k(10/20/50) + score_threshold(0-1 slider) + max_days(7/30/90/365/全部) + 类型 filter(all/note/structured_view/transcript)
- 快捷词 chips（ragSuggestions）
- 结果列表：rank + content（关键词高亮，**客户端转义后高亮**）+ source + section + score/rawScore 分开展示 + type badge
- 快照模式下：自由文本搜索显示 `snapshot_limited` 提示（"快照模式仅支持预设查询，完整检索请使用本地 API"），并展示预设查询结果
- 分页（page/page_size/has_more）
**⑤ 资产研究模式**：8 张资产卡 grid（复用决策台 AssetCardView 风格：asset_id/name/type/description + 因子速览 2-3 条 + 观点倾向），点击 → `#/vault/assets/:assetId`

### 4. 新建 `src/pages/AssetResearchDetailPage.tsx`（default export）

- 面包屑（研究档案库 → 资产名）+ 返回
- **① 资产标题区**：asset_name + asset_id + asset_type（商品/板块/主题 pill）+ summary + as_of_date + 数据模式标
- **② 因子状态**：表格（factor_name / current_state / impact_direction 语义色点 / impact_strength / as_of_date），或卡片网格
- **③ 多空对照**：三列（看多/看空/中性计数）+ 共识 + 分歧度，白底卡
- **④ 最新观点**：latest_views 列表（claim/analyst/date/confidence/stance/entities chips），"查看全部"→ 拉 /views 分页
- **⑤ 证据链**：rag_evidence 列表（content 摘要 + source + score），点击跳对应笔记
- **⑥ 分析师历史**：analyst_scores 表格（analyst/entity/sample_count/hit_rate 百分比），**样本量 <3 显示 — 或"样本不足"**
- **⑦ 决策历史**：user_decision_history（脱敏：不显示金额/持仓）
- loading/error/empty 三态

### 5. i18n：zh.ts/en.ts 补 `vault.*` 全部 key（页面标题/模式名/筛选标签/卡片字段/检索控件/empty/loading/error/snapshot_limited/资产详情各区块标题等）

## 六、快照分片（Phase 3 快照）

扩展 `backend/scripts/generate_snapshots.py`（追加，不动现有 8 个快照）：

```text
snapshots/vault-summary.json
snapshots/notes-index.json            # 全量笔记索引（不含正文，~200-400KB）
snapshots/notes/{note_id}.json        # 单篇详情（按需，生成全部 987 篇 ≈ 5-8MB 总量）
snapshots/assets-index.json
snapshots/assets/{asset_id}/evidence-pack-medium.json
snapshots/assets/{asset_id}/evidence-pack-short.json
snapshots/assets/{asset_id}/evidence-pack-long.json
snapshots/rag/suggestions.json
snapshots/rag/presets/{preset_id}.json  # 预设查询结果（黄金美元/半导体回调/光模块/AI商业化 等 8-12 条）
snapshots/manifest.json                  # {generated_at, counts, modes, note_count, preset_ids}
```

- manifest.json 供前端判断快照完整性
- notes/{note_id}.json 用 sha256 前 12 位作文件名
- 生成日志打印各分片数量与总大小

## 七、验收标准（必须全部满足）

1. `npm run build` 通过
2. 后端 8010 起服务后：`/api/v1/vault/summary`、`/api/v1/notes?page=1&page_size=5`、`/api/v1/notes/{真实note_id}`、`/api/v1/vault/assets/GOLD/evidence-pack`、`/api/v1/rag/query`（POST {"text":"黄金 美元指数"}）、`/api/v1/rag/suggestions` 全部返回合法 JSON
3. **note 详情响应中绝无 `E:\` 或 `source_path` 或绝对路径**（检查）
4. 页面 `#/vault` 三模式可切换：笔记浏览（筛选/分页/详情面板）、RAG 检索（输入/快捷词/结果/高亮/snapshot_limited）、资产研究（8 卡）
5. `#/vault/assets/GOLD` 详情：标题/因子/多空/观点/证据/分析师/决策全渲染
6. 断后端时页面不崩（空结构 + empty 态）
7. 无 console 报错
8. 快照生成脚本跑通：新分片全部生成，manifest.json 计数正确
9. 只输出清单内文件

## 八、输出格式

文件用 `<<<FILE: 相对路径>>> 内容 <<<END>>>` 标记，只输出清单内文件，禁止 ``` 代码围栏。
