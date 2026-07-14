#!/usr/bin/env python3
"""
钱博士Agent — 工具注册表

把 query_rag / tracking / portfolio 包装为统一接口的工具。
Agent 通过 ToolRegistry 发现和调用工具，不直接跑 shell 命令。
"""
import json
import sys
import time
from pathlib import Path

# 确保能找到同目录的 config_loader
sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_data_dir, get_vector_db_path, get_obsidian_path, get_proxy


class ToolRegistry:
    """管理所有可用工具，提供 LLM function-calling 兼容的 schema。"""

    def __init__(self, config=None):
        self.config = config or load_config()
        self._tools = {}
        self._register_builtins()

    # ─── 注册 ─────────────────────────────────────────────

    def _register_builtins(self):
        """注册所有内置工具"""
        self._tools = {
            "query_rag": {
                "name": "query_rag",
                "description": (
                    "检索钱博士知识库，获取钱博士对板块/个股/ETF的历史观点。"
                    "当需要了解钱博士怎么看某标的时使用。"
                    "不用于查实时行情、不用于查持仓盈亏。"
                ),
                "parameters": {
                    "query": {
                        "type": "string",
                        "required": True,
                        "description": "查询关键词，如'光模块 反弹'、'创新药 估值'",
                    },
                    "top_k": {
                        "type": "integer",
                        "required": False,
                        "default": 5,
                        "description": "返回结果条数，3-10",
                    },
                    "show_weights": {
                        "type": "boolean",
                        "required": False,
                        "default": False,
                        "description": "是否显示加权分数明细",
                    },
                },
                "call": self._query_rag,
            },
            "get_portfolio": {
                "name": "get_portfolio",
                "description": (
                    "查询当前持仓、成本和盈亏。"
                    "拉取实时行情计算浮动盈亏。"
                    "当用户问'持仓'、'盈亏'、'赚了多少'时使用。"
                ),
                "parameters": {},
                "call": self._get_portfolio,
            },
            "scan_tracking_pool": {
                "name": "scan_tracking_pool",
                "description": (
                    "扫描标的池行情——返回跟踪的个股/ETF/A股指数的涨跌幅和量比。"
                    "检测异动（涨跌幅>4%或量比>1.5x）。"
                    "当需要了解钱博士提过的标的表现时使用。"
                ),
                "parameters": {
                    "pool": {
                        "type": "string",
                        "required": False,
                        "default": "all",
                        "description": "扫描范围: all(全部) / stocks(A股) / us(美股) / indexes(指数)",
                    },
                },
                "call": self._scan_tracking,
            },
            "get_market_indexes": {
                "name": "get_market_indexes",
                "description": (
                    "拉取A股三大指数(上证/深证/创业板)和美股三大指数(道指/纳指/标普)的实时行情。"
                    "用于盘前简报、大势判断。"
                ),
                "parameters": {},
                "call": self._get_market_indexes,
            },
            "record_trade": {
                "name": "record_trade",
                "description": (
                    "记录一笔买卖交易。持仓自动更新。"
                    "当用户说'买了XX''卖了XX'时使用。"
                ),
                "parameters": {
                    "code": {
                        "type": "string",
                        "required": True,
                        "description": "股票/ETF代码，如 159992、300502",
                    },
                    "type": {
                        "type": "string",
                        "required": True,
                        "enum": ["buy", "sell"],
                        "description": "买或卖",
                    },
                    "amount": {
                        "type": "integer",
                        "required": True,
                        "description": "数量（股/份）",
                    },
                    "price": {
                        "type": "number",
                        "required": False,
                        "description": "成交价。不填则自动拉取最新价",
                    },
                    "name": {
                        "type": "string",
                        "required": False,
                        "description": "标的名称，如'创新药ETF'",
                    },
                },
                "call": self._record_trade,
            },
        }

    # ─── LLM 接口 ─────────────────────────────────────────

    def tool_schemas(self):
        """返回 OpenAI function-calling 格式的工具列表"""
        schemas = []
        for name, t in self._tools.items():
            props = {}
            required = []
            for pname, pinfo in t.get("parameters", {}).items():
                prop = {"type": pinfo["type"], "description": pinfo["description"]}
                if "enum" in pinfo:
                    prop["enum"] = pinfo["enum"]
                if "default" in pinfo:
                    prop["default"] = pinfo["default"]
                props[pname] = prop
                if pinfo.get("required"):
                    required.append(pname)

            schema = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": t["description"],
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            }
            schemas.append(schema)
        return schemas

    def call(self, tool_name, **kwargs):
        """调用工具，返回 JSON 可序列化的结果"""
        if tool_name not in self._tools:
            return {"error": f"未知工具: {tool_name}", "available": list(self._tools.keys())}
        try:
            return self._tools[tool_name]["call"](**kwargs)
        except Exception as e:
            return {"error": f"工具调用失败: {e}", "tool": tool_name}

    # ─── 工具实现 ─────────────────────────────────────────

    def _query_rag(self, query, top_k=5, show_weights=False):
        """检索钱博士知识库"""
        from query_rag import QianboshiRAG

        rag = QianboshiRAG(config=self.config)
        raw = rag.query(query, top_k=top_k)

        results = []
        for r in raw:
            item = {
                "source": r.get("source", "未知"),
                "content": r.get("content", "")[:800],  # 截断长文本
                "score": round(r.get("score", 0), 4),
                "doc_type": r.get("type", "unknown"),
            }
            if show_weights and "weights" in r:
                item["weights"] = r["weights"]
            results.append(item)

        return {
            "query": query,
            "total_hits": len(results),
            "results": results,
            "summary": f"在{len(results)}条结果中找到相关观点" if results else "未找到相关观点",
        }

    def _get_portfolio(self):
        """查询持仓 + 拉实时行情算盈亏"""
        try:
            import yfinance as yf
        except ImportError:
            return {"error": "yfinance 未安装", "holdings": [], "total_value": 0, "total_pnl": 0}

        data_dir = get_data_dir(self.config)
        pf_path = data_dir / "portfolio.json"

        if not pf_path.exists():
            return {"holdings": [], "total_value": 0, "total_pnl": 0, "message": "暂无持仓"}

        pf = json.loads(pf_path.read_text(encoding="utf-8"))
        holdings = pf.get("holdings", {})
        if not holdings:
            return {"holdings": [], "total_value": 0, "total_pnl": 0, "message": "暂无持仓"}

        proxy = get_proxy(self.config)
        results = []
        total_value = 0
        total_cost = 0

        for code, h in holdings.items():
            try:
                t = yf.Ticker(code)
                hist = t.history(period="1d")
                if hist.empty:
                    results.append({"code": code, "name": h.get("name", ""), "error": "无法获取行情"})
                    continue
                price = float(hist["Close"].iloc[-1])
                shares = h.get("shares", 0)
                cost = h.get("avg_cost", 0)
                market_value = round(price * shares, 2)
                cost_value = round(cost * shares, 2)
                pnl = round(market_value - cost_value, 2)
                pnl_pct = round((pnl / cost_value * 100), 2) if cost_value else 0

                total_value += market_value
                total_cost += cost_value

                results.append({
                    "code": code,
                    "name": h.get("name", ""),
                    "shares": shares,
                    "cost": cost,
                    "price": price,
                    "market_value": market_value,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                })
            except Exception as e:
                results.append({"code": code, "name": h.get("name", ""), "error": str(e)})

        total_pnl = round(total_value - total_cost, 2)
        total_pnl_pct = round((total_pnl / total_cost * 100), 2) if total_cost else 0

        return {
            "holdings": results,
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _scan_tracking(self, pool="all"):
        """扫描标的池行情"""
        try:
            import yfinance as yf
        except ImportError:
            return {"error": "yfinance 未安装"}

        data_dir = get_data_dir(self.config)
        tp_path = data_dir / "tracking_pool.json"

        if not tp_path.exists():
            return {"error": "tracking_pool.json 不存在", "items": []}

        tp = json.loads(tp_path.read_text(encoding="utf-8"))

        items = {}

        # A股
        if pool in ("all", "stocks"):
            for code, info in tp.get("stocks", {}).items():
                items[code] = {"name": info.get("name", ""), "market": "A股", "reason": info.get("reason", "")}
            for code, info in tp.get("etfs", {}).items():
                items[code] = {"name": info.get("name", ""), "market": "ETF", "reason": info.get("reason", "")}

        # 美股
        if pool in ("all", "us"):
            for code, info in tp.get("us_stocks", {}).items():
                items[code] = {"name": info.get("name", ""), "market": "美股", "reason": info.get("reason", "")}

        # 指数
        if pool in ("all", "indexes"):
            for code, info in tp.get("cn_indexes", {}).items():
                items[code] = {"name": info.get("name", ""), "market": "A股指数", "reason": info.get("reason", "")}
            for code, info in tp.get("us_indexes", {}).items():
                items[code] = {"name": info.get("name", ""), "market": "美股指数", "reason": info.get("reason", "")}

        results = []
        alerts = []
        for code, meta in items.items():
            try:
                t = yf.Ticker(code)
                hist = t.history(period="5d")
                if hist.empty:
                    results.append({**meta, "code": code, "error": "无行情"})
                    continue

                close = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else close
                change_pct = round((close - prev) / prev * 100, 2)

                volume = float(hist["Volume"].iloc[-1]) if "Volume" in hist else 0
                avg_vol = float(hist["Volume"].iloc[:-1].mean()) if len(hist) > 1 else volume
                vol_ratio = round(volume / avg_vol, 2) if avg_vol > 0 else 1.0

                item = {**meta, "code": code, "price": close, "change_pct": change_pct}
                results.append(item)

                # 异动检测
                if abs(change_pct) >= 4:
                    alerts.append(f"⚠️ {meta['name']}({code}) {'涨' if change_pct > 0 else '跌'}{abs(change_pct)}%")
                if vol_ratio >= 1.5:
                    alerts.append(f"📊 {meta['name']}({code}) 量比 {vol_ratio}x")

            except Exception as e:
                results.append({**meta, "code": code, "error": str(e)})

        return {
            "pool": pool,
            "total": len(results),
            "results": results,
            "alerts": alerts,
            "has_alerts": len(alerts) > 0,
        }

    def _get_market_indexes(self):
        """拉取中美主要指数"""
        try:
            import yfinance as yf
        except ImportError:
            return {"error": "yfinance 未安装"}

        indexes = {
            "000001.SS": "上证指数",
            "399001.SZ": "深证成指",
            "399006.SZ": "创业板指",
            "^DJI": "道琼斯",
            "^IXIC": "纳斯达克",
            "^GSPC": "标普500",
        }

        results = {}
        for code, name in indexes.items():
            try:
                t = yf.Ticker(code)
                hist = t.history(period="2d")
                if hist.empty:
                    results[code] = {"name": name, "error": "无数据"}
                    continue
                close = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else close
                change_pct = round((close - prev) / prev * 100, 2)
                results[code] = {
                    "name": name,
                    "price": close,
                    "change_pct": change_pct,
                    "change_str": f"{'+' if change_pct > 0 else ''}{change_pct}%",
                }
            except Exception as e:
                results[code] = {"name": name, "error": str(e)}

        return {"indexes": results, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    def _record_trade(self, code, type, amount, price=None, name=""):
        """记录交易"""
        data_dir = get_data_dir(self.config)
        trades_path = data_dir / "trades.json"

        # 读现有交易
        if trades_path.exists():
            trades = json.loads(trades_path.read_text(encoding="utf-8"))
        else:
            trades = {"version": 1, "trades": []}

        # 自动拉价格
        if price is None:
            try:
                import yfinance as yf
                t = yf.Ticker(code)
                hist = t.history(period="1d")
                if not hist.empty:
                    price = round(float(hist["Close"].iloc[-1]), 3)
            except Exception:
                pass

        trade = {
            "id": f"{int(time.time())}",
            "type": type,
            "code": code,
            "name": name,
            "amount": amount,
            "price": price or 0,
            "date": time.strftime("%Y-%m-%d"),
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        trades["trades"].append(trade)

        # 更新持仓
        pf_path = data_dir / "portfolio.json"
        if pf_path.exists():
            pf = json.loads(pf_path.read_text(encoding="utf-8"))
            holdings = pf.get("holdings", {})
            if type == "buy":
                if code in holdings:
                    h = holdings[code]
                    total_shares = h["shares"] + amount
                    total_cost = h["avg_cost"] * h["shares"] + (price or 0) * amount
                    h["shares"] = total_shares
                    h["avg_cost"] = round(total_cost / total_shares, 4) if total_shares else 0
                else:
                    holdings[code] = {
                        "shares": amount,
                        "avg_cost": price or 0,
                        "name": name or code,
                        "sector": "",
                        "buy_date": time.strftime("%Y-%m-%d"),
                    }
            elif type == "sell":
                if code in holdings:
                    h = holdings[code]
                    h["shares"] = max(0, h["shares"] - amount)
                    if h["shares"] <= 0:
                        del holdings[code]

            pf["holdings"] = holdings
            pf["updated"] = time.strftime("%Y-%m-%d")
            pf_path.write_text(json.dumps(pf, ensure_ascii=False, indent=2), encoding="utf-8")

        # 写回
        trades_path.write_text(json.dumps(trades, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "recorded": True,
            "code": code,
            "type": type,
            "amount": amount,
            "price": price,
            "total": round((price or 0) * amount, 2),
        }


# ─── 测试 ─────────────────────────────────────────────────
if __name__ == "__main__":
    reg = ToolRegistry()
    print("=== 已注册工具 ===")
    for name in reg._tools:
        print(f"  {name}: {reg._tools[name]['description'][:60]}...")

    print("\n=== 测试 query_rag ===")
    result = reg.call("query_rag", query="光模块")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])

    print("\n=== 测试 get_portfolio ===")
    result = reg.call("get_portfolio")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])
