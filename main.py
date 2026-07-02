#!/usr/bin/env python3
"""
AI Trader — main entry point.

Orchestrates the full agent pipeline: Market → Decision → Risk → Execution
→ Strategy → Validator → Backtest → Learning.

Usage:
    python main.py                        # default: 3 iterations, paper mode
    python main.py --iterations 5         # custom loop count
    python main.py --fail-fast            # stop on first agent error
    python main.py --live                 # enable live execution mode
"""

from __future__ import annotations

import argparse
import sys

from core.director import Director
from core.logger import log

from agents.research.market import MarketAgent
from agents.decision.agent import DecisionAgent
from agents.risk.agent import RiskAgent
from agents.execution.agent import ExecutionAgent
from agents.strategy.agent import StrategyAgent
from agents.strategy.validator import StrategyValidator
from agents.execution.backtester import BacktestAgent
from agents.learning.analyzer import LearningAgent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Trader — autonomous trading strategy pipeline",
    )
    parser.add_argument(
        "--iterations",
        "-n",
        type=int,
        default=3,
        help="Number of pipeline iterations (default: 3)",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop pipeline on first agent error",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live execution mode (default is paper)",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Bootstrap mode: force strategy generation even in neutral markets to collect training data",
    )
    return parser.parse_args(argv)


def build_pipeline() -> list:
    """Construct the ordered list of agents."""
    return [
        MarketAgent(),
        DecisionAgent(),
        RiskAgent(),
        ExecutionAgent(),
        StrategyAgent(),
        StrategyValidator(),
        BacktestAgent(),
        LearningAgent(),
    ]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.live:
        from configs.settings import EXECUTION_MODE

        log.warning("Live execution mode requested — ensure API keys are set!")

    if args.bootstrap:
        log.warning("BOOTSTRAP MODE: forcing strategy generation to collect training data.")

    director = Director(
        iterations=args.iterations,
        fail_fast=args.fail_fast,
        bootstrap=args.bootstrap,
    )

    for agent in build_pipeline():
        director.register(agent)

    log.info("Starting pipeline: {} iterations, {} agents{}", args.iterations, len(director.pipeline),
             " (bootstrap mode)" if args.bootstrap else "")
    log.info("Pipeline: {}", [a.__class__.__name__ for a in director.pipeline])

    try:
        ctx = director.run()
    except KeyboardInterrupt:
        log.warning("Pipeline interrupted by user.")
        return 130
    except Exception as exc:
        log.opt(exception=True).critical("Pipeline crashed: {}", exc)
        return 1

    log.info("Pipeline finished. Iterations={}, Errors={}", ctx.iteration, len(ctx.errors))

    if ctx.errors:
        log.warning("Errors encountered during run:")
        for err in ctx.errors:
            log.warning("  Iter {} | {} | {}", err["iteration"], err["agent"], err["error"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
