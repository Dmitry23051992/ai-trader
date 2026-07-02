"""
Global project settings.

Все остальные модули импортируют настройки отсюда.
Для единого источника конфигурации используется Pydantic-схема.

Usage:
    from configs.settings import (
        DB_PATH, EXCHANGE, TIMEFRAMES, ...
    )
    # или напрямую:
    from configs.schema import load_config
    cfg = load_config()
"""

from pathlib import Path

from configs.schema import AppConfig, load_config

# ── Lazily-loaded singleton ──────────────────────────────────────────

_cfg: AppConfig | None = None


def _config() -> AppConfig:
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Paths                                                              ║
# ╚══════════════════════════════════════════════════════════════════════╝

PROJECT_ROOT = Path(__file__).resolve().parent.parent

AI_DIR = PROJECT_ROOT / _config().paths.ai_dir
DATABASE_DIR = PROJECT_ROOT / _config().paths.database_dir
DB_PATH = PROJECT_ROOT / _config().paths.database_dir / "market.duckdb"
TRADE_DB_PATH = PROJECT_ROOT / _config().paths.database_dir / "trades.duckdb"
LOG_DIR = PROJECT_ROOT / _config().paths.log_dir
MODEL_DIR = PROJECT_ROOT / _config().paths.model_dir
REPORT_DIR = PROJECT_ROOT / _config().paths.report_dir

FREQTRADE_DIR = PROJECT_ROOT / _config().paths.freqtrade_dir
STRATEGY_DIR = PROJECT_ROOT / _config().paths.strategy_dir
BACKTEST_RESULTS_DIR = PROJECT_ROOT / _config().paths.backtest_results_dir

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Exchange                                                           ║
# ╚══════════════════════════════════════════════════════════════════════╝

EXCHANGE = _config().exchange.name
MARKET_TYPE = _config().exchange.market_type
BINANCE_TESTNET = _config().exchange.testnet
SYMBOLS = list(_config().exchange.symbols)
TIMEFRAMES = list(_config().exchange.timeframes)
MARKET_ANALYSIS_SYMBOLS = list(_config().exchange.analysis_symbols)
MARKET_ANALYSIS_TIMEFRAMES = list(_config().exchange.analysis_timeframes)
MARKET_LOOKBACK_BARS = _config().exchange.lookback_bars
MARKET_TREND_ADX_THRESHOLD = _config().exchange.trend_adx_threshold
START_DATE = _config().exchange.start_date
DOWNLOAD_LIMIT = _config().exchange.download_limit
REQUEST_DELAY = _config().exchange.request_delay
UPDATE_OVERLAP = _config().exchange.update_overlap

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Risk Management                                                    ║
# ╚══════════════════════════════════════════════════════════════════════╝

DECISION_CONFIDENCE_THRESHOLD = _config().risk.decision_confidence_threshold
BASE_POSITION_SIZE_PCT = _config().risk.base_position_size_pct
MAX_POSITION_SIZE_PCT = _config().risk.max_position_size_pct
MIN_POSITION_SIZE_PCT = _config().risk.min_position_size_pct
BASE_STOP_LOSS_PCT = _config().risk.base_stop_loss_pct
BASE_TAKE_PROFIT_PCT = _config().risk.base_take_profit_pct
BASE_TRAILING_STOP_PCT = _config().risk.base_trailing_stop_pct
MAX_DAILY_LOSS_PCT = _config().risk.max_daily_loss_pct
MAX_CONSECUTIVE_LOSSES = _config().risk.max_consecutive_losses

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Execution                                                          ║
# ╚══════════════════════════════════════════════════════════════════════╝

EXECUTION_MODE = _config().execution.mode
EXECUTION_MARKET_TYPE = _config().exchange.market_type
PAPER_PORTFOLIO_USDT = _config().execution.paper_portfolio_usdt
DEFAULT_ORDER_TYPE = _config().execution.default_order_type

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Machine Learning / Adaptive                                        ║
# ╚══════════════════════════════════════════════════════════════════════╝

ADAPTIVE_MIN_CLOSED_TRADES = _config().adaptive.min_closed_trades
ADAPTIVE_MIN_POSITION_SIZE_MULTIPLIER = _config().adaptive.min_position_size_multiplier
ADAPTIVE_MAX_POSITION_SIZE_MULTIPLIER = _config().adaptive.max_position_size_multiplier
ADAPTIVE_MAX_CONFIDENCE_THRESHOLD = _config().adaptive.max_confidence_threshold
ADAPTIVE_MIN_CONFIDENCE_THRESHOLD = _config().adaptive.min_confidence_threshold
RANDOM_SEED = _config().adaptive.random_seed
TRAIN_TEST_SPLIT = _config().adaptive.train_test_split
VALIDATION_SPLIT = _config().adaptive.validation_split
