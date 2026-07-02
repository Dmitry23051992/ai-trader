#!/usr/bin/env python3
"""
Deploy the best AI-generated strategy to the running Freqtrade bot.

Usage:
    python scripts/deploy_strategy.py                    # deploy best by profit
    python scripts/deploy_strategy.py --name EMA_RSI_0005  # deploy specific strategy
    python scripts/deploy_strategy.py --dry-run            # show what would be deployed
    python scripts/deploy_strategy.py --rollback          # restore SampleStrategy
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def find_backtest_results() -> list[dict]:
    """Parse backtest result files from Freqtrade."""
    results_dir = Path("freqtrade/user_data/backtest_results")
    if not results_dir.exists():
        print("❌ Backtest results directory not found.")
        return []

    results: list[dict] = []
    for f in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            # Extract strategy stats
            for strategy_name, stats in data.get("strategy", {}).items():
                total_profit = stats.get("profit_total", 0)
                total_profit_pct = stats.get("profit_total_pct", 0)
                sharpe = stats.get("sharpe", 0)
                trades = stats.get("total_trades", 0)
                winrate = stats.get("winrate", 0)
                drawdown = stats.get("max_drawdown", 0)

                results.append({
                    "name": strategy_name,
                    "file": str(f),
                    "profit": total_profit,
                    "profit_pct": total_profit_pct,
                    "sharpe": sharpe,
                    "trades": trades,
                    "winrate": winrate,
                    "drawdown": drawdown,
                })
        except (json.JSONDecodeError, KeyError):
            continue

    return results


def find_strategy_files() -> list[Path]:
    """Find all AI-generated strategy files."""
    strategy_dir = Path("freqtrade/user_data/strategies")
    return sorted(strategy_dir.glob("EMA_RSI_*.py"))


def parse_backtest_from_logs() -> list[dict]:
    """Parse backtest results from pipeline logs (BACKTESTING REPORT)."""
    log_dir = Path("logs")
    results: list[dict] = []

    for log_file in sorted(log_dir.glob("*.log")):
        text = log_file.read_text(encoding="utf-8", errors="replace")

        # Find STRATEGY SUMMARY blocks
        blocks = re.findall(
            r"STRATEGY SUMMARY.*?┃\s+(\w+)\s+┃\s+(\d+)\s+┃\s+([\d.-]+)\s+┃\s+([\d.-]+)\s+┃\s+([\d.-]+)\s+┃\s+([\d\w:,]+)\s+┃\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+\.?\d*)\s+┃\s+([\d.]+)\s+USDT\s+([\d.]+)%",
            text, re.DOTALL,
        )

        for block in blocks:
            results.append({
                "name": block[0],
                "trades": int(block[1]),
                "avg_profit_pct": float(block[2]),
                "total_profit_usdt": float(block[3]),
                "total_profit_pct": float(block[4]),
                "winrate": float(block[9]) if len(block) > 9 else 0,
                "drawdown_usdt": float(block[10]) if len(block) > 10 else 0,
                "drawdown_pct": float(block[11]) if len(block) > 11 else 0,
            })

    return results


def select_best_strategy(results: list[dict]) -> dict | None:
    """Select the best strategy based on profit and Sharpe."""
    if not results:
        return None

    # Filter strategies with positive profit
    profitable = [r for r in results if r.get("profit_pct", -100) > 0 or r.get("total_profit_pct", -100) > 0]

    if profitable:
        # Sort by profit (highest first)
        profitable.sort(key=lambda r: r.get("profit_pct", 0) or r.get("total_profit_pct", 0), reverse=True)
        return profitable[0]

    # If none profitable, return the one with least loss
    results.sort(key=lambda r: r.get("profit_pct", 0) or r.get("total_profit_pct", 0), reverse=True)
    return results[0]


def deploy_strategy(strategy_name: str, dry_run: bool = False) -> bool:
    """Deploy a strategy to the running Freqtrade container."""
    strategy_path = Path(f"freqtrade/user_data/strategies/{strategy_name}.py")

    if not strategy_path.exists():
        print(f"❌ Strategy file not found: {strategy_path}")
        return False

    print(f"\n{'=' * 50}")
    print(f"📦 Deploying strategy: {strategy_name}")
    print(f"{'=' * 50}")

    # Show strategy info
    code = strategy_path.read_text()
    print(f"   File: {strategy_path} ({len(code)} bytes)")

    if dry_run:
        print(f"   ✅ Dry-run: would deploy {strategy_name} to Freqtrade")
        return True

    # Update docker-compose to use the new strategy
    compose_file = Path("freqtrade/docker-compose.yml")
    compose = compose_file.read_text()

    # Replace --strategy argument
    old_strategy = re.search(r"--strategy (\w+)", compose)
    if old_strategy:
        old_name = old_strategy.group(1)
        compose = compose.replace(f"--strategy {old_name}", f"--strategy {strategy_name}")
        compose_file.write_text(compose)
        print(f"   ✅ Updated docker-compose: {old_name} → {strategy_name}")
    else:
        print("   ⚠️ Could not find --strategy in docker-compose.yml")
        return False

    # Restart the container
    print("   🔄 Restarting Freqtrade container...")
    result = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd="freqtrade",
        capture_output=True, text=True, timeout=60,
    )

    if result.returncode == 0:
        print(f"   ✅ Container restarted. Strategy {strategy_name} is now live!")
        return True
    else:
        print(f"   ❌ Container restart failed:\n{result.stderr}")
        return False


def rollback_to_sample(dry_run: bool = False) -> bool:
    """Rollback to SampleStrategy."""
    return deploy_strategy("SampleStrategy", dry_run=dry_run)


def show_deploy_status() -> None:
    """Show current deployment status."""
    compose_file = Path("freqtrade/docker-compose.yml")
    compose = compose_file.read_text()

    match = re.search(r"--strategy (\w+)", compose)
    current = match.group(1) if match else "unknown"

    print(f"\n{'=' * 50}")
    print(f"📊 Deployment Status")
    print(f"{'=' * 50}")
    print(f"   Current strategy: {current}")

    # Check if container is running
    result = subprocess.run(
        ["docker", "ps", "--filter", "name=freqtrade", "--format", "{{.Status}}"],
        capture_output=True, text=True, timeout=10,
    )
    if result.stdout.strip():
        print(f"   Container status: {result.stdout.strip()}")
    else:
        print(f"   ❌ Container NOT running")

    # List available strategies
    print(f"\n   Available AI strategies:")
    for f in find_strategy_files():
        print(f"     • {f.stem}")


def main():
    parser = argparse.ArgumentParser(description="Deploy AI strategy to Freqtrade")
    parser.add_argument("--name", "-n", help="Strategy name to deploy (e.g., EMA_RSI_0005)")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Show what would be deployed")
    parser.add_argument("--rollback", "-r", action="store_true", help="Rollback to SampleStrategy")
    parser.add_argument("--status", "-s", action="store_true", help="Show deployment status")
    parser.add_argument("--list", "-l", action="store_true", help="List all strategies")
    args = parser.parse_args()

    if args.status:
        show_deploy_status()
        return

    if args.list:
        print(f"\n{'=' * 50}")
        print(f"📋 Generated Strategies")
        print(f"{'=' * 50}")
        for f in find_strategy_files():
            code = f.read_text()
            print(f"  • {f.stem} ({len(code)} bytes)")
        return

    if args.rollback:
        rollback_to_sample(dry_run=args.dry_run)
        return

    if args.name:
        deploy_strategy(args.name, dry_run=args.dry_run)
        return

    # Auto-select best strategy
    print("🔍 Searching for best strategy...")

    # Try backtest result files first
    results = find_backtest_results()
    if not results:
        print("   No backtest result files found. Checking logs...")
        results = parse_backtest_from_logs()

    if not results:
        print("   No backtest results found. Please run the pipeline first.")
        print("   Usage: python main.py --bootstrap --iterations 5")
        return

    best = select_best_strategy(results)
    if not best:
        print("   Could not determine best strategy.")
        return

    profit = best.get("profit_pct", 0) or best.get("total_profit_pct", 0)
    print(f"   Best strategy: {best['name']} (profit: {profit:+.2f}%)")

    if profit < -5:
        print(f"   ⚠️ Best strategy is still losing ({profit:+.2f}%). Deploy anyway?")
        print(f"   Use --name to force deploy.")

    deploy_strategy(best["name"], dry_run=args.dry_run)


if __name__ == "__main__":
    main()
