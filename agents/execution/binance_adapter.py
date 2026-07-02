from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from configs.settings import (
    BINANCE_TESTNET,
    DEFAULT_ORDER_TYPE,
    EXECUTION_MARKET_TYPE,
    EXECUTION_MODE,
    PAPER_PORTFOLIO_USDT,
)


@dataclass
class ExecutionIntent:
    mode: str
    status: str
    action: str
    symbol: str
    side: str
    amount: float
    price: float
    notional_usdt: float
    position_size_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    trailing_stop_pct: float
    order_type: str = DEFAULT_ORDER_TYPE
    exchange: str = "binance"
    order_id: str = ""
    reason: str = ""
    payload: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "status": self.status,
            "action": self.action,
            "symbol": self.symbol,
            "side": self.side,
            "amount": round(self.amount, 8),
            "price": round(self.price, 8),
            "notional_usdt": round(self.notional_usdt, 8),
            "position_size_pct": round(self.position_size_pct, 2),
            "stop_loss_pct": round(self.stop_loss_pct, 2),
            "take_profit_pct": round(self.take_profit_pct, 2),
            "trailing_stop_pct": round(self.trailing_stop_pct, 2),
            "order_type": self.order_type,
            "exchange": self.exchange,
            "order_id": self.order_id,
            "reason": self.reason,
            "payload": self.payload or {},
        }


class BinanceExecutionAdapter:

    def __init__(self, execution_mode: str = EXECUTION_MODE):
        self.execution_mode = execution_mode.lower().strip()
        self.paper_portfolio_usdt = PAPER_PORTFOLIO_USDT

        self.exchange = None
        if self.execution_mode == "live":
            self.exchange = self._build_exchange()

    def _build_exchange(self):
        try:
            import ccxt
        except ImportError as exc:
            raise RuntimeError("ccxt is required for live execution") from exc

        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")

        if not api_key or not api_secret:
            raise RuntimeError(
                "BINANCE_API_KEY and BINANCE_API_SECRET are required for live execution."
            )

        exchange = ccxt.binance(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {
                    "defaultType": EXECUTION_MARKET_TYPE,
                },
            }
        )

        if BINANCE_TESTNET:
            exchange.set_sandbox_mode(True)

        return exchange

    def plan_execution(self, ctx) -> ExecutionIntent:
        market = ctx.market or {}
        decision = ctx.decision or {}
        risk = ctx.risk or {}

        action = decision.get("action", "wait")
        selected_state = self._select_state(market.get("states", []), action)
        symbol = selected_state.get("symbol") if selected_state else "BTC/USDT"
        price = float(selected_state.get("last_price", 0.0) or 0.0)

        if price <= 0.0:
            price = self._fallback_price(selected_state, market)

        side = "buy" if action == "buy" else "sell"
        position_size_pct = float(risk.get("position_size_pct", 0.0) or 0.0)
        stop_loss_pct = float(risk.get("stop_loss_pct", 0.0) or 0.0)
        take_profit_pct = float(risk.get("take_profit_pct", 0.0) or 0.0)
        trailing_stop_pct = float(risk.get("trailing_stop_pct", 0.0) or 0.0)

        notional_usdt = self.paper_portfolio_usdt * (position_size_pct / 100.0)
        if price > 0.0:
            amount = notional_usdt / price
        else:
            amount = 0.0

        return ExecutionIntent(
            mode=self.execution_mode,
            status="planned",
            action=action,
            symbol=symbol,
            side=side,
            amount=amount,
            price=price,
            notional_usdt=notional_usdt,
            position_size_pct=position_size_pct,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            trailing_stop_pct=trailing_stop_pct,
            reason=decision.get("reason", ""),
        )

    def execute(self, ctx) -> dict[str, Any]:
        intent = self.plan_execution(ctx)

        return self.execute_intent(intent)

    def execute_intent(self, intent: ExecutionIntent) -> dict[str, Any]:

        if intent.action == "wait":
            intent.status = "skipped"
            intent.reason = "Decision engine selected wait."
            return intent.as_dict()

        if self.execution_mode == "paper":
            intent.status = "paper_executed"
            intent.reason = "Paper execution only; no real order placed."
            return intent.as_dict()

        order = self.exchange.create_order(
            symbol=intent.symbol,
            type=intent.order_type,
            side=intent.side,
            amount=float(intent.amount),
        )

        intent.status = "live_executed"
        intent.order_id = str(order.get("id", ""))
        intent.payload = order
        intent.reason = "Live order submitted to Binance."
        return intent.as_dict()

    def _select_state(self, states: list[dict[str, Any]], action: str) -> dict[str, Any] | None:
        if not states:
            return None

        preferred = [
            state
            for state in states
            if (action == "buy" and state.get("recommendation") == "buy")
            or (action == "sell" and state.get("recommendation") == "sell")
        ]

        candidates = preferred or states
        return max(candidates, key=lambda item: float(item.get("confidence", 0.0) or 0.0))

    def _fallback_price(self, selected_state: dict[str, Any] | None, market: dict[str, Any]) -> float:
        if selected_state and selected_state.get("last_price"):
            return float(selected_state["last_price"])

        states = market.get("states", []) or []
        for state in states:
            last_price = state.get("last_price")
            if last_price:
                return float(last_price)

        return 0.0