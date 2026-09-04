#!/usr/bin/env python3
"""推送到飞书"钱博士Agent"群。

用法:
    python push_portfolio.py                    # 推持仓盈亏（默认）
    python push_portfolio.py --brief            # 推当日盘前简报
    python push_portfolio.py --file data/tmp/xxx.md   # 推任意 markdown 文件
    python push_portfolio.py --text "自定义内容"
    python push_portfolio.py --chat oc_xxxx     # 指定群（默认钱博士Agent群）
    python push_portfolio.py --dry-run          # 只打印不发送

依赖: 标准库 requests（无则 pip install requests）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

# 飞书应用凭据（与 .env 一致；也可用环境变量覆盖）
APP_ID = "cli_aad43116e438dbd8"
APP_SECRET = "REDACTED_FEISHU_SECRET_2026"

# 默认目标群：钱博士Agent
DEFAULT_CHAT_ID = "oc_47a6eeb5b1e02943fc50c479584b6324"
BRIEF_FILE = DATA_DIR / "briefs" / "日报_%Y-%m-%d.md"


def _get_token() -> str:
    import urllib.request
    body = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    if data.get("code") != 0:
        raise RuntimeError(f"获取token失败: {data.get('msg')}")
    return data["tenant_access_token"]


def send_text(chat_id: str, text: str, token: str | None = None) -> dict:
    import urllib.request
    token = token or _get_token()
    payload = json.dumps(
        {"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": text})}
    ).encode()
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


# ─── 持仓盈亏计算 ────────────────────────────────────────────

def _load_json(name: str) -> dict:
    p = DATA_DIR / name
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _fmt_pnl(pnl: float, pct: float) -> str:
    sign = "+" if pnl >= 0 else ""
    return f"{sign}{pnl:.2f}元（{sign}{pct:.2f}%）"


def portfolio_summary() -> str:
    """计算持仓盈亏，返回推送文本。黄金联接按场内518880涨跌推净值。"""
    cache = _load_json("market_cache.json")
    portfolio = _load_json("portfolio.json")
    trends = _load_json("price_trends.json")
    holdings = portfolio.get("holdings", {})
    if not holdings:
        return "📊 持仓为空（portfolio.json 无 holdings）"

    lines = [f"📊 持仓情况（数据截至 {datetime.now().strftime('%Y-%m-%d %H:%M')}）", ""]
    total_cost = 0.0
    total_mv = 0.0

    for code, p in holdings.items():
        name = p.get("name", code)
        market_code = p.get("market_code")  # 场外基金对应的场内代码
        sym = market_code or (code if "." in code else f"{code}.SZ")
        cur = cache.get(sym, {})

        if market_code:
            # 场外联接基金：净值 = 成本净值 × (1 + 场内自 nav_date 起涨跌幅)
            # 基准取 nav_date 当天或之前最近收盘价（与 tool_registry/_estimate_offshore_nav 口径一致）
            shares = float(p.get("shares", 0))
            buy_amount = float(p.get("buy_amount", 0))
            nav = float(p.get("avg_cost", 0))
            cost = buy_amount
            anchor = p.get("nav_date") or p.get("buy_date") or ""
            hist = trends.get(sym, {})
            dates = sorted(hist.keys())
            base_price = None
            for d in dates:
                if d <= anchor:
                    base_price = hist[d].get("price")
                else:
                    break
            if base_price is None and dates:
                base_price = hist[dates[0]].get("price")
            cur_price = cur.get("price")
            if base_price and cur_price:
                ret = (cur_price - base_price) / base_price
                cur_nav = nav * (1 + ret)
                mv = cur_nav * shares
            else:
                cur_nav, mv = None, None
            pnl = (mv - cost) if mv is not None else None
            pct = (pnl / cost * 100) if pnl is not None else None
            lines.append(f"【{name} {code}】")
            lines.append(f"· 持仓：{shares}份（{cost:.0f}元），买入净值{nav}")
            lines.append(
                f"· 场内{sym}：{base_price or '?'} → {cur_price or '?'}（{((cur_price-base_price)/base_price*100 if base_price and cur_price else 0):+.2f}%）"
            )
            if cur_nav is not None:
                lines.append(f"· 推算净值：{cur_nav:.4f}")
                lines.append(f"· 盈亏：{_fmt_pnl(pnl, pct)}")
            else:
                lines.append("· 盈亏：数据不足（缺行情）")
        else:
            # 场内标的
            shares = float(p.get("shares", 0))
            cost_price = float(p.get("avg_cost", 0))
            cost = shares * cost_price
            price = cur.get("price")
            if price:
                mv = shares * price
                pnl = mv - cost
                pct = pnl / cost * 100
                chg = cur.get("change_pct")
                chg_s = f"{chg:+.2f}%" if chg is not None else "N/A"
                lines.append(f"【{name} {code}】")
                lines.append(f"· 持仓：{shares:.0f}股 @ {cost_price}")
                lines.append(f"· 现价：{price}（{chg_s}）")
                lines.append(f"· 市值：{mv:.2f} | 成本：{cost:.2f}")
                lines.append(f"· 盈亏：{_fmt_pnl(pnl, pct)}")
            else:
                mv = None
                lines.append(f"【{name} {code}】")
                lines.append(f"· 持仓：{shares:.0f}股 @ {cost_price}")
                lines.append("· 现价：缺行情数据")
        if mv is not None:
            total_cost += cost
            total_mv += mv
        lines.append("")

    if total_mv:
        total_pnl = total_mv - total_cost
        lines.append("【合计】")
        lines.append(f"· 总成本：{total_cost:.2f} | 总市值：{total_mv:.2f}")
        lines.append(f"· 总盈亏：{_fmt_pnl(total_pnl, total_pnl/total_cost*100)}")
    lines.append("")
    lines.append("⚠️ 非投资建议，仅供参考")
    return "\n".join(lines)


def brief_text() -> str | None:
    """读取当日盘前简报（日报_YYYY-MM-DD.md 或 YYYY-MM-DD.md）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    for name in [f"日报_{today}.md", f"{today}.md"]:
        p = DATA_DIR / "briefs" / name
        if p.exists():
            text = p.read_text(encoding="utf-8")
            # 简报太长就截断（飞书消息限制）
            return text[:6000]
    # 回退到最新的简报
    briefs = sorted((DATA_DIR / "briefs").glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
    for p in briefs:
        if "日报" in p.name or p.name[:4].isdigit():
            text = p.read_text(encoding="utf-8")
            return f"📋 简报（回退到最新 {p.name}）\n\n" + text[:6000]
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="推送到飞书钱博士Agent群")
    ap.add_argument("--brief", action="store_true", help="推当日盘前简报")
    ap.add_argument("--file", help="推送指定 markdown 文件")
    ap.add_argument("--text", help="推送自定义文本")
    ap.add_argument("--chat", default=DEFAULT_CHAT_ID, help="目标群 chat_id")
    ap.add_argument("--dry-run", action="store_true", help="只打印不发送")
    args = ap.parse_args()

    if args.brief:
        text = brief_text()
        if not text:
            print("❌ 找不到当日简报（data/briefs/ 下没有 日报_今日.md 或 今日.md）", file=sys.stderr)
            raise SystemExit(1)
    elif args.file:
        p = Path(args.file)
        if not p.exists():
            print(f"❌ 文件不存在: {p}", file=sys.stderr)
            raise SystemExit(1)
        text = p.read_text(encoding="utf-8")[:6000]
    elif args.text:
        text = args.text
    else:
        text = portfolio_summary()

    print("─" * 40)
    print(text)
    print("─" * 40)

    if args.dry_run:
        print("\n[dry-run] 未发送")
        return

    res = send_text(args.chat, text)
    if res.get("code") == 0:
        print(f"\n✅ 已发送到群 {args.chat}（message_id={res.get('data', {}).get('message_id')}）")
    else:
        print(f"\n❌ 发送失败: {res.get('code')} {res.get('msg')}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
