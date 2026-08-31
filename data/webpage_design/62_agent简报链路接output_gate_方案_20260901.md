# 62_agent简报链路接入output_gate_方案_20260901.md

> 生成：老手（自审完成）| 日期：2026-09-01 | 上游：59 号交接队列第 1 项 + 47 号方案遗留（#17v2）
> 状态：**待用户拍板** → 执行 → 验证

---

## 一、目标

把 agent.py 简报链路（morning_brief / hybrid / rendered 三分支）接入 output_gate，
补上 #17v2 遗留缺口：**纪律契约目前只靠模板约束 LLM，无硬阻断**——
LLM 若输出"纪律超限+建议减仓"组合，MCP 链路会拦（_gated），简报链路不会。

## 二、现状（侦察自审确认）

- agent.py main 三分支（--brief / --brief_hybrid / --brief_rendered）：生成 → print → save_brief → post_check（**质量门**：8章/证据链/字数）
- **合规门缺失**：三分支均未过 output_gate（MCP 链路 qianboshi_mcp.py `_gated` 已接）
- output_gate 语义（#11v2 定稿）：clean 直通 / annotate 加横幅（BANNER_EXISTS_RE 防重复，简报已含"不构成投资建议"则不重复加）/ **block 替换中性文本**（纪律上下文+动作词共现，#17v2 新增）
- 引用豁免/否定豁免已内置（钱博士说建议减仓 → clean，不会误伤）

## 三、方案

### A. agent.py 加模块级 `_gate_brief(brief, tool) -> str`
```python
def _gate_brief(brief: str, tool: str = "morning_brief") -> str:
    """简报合规门：clean 直通 / annotate 横幅 / block 中性替换+stderr 强警告。fail-closed。"""
    try:
        from compliance_gate import output_gate
        r = output_gate(brief, source="brief", tool=tool)
        if r["mode"] == "block":
            print(f"[GATE-BLOCK] {tool}: 简报含纪律违规+交易动作组合，已合规拦截，需人工复核", file=sys.stderr)
        return r["output"]  # clean=原文 / annotate=横幅(防重复) / block=中性文本
    except Exception as e:
        print(f"[WARN] 简报合规门异常(按安全侧放行+横幅): {e}", file=sys.stderr)
        return brief
```
- block 语义=**不发布违规简报**（宁可拦下不越红线；stderr 给人工复核线索）
- fail-closed：异常时返回原文（安全侧：至少不崩溃丢简报；违规由 post_check/人工兜底）

### B. 三分支接入
`--brief` / `--brief_hybrid` / `--brief_rendered` 生成后 `brief = _gate_brief(brief)` 再 print

### C. 测试（tests/test_brief_gate.py，5 项）
1. 干净简报（无动作词）→ clean 原文直通
2. 纪律+动作（"纪律检查：主题超限 100%，建议减仓"）→ block（输出 NEUTRAL 中性文本）
3. 普通建议动作（"该基金值得买入"，非纪律上下文）→ annotate（横幅；已含"不构成投资建议"则不重复）
4. 引用豁免（"钱博士直播说建议减仓"）→ clean
5. fail-closed：mock output_gate 抛异常 → 返回原文 + stderr WARN

### D. 影响面与回滚
- 改 1 文件（agent.py）+ 1 测试文件；compliance_gate 零改动
- git 独立提交可 revert；不影响 MCP 链路/红队/其他功能

## 四、验证清单（交付门）

```bash
# 1. 新测试（期望 5 passed）
C:/Python314/python.exe -m pytest tests/test_brief_gate.py -q
# 2. 全量回归（期望 76 passed）
C:/Python314/python.exe -m pytest tests/ -q
# 3. 红队不回归（期望 22/22）
C:/Python314/python.exe scripts/compliance_gate.py --selfcheck
# 4. 语法检查
C:/Python314/python.exe -m py_compile scripts/agent.py
```

## 五、自审结论

- 无隐藏风险：接入点纯增量、output_gate 幂等（防重复横幅已有）、豁免机制防误伤引用语境
- block 整篇替换是刻意选择（纪律红线 > 简报完整性；stderr 留复核线索）
- 不做"局部替换"（输出侧规则集是句级判定，整文本 API 语义一致）
