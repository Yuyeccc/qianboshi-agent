"""资产注册表加载、解析与变更检测工具。"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_REGISTRY_PATH = Path("E:/qianboshi-agent/config/asset_registry.json")
DEFAULT_RULES_PATH = Path("E:/qianboshi-agent/config/review_rules.json")
DEFAULT_OLD_REGISTRY_PATH = Path(
    "E:/qianboshi-agent/config/asset_registry.previous.json"
)


class RegistryError(Exception):
    """资产注册表或复盘规则配置无效时抛出的异常。"""


def _load_json(path: Path | str, description: str) -> dict:
    """读取并解析 JSON 对象文件。"""
    file_path = Path(path)

    try:
        with file_path.open("r", encoding="utf-8") as file:
            value = json.load(file)
    except FileNotFoundError as exc:
        raise RegistryError(f"{description}不存在: {file_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"{description}读取或解析失败: {file_path}") from exc

    if not isinstance(value, dict):
        raise RegistryError(f"{description}根节点必须是JSON对象: {file_path}")

    return value


def _is_non_empty_string(value: Any) -> bool:
    """判断值是否为非空字符串。"""
    return isinstance(value, str) and bool(value.strip())


def _is_ascii_digits(value: Any) -> bool:
    """判断值是否仅由 ASCII 数字组成。"""
    return isinstance(value, str) and bool(value) and all(
        "0" <= character <= "9" for character in value
    )


def _is_valid_symbol(value: Any) -> bool:
    """判断证券代码是否符合带市场后缀或纯数字基金代码格式。"""
    if not isinstance(value, str) or not value:
        return False

    if _is_ascii_digits(value):
        return True

    if len(value) > 3 and value[-3:] in {".SS", ".SZ"}:
        return _is_ascii_digits(value[:-3])

    return False


def _parse_date(value: str | date, field_name: str) -> date:
    """将 ISO 日期字符串或 date 对象转换为 date。"""
    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise RegistryError(
                f"{field_name}必须是有效的ISO日期: {value}"
            ) from exc

    raise RegistryError(f"{field_name}必须是ISO日期字符串或date对象")


def load_registry(path: Path | str | None = None) -> dict:
    """加载并校验资产注册表，返回解析后的字典。"""
    registry_path = DEFAULT_REGISTRY_PATH if path is None else path
    registry = _load_json(registry_path, "资产注册表")
    problems = validate_registry(registry)

    if problems:
        raise RegistryError(
            f"资产注册表校验失败: {'; '.join(problems)}"
        )

    return registry


def load_rules(path: Path | str | None = None) -> dict:
    """加载并校验复盘判定规则，返回解析后的字典。"""
    rules_path = DEFAULT_RULES_PATH if path is None else path
    rules = _load_json(rules_path, "复盘规则")

    if not _is_non_empty_string(rules.get("rule_version")):
        raise RegistryError("复盘规则缺少非空rule_version")

    return rules


def resolve_asset(
    asset_id: str,
    registry: dict | None = None,
    as_of: str | date | None = None,
) -> dict:
    """按资产 ID 和生效日期解析可用于复盘的注册信息。"""
    if not isinstance(asset_id, str) or not asset_id.strip():
        raise RegistryError(f"asset_id无效: {asset_id!r}")

    current_registry = load_registry() if registry is None else registry
    problems = validate_registry(current_registry)
    if problems:
        raise RegistryError(
            f"资产注册表校验失败: {'; '.join(problems)}"
        )

    assets = current_registry["assets"]
    record = assets.get(asset_id)

    if record is None:
        raise RegistryError(f"资产未注册: {asset_id}")

    effective_from = _parse_date(
        record["effective_from"],
        f"{asset_id}.effective_from",
    )
    requested_date = date.today() if as_of is None else _parse_date(
        as_of,
        "as_of",
    )

    if requested_date < effective_from:
        raise RegistryError(
            f"资产未生效: {asset_id}，effective_from={record['effective_from']}"
        )

    status = record["status"]
    if status != "active":
        raise RegistryError(
            f"资产不可用于复盘: {asset_id}，status={status}"
        )

    return {
        "asset_id": asset_id,
        "name": record["name"],
        "primary_symbol": record["primary_symbol"],
        "proxy": record.get("proxy"),
        "benchmark_symbol": record["benchmark_symbol"],
        "status": record["status"],
        "reason": record.get("reason", ""),
    }


def detect_mapping_changes(
    old_path: Path | str | None = None,
    new_path: Path | str | None = None,
) -> list[dict]:
    """比较新旧注册表并返回主标的代码发生变化的资产。"""
    previous_path = (
        DEFAULT_OLD_REGISTRY_PATH if old_path is None else Path(old_path)
    )
    if not previous_path.exists():
        return []

    current_path = DEFAULT_REGISTRY_PATH if new_path is None else new_path
    old_registry = load_registry(previous_path)
    new_registry = load_registry(current_path)

    old_assets = old_registry["assets"]
    new_assets = new_registry["assets"]
    changes: list[dict] = []

    for asset_id, new_record in new_assets.items():
        old_record = old_assets.get(asset_id)
        if old_record is None:
            continue

        old_symbol = old_record.get("primary_symbol")
        new_symbol = new_record.get("primary_symbol")
        if old_symbol != new_symbol:
            changes.append(
                {
                    "asset_id": asset_id,
                    "change_type": "primary_changed",
                    "old_symbol": old_symbol,
                    "new_symbol": new_symbol,
                    "invalidation_reason": new_record.get(
                        "invalidation_reason",
                        "",
                    ),
                }
            )

    return changes


def affected_decisions(
    changes: list[dict],
    conn: sqlite3.Connection,
) -> list[str]:
    """查询所有受标的映射变更影响的决策 ID。"""
    asset_ids: list[str] = []
    for change in changes:
        asset_id = change.get("asset_id")
        if isinstance(asset_id, str) and asset_id not in asset_ids:
            asset_ids.append(asset_id)

    if not asset_ids:
        return []

    placeholders = ", ".join("?" for _ in asset_ids)
    query = (
        "SELECT DISTINCT decision_id "
        "FROM user_decision_logs "
        f"WHERE asset_id IN ({placeholders}) "
        "ORDER BY decision_id"
    )

    rows = conn.execute(query, asset_ids).fetchall()
    return [str(row[0]) for row in rows if row[0] is not None]


def validate_registry(registry: dict) -> list[str]:
    """检查资产注册表结构和字段格式，返回问题清单。"""
    problems: list[str] = []

    if not isinstance(registry, dict):
        return ["根节点必须是JSON对象"]

    if "version" not in registry:
        problems.append("缺少version")
    if "updated_at" not in registry:
        problems.append("缺少updated_at")

    assets = registry.get("assets")
    if not isinstance(assets, dict):
        problems.append("缺少有效的assets对象")
        return problems

    valid_statuses = {"active", "inactive", "invalidated"}
    required_fields = {
        "name",
        "primary_symbol",
        "benchmark_symbol",
        "effective_from",
        "status",
    }

    for asset_id, record in assets.items():
        prefix = f"assets.{asset_id}"

        if not isinstance(asset_id, str) or not asset_id.strip():
            problems.append(f"{prefix}: asset_id无效")
            continue

        if not isinstance(record, dict):
            problems.append(f"{prefix}:记录必须是对象")
            continue

        missing = sorted(field for field in required_fields if field not in record)
        for field in missing:
            problems.append(f"{prefix}:缺少{field}")

        if missing:
            continue

        if not _is_non_empty_string(record["name"]):
            problems.append(f"{prefix}.name必须是非空字符串")

        if not _is_valid_symbol(record["primary_symbol"]):
            problems.append(
                f"{prefix}.primary_symbol格式无效: "
                f"{record['primary_symbol']!r}"
            )

        if not _is_valid_symbol(record["benchmark_symbol"]):
            problems.append(
                f"{prefix}.benchmark_symbol格式无效: "
                f"{record['benchmark_symbol']!r}"
            )

        try:
            _parse_date(
                record["effective_from"],
                f"{prefix}.effective_from",
            )
        except RegistryError as exc:
            problems.append(str(exc))

        if record["status"] not in valid_statuses:
            problems.append(
                f"{prefix}.status必须是active/inactive/invalidated"
            )

        proxy = record.get("proxy")
        if proxy is not None and not _is_valid_symbol(proxy):
            problems.append(f"{prefix}.proxy格式无效: {proxy!r}")

    return problems


if __name__ == "__main__":
    try:
        registry = load_registry()
        load_rules()

        problems = validate_registry(registry)
        if problems:
            for problem in problems:
                print(f"FAIL: {problem}")
            raise SystemExit(1)

        asset_ids = [
            "GOLD",
            "INNOV_DRUG",
            "TECH",
            "BAIJIU",
            "ALUMINUM",
            "SEMI",
            "BATTERY",
        ]

        print("asset\tsymbol\tbenchmark\tstatus")
        for asset_id in asset_ids:
            resolved = resolve_asset(
                asset_id,
                registry=registry,
                as_of=date.today(),
            )
            print(
                f"{resolved['asset_id']}\t"
                f"{resolved['primary_symbol']}\t"
                f"{resolved['benchmark_symbol']}\t"
                f"{resolved['status']}"
            )
    except Exception as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(1)
