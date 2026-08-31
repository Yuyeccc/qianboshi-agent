# SQLite Schema Report

- Database: `E:\qianboshi-agent\data\qianboshi_decision.db`

## Table: `analyst_scores`

- Columns: `analyst`, `entity`, `horizon`, `window_days`, `sample_count`, `hit_rate`, `avg_return`, `score`, `updated_at`
- Row count: `335`
- First two rows:

```text
'趋势天哥' | '300308.SZ' | 'intraday,medium,short,unknown' | 1 | 41 | 0.4634 | -1.9363 | 0.4634 | '2026-08-06T16:11:43'
'趋势天哥' | '300308.SZ' | 'intraday,medium,short,unknown' | 10 | 41 | 0.4634 | -0.5974 | 0.4634 | '2026-08-06T16:11:43'
```

## Table: `asset_card_versions`

- Columns: `version_id`, `asset_id`, `version`, `config_json`, `change_reason`, `changed_by`, `linked_review_id`, `created_at`
- Row count: `8`
- First two rows:

```text
'GOLD_v1' | 'GOLD' | 1 | '{"asset_id": "GOLD", "asset_name": "黄金", "asset_type": "commodity", "config_path": "E:\\\\qianboshi-agent\\\\configs\\\\asset_cards\\\\gold.yaml", "default_horizon": "medium", "description": "黄金中期趋势分析框架", "factors": [{"category": "macro", "data_binding": {"fields": ["close", "pct_change_5d", "pct_change_20d"], "source": "yfinance", "symbol": "DX-Y.NYB", "type": "market"}, "factor_id": "DXY", "factor_name": "美元指数", "impact_rule": {"description": "美元走强通常压制黄金，美元走弱通常利好黄金", "relation": "negative", "strength": "high"}, "refresh_policy": {"frequency": "daily", "mode": "scheduled"}}, {"category": "macro", "data_binding": {"fields": ["close", "change_5d", "change_20d"], "source": "yfinance", "symbol": "^TNX", "type": "market"}, "factor_id": "US_REAL_YIELD", "factor_name": "美债实际利率", "impact_rule": {"description": "实际利率上行压制无息资产黄金，实际利率下行利好黄金", "relation": "negative", "strength": "high"}, "refresh_policy": {"frequency": "daily", "mode": "scheduled"}}, {"category": "event", "data_binding": {"lookback_days": 14, "query_terms": ["地缘", "战争", "中东", "避险", "冲突"], "type": "view_query", "view_types": ["risk", "event", "market"]}, "factor_id": "GEOPOLITICAL_RISK", "factor_name": "地缘风险", "impact_rule": {"description": "地缘风险升温通常强化黄金避险需求", "relation": "positive", "strength": "medium"}, "refresh_policy": {"frequency": "daily", "mode": "scheduled"}}, {"category": "fundamental", "data_binding": {"lookback_days": 60, "query_terms": ["央行购金", "黄金储备", "去美元化"], "type": "view_query", "view_types": ["framework", "market", "sector"]}, "factor_id": "CENTRAL_BANK_BUYING", "factor_name": "央行购金", "impact_rule": {"description": "央行购金构成黄金中长期配置支撑", "relation": "positive", "strength": "high"}, "refresh_policy": {"frequency": "daily", "mode": "scheduled"}}], "version": 1}' | 'auto_refresh' | 'system' | None | '2026-08-06T00:34:58'
'SEMI_v1' | 'SEMI' | 1 | '{"asset_id": "SEMI", "asset_name": "半导体", "asset_type": "sector", "config_path": "E:\\\\qianboshi-agent\\\\configs\\\\asset_cards\\\\semiconductor.yaml", "default_horizon": "medium", "description": "半导体中期趋势分析框架", "factors": [{"category": "market", "data_binding": {"fields": ["close", "pct_change_5d", "pct_change_20d"], "source": "yfinance", "symbol": "^SOX", "type": "market"}, "factor_id": "SOX", "factor_name": "费城半导体指数", "impact_rule": {"description": "费城半导体指数走强通常映射全球半导体风险偏好改善", "relation": "positive", "strength": "high"}, "refresh_policy": {"frequency": "daily", "mode": "scheduled"}}, {"category": "policy", "data_binding": {"lookback_days": 30, "query_terms": ["国产替代", "自主可控", "半导体设备", "材料", "中芯"], "type": "view_query", "view_types": ["framework", "sector", "market"]}, "factor_id": "DOMESTIC_SUBSTITUTION", "factor_name": "国产替代", "impact_rule": {"description": "国产替代逻辑升温通常支撑国内半导体景气预期", "relation": "positive", "strength": "high"}, "refresh_policy": {"frequency": "daily", "mode": "scheduled"}}, {"category": "industry", "data_binding": {"lookback_days": 30, "query_terms": ["英伟达", "NVDA", "算力", "HBM", "AI芯片"], "type": "view_query", "view_types": ["framework", "sector", "market"]}, "factor_id": "NVIDIA_CHAIN", "factor_name": "英伟达产业链", "impact_rule": {"description": "英伟达产业链景气强化通常利好AI相关半导体资产", "relation": "positive", "strength": "medium"}, "refresh_policy": {"frequency": "daily", "mode": "scheduled"}}, {"category": "industry", "data_binding": {"lookback_days": 45, "query_terms": ["云厂商资本开支", "Capex", "北美云", "微软", "谷歌", "Meta", "AWS"], "type": "view_query", "view_types": ["framework", "sector", "market"]}, "factor_id": "CLOUD_CAPEX", "factor_name": "北美云厂商资本开支", "impact_rule": {"description": "北美云厂商资本开支上修通常支撑AI算力和半导体需求", "relation": "positive", "strength": "high"}, "refresh_policy": {"frequency": "daily", "mode": "scheduled"}}], "version": 1}' | 'auto_refresh' | 'system' | None | '2026-08-06T00:34:59'
```

## Table: `asset_cards`

- Columns: `asset_id`, `asset_name`, `asset_type`, `current_version`, `default_horizon`, `description`, `config_path`, `created_at`, `updated_at`
- Row count: `8`
- First two rows:

```text
'GOLD' | '黄金' | 'commodity' | 1 | 'medium' | '黄金中期趋势分析框架' | 'E:\\qianboshi-agent\\configs\\asset_cards\\gold.yaml' | '2026-08-06T00:34:58' | '2026-08-06T16:55:24'
'SEMI' | '半导体' | 'sector' | 1 | 'medium' | '半导体中期趋势分析框架' | 'E:\\qianboshi-agent\\configs\\asset_cards\\semiconductor.yaml' | '2026-08-06T00:34:59' | '2026-08-06T12:14:17'
```

## Table: `debate_card_items`

- Columns: `id`, `card_id`, `view_id`, `stance`, `analyst`, `date`, `claim`, `logic`, `risk`, `evidence`, `confidence`, `cluster_id`, `cluster_label`, `analyst_score_snapshot`, `source_file`
- Row count: `8476`
- First two rows:

```text
391 | 'debate_半导体_all_2026-05-22_2026-07-20' | 'c944bf66e6e1b048' | 'bullish' | '钱博士直播' | '2026-07-09' | '短线：看多 🐂📈' | '发展国产GPU是决心下的既定战略，且GPU制造本质是工艺问题，给机会就能突破。' | '短线：看多 🐂📈 逻辑：发展国产GPU是决心下的既定战略，且GPU制造本质是工艺问题，给机会就能突破。 (00:73:45-00:74:08) 英伟打在国内的分额归零了，就是现在不是说，现在不是说你卖不卖给我的问题，是我不卖的...因为我们要给我们国产GPU机会。 (00:74:56-00:75:00) GPU这个东西，不要以为是有多高的高科技，科学原理非常清楚。核心的卡点在工艺，工艺就是参数。只要给我们国产GPU机会，调工艺调参数，一' | '短线：看多 🐂📈 逻辑：发展国产GPU是决心下的既定战略，且GPU制造本质是工艺问题，给机会就能突破。 (00:73:45-00:74:08) 英伟打在国内的分额归零了，就是现在不是说，现在不是说你卖不卖给我的问题，是我不卖的...因为我们要给我们国产GPU机会。 (00:74:56-00:75:00) GPU这个东西，不要以为是有多高的高科技，科学原理非常清楚。核心的卡点在工艺，工艺就是参数。只要给我们国产GPU机会，调工艺调参数，一年两年三年，就可能赶到给我们认为大差不多。根本不是科学问题，是工艺问题。' | 0.91 | '' | '' | None | '钱博士直播复盘 2026.07.09 BV1SLMn6wE6n.md'
392 | 'debate_半导体_all_2026-05-22_2026-07-20' | 'd446d4df94792807' | 'bearish' | '钱博士直播' | '2026-07-13' | '中长线：看空 🐻📉（短期强势反弹后的回调风险）' | '科技股前期涨幅巨大（如科创50涨71%），许多个股已反弹30%，获利盘压力大。国产替代虽是主线逻辑，但当这一逻辑演绎完毕，市场容易进入调整。' | '中长线：看空 🐻📉（短期强势反弹后的回调风险） 逻辑：科技股前期涨幅巨大（如科创50涨71%），许多个股已反弹30%，获利盘压力大。国产替代虽是主线逻辑，但当这一逻辑演绎完毕，市场容易进入调整。 (839.00s-857.00s) 这个有些科技股已经跌了30%了...你那个很多的股票其实已经调整了很多了 (904.00s-913.00s) 前面因为3到6月份整个的科创版就是涨了71%...很多的各个都是方便的情况之下 (1194.00s' | '中长线：看空 🐻📉（短期强势反弹后的回调风险） 逻辑：科技股前期涨幅巨大（如科创50涨71%），许多个股已反弹30%，获利盘压力大。国产替代虽是主线逻辑，但当这一逻辑演绎完毕，市场容易进入调整。 (839.00s-857.00s) 这个有些科技股已经跌了30%了...你那个很多的股票其实已经调整了很多了 (904.00s-913.00s) 前面因为3到6月份整个的科创版就是涨了71%...很多的各个都是方便的情况之下 (1194.00s-1208.00s) 国产串理是整个科技的最后一站...这一盘菜一旦一次完，这个市场就要...进入到买单的这样一个结段了' | 0.91 | '' | '' | None | '钱博士直播复盘 2026.07.13 BV1TkN26fE51.md'
```

## Table: `debate_cards`

- Columns: `card_id`, `entity_id`, `entity_name`, `entity_type`, `horizon`, `window_start`, `window_end`, `bullish_count`, `bearish_count`, `neutral_count`, `risk_count`, `watch_count`, `consensus_direction`, `disagreement_level`, `confidence_level`, `novelty_level`, `highlight_tags`, `summary`, `created_at`, `updated_at`
- Row count: `163`
- First two rows:

```text
'debate_半导体_all_2026-05-22_2026-07-20' | '半导体' | '半导体' | 'sector' | 'all' | '2026-05-22' | '2026-07-20' | 77 | 53 | 95 | 3 | 1 | 'neutral' | 0.4629 | 0.7424 | 0.0 | '["高置信"]' | '半导体：多头77条，空头53条，风险3条，中性95条，共识方向=neutral，分歧度=0.46。' | '2026-08-05T01:30:06' | '2026-08-05T01:51:05'
'debate_光模块_all_2026-05-22_2026-07-20' | '光模块' | '光模块' | 'sector' | 'all' | '2026-05-22' | '2026-07-20' | 60 | 51 | 48 | 2 | 0 | 'bullish' | 0.6335 | 0.795 | 0.0 | '["高置信", "强分歧"]' | '光模块：多头60条，空头51条，风险2条，中性48条，共识方向=bullish，分歧度=0.63。' | '2026-08-05T01:31:01' | '2026-08-05T01:54:24'
```

## Table: `decision_reviews`

- Columns: `review_id`, `decision_id`, `review_date`, `horizon_days`, `outcome_return`, `benchmark_return`, `excess_return`, `max_drawdown`, `result_label`, `what_went_right`, `what_went_wrong`, `missed_factors`, `over_weighted_factors`, `new_rule_learned`, `suggest_asset_card_update`, `linked_new_card_version`, `created_at`
- Row count: `2`
- First two rows:

```text
'rev_dec_2026-08-06_TECH_001_2026-08-11' | 'dec_2026-08-06_TECH_001' | '2026-08-11' | 5 | 1.9048 | None | None | None | 'wrong' | None | None | None | None | None | 0 | None | '2026-08-11T22:30:53'
'rev_dec_2026-08-06_BAIJIU_001_2026-08-11' | 'dec_2026-08-06_BAIJIU_001' | '2026-08-11' | 5 | 2.3256 | None | None | None | 'wrong' | None | None | None | None | None | 0 | None | '2026-08-11T22:30:53'
```

## Table: `factor_states`

- Columns: `state_id`, `asset_id`, `card_version`, `factor_id`, `factor_name`, `as_of_date`, `raw_value`, `current_state`, `change_direction`, `impact_direction`, `impact_strength`, `confidence`, `evidence_refs`, `summary`, `created_at`
- Row count: `31`
- First two rows:

```text
'GOLD_1_DXY_2026-08-06' | 'GOLD' | 1 | 'DXY' | '美元指数' | '2026-08-06' | '{"symbol": "DX-Y.NYB", "close": 99.724, "date": "2026-08-05", "pct_change_5d": -1.0675, "pct_change_20d": -1.3122, "source": "price_trends"}' | '近5日走弱-1.07%' | 'down' | 'positive' | 'high' | 0.8 | '["yfinance"]' | '美元指数近5日走弱-1.07%，对GOLD构成positive影响。' | '2026-08-06T00:34:58'
'GOLD_1_US_REAL_YIELD_2026-08-06' | 'GOLD' | 1 | 'US_REAL_YIELD' | '美债实际利率' | '2026-08-06' | '{"symbol": "^TNX", "close": 4.637, "date": "2026-08-05", "pct_change_5d": 0.3245, "pct_change_20d": 1.4883, "source": "price_trends"}' | '近5日走强+0.32%' | 'up' | 'negative' | 'high' | 0.8 | '["yfinance"]' | '美债实际利率近5日走强+0.32%，对GOLD构成negative影响。' | '2026-08-06T00:34:58'
```

## Table: `market_outcomes`

- Columns: `symbol`, `date`, `price`, `change_pct`
- Row count: `385`
- First two rows:

```text
'300308.SZ' | '2026-07-08' | 1128.35 | 0.57
'300308.SZ' | '2026-07-09' | 1194.9 | 5.9
```

## Table: `prediction_events`

- Columns: `event_id`, `view_id`, `analyst`, `entity`, `entity_type`, `stance`, `horizon`, `claim`, `event_date`, `window_days`, `price_at_event`, `price_at_window`, `return_pct`, `status`, `skip_reason`
- Row count: `31320`
- First two rows:

```text
'pred_6ddd2d8cae9d2bd6_stock_300308.SZ_1' | '6ddd2d8cae9d2bd6' | '任泽平' | '300308.SZ' | 'stock' | 'bullish' | 'intraday' | '中长线：看多 🐂📈' | '2026-06-27' | 1 | 1253.89 | 1220.0 | -2.7028 | 'resolved' | None
'pred_6ddd2d8cae9d2bd6_stock_300308.SZ_3' | '6ddd2d8cae9d2bd6' | '任泽平' | '300308.SZ' | 'stock' | 'bullish' | 'intraday' | '中长线：看多 🐂📈' | '2026-06-27' | 3 | 1253.89 | 1223.17 | -2.45 | 'resolved' | None
```

## Table: `prediction_events_legacy`

- Columns: `event_id`, `view_id`, `analyst`, `entity`, `entity_type`, `stance`, `horizon`, `claim`, `event_date`, `window_days`, `price_at_event`, `price_at_window`, `return_pct`, `status`
- Row count: `16225`
- First two rows:

```text
'pred_6ddd2d8cae9d2bd6_1' | '6ddd2d8cae9d2bd6' | '任泽平' | '300308.SZ' | 'stock' | 'bullish' | 'intraday' | '中长线：看多 🐂📈' | '2026-06-27' | 1 | 1220.0 | 1270.0 | 4.0984 | 'resolved'
'pred_6ddd2d8cae9d2bd6_3' | '6ddd2d8cae9d2bd6' | '任泽平' | '300308.SZ' | 'stock' | 'bullish' | 'intraday' | '中长线：看多 🐂📈' | '2026-06-27' | 3 | 1220.0 | 1143.0 | -6.3115 | 'resolved'
```

## Table: `prediction_events_pilot`

- Columns: `event_id`, `view_id`, `analyst`, `entity`, `entity_type`, `stance`, `horizon`, `claim`, `event_date`, `window_days`, `price_at_event`, `price_at_window`, `return_pct`, `status`, `skip_reason`
- Row count: `4005`
- First two rows:

```text
'pred_a4a1fcddc2dfd5c3_sector_大盘_1' | 'a4a1fcddc2dfd5c3' | '任泽平' | '大盘' | 'sector' | 'bullish' | 'short' | '短线：看多 🐂📈' | '2026-07-06' | 1 | None | None | None | 'skipped' | 'sector_outcome_unsupported'
'pred_a4a1fcddc2dfd5c3_sector_大盘_3' | 'a4a1fcddc2dfd5c3' | '任泽平' | '大盘' | 'sector' | 'bullish' | 'short' | '短线：看多 🐂📈' | '2026-07-06' | 3 | None | None | None | 'skipped' | 'sector_outcome_unsupported'
```

## Table: `sector_backtest_results`

- Columns: `event_id`, `entity`, `stance`, `window_days`, `event_date`, `pool_size`, `coverage`, `p0`, `p1`, `return_pct`, `hit`, `status`
- Row count: `2360`
- First two rows:

```text
'pred_d67e7d6f949cd4d5_sector_大消费_1' | '大消费' | 'bullish' | 1 | '2026-06-01' | 3 | 2 | 40.6425 | 40.298500000000004 | -0.8464 | 0 | 'resolved'
'pred_d67e7d6f949cd4d5_sector_大消费_3' | '大消费' | 'bullish' | 3 | '2026-06-01' | 3 | 2 | 40.6425 | 39.5105 | -2.7853 | 0 | 'resolved'
```

## Table: `user_decision_evidence`

- Columns: `id`, `decision_id`, `evidence_type`, `evidence_id`, `title`, `content`, `source_ref`, `created_at`
- Row count: `6`
- First two rows:

```text
1 | 'dec_2026-08-06_GOLD_001' | 'note' | None | '飞书群聊决策记录' | None | 'qianboshi群 2026-08-06 00:44' | '2026-08-06T00:48:17'
2 | 'dec_2026-08-06_GOLD_001' | 'note' | None | '飞书群聊决策记录' | None | 'qianboshi群 2026-08-06 00:44' | '2026-08-06T00:49:22'
```

## Table: `user_decision_logs`

- Columns: `decision_id`, `user_id`, `asset_id`, `asset_name`, `asset_type`, `decision_date`, `horizon`, `direction`, `conviction`, `thesis`, `key_reasons`, `invalidation_conditions`, `action_note`, `asset_card_version`, `debate_card_id`, `market_snapshot`, `status`, `created_at`, `updated_at`
- Row count: `5`
- First two rows:

```text
'dec_2026-08-06_GOLD_001' | 'default' | 'GOLD' | '黄金' | 'commodity' | '2026-08-06' | 'medium' | 'bullish' | 0.7 | '黄金强相关于美元加息降息，8月已兑现9月加息趋势，该跌的已跌得差不多；预计再震荡一段时间后，9月开始往上走。' | '["8月已兑现9月加息预期，利空出尽", "美元加息周期末端，黄金压力释放", "该跌的已经跌得差不多"]' | '["9月未如期上涨反而继续下跌", "美元重新走强/加息超预期", "黄金跌破关键支撑位"]' | '加仓档位：涨投100元，大跌约10%投500元，小跌投200元。持仓000217华安黄金ETF联接C' | None | None | '{}' | 'open' | '2026-08-06T00:48:17' | '2026-08-06T00:49:22'
'dec_2026-08-06_INNOV_DRUG_001' | 'default' | 'INNOV_DRUG' | '创新药' | 'sector' | '2026-08-06' | 'medium' | 'bullish' | 0.6 | '医疗板块已阴跌很久，创新药被带下来只是简单带下来，未来有涨的趋势，想买港股创新药（需进一步分析）。' | '["医疗板块阴跌已久，估值压力释放", "被大盘带下来而非基本面恶化"]' | '["医疗板块继续创新低", "港股创新药基本面恶化"]' | '考虑港股创新药，待分析后再决定；当前持仓1100股创新药ETF 159992 成本0.8991' | None | None | '{}' | 'open' | '2026-08-06T00:49:22' | '2026-08-06T00:49:22'
```

## Structured JSONL

- JSONL: `E:\qianboshi-agent\data\views\structured_views.jsonl`

### First three raw records

```json
[
  {
    "analyst": "任泽平",
    "claim": "中长线：看多 🐂📈",
    "confidence": 0.83,
    "date": "2026-06-27",
    "entities": {
      "etfs": [
        "159813.SZ"
      ],
      "sectors": [
        "半导体",
        "算力"
      ],
      "stocks": [
        "300308.SZ",
        "300502.SZ",
        "688981.SS"
      ],
      "themes": [
        "先进制程",
        "国产替代",
        "设备材料"
      ],
      "us_mapping": [
        "AMD",
        "AVGO",
        "MRVL",
        "NVDA"
      ]
    },
    "evidence": "中长线：看多 🐂📈 逻辑：主播认为AI科技的基本面和景气度都很强，电子行业利润增速非常高，AI相关的二级、三级公司业绩也“更炸裂”。他还反复强调“AI不是风口是海啸”“科技牛继续”，并把未来一到三年的机会直接定义为“下一个光、下一个英伟达”式的成长机会。 (00:15:17-00:15:20) 电子行业的利润啊 就在人工智能和新年半导体你们猜猜 (00:15:17-00:15:20) 电子行业的利润 供现在整个全国工业规模起 一家利润的43% (00:17:23-00:17:26) 还有今天公布了国家腾局 公布了一些数据 (00:42:52-00:42:58) 科技牛继续 调整式机会千金的安排牛继续投",
    "horizon": "intraday",
    "logic": "主播认为AI科技的基本面和景气度都很强，电子行业利润增速非常高，AI相关的二级、三级公司业绩也“更炸裂”。他还反复强调“AI不是风口是海啸”“科技牛继续”，并把未来一到三年的机会直接定义为“下一个光、下一个英伟达”式的成长机会。",
    "quality_flags": [
      "has_date",
      "has_evidence",
      "has_logic",
      "has_stance",
      "has_horizon"
    ],
    "risk": "",
    "section": "科技牛 / AI科技 / 算力 / 半导体",
    "source_bv": "BV1Zz7W6yEHo",
    "source_file": "任泽平 2026.06.27 BV1Zz7W6yEHo.md",
    "source_path": "E:\\obsidian-vault\\学习\\钱博士\\任泽平 2026.06.27 BV1Zz7W6yEHo.md",
    "source_type": "livestream",
    "stance": "bullish",
    "timestamp": "00:15:17-00:15:20",
    "version": 1,
    "view_id": "6ddd2d8cae9d2bd6",
    "view_type": "sector"
  },
  {
    "analyst": "任泽平",
    "claim": "涉及资产：电子行业、AI相关公司、算力、半导体、光模块、芯片",
    "confidence": 0.67,
    "date": "2026-06-27",
    "entities": {
      "etfs": [
        "159813.SZ"
      ],
      "sectors": [
        "光模块",
        "半导体",
        "存储",
        "算力"
      ],
      "stocks": [
        "300308.SZ",
        "300394.SZ",
        "300502.SZ",
        "688981.SS"
      ],
      "themes": [
        "先进制程",
        "北美云厂商资本开支",
        "国产替代",
        "海外算力",
        "涨价周期",
        "英伟达产业链",
        "设备扩产",
        "设备材料"
      ],
      "us_mapping": [
        "AMD",
        "AVGO",
        "MRVL",
        "MU",
        "NVDA",
        "WDC"
      ]
    },
    "evidence": "涉及资产：电子行业、AI相关公司、算力、半导体、光模块、芯片 影响与结果：主播引用工业利润数据和海外龙头业绩，认为这些方向的盈利爆发已经出现 逻辑：利润高增 + 需求强 + 产业链短缺/扩产持续 依据类型：事实数据 / 逻辑推演 (00:15:17-00:15:20) 今年1到5月份，电子行业利润增长了104% (00:17:23-00:17:26) 美光公布的业绩啊 统比暴增三倍以上 然后还比暴增70%以上",
    "horizon": "unknown",
    "logic": "利润高增 + 需求强 + 产业链短缺/扩产持续",
    "quality_flags": [
      "has_date",
      "has_evidence",
      "has_logic"
    ],
    "risk": "",
    "section": "科技牛 / AI科技 / 算力 / 半导体",
    "source_bv": "BV1Zz7W6yEHo",
    "source_file": "任泽平 2026.06.27 BV1Zz7W6yEHo.md",
    "source_path": "E:\\obsidian-vault\\学习\\钱博士\\任泽平 2026.06.27 BV1Zz7W6yEHo.md",
    "source_type": "livestream",
    "stance": "neutral",
    "timestamp": "00:15:17-00:15:20",
    "version": 1,
    "view_id": "24fbbda1acb3a624",
    "view_type": "sector"
  },
  {
    "analyst": "任泽平",
    "claim": "涉及资产：美光",
    "confidence": 0.67,
    "date": "2026-06-27",
    "entities": {
      "etfs": [
        "159813.SZ"
      ],
      "sectors": [
        "半导体",
        "存储",
        "算力"
      ],
      "stocks": [
        "300308.SZ",
        "300502.SZ",
        "688981.SS"
      ],
      "themes": [
        "先进制程",
        "国产替代",
        "涨价周期",
        "设备扩产",
        "设备材料"
      ],
      "us_mapping": [
        "AMD",
        "AVGO",
        "MRVL",
        "MU",
        "NVDA",
        "WDC"
      ]
    },
    "evidence": "涉及资产：美光 影响与结果：主播说其业绩同比暴增三倍以上、环比增长70%以上，毛利率到85% 逻辑：用来证明AI/存储需求强、行业供需紧张 依据类型：事实数据 (00:17:23-00:17:26) 美光公布的业绩啊 统比暴增三倍以上 然后还比暴增70%以上 (00:17:23-00:17:26) 美光的毛利率85%已经超过因为了",
    "horizon": "unknown",
    "logic": "用来证明AI/存储需求强、行业供需紧张",
    "quality_flags": [
      "has_date",
      "has_evidence",
      "has_logic"
    ],
    "risk": "",
    "section": "科技牛 / AI科技 / 算力 / 半导体",
    "source_bv": "BV1Zz7W6yEHo",
    "source_file": "任泽平 2026.06.27 BV1Zz7W6yEHo.md",
    "source_path": "E:\\obsidian-vault\\学习\\钱博士\\任泽平 2026.06.27 BV1Zz7W6yEHo.md",
    "source_type": "livestream",
    "stance": "neutral",
    "timestamp": "00:17:23-00:17:26",
    "version": 1,
    "view_id": "c6fc80547caaba7f",
    "view_type": "sector"
  }
]
```

### Top-level fields

- `analyst`
- `claim`
- `confidence`
- `date`
- `entities`
- `evidence`
- `horizon`
- `logic`
- `quality_flags`
- `risk`
- `section`
- `source_bv`
- `source_file`
- `source_path`
- `source_type`
- `stance`
- `timestamp`
- `version`
- `view_id`
- `view_type`

