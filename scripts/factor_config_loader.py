#!/usr/bin/env python3
"""资产分析卡配置加载器。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs" / "asset_cards"


def load_asset_card_config(asset_id: str) -> dict[str, Any]:
    """读取单个资产分析卡配置。"""
    if not asset_id:
        raise ValueError("asset_id 不能为空")
    path = CONFIG_DIR / f"{asset_id.lower()}.yaml"
    if not path.exists():
        for candidate in sorted(CONFIG_DIR.glob("*.yaml")):
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and str(data.get("asset_id") or "").upper() == asset_id.upper():
                data.setdefault("config_path", str(candidate))
                return data
        raise FileNotFoundError(f"资产分析卡配置不存在: {path}，且未找到 asset_id={asset_id} 的配置")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"资产分析卡配置格式错误，应为 YAML 对象: {path}")
    data.setdefault("config_path", str(path))
    return data


def load_all_asset_configs() -> list[dict[str, Any]]:
    """读取全部资产分析卡配置。"""
    if not CONFIG_DIR.exists():
        raise FileNotFoundError(f"资产分析卡配置目录不存在: {CONFIG_DIR}")
    configs: list[dict[str, Any]] = []
    for path in sorted(CONFIG_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"资产分析卡配置格式错误，应为 YAML 对象: {path}")
        data.setdefault("config_path", str(path))
        configs.append(data)
    if not configs:
        raise FileNotFoundError(f"资产分析卡配置目录为空: {CONFIG_DIR}")
    return configs
