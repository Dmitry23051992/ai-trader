"""
Pydantic configuration schema.

This module defines the canonical settings model for the project.
All runtime settings should be read from an instance of ``AppConfig``.

Usage::

    from configs.schema import load_config

    cfg = load_config()
    cfg.exchange.symbols         # list of trading pairs
    cfg.risk.max_daily_loss_pct  # daily loss limit
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Nested models                                                      ║
# ╚══════════════════════════════════════════════════════════════════════╝


class ExchangeConfig(BaseSettings):
    """Exchange connection & data-collection settings."""

    name: str = Field(default="binance", description="Exchange name (ccxt id)")
    market_type: Literal["spot", "future"] = Field(default="spot")
    testnet: bool = Field(default=False)
    symbols: list[str] = Field(
        default=["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    )
    analysis_symbols: list[str] = Field(
        default=["BTC/USDT", "ETH/USDT"]
    )
    timeframes: list[str] = Field(
        default=["5m", "15m", "1h", "4h"]
    )
    analysis_timeframes: list[str] = Field(
        default=["15m", "1h"]
    )
    lookback_bars: int = Field(default=240, ge=20)
    trend_adx_threshold: float = Field(default=25.0, ge=0, le=100)
    start_date: str = Field(default="2019-01-01")
    download_limit: int = Field(default=1000)
    request_delay: float = Field(default=0.2, ge=0)
    update_overlap: int = Field(default=10)


class RiskConfig(BaseSettings):
    """Risk-management parameters."""

    decision_confidence_threshold: float = Field(default=0.65, ge=0, le=1)
    base_position_size_pct: float = Field(default=1.0, ge=0, le=100)
    max_position_size_pct: float = Field(default=3.0, ge=0, le=100)
    min_position_size_pct: float = Field(default=0.25, ge=0, le=100)
    base_stop_loss_pct: float = Field(default=1.5, ge=0)
    base_take_profit_pct: float = Field(default=3.0, ge=0)
    base_trailing_stop_pct: float = Field(default=1.0, ge=0)
    max_daily_loss_pct: float = Field(default=3.0, ge=0)
    max_consecutive_losses: int = Field(default=3, ge=1)


class ExecutionConfig(BaseSettings):
    """Order-execution settings."""

    mode: Literal["paper", "live"] = Field(default="paper")
    paper_portfolio_usdt: float = Field(default=1000.0, ge=0)
    default_order_type: Literal["market", "limit"] = Field(default="market")


class AdaptiveConfig(BaseSettings):
    """ML / adaptive-learning settings."""

    min_closed_trades: int = Field(default=3, ge=1)
    min_position_size_multiplier: float = Field(default=0.5, ge=0, le=1)
    max_position_size_multiplier: float = Field(default=1.25, ge=1)
    max_confidence_threshold: float = Field(default=0.85, ge=0, le=1)
    min_confidence_threshold: float = Field(default=0.55, ge=0, le=1)
    random_seed: int = Field(default=42)
    train_test_split: float = Field(default=0.8, ge=0, le=1)
    validation_split: float = Field(default=0.1, ge=0, le=1)


class PathsConfig(BaseSettings):
    """Filesystem paths (relative to project root)."""

    ai_dir: str = "ai"
    database_dir: str = "ai/database"
    log_dir: str = "logs"
    model_dir: str = "models"
    report_dir: str = "reports"
    freqtrade_dir: str = "freqtrade"
    strategy_dir: str = "freqtrade/user_data/strategies"
    backtest_results_dir: str = "freqtrade/user_data/backtest_results"

    @property
    def db_path(self) -> str:
        return f"{self.database_dir}/market.duckdb"

    @property
    def trade_db_path(self) -> str:
        return f"{self.database_dir}/trades.duckdb"


class LLMConfig(BaseSettings):
    """LLM provider settings."""

    provider: Literal["openrouter", "ollama"] = Field(default="openrouter")
    model: str = Field(default="openai/gpt-4o-mini")


class LoopConfig(BaseSettings):
    """Pipeline orchestration settings."""

    max_iterations: int = Field(default=20, ge=1, le=100)
    fail_fast: bool = Field(default=False)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Root model                                                         ║
# ╚══════════════════════════════════════════════════════════════════════╝


class AppConfig(BaseSettings):
    """Top-level application configuration.

    Settings are loaded from (in priority order):
      1. Environment variables (prefix ``AI_TRADER_`` or direct names)
      2. ``configs/ai_trader.yaml`` YAML file
      3. Defaults defined in each nested model
    """

    model_config = SettingsConfigDict(
        yaml_file=("configs/ai_trader.yaml", "ai_trader.yaml"),
        env_prefix="AI_TRADER_",
        env_nested_delimiter="__",
        extra="ignore",
        frozen=False,
    )

    # ── Core sections ──────────────────────────────────────────────
    project_root: Path = Field(default_factory=lambda: Path.cwd())
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    adaptive: AdaptiveConfig = Field(default_factory=AdaptiveConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)

    # ── Derived properties ─────────────────────────────────────────

    @property
    def db_path(self) -> Path:
        return self.project_root / self.paths.db_path

    @property
    def trade_db_path(self) -> Path:
        return self.project_root / self.paths.trade_db_path

    @property
    def log_dir(self) -> Path:
        return self.project_root / self.paths.log_dir

    @property
    def strategy_dir(self) -> Path:
        return self.project_root / self.paths.strategy_dir

    @property
    def backtest_results_dir(self) -> Path:
        return self.project_root / self.paths.backtest_results_dir

    @property
    def freqtrade_dir(self) -> Path:
        return self.project_root / self.paths.freqtrade_dir

    @field_validator("project_root", mode="before")
    @classmethod
    def _resolve_project_root(cls, v: str | Path | None) -> Path:
        if v is None:
            return Path.cwd()
        return Path(v).resolve()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load settings from YAML file, then env vars, then defaults."""
        return (
            YamlConfigSettingsSource(settings_cls),
            env_settings,
            init_settings,
        )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Convenience loader                                                 ║
# ╚══════════════════════════════════════════════════════════════════════╝

_config_cache: AppConfig | None = None


def load_config(reload: bool = False) -> AppConfig:
    """Return the singleton application config.

    Args:
        reload: If True, force re-read from disk/environment.

    Returns:
        An ``AppConfig`` instance with all settings resolved.
    """
    global _config_cache
    if _config_cache is None or reload:
        _config_cache = AppConfig()
    return _config_cache
