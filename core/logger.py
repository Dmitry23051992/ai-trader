"""
Structured logging module.

Provides a pre-configured logger for the entire project.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from configs.settings import LOG_DIR


def setup_logger(
    log_dir: Path | str | None = None,
    level: str = "DEBUG",
    rotation: str = "10 MB",
    retention: str = "30 days",
):
    """Configure loguru with console and file sinks.

    Args:
        log_dir: Directory for log files. Defaults to LOG_DIR from settings.
        level: Minimum log level.
        rotation: Log rotation threshold (size or time).
        retention: How long to keep old logs.
    """
    log_dir = Path(log_dir or LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Remove default handler
    logger.remove()

    # Console — colourised, DEBUG+
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        level=level,
        colorize=True,
    )

    # File — full JSON for production analysis
    logger.add(
        log_dir / "ai_trader_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation=rotation,
        retention=retention,
        level="DEBUG",
        compression="gz",
    )

    # Error file — only WARNING+
    logger.add(
        log_dir / "errors_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation=rotation,
        retention=retention,
        level="WARNING",
        compression="gz",
    )

    return logger


log = setup_logger()
