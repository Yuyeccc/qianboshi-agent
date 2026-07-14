#!/usr/bin/env python3
"""
钱博士Agent — 独立AI Agent核心

不依赖 Hermes，自己拿着 API key 调 DeepSeek，自己决定何时调用什么工具。

用法:
    python agent.py                    # 交互模式
    python agent.py "光模块怎么看"      # 单次查询
    python agent.py --brief            # 生成盘前简报
    python agent.py --advice           # 生成投资建议
    python agent.py --schedule         # 启动定时调度（后台运行）

架构:
    Agent.run(task)
      → 构建 system prompt（钱博士分析框架）
      → 调用 DeepSeek API（带工具列表）
      → 模型返回 tool_calls → Agent 执行工具 → 结果回传
      → 模型综合工具结果 → 生成最终回复
"""
import json
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

# 确保能找到同目录模块
sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_llm_config
from tool_registry import ToolRegistry


# ─── System Prompt ────────────────────────────────────────

SYSTEM_PROMPT = """你是多分析师投资研究助手，知识库覆盖10位财经主播的直播观点（钱博士、李一恩、旗帜鲜明、任泽平、投机大拿、柏年说、主力行为学、汤山老王、马跑跑、财联社），时间跨度2026年6-7月。

## 你的能力
- 检索知识库，获取多位分析师对同一板块/标的的观点
- 查询实时行情（A股/美股/指数）
- 查看持仓盈亏、扫描标的池异动
- 记录买卖交易

## 核心原则
1. **不推荐买卖** — 整理观点+数据，不做买卖建议
2. **来源标注** — 每条观点标注分析师名+日期："（李一恩 7.8上午场）"
3. **多角度对照** — 同一板块，列出不同分析师的观点，标注一致/分歧
4. **数据说话** — 有实时数据就用数据
5. **风险提示** — 每次涉及判断附风险提示

## 分析师特征速查
- **钱博士**: 板块确定性排序(创新药>机器人>光模块>存储>AI应用), 逃顶信号体系, 周期股心法
- **李一恩**: 产量最大(11篇), 覆盖面广, 技术面+基本面结合
- **旗帜鲜明**: 观点鲜明直接, 擅长抓核心矛盾
- **任泽平**: 宏观视角, 政策解读强
- **投机大拿**: 短线交易视角, 题材热点敏感
- **柏年说**: 中长期价值视角
- **主力行为学**: 资金流向分析
- **汤山老王**: 散户视角, 接地气
- **马跑跑**: 板块轮动分析
- **财联社**: 资讯汇总, 新闻驱动

## 回复格式
- 先给综合判断（共识/分歧）
- 再列各分析师观点（标注来源+日期）
- 有行情数据对比时优先用数据
- 最后附风险提示"""



# ─── Agent 核心 ────────────────────────────────────────────

class QianboshiAgent:
    """独立Agent。拿着API key自己调DeepSeek，自己决定用什么工具。"""

    def __init__(self, config_path=None):
        self.config = load_config(config_path)
        self.llm = get_llm_config(self.config)
        self.tools = ToolRegistry(self.config)

        if not self.llm["api_key"]:
            raise RuntimeError(
                "API key 未配置。请在 .env 文件中设置 DEEPSEEK_API_KEY=sk-xxx\n"
                "或设置环境变量 DEEPSEEK_API_KEY"
            )

    # ─── 推理 ──────────────────────────────────────────

    def run(self, task, model="auto", stream=True):
        """
        执行一个任务。Agent 自动决定使用哪些工具。

        参数:
            task: 用户问题，如 "光模块现在怎么看"
            model: "routine"(便宜) / "analysis"(高质量) / "auto"(自动选择)
            stream: 是否流式输出
        """
        if model == "auto":
            # 简单查询用 routine，分析/建议用 analysis
            is_analysis = any(kw in task for kw in ["分析", "建议", "简报", "策略", "怎么看", "还能不能"])
            model = "analysis" if is_analysis else "routine"

        model_name = self.llm["analysis_model"] if model == "analysis" else self.llm["routine_model"]
        temperature = self.llm["temperature_analysis"] if model == "analysis" else self.llm["temperature_routine"]

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]

        tool_schemas = self.tools.tool_schemas()

        # Agent 循环：模型可能多次调用工具
        max_rounds = 5
        for round_num in range(max_rounds):
            response = self._call_api(messages, tool_schemas, model_name, temperature)

            choice = response["choices"][0]
            msg = choice["message"]

            # 模型想调用工具
            if msg.get("tool_calls"):
                messages.append(msg)

                for tc in msg["tool_calls"]:
                    func_name = tc["function"]["name"]
                    func_args = json.loads(tc["function"]["arguments"])

                    print(f"  🔧 {func_name}({json.dumps(func_args, ensure_ascii=False)})", file=sys.stderr)

                    result = self.tools.call(func_name, **func_args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })

                continue  # 下一轮，模型看到工具结果后继续推理

            # 模型给出最终回复
            content = msg.get("content", "")
            if stream:
                return content
            else:
                return content

        return "推理超过最大轮数，请简化问题重试。"

    def _call_api(self, messages, tools, model, temperature):
        """调用 DeepSeek API（兼容 OpenAI 格式）"""
        import requests

        headers = {
            "Authorization": f"Bearer {self.llm['api_key']}",
            "Content-Type": "application/json",
        }

        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.llm["max_tokens"],
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        url = f"{self.llm['api_base']}/chat/completions"

        resp = requests.post(url, headers=headers, json=body, timeout=120)
        resp.raise_for_status()
        return resp.json()

    # ─── 预置任务 ──────────────────────────────────────

    def morning_brief(self):
        """盘前简报：美股收盘 + 标的池 + 持仓 + RAG观点"""
        print("=" * 50)
        print(f"  钱博士盘前简报 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 50)
        print()

        # 采集数据
        print("📊 采集数据...", file=sys.stderr)

        indexes = self.tools.call("get_market_indexes")
        pool = self.tools.call("scan_tracking_pool")
        portfolio = self.tools.call("get_portfolio")

        # 组装上下文
        context = f"""## 当前时间
{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 市场指数
{json.dumps(indexes, ensure_ascii=False, indent=2)}

## 标的池行情
{json.dumps(pool, ensure_ascii=False, indent=2)[:2000]}

## 持仓状态
{json.dumps(portfolio, ensure_ascii=False, indent=2)}

请基于以上数据，结合钱博士分析框架，生成一份盘前简报。包含：
1. 大势判断（美股+中国指数）
2. 持仓诊断
3. 标的池异动提醒
4. 今日关注（检索RAG获取钱博士最新观点）
5. 风险提醒
"""

        return self.run(context, model="analysis")

    def investment_advice(self):
        """生成投资建议（三层金字塔：数据→观点→建议）"""
        print("📊 生成投资建议...", file=sys.stderr)

        task = """请基于当前市场数据和钱博士知识库，生成一份投资建议。

先调用 get_market_indexes 获取指数数据，
再调用 scan_tracking_pool 扫描标的池，
再调用 get_portfolio 查看持仓，
然后调用 query_rag 检索钱博士对相关板块的最新观点。

最后综合所有数据，按以下结构输出：

## 市场状态
- 美股环境（利好/中性/利空）
- A股情绪（积极/谨慎/悲观）

## 板块分析
- 🥇 确定性最高（钱博士最看好的方向）
- 🥈 可以关注
- 🥉 等待信号
- ❌ 规避

## 持仓诊断
- 每只持仓：当前状态 + 钱博士观点对照

## 逃顶信号检查
- 逐个检查：放量滞涨 / 龙头破位 / 情绪过热 / 宏观转向

## 参考仓位
- 建议仓位比例 + 逻辑
"""

        return self.run(task, model="analysis")

    # ─── 交互模式 ──────────────────────────────────────

    def interactive(self):
        """交互式对话"""
        print("钱博士Agent — 独立版")
        print(f"模型: {self.llm['routine_model']}(日常) / {self.llm['analysis_model']}(分析)")
        print("输入 'quit' 退出, 'brief' 盘前简报, 'advice' 投资建议")
        print("-" * 50)

        while True:
            try:
                user_input = input("\n你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见")
                break

            if not user_input:
                continue
            if user_input.lower() == "quit":
                break
            if user_input.lower() == "brief":
                print(self.morning_brief())
                continue
            if user_input.lower() == "advice":
                print(self.investment_advice())
                continue

            print(f"\n钱博士: {self.run(user_input)}")


# ─── 调度器 ────────────────────────────────────────────────

def run_schedule(agent):
    """简易定时调度（不依赖 Hermes cron）"""
    import schedule as sched
    import threading

    def morning_job():
        print(f"\n⏰ [{datetime.now()}] 执行盘前简报...")
        try:
            result = agent.morning_brief()
            print(result)
            # TODO: 推送到飞书
        except Exception as e:
            print(f"❌ 简报失败: {e}")

    # 交易日 08:50
    sched.every().day.at("08:50").do(morning_job)

    print("🕐 调度器已启动（交易日 08:50 盘前简报）")
    print("   按 Ctrl+C 停止")

    # 简单的周末跳过（生产环境用完整交易日历）
    def run_loop():
        while True:
            now = datetime.now()
            if now.weekday() < 5:  # 周一到周五
                sched.run_pending()
            time.sleep(30)

    try:
        run_loop()
    except KeyboardInterrupt:
        print("\n调度器已停止")


# ─── CLI 入口 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="钱博士Agent — 独立AI助手")
    parser.add_argument("task", nargs="?", help='单次查询（如: 光模块怎么看）')
    parser.add_argument("--brief", action="store_true", help="生成盘前简报")
    parser.add_argument("--advice", action="store_true", help="生成投资建议")
    parser.add_argument("--schedule", action="store_true", help="启动定时调度（后台运行）")
    parser.add_argument("--model", choices=["routine", "analysis", "auto"], default="auto")
    parser.add_argument("--config", help="指定 config.yaml 路径")
    parser.add_argument("--no-stream", action="store_true", help="禁用流式输出")

    args = parser.parse_args()

    try:
        agent = QianboshiAgent(args.config)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    if args.schedule:
        run_schedule(agent)
    elif args.brief:
        print(agent.morning_brief())
    elif args.advice:
        print(agent.investment_advice())
    elif args.task:
        print(agent.run(args.task, model=args.model))
    else:
        agent.interactive()


if __name__ == "__main__":
    main()
