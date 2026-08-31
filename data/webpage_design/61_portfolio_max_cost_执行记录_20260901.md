# 61_portfolio_max_cost规则实现_执行记录_20260901.md

> 执行：老手 | 方案：60 号（自审通过，用户授权"你审核然后开始执行"）| 日期：2026-09-01
> 状态：✅ 完成（git b07e69d）

---

## 一、完成总览

| 模块 | 状态 | 关键产出 |
|---|---|---|
| 第 4 层规则 | ✅ | 组合持仓总成本上限：current_open_cost > portfolio_max_cost → 触发违规（type: portfolio_max_cost，含 current/max） |
| 边界处理 | ✅ | `>` 严格大于（相等不触发）；配置缺失/0/非法 → 跳过不崩 |
| schema | ✅ | 不扩展 #17v2 定稿 schema（违规只进 violations 列表） |
| 测试 | ✅ | +4 项（真实不触发/超限触发/边界相等/配置异常跳过）；test_discipline_17v2 20 passed |
| 全量回归 | ✅ | 76 passed |
| 实跑验证 | ✅ | 真实数据 violations 仅 theme_cap/single_cap（500<10000 不触发）；net=371.09 profit 不变 |
| 决策台注入 | ✅ | discipline 段正常（自动继承新规则，无需改 decision_desk/agent/模板） |
| git | ✅ | b07e69d（2 文件可 revert） |

## 二、规则实现（check_discipline 第 4 层）

```python
pmc = rules.get("portfolio_max_cost")
if pmc is not None:
    try:
        pmc_f = float(pmc)
    except (TypeError, ValueError):
        pmc_f = 0.0
    if pmc_f > 0 and current_open_cost > pmc_f:
        violations.append({
            "type": "portfolio_max_cost",
            "current": round(current_open_cost, 2),
            "max": pmc_f,
            "message": f"组合持仓总成本 {current_open_cost:.2f} 超上限 {pmc_f:.2f}，需人工确认",
        })
```

## 三、坑记录（本刀 1 条）

| 坑 | 现象 → 修复 |
|---|---|
| 测试配置缺失 | test_14 期望触发但模块级 RULES 常量无 portfolio_max_cost → 规则跳过 → 在 RULES 补 10000（其他测试不受影响） |

## 四、遗留登记

- agent 简报链路接入 output_gate / brief_post_check（下一候选）
- 阈值校准（0.70/0.50 与分层命中率交叉验证）
- 8 月 error 事件行情补拉 → #14v2 复跑对照
- position ledger（P2）

## 五、回滚

`git revert b07e69d` 即还原（只 2 文件）。
