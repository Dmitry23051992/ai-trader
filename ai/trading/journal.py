from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

from configs.settings import TRADE_DB_PATH


class TradeJournal:
    def __init__(self, db_path: Path | str = TRADE_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = duckdb.connect(str(self.db_path))
        self._create_schema()

    def _create_schema(self) -> None:
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_events(
                event_time TIMESTAMP,
                iteration INTEGER,
                trade_mode VARCHAR,
                action VARCHAR,
                status VARCHAR,
                symbol VARCHAR,
                side VARCHAR,
                amount DOUBLE,
                price DOUBLE,
                notional_usdt DOUBLE,
                confidence DOUBLE,
                stop_loss_pct DOUBLE,
                take_profit_pct DOUBLE,
                trailing_stop_pct DOUBLE,
                reason VARCHAR,
                payload VARCHAR
            )
            """
        )

        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_outcomes(
                outcome_time TIMESTAMP,
                iteration INTEGER,
                symbol VARCHAR,
                side VARCHAR,
                entry_price DOUBLE,
                exit_price DOUBLE,
                amount DOUBLE,
                fees DOUBLE,
                pnl_usdt DOUBLE,
                pnl_pct DOUBLE,
                was_win BOOLEAN,
                hold_bars INTEGER,
                regime VARCHAR,
                volatility VARCHAR,
                confidence DOUBLE,
                mistake VARCHAR,
                lesson VARCHAR,
                payload VARCHAR
            )
            """
        )

        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS open_positions(
                opened_at TIMESTAMP,
                updated_at TIMESTAMP,
                entry_iteration INTEGER,
                trade_mode VARCHAR,
                symbol VARCHAR,
                position_side VARCHAR,
                amount DOUBLE,
                entry_price DOUBLE,
                notional_usdt DOUBLE,
                stop_loss_pct DOUBLE,
                take_profit_pct DOUBLE,
                trailing_stop_pct DOUBLE,
                confidence DOUBLE,
                regime VARCHAR,
                volatility VARCHAR,
                reason VARCHAR,
                payload VARCHAR
            )
            """
        )

        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS adaptive_params(
                updated_at TIMESTAMP,
                decision_confidence_threshold DOUBLE,
                position_size_multiplier DOUBLE,
                stop_loss_multiplier DOUBLE,
                take_profit_multiplier DOUBLE,
                caution_mode BOOLEAN,
                based_on_trades INTEGER,
                winrate DOUBLE,
                profit_factor DOUBLE,
                reason VARCHAR,
                payload VARCHAR
            )
            """
        )

    def record(self, ctx, execution: dict[str, Any]) -> None:
        payload = execution.get("payload", {})
        self.db.execute(
            """
            INSERT INTO trade_events VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                datetime.now(timezone.utc),
                int(getattr(ctx, "iteration", 0) or 0),
                str((ctx.market or {}).get("trade_mode", "wait")),
                str(execution.get("action", "wait")),
                str(execution.get("status", "unknown")),
                str(execution.get("symbol", "")),
                str(execution.get("side", "")),
                float(execution.get("amount", 0.0) or 0.0),
                float(execution.get("price", 0.0) or 0.0),
                float(execution.get("notional_usdt", 0.0) or 0.0),
                float((ctx.decision or {}).get("confidence", 0.0) or 0.0),
                float(execution.get("stop_loss_pct", 0.0) or 0.0),
                float(execution.get("take_profit_pct", 0.0) or 0.0),
                float(execution.get("trailing_stop_pct", 0.0) or 0.0),
                str(execution.get("reason", "")),
                str(payload),
            ],
        )

    def record_outcome(self, ctx, outcome: dict[str, Any]) -> None:
        payload = outcome.get("payload", {})
        self.db.execute(
            """
            INSERT INTO trade_outcomes VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                datetime.now(timezone.utc),
                int(getattr(ctx, "iteration", 0) or 0),
                str(outcome.get("symbol", "")),
                str(outcome.get("side", "")),
                float(outcome.get("entry_price", 0.0) or 0.0),
                float(outcome.get("exit_price", 0.0) or 0.0),
                float(outcome.get("amount", 0.0) or 0.0),
                float(outcome.get("fees", 0.0) or 0.0),
                float(outcome.get("pnl_usdt", 0.0) or 0.0),
                float(outcome.get("pnl_pct", 0.0) or 0.0),
                bool(outcome.get("was_win", False)),
                int(outcome.get("hold_bars", 0) or 0),
                str(outcome.get("regime", "")),
                str(outcome.get("volatility", "")),
                float(outcome.get("confidence", 0.0) or 0.0),
                str(outcome.get("mistake", "")),
                str(outcome.get("lesson", "")),
                str(payload),
            ],
        )

    def get_open_position(self, symbol: str, trade_mode: str) -> dict[str, Any] | None:
        row = self.db.execute(
            """
            SELECT
                opened_at,
                updated_at,
                entry_iteration,
                trade_mode,
                symbol,
                position_side,
                amount,
                entry_price,
                notional_usdt,
                stop_loss_pct,
                take_profit_pct,
                trailing_stop_pct,
                confidence,
                regime,
                volatility,
                reason,
                payload
            FROM open_positions
            WHERE symbol = ? AND trade_mode = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            [str(symbol), str(trade_mode)],
        ).fetchone()

        if not row:
            return None

        columns = [
            "opened_at",
            "updated_at",
            "entry_iteration",
            "trade_mode",
            "symbol",
            "position_side",
            "amount",
            "entry_price",
            "notional_usdt",
            "stop_loss_pct",
            "take_profit_pct",
            "trailing_stop_pct",
            "confidence",
            "regime",
            "volatility",
            "reason",
            "payload",
        ]
        return dict(zip(columns, row, strict=False))

    def upsert_open_position(self, ctx, execution: dict[str, Any]) -> dict[str, Any]:
        trade_mode = str(execution.get("mode") or (ctx.market or {}).get("trade_mode", "paper"))
        symbol = str(execution.get("symbol", ""))
        now = datetime.now(timezone.utc)

        self.db.execute(
            "DELETE FROM open_positions WHERE symbol = ? AND trade_mode = ?",
            [symbol, trade_mode],
        )

        self.db.execute(
            """
            INSERT INTO open_positions VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                now,
                now,
                int(getattr(ctx, "iteration", 0) or 0),
                trade_mode,
                symbol,
                "long",
                float(execution.get("amount", 0.0) or 0.0),
                float(execution.get("price", 0.0) or 0.0),
                float(execution.get("notional_usdt", 0.0) or 0.0),
                float(execution.get("stop_loss_pct", 0.0) or 0.0),
                float(execution.get("take_profit_pct", 0.0) or 0.0),
                float(execution.get("trailing_stop_pct", 0.0) or 0.0),
                float((ctx.decision or {}).get("confidence", 0.0) or 0.0),
                str((ctx.market or {}).get("regime", "")),
                str((ctx.market or {}).get("volatility", "")),
                str(execution.get("reason", "")),
                str(execution.get("payload", {})),
            ],
        )

        return self.get_open_position(symbol, trade_mode) or {}

    def close_open_position(self, ctx, execution: dict[str, Any], fees: float = 0.0) -> dict[str, Any] | None:
        trade_mode = str(execution.get("mode") or (ctx.market or {}).get("trade_mode", "paper"))
        symbol = str(execution.get("symbol", ""))
        position = self.get_open_position(symbol, trade_mode)
        if not position:
            return None

        entry_price = float(position.get("entry_price", 0.0) or 0.0)
        exit_price = float(execution.get("price", 0.0) or 0.0)
        amount = float(position.get("amount", 0.0) or 0.0)
        pnl_usdt = ((exit_price - entry_price) * amount) - float(fees or 0.0)
        pnl_pct = ((exit_price - entry_price) / entry_price * 100.0) if entry_price > 0 else 0.0

        outcome = {
            "symbol": symbol,
            "side": str(position.get("position_side", "long")),
            "entry_price": round(entry_price, 8),
            "exit_price": round(exit_price, 8),
            "amount": round(amount, 8),
            "fees": round(float(fees or 0.0), 8),
            "pnl_usdt": round(pnl_usdt, 8),
            "pnl_pct": round(pnl_pct, 4),
            "was_win": pnl_usdt > 0.0,
            "hold_bars": max(int(getattr(ctx, "iteration", 0) or 0) - int(position.get("entry_iteration", 0) or 0), 0),
            "regime": str((ctx.market or {}).get("regime") or position.get("regime", "")),
            "volatility": str((ctx.market or {}).get("volatility") or position.get("volatility", "")),
            "confidence": float((ctx.decision or {}).get("confidence", position.get("confidence", 0.0)) or 0.0),
            "mistake": "",
            "lesson": "",
            "payload": {
                "entry_reason": position.get("reason", ""),
                "exit_reason": execution.get("reason", ""),
                "trade_mode": trade_mode,
            },
        }

        self.db.execute(
            "DELETE FROM open_positions WHERE symbol = ? AND trade_mode = ?",
            [symbol, trade_mode],
        )

        return outcome

    def active_positions(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """
            SELECT
                opened_at,
                updated_at,
                entry_iteration,
                trade_mode,
                symbol,
                position_side,
                amount,
                entry_price,
                notional_usdt,
                stop_loss_pct,
                take_profit_pct,
                trailing_stop_pct,
                confidence,
                regime,
                volatility,
                reason,
                payload
            FROM open_positions
            ORDER BY updated_at DESC
            """
        ).fetchall()

        columns = [
            "opened_at",
            "updated_at",
            "entry_iteration",
            "trade_mode",
            "symbol",
            "position_side",
            "amount",
            "entry_price",
            "notional_usdt",
            "stop_loss_pct",
            "take_profit_pct",
            "trailing_stop_pct",
            "confidence",
            "regime",
            "volatility",
            "reason",
            "payload",
        ]
        return [dict(zip(columns, row, strict=False)) for row in rows]

    def save_adaptive_params(self, params: dict[str, Any]) -> None:
        self.db.execute("DELETE FROM adaptive_params")
        self.db.execute(
            """
            INSERT INTO adaptive_params VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                datetime.now(timezone.utc),
                float(params.get("decision_confidence_threshold", 0.0) or 0.0),
                float(params.get("position_size_multiplier", 1.0) or 1.0),
                float(params.get("stop_loss_multiplier", 1.0) or 1.0),
                float(params.get("take_profit_multiplier", 1.0) or 1.0),
                bool(params.get("caution_mode", False)),
                int(params.get("based_on_trades", 0) or 0),
                float(params.get("winrate", 0.0) or 0.0),
                float(params.get("profit_factor", 0.0) or 0.0),
                str(params.get("reason", "")),
                str(params.get("payload", {})),
            ],
        )

    def get_adaptive_params(self) -> dict[str, Any]:
        row = self.db.execute(
            """
            SELECT
                updated_at,
                decision_confidence_threshold,
                position_size_multiplier,
                stop_loss_multiplier,
                take_profit_multiplier,
                caution_mode,
                based_on_trades,
                winrate,
                profit_factor,
                reason,
                payload
            FROM adaptive_params
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ).fetchone()

        if not row:
            return {}

        columns = [
            "updated_at",
            "decision_confidence_threshold",
            "position_size_multiplier",
            "stop_loss_multiplier",
            "take_profit_multiplier",
            "caution_mode",
            "based_on_trades",
            "winrate",
            "profit_factor",
            "reason",
            "payload",
        ]
        return dict(zip(columns, row, strict=False))

    def count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0])

    def outcomes_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM trade_outcomes").fetchone()[0])

    def recent_outcomes(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """
            SELECT
                outcome_time,
                iteration,
                symbol,
                side,
                entry_price,
                exit_price,
                amount,
                fees,
                pnl_usdt,
                pnl_pct,
                was_win,
                hold_bars,
                regime,
                volatility,
                confidence,
                mistake,
                lesson,
                payload
            FROM trade_outcomes
            ORDER BY outcome_time DESC
            LIMIT ?
            """,
            [int(limit)],
        ).fetchall()

        columns = [
            "outcome_time",
            "iteration",
            "symbol",
            "side",
            "entry_price",
            "exit_price",
            "amount",
            "fees",
            "pnl_usdt",
            "pnl_pct",
            "was_win",
            "hold_bars",
            "regime",
            "volatility",
            "confidence",
            "mistake",
            "lesson",
            "payload",
        ]
        return [dict(zip(columns, row, strict=False)) for row in rows]

    def performance_summary(self, limit: int = 50) -> dict[str, Any]:
        rows = self.db.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN was_win THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN NOT was_win THEN 1 ELSE 0 END) AS losses,
                COALESCE(SUM(pnl_usdt), 0) AS total_pnl_usdt,
                COALESCE(AVG(pnl_pct), 0) AS avg_pnl_pct,
                COALESCE(AVG(CASE WHEN was_win THEN pnl_pct END), 0) AS avg_win_pct,
                COALESCE(AVG(CASE WHEN NOT was_win THEN pnl_pct END), 0) AS avg_loss_pct,
                COALESCE(SUM(CASE WHEN pnl_usdt > 0 THEN pnl_usdt ELSE 0 END), 0) AS gross_profit_usdt,
                COALESCE(ABS(SUM(CASE WHEN pnl_usdt < 0 THEN pnl_usdt ELSE 0 END)), 0) AS gross_loss_usdt
            FROM (
                SELECT * FROM trade_outcomes
                ORDER BY outcome_time DESC
                LIMIT ?
            )
            """,
            [int(limit)],
        ).fetchone()

        total = int(rows[0] or 0)
        wins = int(rows[1] or 0)
        losses = int(rows[2] or 0)
        total_pnl_usdt = float(rows[3] or 0.0)
        avg_pnl_pct = float(rows[4] or 0.0)
        avg_win_pct = float(rows[5] or 0.0)
        avg_loss_pct = float(rows[6] or 0.0)
        gross_profit_usdt = float(rows[7] or 0.0)
        gross_loss_usdt = float(rows[8] or 0.0)

        winrate = (wins / total) if total else 0.0
        profit_factor = (
            gross_profit_usdt / gross_loss_usdt
            if gross_loss_usdt > 0.0
            else 0.0
        )

        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "winrate": round(winrate, 3),
            "total_pnl_usdt": round(total_pnl_usdt, 4),
            "avg_pnl_pct": round(avg_pnl_pct, 4),
            "avg_win_pct": round(avg_win_pct, 4),
            "avg_loss_pct": round(avg_loss_pct, 4),
            "gross_profit_usdt": round(gross_profit_usdt, 4),
            "gross_loss_usdt": round(gross_loss_usdt, 4),
            "profit_factor": round(profit_factor, 3),
        }

    def consecutive_losses(self, limit: int = 20) -> int:
        rows = self.db.execute(
            """
            SELECT was_win
            FROM trade_outcomes
            ORDER BY outcome_time DESC
            LIMIT ?
            """,
            [int(limit)],
        ).fetchall()

        streak = 0
        for row in rows:
            was_win = bool(row[0])
            if was_win:
                break
            streak += 1
        return streak

    def daily_pnl_usdt(self, target_date: datetime | None = None) -> float:
        current = target_date.astimezone(timezone.utc) if target_date else datetime.now(timezone.utc)
        start = datetime.combine(current.date(), time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)

        row = self.db.execute(
            """
            SELECT COALESCE(SUM(pnl_usdt), 0)
            FROM trade_outcomes
            WHERE outcome_time >= ? AND outcome_time < ?
            """,
            [start, end],
        ).fetchone()

        return float((row or [0.0])[0] or 0.0)

    def risk_guard(self, portfolio_usdt: float, max_daily_loss_pct: float, max_consecutive_losses: int) -> dict[str, Any]:
        daily_pnl = self.daily_pnl_usdt()
        consecutive_losses = self.consecutive_losses(limit=max(20, int(max_consecutive_losses) * 3))
        daily_loss_pct = abs(min(daily_pnl, 0.0)) / portfolio_usdt * 100.0 if portfolio_usdt > 0 else 0.0

        blocked = False
        reasons: list[str] = []

        if max_daily_loss_pct > 0 and daily_loss_pct >= max_daily_loss_pct:
            blocked = True
            reasons.append(
                f"Daily realized loss {round(daily_loss_pct, 2)}% reached the limit {round(max_daily_loss_pct, 2)}%."
            )

        if max_consecutive_losses > 0 and consecutive_losses >= max_consecutive_losses:
            blocked = True
            reasons.append(
                f"Consecutive losses {consecutive_losses} reached the limit {int(max_consecutive_losses)}."
            )

        return {
            "blocked": blocked,
            "daily_pnl_usdt": round(daily_pnl, 4),
            "daily_loss_pct": round(daily_loss_pct, 4),
            "consecutive_losses": consecutive_losses,
            "max_daily_loss_pct": float(max_daily_loss_pct),
            "max_consecutive_losses": int(max_consecutive_losses),
            "reason": " ".join(reasons),
        }

    def close(self) -> None:
        self.db.close()