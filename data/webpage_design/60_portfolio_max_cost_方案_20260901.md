# 60_portfolio_max_cost规则实现_方案_20260901.md

> 生成：老手（自审完成）| 日期：2026-09-01 | 上游：59 号交接队列第 1 项 + 47 号方案遗留登记
> 状态：**待用户拍板** → 执行 → 验证

---

## 一、目标

实现纪律检查第 4 层：**组合持仓总成本上限**（portfolio_max_cost，配置已存在 10000）。
当前持仓成本 > 上限 → 触发违规提醒。纯增量，不触碰 #17v2 定稿 schema。

## 二、现状（自审确认）

- config/discipline_rules.json：`portfolio_max_cost: 10000` 已配置（v1 遗留）
- discipline_checker.py：仅 15 行遗留登记注释，规则未实现
- 当前持仓成本 500 << 10000（真实数据不触发，测试用合成数据）
- 影响面：仅 discipline_checker.py + 测试；decision_desk/agent/模板自动继承（discipline 段输出 violations 即带出新违规），**无需改其他文件**

## 三、方案

### A. discipline_checker.py 加第 4 层（check_discipline 内）
```python
# 4. 组合持仓总成本上限（portfolio_max_cost）
pmc = rules.get("portfolio_max_cost")
if pmc and float(pmc) > 0 and current_open_cost > float(pmc):
    violations.append({
        "type": "portfolio_max_cost",
        "current": round(current_open_cost, 2),
        "max": float(pmc),
        "message": f"组合持仓总成本 {current_open_cost:.2f} 超上限 {pmc:.2f}，需人工确认",
    })
```
- 边界：`>` 不触发相等（与 theme_cap 一致）；配置缺失/0 → 跳过
- **不扩展 schema**（#17v2 gpt 定稿 schema 保持；违规只进 violations 列表，含 current/max 字段）
- 遗留注释更新（移除"未实现"，改 P2：position ledger）

### B. 测试（test_discipline_17v2.py 追加 4 项）
1. 真实数据不触发（500 < 10000）
2. 合成超限（15000 > 10000）→ 触发 portfolio_max_cost
3. 边界相等（10000 == 10000）→ 不触发
4. 配置缺失/0 → 跳过不崩

### C. 影响面与回滚
- 改 1 文件 + 1 测试文件；git 独立提交可 revert
- 决策台/简报自动继承（discipline 段 violations 含新类型；模板契约"只陈述违规类型/比例/上限/需人工确认"已覆盖）

## 四、验证清单（交付门）

```bash
# 1. 新测试（期望 4 passed 追加）
C:/Python314/python.exe -m pytest tests/test_discipline_17v2.py -q
# 2. 全量回归（期望 72 passed）
C:/Python314/python.exe -m pytest tests/ -q
# 3. 真实数据实跑（期望无 portfolio_max_cost 违规，其余照常）
C:/Python314/python.exe scripts/discipline_checker.py --json
# 4. 决策台注入不回归（discipline 段正常）
C:/Python314/python.exe -c "import sys; sys.path.insert(0,'scripts'); from decision_desk import build_decision_desk_context; d=build_decision_desk_context(); print(d['discipline']['ok'], d['discipline']['net_invested'])"
```
