# 34_task2文本证据标注_完成报告.md — 500条维度标注 + 指标4真实化

> 执行：老手 | 日期：2026-08-29
> 任务：task2 文本证据命中率真实化 + 维度增补（证据权威/推理类型/因果主线）
> 覆盖：最近1个月锚定观点（date≥2026-07-29）取最新 500 条，gpt-5.6-sol stream 标注

---

## 一、完成情况
- 已标注 **501 条**（进 view_evidence_annotation + claim 表），主导航 batch 5×100，耗时 ~123 分钟
- 期间修复：fluxionai **中文 mojibake bug**（iter_lines decode_unicode → ISO-8859-1 误解码，改手动 utf-8）

## 二、维度分布

### 证据权威（直播4档）
| 等级 | 数量 | 占比 | 含义 |
|---|---|---|---|
| A 直接原话 | 259 | 52% | quote 逐字来自分析师 |
| D 推断 | 154 | 31% | 非原话，解读/推断 |
| B 近距转述 | 48 | 10% | 概括保留关键 |
| C 二手概括 | 40 | 8% | 他处转述 |

### 推理类型
interpretation 205 / causal_claim 119 / fact 114 / forecast 51 / correlation 10 / hypothesis 2

### 因果主线 top
半导体36 · 大盘34 · 光模块31 · 算力30 · 黄金15 · 港股9 · 科技9 · PCB8 · 创新药8 · 通胀8

## 三、指标4（文本证据命中率）真实化
- **supported=True: 274/501 = 54.7%**（真正有原文支撑）
- 平均 match_quality: 0.52
- 之前的"22% 关键词粗查"已升级为**基于 gpt 原文语义判定的真实支撑率**——技术命中(22%)≠内容支撑(54.7%)，现在分得清"落进时间窗"和"原文真撑观点"
- **支持率低的原因**：31% 是 D(推断)类非原话，多因候选段无直接对应原文；此类标记 unsupported 进"待重标/人工"

## 四、claim 落库（维度进 claim）
- claim 表 **501 条**（evidence_authority / inference_type / topic / 三维confidence(证据/推理/预测) / support_level / materiality / lifecycle_status 全部落位）

## 五、当前证据链质量
```
anchored 可下钻   6,817 / 11,311 (60.3%)
task2 标注(维度)   501 条(最近1月的高价值子集)
真实证据支撑率     54.7% (supported 274/501)
下钻关联         48,593 (view_evidence_link)
```

## 六、下一步
1. 更新 recompute_metrics 指标4 = 真实支撑率（做完）
2. #6 reasoning_unit：让 gpt 设计"句子候选→语义归并"规则；适配 annotation 维度
3. 可铺开 task2 到全部 1400 条最近1月（当前 500 是子集），或全量 6817
4. 其余待办按蓝图（out_of_duration由LLM重标 / 8问框架 / 绝对估值calc / compliance gate）
