#!/usr/bin/env python3
"""
钱博士Agent — 数据迁移工具

将旧格式数据文件升级到新格式（添加 version 字段等）。
只读不改（输出新文件），不会破坏旧数据。

用法:
    python scripts/migrate.py status             # 检查所有数据文件版本状态
    python scripts/migrate.py portfolio          # 迁移 portfolio.json 到 v2
    python scripts/migrate.py tracking           # 迁移 tracking_pool.json 到 v2
    python scripts/migrate.py trades             # 创建 trades.json v1（如不存在）
    python scripts/migrate.py all                # 全部迁移
"""
import json
import os
import sys
import shutil
from datetime import date, datetime
from pathlib import Path
from config_loader import load_config, get_data_dir


def _find_source(name):
    """查找源文件：先找 skill 目录下的旧文件，再找 data/ 目录下的"""
    cfg = load_config()
    data_dir = get_data_dir(cfg)

    # 已知的可能位置
    candidates = [
        data_dir / name,                                    # data/ 目录
        Path(__file__).parent.parent / name,                # E:\qianboshi-agent\
        Path.home() / "AppData/Local/hermes/skills/research"
                    / "qianboshi-agent" / name,             # Hermes skill 目录
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _target_path(name, data_dir):
    """目标路径：data/ 目录下"""
    return data_dir / name


def _backup(path):
    """备份旧文件"""
    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(path, backup)
        print(f"  [BAK] 已备份: {backup}")


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 迁移函数 ──

def migrate_portfolio(data_dir):
    """portfolio.json → v2（加 version 字段 + sector/buy_date）"""
    src = _find_source("portfolio.json")
    if src is None:
        print("[SKIP] portfolio.json 不存在")
        return

    dst = _target_path("portfolio.json", data_dir)
    data = _read_json(src)

    if data.get("version") == 2:
        print("[OK] portfolio.json 已是最新版本 (v2)")
        return

    print(f"[MIGRATE] portfolio.json → v2")
    _backup(src)

    holdings = data.get("holdings", {})
    for code, info in holdings.items():
        if "sector" not in info:
            info["sector"] = ""
        if "buy_date" not in info:
            info["buy_date"] = str(date.today())

    # 计算总成本
    total_cost = sum(
        v["shares"] * v["avg_cost"]
        for v in holdings.values()
        if v.get("shares") and v.get("avg_cost")
    )

    v2 = {
        "version": 2,
        "updated": str(date.today()),
        "holdings": holdings,
        "cash": data.get("cash", 0),
        "currency": data.get("currency", "CNY"),
        "total_cost": round(total_cost, 2),
        "history": [],
    }

    _write_json(dst, v2)
    print(f"  [DST] {dst}")
    print(f"  [OK]  持仓 {len(holdings)} 项, 总成本 ¥{total_cost:.2f}")


def migrate_tracking(data_dir):
    """tracking_pool.json → v2（加 version + cn_indexes + cache）"""
    src = _find_source("tracking_pool.json")
    if src is None:
        print("[SKIP] tracking_pool.json 不存在")
        return

    dst = _target_path("tracking_pool.json", data_dir)
    data = _read_json(src)

    if data.get("version") == 2:
        print("[OK] tracking_pool.json 已是最新版本 (v2)")
        return

    print(f"[MIGRATE] tracking_pool.json → v2")
    _backup(src)

    v2 = {
        "version": 2,
        "updated": str(date.today()),
        "description": data.get("description", "钱博士Agent - 跟踪标的池"),
        "stocks": data.get("stocks", {}),
        "etfs": data.get("etfs", {}),
        "sectors": data.get("sectors", []),
        "us_stocks": data.get("us_stocks", {}),
        "us_indexes": data.get("us_indexes", {
            "^DJI": {"name": "道琼斯", "reason": "美股大盘"},
            "^IXIC": {"name": "纳斯达克", "reason": "科技股风向标"},
            "^GSPC": {"name": "标普500", "reason": "美股整体"},
        }),
        "cn_indexes": {
            "000001.SS": {"name": "上证指数", "reason": "A股大盘"},
            "399001.SZ": {"name": "深证成指", "reason": "A股大盘"},
            "399006.SZ": {"name": "创业板指", "reason": "成长股风向标"},
        },
        "cache": {},
    }

    _write_json(dst, v2)
    stats = {
        "A股": len(v2["stocks"]),
        "美股": len(v2["us_stocks"]),
        "指数": len(v2["us_indexes"]) + len(v2["cn_indexes"]),
        "板块": len(v2["sectors"]),
    }
    print(f"  [DST] {dst}")
    print(f"  [OK]  标的池: {stats}")


def migrate_trades(data_dir):
    """创建 trades.json v1（如不存在）"""
    dst = _target_path("trades.json", data_dir)
    if dst.exists():
        data = _read_json(dst)
        if data.get("version") == 1:
            print("[OK] trades.json 已存在且为最新版本 (v1)")
            return
        print(f"[MIGRATE] trades.json 已存在但无版本号，升级到 v1")
        _backup(dst)
    else:
        print(f"[MIGRATE] 创建 trades.json v1")

    v1 = {
        "version": 1,
        "trades": [],
    }
    _write_json(dst, v1)
    print(f"  [DST] {dst}")
    print(f"  [OK]  空交易流水已创建")


def cmd_status(data_dir):
    """检查所有数据文件版本状态"""
    print("=== 数据文件版本状态 ===\n")
    files = ["portfolio.json", "tracking_pool.json", "trades.json"]
    for name in files:
        src = _find_source(name)
        dst = _target_path(name, data_dir)
        if src:
            data = _read_json(src)
            ver = data.get("version", "无版本 (v1)")
            print(f"  {name}")
            print(f"    旧位置: {src}  [v{ver}]")
        else:
            print(f"  {name}  [不存在]")

        if dst.exists():
            data = _read_json(dst)
            ver = data.get("version", "?")
            print(f"    新位置: {dst}  [v{ver}]")
        else:
            print(f"    新位置: {dst}  [不存在]")
        print()


if __name__ == "__main__":
    cfg = load_config()
    data_dir = get_data_dir(cfg)
    data_dir.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    commands = {
        "status": cmd_status,
        "portfolio": lambda d: migrate_portfolio(d),
        "tracking": lambda d: migrate_tracking(d),
        "trades": lambda d: migrate_trades(d),
    }

    if cmd == "all":
        for name in ["portfolio", "tracking", "trades"]:
            commands[name](data_dir)
    elif cmd in commands:
        commands[cmd](data_dir)
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)
