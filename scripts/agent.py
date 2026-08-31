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
from decision_desk import build_decision_desk_context


# ─── System Prompt ────────────────────────────────────────

SYSTEM_PROMPT = """你是多分析师投资研究助手，知识库覆盖保留名单内财经主播的公开观点（钱博士直播、钱博士短视频、李一恩、旗帜鲜明、任泽平、投机大拿、柏年说、财联社、笨笨的韭菜、史诗级韭菜、趋势天哥），时间跨度以知识库检索结果为准（最新：李一恩7.20、投机大拿7.20、旗帜鲜明7.20、钱博士7.19直播、笨笨的韭菜7.20）。

## 你的能力
- 检索知识库，获取多位分析师对同一板块/标的的观点
- 查询实时行情（A股/美股/指数）
- 查看持仓盈亏、扫描标的池异动
- 记录买卖交易
- 调用 **get_latest_digest** 获取结构化最近观点总览
- 调用 **query_views** 按实体/日期/分析师硬过滤结构化观点
- 必要时才调用 **query_rag** 补充原文证据；普通RAG不再决定今日主观点

## 核心原则
1. **不推荐买卖** — 整理观点+数据，不做买卖建议
2. **来源标注** — 每条观点标注分析师名+日期："（李一恩 7.8上午场）"
3. **多角度对照** — 同一板块，列出不同分析师的观点，标注一致/分歧
4. **数据说话** — 有实时数据就用数据
5. **风险提示** — 每次涉及判断附风险提示

## 分析师保留名单与特征速查
- **钱博士/钱博士直播/钱博士短视频**: 板块确定性排序(创新药>机器人>光模块>存储>AI应用), 逃顶信号体系, 周期股心法
- **李一恩**: 覆盖面广, 技术面+基本面结合
- **旗帜鲜明**: 观点鲜明直接, 擅长抓核心矛盾
- **任泽平**: 宏观视角, 政策解读强
- **投机大拿**: 短线交易视角, 题材热点敏感
- **柏年说**: 中长期价值视角
- **财联社**: 资讯汇总, 新闻驱动
- **笨笨的韭菜**: 交易情绪和盘面观察
- **史诗级韭菜**: 交易复盘和个股观察
- **趋势天哥**: 趋势跟踪和板块轮动

## 禁用来源（不得引用、不得进入分歧对照）
主力行为学、汤山老王、马跑跑、邻居大爷、八叔不啰嗦。即使RAG返回这些来源，也必须忽略。

## 回复格式
- 先给综合判断（共识/分歧）
- 再列各分析师观点（标注来源+日期）
- 有行情数据对比时优先用数据
- 最后附风险提示

## 注意：数据源独立
- **行情数据(get_market_indexes)和知识库(query_rag)是两套独立系统**
- 行情限流（非交易时段常见）**不影响**知识库检索
- query_rag返回空结果才说明知识库有问题，行情拿不到数据时照常检索知识库

## 关键：优先使用结构化最近观点
- 盘前简报和“现在怎么看”类问题，必须先用 **get_latest_digest** 获取最近观点总览，再对重点实体调用 **query_views**
- query_views 返回的 view_id/source_file/date/analyst/evidence 是观点证据链，进入简报的关键判断必须能回溯这些字段
- **query_rag 只作为原文证据补充器**，不得让普通 chunk RAG 决定今日主观点
- 标注观点时**必须带上具体日期**（如"钱博士 7.19直播"、"李一恩 7.20直播"），不要笼统说"近期"、"最新"，也不要只写"直播/短视频"但不写日期
- A股非交易时段的缓存价格只能称为"昨收/缓存价"，不得写成"涨跌幅0%"
- 如果某板块只有较旧的观点（如6月），则标注旧日期并补充说明时效性"""



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
        max_rounds = 8
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
        """调用 LLM API（兼容 OpenAI 格式）。analysis 模型时 sol 优先（2026-08-27 指令：仅可用 flash/sol，禁 pro）"""
        import requests

        # analysis 模型先试 premium(gpt-5.6-sol)，失败/截断 fallback 本模型(flash)
        if model == self.llm["analysis_model"]:
            try:
                from llm_fallback import call_premium

                premium_resp = call_premium(
                    self.llm, messages, tools, temperature=temperature, timeout=150
                )
                if premium_resp is not None:
                    return premium_resp
                print("⚡ premium(gpt-5.6-sol) 不可用/截断，fallback flash", file=sys.stderr)
            except Exception:
                pass

        headers = {
            "Authorization": f"Bearer {self.llm['api_key']}",
            "Content-Type": "application/json",
        }

        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.llm["max_tokens"],
            "thinking": {"type": "disabled"},  # deepseek-v4-flash 推理模型必须关思考，否则 reasoning 吃光 max_tokens 输出截断（2026-08-05 血泪坑）
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

        # 判断当前交易时段
        now = datetime.now()
        weekday = now.weekday()
        h = now.hour
        a_open = weekday < 5 and ((h == 9 and now.minute >= 30) or (10 <= h < 15))
        us_open = weekday < 5 and (h >= 21 or h < 4)

        # 采集数据
        print("📊 采集数据...", file=sys.stderr)

        indexes = {"indexes": {}, "note": "未获取"}
        pool = {"alerts": [], "message": "未获取"}
        portfolio = {"holdings": [], "message": "未获取"}

        # 先读缓存保底
        try:
            import importlib
            mc = importlib.import_module('market_cache')
            cache = mc.get_cached_prices()
            cache_str = json.dumps(cache, ensure_ascii=False, indent=2)[:3000] if cache else "无"
        except Exception:
            cache = {}
            cache_str = "无"

        if a_open or us_open:
            try:
                indexes = self.tools.call("get_market_indexes")
            except Exception:
                indexes = {"indexes": {}, "error": "行情获取失败", "cache_size": len(cache)}

            # 持仓：无论A股是否开盘都拉（美股时段也生成日报，持仓不能缺）
            try:
                portfolio = self.tools.call("get_portfolio")
            except Exception:
                portfolio = {"holdings": [], "error": "持仓获取失败"}

            if a_open:
                try:
                    pool = self.tools.call("scan_tracking_pool")
                except Exception:
                    pool = {"alerts": [], "error": "标的池获取失败"}
        else:
            # 非交易时段：静态读取持仓和标的池（不依赖实时行情接口）
            try:
                pf_path = Path(__file__).resolve().parent.parent / "data" / "portfolio.json"
                if pf_path.exists():
                    pf = json.loads(pf_path.read_text(encoding="utf-8"))
                    holdings = pf.get("holdings", {})
                    try:
                        from tool_registry import _estimate_offshore_nav
                    except Exception:
                        _estimate_offshore_nav = None
                    portfolio_holdings = []
                    for code, info in holdings.items():
                        item = {
                            "code": code,
                            "shares": info.get("shares"),
                            "avg_cost": info.get("avg_cost"),
                            "name": info.get("name", code),
                            "sector": info.get("sector", ""),
                            "market_code": info.get("market_code", ""),  # 场外基金→场内对应代码
                        }
                        # 场外基金：用场内涨跌幅推算最新净值，LLM 拿推算结果避免混算
                        if info.get("market_code") and info.get("nav_date") and _estimate_offshore_nav:
                            est = _estimate_offshore_nav(code, info)
                            if est:
                                item["est_nav"] = est["nav"]
                                item["est_nav_note"] = f"净值推算(场内{info['market_code']}累计{est['cum_pct']:+.2f}%)"
                        portfolio_holdings.append(item)
                    portfolio = {
                        "holdings": portfolio_holdings,
                        "message": "非交易时段静态读取，价格为缓存/成本价",
                        "total_cost": pf.get("total_cost"),
                    }
                else:
                    portfolio = {"holdings": [], "message": "portfolio.json 不存在"}
            except Exception as e:
                portfolio = {"holdings": [], "error": f"静态持仓读取失败: {e}"}
            try:
                tp_path = Path(__file__).resolve().parent.parent / "data" / "tracking_pool.json"
                if tp_path.exists():
                    tp = json.loads(tp_path.read_text(encoding="utf-8"))
                    pool = {
                        "alerts": [],
                        "message": "非交易时段，无实时异动",
                        "stocks": tp.get("stocks", []),
                        "etfs": tp.get("etfs", []),
                    }
                else:
                    pool = {"alerts": [], "message": "tracking_pool.json 不存在"}
            except Exception as e:
                pool = {"alerts": [], "error": f"静态标的池读取失败: {e}"}

        session_note = "A股交易时段" if a_open else ("美股交易时段" if us_open else "非交易时段")

        # 读取上一期简报，提取近期提及的标的
        brief_parser = importlib.import_module('brief_parser')
        recent_stocks = brief_parser.extract_from_brief()
        recent_stocks_str = ", ".join(sorted(recent_stocks)[:20]) if recent_stocks else "暂无"

        # 从缓存提取简报提及标的的行情
        tracked_prices = {}
        for sym in recent_stocks:
            if sym in cache:
                tracked_prices[sym] = dict(cache[sym])
        # 再加默认重要标的
        for sym in ['^DJI', '^IXIC', '^GSPC', 'NVDA', 'AMD', '159992.SZ', '300502.SZ']:
            if sym in cache and sym not in tracked_prices:
                tracked_prices[sym] = dict(cache[sym])
        # A股标的用 price_trends 补最新价（cache 可能停更，price_trends 有到最近交易日的数据）
        try:
            import json as _json
            _trend_path = Path(__file__).resolve().parent.parent / "data" / "price_trends.json"
            if _trend_path.exists():
                trends = _json.loads(_trend_path.read_text(encoding="utf-8"))
                for sym in list(tracked_prices.keys()):
                    if not (sym.endswith(".SS") or sym.endswith(".SZ")):
                        continue  # 美股保持 cache（实时收盘）
                    entry = trends.get(sym) or {}
                    if not entry:
                        continue
                    dates = sorted(entry.keys())
                    if not dates:
                        continue
                    last = entry[dates[-1]]
                    price = last.get("price")
                    if price is None:
                        continue
                    # 用 price_trends 重建 10 日价格序列
                    recent_dates = dates[-10:]
                    prices = [entry[d].get("price") for d in recent_dates]
                    prices = [p for p in prices if isinstance(p, (int, float)) and p == p]
                    tracked_prices[sym]["price"] = price
                    tracked_prices[sym]["prices"] = prices
                    if last.get("change_pct") is not None:
                        tracked_prices[sym]["change_pct"] = last["change_pct"]
                    tracked_prices[sym]["note"] = f"A股价格更新至 {dates[-1]}（price_trends）"
        except Exception:
            pass  # price_trends 不可用不影响
        # A股缓存若只有一个价格点，只能视作昨收/缓存价，不是涨跌幅0%。
        for sym, info in tracked_prices.items():
            if isinstance(info, dict) and (sym.endswith(".SS") or sym.endswith(".SZ")) and len(info.get("prices", [])) < 2:
                info["change_pct"] = None
                info["change_str"] = "N/A（昨收/缓存价，未计算今日涨跌）"
                info["note"] = "A股昨收/缓存价，非今日涨跌0%"
        tracked_str = json.dumps(tracked_prices, ensure_ascii=False, indent=2)[:2500] if tracked_prices else "无数据"

        # 读取结构化最近观点 digest，作为简报主观点来源；RAG 只做证据补充。
        latest_digest = self.tools.call("get_latest_digest", days=30, limit=40)
        latest_digest_str = json.dumps(latest_digest, ensure_ascii=False, indent=2)[:6000]

        # 对重点板块做结构化观点硬过滤，减少普通 RAG 弱相关污染。
        focus_entities = ["大盘", "半导体", "光模块", "创新药", "机器人", "存储", "大金融", "大消费", "黄金有色"]
        structured_focus = {}
        for entity in focus_entities:
            try:
                structured_focus[entity] = self.tools.call("query_views", entity=entity, date_range="30d", limit=4)
            except Exception as e:
                structured_focus[entity] = {"error": str(e), "results": []}
        structured_focus_str = json.dumps(structured_focus, ensure_ascii=False, indent=2)[:9000]

        decision_desk = build_decision_desk_context()
        decision_user_decisions_str = json.dumps(decision_desk.get("user_decisions", decision_desk), ensure_ascii=False, indent=2)[:9000]
        decision_debate_cards_str = json.dumps(decision_desk.get("debate_cards", decision_desk), ensure_ascii=False, indent=2)[:9000]
        decision_factor_states_str = json.dumps(decision_desk.get("factor_states", decision_desk), ensure_ascii=False, indent=2)[:9000]
        # #17v2：纪律段小，全量注入不截断（gpt 意见 10：结构化裁剪保证 JSON 完整）
        discipline_data = decision_desk.get("discipline") if isinstance(decision_desk, dict) else {}
        if not isinstance(discipline_data, dict):
            discipline_data = {}
        decision_discipline_str = json.dumps(discipline_data, ensure_ascii=False, indent=2)

        fallback_prompt = """请基于以上数据，结合钱博士分析框架，生成一份盘前简报。
必须优先使用 **get_latest_digest/query_views** 已提供的结构化观点作为主观点；如仍需补原文，才调用 query_rag。包含：
1. 大势判断（美股/中国指数）
2. 持仓诊断
3. 标的池异动提醒
4. 今日关注（检索RAG获取钱博士最新观点，列出近期简报提及标的的趋势分析，引用缓存中的实时价格数据）
5. 风险提醒

硬性要求：
- 每条关键判断至少标注一组证据链：view_id + source_file + analyst + date；没有证据链的句子只能写成“待验证”。
- 不得引用禁用来源：主力行为学、汤山老王、马跑跑、邻居大爷、八叔不啰嗦。
- 每条分析师观点必须写具体日期；没有日期就不要引用。
- A股缓存价只写“昨收/缓存价/N/A”，不得写“涨跌幅0%”。
"""
        prompt_path = Path(__file__).resolve().parent.parent / "templates" / "daily_brief_prompt_v3.md"
        try:
            brief_prompt = prompt_path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[WARN] 读取日报模板失败，使用内嵌fallback: {prompt_path} ({e})", file=sys.stderr)
            brief_prompt = fallback_prompt

        # 组装上下文
        context = f"""## 当前时间
{datetime.now().strftime('%Y-%m-%d %H:%M')} ({session_note})

## 市场指数
{json.dumps(indexes, ensure_ascii=False, indent=2)}

## 标的池行情
{json.dumps(pool, ensure_ascii=False, indent=2)[:2000]}

## 持仓状态
{json.dumps(portfolio, ensure_ascii=False, indent=2)}

## 近期简报提及的标的（建议重点追踪）
{recent_stocks_str}

## 缓存的实时行情（含简报提及标的 + 重要指数/个股）
{tracked_str}

## 结构化最近观点 digest（主观点来源，优先级高于普通RAG）
{latest_digest_str}

## 重点板块 query_views 结果（带 view_id/source_file/date/evidence）
{structured_focus_str}

## 决策台：用户决策跟踪
{decision_user_decisions_str}

## 决策台：多空对照
{decision_debate_cards_str}

## 决策台：资产卡因素速览
{decision_factor_states_str}

## 决策台：组合纪律检查
{decision_discipline_str}

{brief_prompt}
"""

        return self.run(context, model="analysis")

    def morning_brief_json(self, days=30, per_entity=4):
        """结构化盘前简报 JSON：先确定性组装，再交给 renderer 输出 Markdown。"""
        import brief_renderer
        return brief_renderer.build_from_views(days=days, per_entity=per_entity)

    def morning_brief_rendered(self, days=30, per_entity=4):
        """稳定渲染版盘前简报，不走 LLM 自由 Markdown。"""
        import brief_renderer
        data = self.morning_brief_json(days=days, per_entity=per_entity)
        return brief_renderer.render_markdown(data)

    def morning_brief_hybrid(self, days=30, per_entity=4):
        """Hybrid 盘前简报：结构化证据链 + LLM 白名单润色。"""
        import brief_hybrid
        data = brief_hybrid.build_hybrid(days=days, per_entity=per_entity)
        return brief_hybrid.render_markdown(data)

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
                print(self.morning_brief_hybrid())
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
            result = agent.morning_brief_hybrid()
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
    parser.add_argument("--brief", action="store_true", help="生成盘前简报（LLM综合版）")
    parser.add_argument("--brief-rendered", action="store_true", help="生成盘前简报（结构化JSON→Markdown稳定渲染版）")
    parser.add_argument("--brief-hybrid", action="store_true", help="生成盘前简报（结构化证据链→LLM白名单润色→Markdown）")
    parser.add_argument("--brief-json", action="store_true", help="输出盘前简报结构化JSON")
    parser.add_argument("--advice", action="store_true", help="生成投资建议")
    parser.add_argument("--schedule", action="store_true", help="启动定时调度（后台运行）")
    parser.add_argument("--model", choices=["routine", "analysis", "auto"], default="auto")
    parser.add_argument("--config", help="指定 config.yaml 路径")
    parser.add_argument("--days", type=int, default=30, help="结构化观点回看天数（用于 --brief-json/--brief-rendered/--brief-hybrid）")
    parser.add_argument("--per-entity", type=int, default=4, help="每个板块引用观点数（用于 --brief-json/--brief-rendered/--brief-hybrid）")
    parser.add_argument("--no-stream", action="store_true", help="禁用流式输出")

    args = parser.parse_args()

    try:
        agent = QianboshiAgent(args.config)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    if args.schedule:
        run_schedule(agent)
    elif args.brief_json:
        data = agent.morning_brief_json(days=args.days, per_entity=args.per_entity)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.brief_rendered:
        brief = agent.morning_brief_rendered(days=args.days, per_entity=args.per_entity)
        print(brief)
        try:
            import importlib
            bp = importlib.import_module('brief_parser')
            bp.save_brief(brief)
            try:
                import post_check
                report = post_check.check_brief(brief, require_evidence=True)
                if report["has_errors"] or report["has_warnings"]:
                    print(post_check.format_report(report), file=sys.stderr)
            except Exception as e:
                print(f"[WARN] 简报质检失败: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] 简报保存失败: {e}", file=sys.stderr)
    elif args.brief_hybrid:
        brief = agent.morning_brief_hybrid(days=args.days, per_entity=args.per_entity)
        print(brief)
        try:
            import importlib
            bp = importlib.import_module('brief_parser')
            bp.save_brief(brief)
            try:
                import post_check
                report = post_check.check_brief(brief, require_evidence=True)
                if report["has_errors"] or report["has_warnings"]:
                    print(post_check.format_report(report), file=sys.stderr)
            except Exception as e:
                print(f"[WARN] 简报质检失败: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] 简报保存失败: {e}", file=sys.stderr)
    elif args.brief:
        brief = agent.morning_brief()
        print(brief)
        # 保存简报用于后续提取标的
        try:
            import importlib
            bp = importlib.import_module('brief_parser')
            bp.save_brief(brief)
            try:
                import post_check
                report = post_check.check_brief(brief, require_evidence=True)
                if report["has_errors"]:
                    print(post_check.format_report(report), file=sys.stderr)
            except Exception as e:
                print(f"[WARN] 简报质检失败: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] 简报保存失败: {e}", file=sys.stderr)
    elif args.advice:
        print(agent.investment_advice())
    elif args.task:
        print(agent.run(args.task, model=args.model))
    else:
        agent.interactive()


if __name__ == "__main__":
    main()
