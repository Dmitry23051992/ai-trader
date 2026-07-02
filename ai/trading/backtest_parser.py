from __future__ import annotations

import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any


class BacktestReportParser:
    def parse(self, report_path: str | Path, strategy_name: str = "") -> dict[str, Any]:
        path = Path(report_path) if report_path else None
        if not path or not path.exists():
            return {
                "status": "missing",
                "source_path": str(report_path or ""),
            }

        try:
            payload = self._load_payload(path)
            summary = self._extract_summary(payload, strategy_name)
            summary["status"] = "parsed"
            summary["source_path"] = str(path)
            if strategy_name and not summary.get("strategy"):
                summary["strategy"] = strategy_name
            return summary
        except Exception as exc:
            return {
                "status": "invalid",
                "source_path": str(path),
                "error": str(exc),
            }

    def _load_payload(self, path: Path) -> Any:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if not name.lower().endswith(".json"):
                        continue
                    if any(excluded in name.lower() for excluded in ("config", "strategy", "metadata")):
                        continue
                    with archive.open(name) as handle:
                        return json.load(handle)
                raise ValueError("No JSON report found inside backtest archive.")

        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _extract_summary(self, payload: Any, strategy_name: str) -> dict[str, Any]:
        summary = self._summary_from_payload(payload, strategy_name)
        if summary:
            return summary

        trades = self._extract_trades(payload, strategy_name)
        if trades:
            return self._summary_from_trades(trades, strategy_name)

        raise ValueError("Backtest payload does not contain a supported summary or trades structure.")

    def _summary_from_payload(self, payload: Any, strategy_name: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        strategy_payload = payload.get("strategy")
        if isinstance(strategy_payload, dict):
            if strategy_name and isinstance(strategy_payload.get(strategy_name), dict):
                candidate = strategy_payload[strategy_name]
                if self._looks_like_summary(candidate):
                    return self._normalize_summary(candidate, strategy_name)

            nested_dicts = [
                (name, data)
                for name, data in strategy_payload.items()
                if isinstance(data, dict)
            ]
            if len(nested_dicts) == 1:
                name, data = nested_dicts[0]
                if self._looks_like_summary(data):
                    return self._normalize_summary(data, str(name))

            if self._looks_like_summary(strategy_payload):
                return self._normalize_summary(strategy_payload, strategy_name)

        comparison = payload.get("strategy_comparison")
        if isinstance(comparison, list) and comparison:
            row = None
            if strategy_name:
                row = next(
                    (
                        item for item in comparison
                        if str(item.get("key") or item.get("strategy") or item.get("strategy_name") or "") == strategy_name
                    ),
                    None,
                )
            row = row or comparison[0]
            return self._normalize_summary(row, strategy_name or str(row.get("key") or ""))

        for key in ("backtest_result", "results", "summary"):
            candidate = payload.get(key)
            if isinstance(candidate, dict):
                nested = self._summary_from_payload(candidate, strategy_name)
                if nested:
                    return nested

        return {}

    def _looks_like_summary(self, candidate: Any) -> bool:
        if not isinstance(candidate, dict):
            return False
        return any(
            key in candidate
            for key in (
                "total_trades",
                "trade_count",
                "profit_total_abs",
                "absolute_profit",
                "profit_factor",
                "max_drawdown_account",
                "sharpe",
                "sortino",
            )
        )

    def _extract_trades(self, payload: Any, strategy_name: str) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

        if not isinstance(payload, dict):
            return []

        for key in ("trades", "trade_history"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]

        strategy_payload = payload.get("strategy")
        if isinstance(strategy_payload, dict):
            strategy_block = None
            if strategy_name and isinstance(strategy_payload.get(strategy_name), dict):
                strategy_block = strategy_payload[strategy_name]
            elif len(strategy_payload) == 1:
                only_value = next(iter(strategy_payload.values()))
                if isinstance(only_value, dict):
                    strategy_block = only_value
            if isinstance(strategy_block, dict):
                for key in ("trades", "results", "trade_history"):
                    candidate = strategy_block.get(key)
                    if isinstance(candidate, list):
                        return [item for item in candidate if isinstance(item, dict)]

        return []

    def _summary_from_trades(self, trades: list[dict[str, Any]], strategy_name: str) -> dict[str, Any]:
        total = len(trades)
        wins = 0
        losses = 0
        draws = 0
        total_profit_abs = 0.0
        total_profit_ratio = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        rejected_signals = 0
        exit_reasons: Counter[str] = Counter()

        for trade in trades:
            profit_abs = self._to_float(
                trade.get("profit_abs"),
                trade.get("close_profit_abs"),
                trade.get("profit_total_abs"),
                default=0.0,
            )
            profit_ratio = self._to_float(
                trade.get("profit_ratio"),
                trade.get("close_profit"),
                trade.get("profit_pct"),
                default=0.0,
            )
            if abs(profit_ratio) > 3:
                profit_ratio = profit_ratio / 100.0

            total_profit_abs += profit_abs
            total_profit_ratio += profit_ratio
            if profit_abs > 0:
                wins += 1
                gross_profit += profit_abs
            elif profit_abs < 0:
                losses += 1
                gross_loss += abs(profit_abs)
            else:
                draws += 1

            exit_reason = str(trade.get("exit_reason") or "")
            if exit_reason:
                exit_reasons[exit_reason] += 1

            rejected_signals += int(trade.get("rejected_signals", 0) or 0)

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
        winrate = wins / total if total else 0.0
        avg_profit_pct = (total_profit_ratio / total) * 100.0 if total else 0.0

        return {
            "strategy": strategy_name,
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "winrate": round(winrate, 3),
            "profit_factor": round(profit_factor, 3),
            "absolute_profit": round(total_profit_abs, 4),
            "total_profit_pct": round(total_profit_ratio * 100.0, 4),
            "avg_profit_pct": round(avg_profit_pct, 4),
            "gross_profit": round(gross_profit, 4),
            "gross_loss": round(gross_loss, 4),
            "rejected_signals": rejected_signals,
            "top_exit_reasons": [name for name, _ in exit_reasons.most_common(3)],
        }

    def _normalize_summary(self, summary: dict[str, Any], strategy_name: str = "") -> dict[str, Any]:
        wins = int(self._to_float(summary.get("wins"), summary.get("win_count"), default=0.0))
        losses = int(self._to_float(summary.get("losses"), summary.get("loss_count"), default=0.0))
        draws = int(self._to_float(summary.get("draws"), summary.get("draw_count"), default=0.0))
        total_trades = int(
            self._to_float(
                summary.get("total_trades"),
                summary.get("trade_count"),
                summary.get("trades"),
                default=float(wins + losses + draws),
            )
        )

        winrate = self._to_float(summary.get("winrate"), summary.get("winrate_pct"), default=0.0)
        if winrate == 0.0 and total_trades > 0:
            winrate = wins / total_trades
        elif winrate > 1.0:
            winrate = winrate / 100.0

        total_profit_pct = self._to_float(
            summary.get("profit_total"),
            summary.get("total_profit_pct"),
            summary.get("tot_profit_pct"),
            default=0.0,
        )
        if abs(total_profit_pct) <= 3:
            total_profit_pct *= 100.0

        avg_profit_pct = self._to_float(
            summary.get("profit_mean"),
            summary.get("avg_profit_pct"),
            summary.get("profit_mean_pct"),
            default=0.0,
        )
        if abs(avg_profit_pct) <= 3:
            avg_profit_pct *= 100.0

        cagr = self._to_float(summary.get("cagr"), summary.get("cagr_pct"), default=0.0)
        if abs(cagr) <= 3:
            cagr *= 100.0

        max_drawdown_pct = self._to_float(
            summary.get("max_drawdown_account"),
            summary.get("max_drawdown_pct"),
            summary.get("drawdown_pct"),
            default=0.0,
        )
        if abs(max_drawdown_pct) <= 1:
            max_drawdown_pct *= 100.0

        top_exit_reasons = []
        exit_reason_stats = summary.get("exit_reason_summary") or summary.get("exit_reason_stats")
        if isinstance(exit_reason_stats, list):
            pairs = []
            for item in exit_reason_stats:
                if not isinstance(item, dict):
                    continue
                reason = str(item.get("exit_reason") or item.get("key") or item.get("name") or "")
                count = int(self._to_float(item.get("exits"), item.get("trades"), default=0.0))
                if reason:
                    pairs.append((reason, count))
            top_exit_reasons = [reason for reason, _ in sorted(pairs, key=lambda pair: pair[1], reverse=True)[:3]]

        return {
            "strategy": strategy_name or str(summary.get("key") or summary.get("strategy_name") or summary.get("strategy") or ""),
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "winrate": round(winrate, 3),
            "profit_factor": round(self._to_float(summary.get("profit_factor"), default=0.0), 3),
            "absolute_profit": round(
                self._to_float(summary.get("profit_total_abs"), summary.get("absolute_profit"), summary.get("tot_profit"), default=0.0),
                4,
            ),
            "total_profit_pct": round(total_profit_pct, 4),
            "avg_profit_pct": round(avg_profit_pct, 4),
            "max_drawdown_pct": round(max_drawdown_pct, 4),
            "sharpe": round(self._to_float(summary.get("sharpe"), summary.get("sharpe_ratio"), default=0.0), 4),
            "sortino": round(self._to_float(summary.get("sortino"), summary.get("sortino_ratio"), default=0.0), 4),
            "cagr": round(cagr, 4),
            "starting_balance": round(self._to_float(summary.get("starting_balance"), default=0.0), 4),
            "final_balance": round(self._to_float(summary.get("final_balance"), default=0.0), 4),
            "rejected_signals": int(self._to_float(summary.get("rejected_signals"), default=0.0)),
            "max_consecutive_losses": int(self._to_float(summary.get("max_consecutive_losses"), default=0.0)),
            "expectancy_ratio": round(self._to_float(summary.get("expectancy_ratio"), default=0.0), 4),
            "market_change_pct": round(self._to_float(summary.get("market_change"), default=0.0), 4),
            "top_exit_reasons": top_exit_reasons,
        }

    def _to_float(self, *values: Any, default: float = 0.0) -> float:
        for value in values:
            if value is None or value == "":
                continue
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                cleaned = value.replace("USDT", "").replace("%", "").strip()
                if "(" in cleaned:
                    cleaned = cleaned.split("(", 1)[0].strip()
                if "/" in cleaned:
                    cleaned = cleaned.split("/", 1)[0].strip()
                try:
                    return float(cleaned)
                except ValueError:
                    continue
        return float(default)