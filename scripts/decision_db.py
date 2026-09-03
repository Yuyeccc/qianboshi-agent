#!/usr/bin/env python3
"""决策台 SQLite 存储层。"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import get_data_dir, load_config


_INITIALIZED_DB_PATHS: set[str] = set()


def decision_db_path(config: dict[str, Any] | None = None) -> Path:
    """返回决策台数据库路径。"""
    config = config or load_config()
    decision_cfg = config.get("decision", {}) if isinstance(config, dict) else {}
    p = decision_cfg.get("db_path")
    if p:
        path = Path(p)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        return path
    return get_data_dir(config) / "qianboshi_decision.db"


def connect(path: str | Path | None = None, config: dict[str, Any] | None = None) -> sqlite3.Connection:
    """连接数据库并确保表结构存在。"""
    db_path = Path(path) if path else decision_db_path(config)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    db_key = str(db_path.resolve())
    if db_key not in _INITIALIZED_DB_PATHS:
        init_db(conn)
        _INITIALIZED_DB_PATHS.add(db_key)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """幂等创建决策台阶段一表。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS debate_cards (
            card_id TEXT PRIMARY KEY,
            entity_id TEXT,
            entity_name TEXT,
            entity_type TEXT,
            horizon TEXT,
            window_start TEXT,
            window_end TEXT,
            bullish_count INTEGER,
            bearish_count INTEGER,
            neutral_count INTEGER,
            risk_count INTEGER,
            watch_count INTEGER,
            consensus_direction TEXT,
            disagreement_level REAL,
            confidence_level REAL,
            novelty_level REAL,
            highlight_tags TEXT,
            summary TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS debate_card_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT,
            view_id TEXT,
            stance TEXT,
            analyst TEXT,
            date TEXT,
            claim TEXT,
            logic TEXT,
            risk TEXT,
            evidence TEXT,
            confidence REAL,
            cluster_id TEXT,
            cluster_label TEXT,
            analyst_score_snapshot REAL,
            source_file TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_events (
            event_id TEXT PRIMARY KEY,
            view_id TEXT,
            analyst TEXT,
            entity TEXT,
            entity_type TEXT,
            stance TEXT,
            horizon TEXT,
            claim TEXT,
            event_date TEXT,
            window_days INTEGER,
            price_at_event REAL,
            price_at_window REAL,
            return_pct REAL,
            status TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_outcomes (
            symbol TEXT,
            date TEXT,
            price REAL,
            change_pct REAL,
            PRIMARY KEY(symbol, date)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pred_events_status_date
        ON prediction_events(status, event_date)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pred_events_entity_date
        ON prediction_events(entity, event_date)
        """
    )
    ensure_asset_card_schema(conn)
    ensure_analyst_scores_schema(conn)
    ensure_decision_log_schema(conn)
    conn.commit()


def ensure_decision_log_schema(conn: sqlite3.Connection) -> None:
    """确保用户决策日志阶段四表结构存在。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_decision_logs (
            decision_id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'default',
            asset_id TEXT NOT NULL,
            asset_name TEXT NOT NULL,
            asset_type TEXT,
            decision_date TEXT NOT NULL,
            horizon TEXT NOT NULL,
            direction TEXT NOT NULL,
            conviction REAL,
            thesis TEXT NOT NULL,
            key_reasons TEXT,
            premise TEXT,
            invalidation_conditions TEXT,
            action_note TEXT,
            asset_card_version INTEGER,
            debate_card_id TEXT,
            market_snapshot TEXT,
            user_view_version_ids TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    # 迁移：老库补 user_view_version_ids 列（记忆体系 P1a，决策冻结信念版本，2026-09-03）
    _ensure_column(conn, "user_decision_logs", "user_view_version_ids", "TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_decision_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            evidence_id TEXT,
            title TEXT,
            content TEXT,
            source_ref TEXT,
            created_at TEXT,
            FOREIGN KEY(decision_id) REFERENCES user_decision_logs(decision_id)
        )
        """
    )
    # 迁移：老库补 premise 列（条件树 #16，2026-08-30）
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(user_decision_logs)")}
        if "premise" not in cols:
            conn.execute("ALTER TABLE user_decision_logs ADD COLUMN premise TEXT")
            conn.commit()
    except Exception:
        pass  # 表不存在等情况交给 CREATE TABLE IF NOT EXISTS
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_reviews (
            review_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL,
            review_date TEXT NOT NULL,
            horizon_days INTEGER,
            outcome_return REAL,
            benchmark_return REAL,
            excess_return REAL,
            max_drawdown REAL,
            result_label TEXT,
            what_went_right TEXT,
            what_went_wrong TEXT,
            missed_factors TEXT,
            over_weighted_factors TEXT,
            new_rule_learned TEXT,
            suggest_asset_card_update INTEGER DEFAULT 0,
            linked_new_card_version TEXT,
            created_at TEXT,
            FOREIGN KEY(decision_id) REFERENCES user_decision_logs(decision_id)
        )
        """
    )


def upsert_decision_log(decision: dict[str, Any], path: str | Path | None = None) -> str:
    """写入或更新一条用户决策日志。"""
    now = datetime_now()
    decision_id = decision.get("decision_id") or f"dec_{decision.get('decision_date', '')}_{decision.get('asset_id', '')}"
    with connect(path=path) as conn:
        conn.execute(
            """
            INSERT INTO user_decision_logs (
                decision_id, user_id, asset_id, asset_name, asset_type,
                decision_date, horizon, direction, conviction,
                thesis, key_reasons, premise, invalidation_conditions, action_note,
                asset_card_version, debate_card_id, market_snapshot, user_view_version_ids,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(decision_id) DO UPDATE SET
                thesis=excluded.thesis,
                key_reasons=excluded.key_reasons,
                premise=excluded.premise,
                invalidation_conditions=excluded.invalidation_conditions,
                action_note=excluded.action_note,
                horizon=excluded.horizon,
                direction=excluded.direction,
                conviction=excluded.conviction,
                status=excluded.status,
                user_view_version_ids=excluded.user_view_version_ids,
                updated_at=excluded.updated_at
            """,
            (
                decision_id,
                decision.get("user_id", "default"),
                decision.get("asset_id", ""),
                decision.get("asset_name", ""),
                decision.get("asset_type"),
                decision.get("decision_date", ""),
                decision.get("horizon", "medium"),
                decision.get("direction", "neutral"),
                decision.get("conviction"),
                decision.get("thesis", ""),
                json.dumps(decision.get("key_reasons", []), ensure_ascii=False),
                json.dumps(decision.get("premise", []), ensure_ascii=False),
                json.dumps(decision.get("invalidation_conditions", []), ensure_ascii=False),
                decision.get("action_note"),
                decision.get("asset_card_version"),
                decision.get("debate_card_id"),
                json.dumps(decision.get("market_snapshot", {}), ensure_ascii=False),
                json.dumps(decision.get("user_view_version_ids"), ensure_ascii=False)
                if decision.get("user_view_version_ids") is not None else None,
                decision.get("status", "open"),
                now,
                now,
            ),
        )
        # 证据快照
        for ev in decision.get("evidence", []) or []:
            conn.execute(
                """
                INSERT INTO user_decision_evidence (
                    decision_id, evidence_type, evidence_id, title, content, source_ref, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    ev.get("type", "note"),
                    ev.get("id"),
                    ev.get("title"),
                    ev.get("content"),
                    ev.get("source_ref"),
                    now,
                ),
            )
        conn.commit()
    return decision_id


def fetch_decisions(status: str | None = None, path: str | Path | None = None) -> list[dict[str, Any]]:
    """读取决策日志，按日期降序。"""
    sql = "SELECT * FROM user_decision_logs"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY decision_date DESC, created_at DESC"
    with connect(path=path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _json_dumps(value: Any) -> str | None:
    """安全序列化 dict/list 为 JSON 字符串（None→None），71号方案#10-1。"""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """幂等给已存在的表补列（先 PRAGMA 检查再 ALTER），71号方案#10-1。"""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def ensure_asset_card_schema(conn: sqlite3.Connection) -> None:
    """确保资产分析卡阶段三表结构存在。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_cards (
            asset_id TEXT PRIMARY KEY,
            asset_name TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            current_version INTEGER NOT NULL,
            default_horizon TEXT,
            description TEXT,
            config_path TEXT,
            extra_json TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    # 幂等迁移（2026-09-01 71号方案#10-1）：旧库补 extra_json 列（存 data_status/quality/valuation 快照）
    _ensure_column(conn, "asset_cards", "extra_json", "TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_card_versions (
            version_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            config_json TEXT NOT NULL,
            change_reason TEXT,
            changed_by TEXT,
            linked_review_id TEXT,
            created_at TEXT,
            FOREIGN KEY(asset_id) REFERENCES asset_cards(asset_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_states (
            state_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            card_version INTEGER NOT NULL,
            factor_id TEXT NOT NULL,
            factor_name TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            raw_value TEXT,
            current_state TEXT,
            change_direction TEXT,
            impact_direction TEXT,
            impact_strength TEXT,
            confidence REAL,
            evidence_refs TEXT,
            summary TEXT,
            created_at TEXT
        )
        """
    )


def ensure_analyst_scores_schema(conn: sqlite3.Connection) -> None:
    """确保 analyst_scores 按回测窗口聚合；旧表可重算，直接重建。"""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'analyst_scores'"
    ).fetchone()
    if exists:
        rows = conn.execute("PRAGMA table_info(analyst_scores)").fetchall()
        columns = {row["name"] for row in rows}
        pk_columns = [row["name"] for row in sorted(rows, key=lambda row: row["pk"]) if row["pk"]]
        if "window_days" not in columns or pk_columns != ["analyst", "entity", "window_days"]:
            conn.execute("DROP TABLE analyst_scores")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analyst_scores (
            analyst TEXT,
            entity TEXT,
            horizon TEXT,
            window_days INTEGER,
            sample_count INTEGER,
            hit_rate REAL,
            avg_return REAL,
            score REAL,
            updated_at TEXT,
            PRIMARY KEY(analyst, entity, window_days)
        )
        """
    )


def clear_prediction_backtest(path: str | Path | None = None) -> None:
    """清空分析师回测事件和评分，供 --rebuild 使用。"""
    with connect(path=path) as conn:
        conn.execute("DELETE FROM prediction_events")
        conn.execute("DELETE FROM analyst_scores")
        conn.commit()


def upsert_prediction_events(events: list[dict[str, Any]], path: str | Path | None = None) -> int:
    """批量覆盖写入预测事件。"""
    if not events:
        return 0
    with connect(path=path) as conn:
        conn.executemany(
            """
            INSERT INTO prediction_events (
                event_id, view_id, analyst, entity, entity_type, stance, horizon, claim,
                event_date, window_days, price_at_event, price_at_window, return_pct, status
            )
            VALUES (
                :event_id, :view_id, :analyst, :entity, :entity_type, :stance, :horizon, :claim,
                :event_date, :window_days, :price_at_event, :price_at_window, :return_pct, :status
            )
            ON CONFLICT(event_id) DO UPDATE SET
                view_id=excluded.view_id,
                analyst=excluded.analyst,
                entity=excluded.entity,
                entity_type=excluded.entity_type,
                stance=excluded.stance,
                horizon=excluded.horizon,
                claim=excluded.claim,
                event_date=excluded.event_date,
                window_days=excluded.window_days,
                price_at_event=excluded.price_at_event,
                price_at_window=excluded.price_at_window,
                return_pct=excluded.return_pct,
                status=excluded.status
            """,
            events,
        )
        conn.commit()
    return len(events)


def fetch_pending_prediction_events(limit: int = 100, path: str | Path | None = None, since: str | None = None) -> list[dict[str, Any]]:
    """读取待回填的预测事件。"""
    with connect(path=path) as conn:
        params: list[Any] = []
        where = "status = 'pending'"
        if since:
            where += " AND event_date >= ?"
            params.append(since)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT * FROM prediction_events
            WHERE {where}
            ORDER BY event_date, event_id
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def update_prediction_event_outcome(
    event_id: str,
    status: str,
    price_at_event: float | None = None,
    price_at_window: float | None = None,
    return_pct: float | None = None,
    path: str | Path | None = None,
) -> None:
    """更新单条预测事件的回填结果。"""
    with connect(path=path) as conn:
        conn.execute(
            """
            UPDATE prediction_events
            SET price_at_event = ?, price_at_window = ?, return_pct = ?, status = ?
            WHERE event_id = ?
            """,
            (price_at_event, price_at_window, return_pct, status, event_id),
        )
        conn.commit()


def update_prediction_event_outcomes_batch(updates: list[dict[str, Any]], path: str | Path | None = None) -> int:
    """批量更新预测事件的回填结果。"""
    if not updates:
        return 0
    with connect(path=path) as conn:
        conn.executemany(
            """
            UPDATE prediction_events
            SET price_at_event = :price_at_event,
                price_at_window = :price_at_window,
                return_pct = :return_pct,
                status = :status
            WHERE event_id = :event_id
            """,
            updates,
        )
        conn.commit()
    return len(updates)


def upsert_market_outcome(symbol: str, date: str, price: float, change_pct: float | None = None, path: str | Path | None = None) -> None:
    """缓存单日市场结果。"""
    with connect(path=path) as conn:
        conn.execute(
            """
            INSERT INTO market_outcomes (symbol, date, price, change_pct)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol, date) DO UPDATE SET
                price=excluded.price,
                change_pct=excluded.change_pct
            """,
            (symbol, date, price, change_pct),
        )
        conn.commit()


def upsert_market_outcomes_batch(rows: list[dict[str, Any]], path: str | Path | None = None) -> int:
    """批量缓存单日市场结果。"""
    if not rows:
        return 0
    with connect(path=path) as conn:
        conn.executemany(
            """
            INSERT INTO market_outcomes (symbol, date, price, change_pct)
            VALUES (:symbol, :date, :price, :change_pct)
            ON CONFLICT(symbol, date) DO UPDATE SET
                price=excluded.price,
                change_pct=excluded.change_pct
            """,
            rows,
        )
        conn.commit()
    return len(rows)


def upsert_analyst_scores(scores: list[dict[str, Any]], path: str | Path | None = None) -> int:
    """批量覆盖写入分析师回测分。"""
    if not scores:
        return 0
    with connect(path=path) as conn:
        conn.executemany(
            """
            INSERT INTO analyst_scores (
                analyst, entity, horizon, window_days, sample_count, hit_rate, avg_return, score, updated_at
            )
            VALUES (
                :analyst, :entity, :horizon, :window_days, :sample_count, :hit_rate, :avg_return, :score, :updated_at
            )
            ON CONFLICT(analyst, entity, window_days) DO UPDATE SET
                horizon=excluded.horizon,
                sample_count=excluded.sample_count,
                hit_rate=excluded.hit_rate,
                avg_return=excluded.avg_return,
                score=excluded.score,
                updated_at=excluded.updated_at
            """,
            scores,
        )
        conn.commit()
    return len(scores)


def fetch_analyst_scores(
    entity: str,
    window_days: int | None = None,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """按标的读取分析师历史命中率，可按回测窗口过滤。"""
    with connect(path=path) as conn:
        params: list[Any] = [entity]
        where = "entity = ?"
        if window_days is not None:
            where += " AND window_days = ?"
            params.append(window_days)
        rows = conn.execute(
            f"""
            SELECT analyst, entity, horizon, window_days, sample_count, hit_rate, avg_return, score, updated_at
            FROM analyst_scores
            WHERE {where}
            ORDER BY analyst, window_days, updated_at DESC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


_DEBATE_CARD_SQL = """
INSERT INTO debate_cards (
    card_id, entity_id, entity_name, entity_type, horizon,
    window_start, window_end,
    bullish_count, bearish_count, neutral_count, risk_count, watch_count,
    consensus_direction, disagreement_level, confidence_level, novelty_level,
    highlight_tags, summary, created_at, updated_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(card_id) DO UPDATE SET
    entity_id=excluded.entity_id,
    entity_name=excluded.entity_name,
    entity_type=excluded.entity_type,
    horizon=excluded.horizon,
    window_start=excluded.window_start,
    window_end=excluded.window_end,
    bullish_count=excluded.bullish_count,
    bearish_count=excluded.bearish_count,
    neutral_count=excluded.neutral_count,
    risk_count=excluded.risk_count,
    watch_count=excluded.watch_count,
    consensus_direction=excluded.consensus_direction,
    disagreement_level=excluded.disagreement_level,
    confidence_level=excluded.confidence_level,
    novelty_level=excluded.novelty_level,
    highlight_tags=excluded.highlight_tags,
    summary=excluded.summary,
    updated_at=excluded.updated_at
"""

_DEBATE_CARD_ITEM_SQL = """
INSERT INTO debate_card_items (
    card_id, view_id, stance, analyst, date, claim, logic, risk, evidence,
    confidence, cluster_id, cluster_label, analyst_score_snapshot, source_file
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _debate_card_row(conn: sqlite3.Connection, card: dict[str, Any]) -> tuple[Any, ...]:
    now = card.get("updated_at") or card.get("created_at")
    existing = conn.execute(
        "SELECT created_at FROM debate_cards WHERE card_id = ?",
        (card.get("card_id"),),
    ).fetchone()
    created_at = existing["created_at"] if existing else card.get("created_at")
    counts = card.get("counts") or {}
    window = card.get("window") or {}
    metrics = card.get("metrics") or {}
    return (
        card.get("card_id"),
        card.get("entity_id") or card.get("entity_name"),
        card.get("entity_name"),
        card.get("entity_type"),
        card.get("horizon"),
        window.get("start"),
        window.get("end"),
        counts.get("bullish", 0),
        counts.get("bearish", 0),
        counts.get("neutral", 0),
        counts.get("risk", 0),
        counts.get("watch", 0),
        metrics.get("consensus_direction"),
        metrics.get("disagreement_level", 0.0),
        metrics.get("confidence_level", 0.0),
        metrics.get("novelty_level", 0.0),
        json.dumps(card.get("highlights") or [], ensure_ascii=False),
        card.get("summary", ""),
        created_at or now,
        now,
    )


def _debate_card_item_rows(card: dict[str, Any]) -> list[tuple[Any, ...]]:
    rows = []
    for item in card.get("items") or []:
        rows.append((
            card.get("card_id"),
            item.get("view_id"),
            item.get("stance"),
            item.get("analyst"),
            item.get("date"),
            item.get("claim"),
            item.get("logic"),
            item.get("risk"),
            item.get("evidence"),
            item.get("confidence"),
            item.get("cluster_id"),
            item.get("cluster_label"),
            item.get("analyst_score_snapshot"),
            item.get("source_file"),
        ))
    return rows


def upsert_debate_card(card: dict[str, Any], path: str | Path | None = None) -> None:
    """覆盖写入一张多空对照卡及其明细。"""
    with connect(path=path) as conn:
        conn.execute(_DEBATE_CARD_SQL, _debate_card_row(conn, card))
        conn.execute("DELETE FROM debate_card_items WHERE card_id = ?", (card.get("card_id"),))
        conn.executemany(_DEBATE_CARD_ITEM_SQL, _debate_card_item_rows(card))
        conn.commit()


def upsert_debate_cards(cards: list[dict[str, Any]], path: str | Path | None = None) -> int:
    """批量覆盖写入多张多空对照卡及其明细。"""
    if not cards:
        return 0
    with connect(path=path) as conn:
        conn.executemany(_DEBATE_CARD_SQL, [_debate_card_row(conn, card) for card in cards])
        conn.executemany(
            "DELETE FROM debate_card_items WHERE card_id = ?",
            [(card.get("card_id"),) for card in cards],
        )
        item_rows = []
        for card in cards:
            item_rows.extend(_debate_card_item_rows(card))
        conn.executemany(_DEBATE_CARD_ITEM_SQL, item_rows)
        conn.commit()
    return len(cards)


def upsert_asset_card(card_meta: dict[str, Any], path: str | Path | None = None) -> None:
    """覆盖写入资产分析卡元数据。"""
    now = datetime_now()
    asset_id = card_meta.get("asset_id")
    with connect(path=path) as conn:
        existing = conn.execute("SELECT created_at FROM asset_cards WHERE asset_id = ?", (asset_id,)).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            """
            INSERT INTO asset_cards (
                asset_id, asset_name, asset_type, current_version, default_horizon,
                description, config_path, extra_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
                asset_name=excluded.asset_name,
                asset_type=excluded.asset_type,
                current_version=excluded.current_version,
                default_horizon=excluded.default_horizon,
                description=excluded.description,
                config_path=excluded.config_path,
                extra_json=excluded.extra_json,
                updated_at=excluded.updated_at
            """,
            (
                asset_id,
                card_meta.get("asset_name"),
                card_meta.get("asset_type") or "unknown",
                int(card_meta.get("version") or card_meta.get("current_version") or 1),
                card_meta.get("default_horizon"),
                card_meta.get("description"),
                card_meta.get("config_path"),
                _json_dumps(card_meta.get("extra")),
                created_at,
                now,
            ),
        )
        conn.commit()


def save_asset_card_version(
    asset_id: str,
    version: int,
    config_json: dict[str, Any],
    change_reason: str | None = None,
    changed_by: str | None = "system",
    linked_review_id: str | None = None,
    path: str | Path | None = None,
) -> str:
    """保存资产分析卡版本快照。"""
    now = datetime_now()
    version_id = f"{asset_id}_v{version}"
    with connect(path=path) as conn:
        conn.execute(
            """
            INSERT INTO asset_card_versions (
                version_id, asset_id, version, config_json, change_reason,
                changed_by, linked_review_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(version_id) DO UPDATE SET
                config_json=excluded.config_json,
                change_reason=excluded.change_reason,
                changed_by=excluded.changed_by,
                linked_review_id=excluded.linked_review_id
            """,
            (
                version_id,
                asset_id,
                int(version),
                json.dumps(config_json, ensure_ascii=False, sort_keys=True),
                change_reason,
                changed_by,
                linked_review_id,
                now,
            ),
        )
        conn.commit()
    return version_id


def upsert_factor_state(state: dict[str, Any], path: str | Path | None = None) -> None:
    """覆盖写入单个因素状态。"""
    now = datetime_now()
    with connect(path=path) as conn:
        conn.execute(
            """
            INSERT INTO factor_states (
                state_id, asset_id, card_version, factor_id, factor_name, as_of_date,
                raw_value, current_state, change_direction, impact_direction,
                impact_strength, confidence, evidence_refs, summary, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(state_id) DO UPDATE SET
                raw_value=excluded.raw_value,
                current_state=excluded.current_state,
                change_direction=excluded.change_direction,
                impact_direction=excluded.impact_direction,
                impact_strength=excluded.impact_strength,
                confidence=excluded.confidence,
                evidence_refs=excluded.evidence_refs,
                summary=excluded.summary
            """,
            (
                state.get("state_id"),
                state.get("asset_id"),
                int(state.get("card_version") or 1),
                state.get("factor_id"),
                state.get("factor_name"),
                state.get("as_of_date"),
                json.dumps(state.get("raw_value"), ensure_ascii=False),
                state.get("current_state"),
                state.get("change_direction"),
                state.get("impact_direction"),
                state.get("impact_strength"),
                state.get("confidence"),
                json.dumps(state.get("evidence_refs") or [], ensure_ascii=False),
                state.get("summary"),
                now,
            ),
        )
        conn.commit()


def datetime_now() -> str:
    """返回 SQLite 记录使用的本地时间字符串。"""
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")
