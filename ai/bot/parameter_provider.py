"""
AI Parameter Provider — связывает AI Trader pipeline с работающим Freqtrade ботом.

Позволяет AI-агенту динамически обновлять параметры стратегии
(стоплосс, тейк-профит, размер позиции) без перезапуска контейнера.

Стратегия Freqtrade читает параметры из JSON-файла на каждой свече.
AI-пайплайн записывает новые параметры после каждого цикла анализа.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logger import log


class AIParameterProvider:
    """Провайдер AI-параметров для Freqtrade стратегии.

    Параметры хранятся в JSON-файле, который одновременно читается
    стратегией (Freqtrade) и записывается AI-пайплайном.

    Usage:
        provider = AIParameterProvider()
        params = provider.load()  # читает текущие параметры
        provider.save({...})      # записывает новые параметры
    """

    def __init__(self, params_path: str | Path | None = None):
        if params_path is None:
            # По умолчанию файл рядом с конфигом Freqtrade
            params_path = Path(
                __file__
            ).parent.parent.parent / "freqtrade" / "user_data" / "ai_params.json"
        self.params_path = Path(params_path)
        self._cache: dict[str, Any] | None = None
        self._mtime: float = 0.0

    # ── Публичные методы ──────────────────────────────────────────

    def load(self, force: bool = False) -> dict[str, Any]:
        """Загрузить AI-параметры из JSON-файла.

        Args:
            force: Принудительно перечитать файл (сбросить кеш).

        Returns:
            Словарь с AI-параметрами. Если файла нет — возвращает
            пустой словарь (стратегия использует значения по умолчанию).
        """
        path = self.params_path
        if not path.exists():
            return {}

        # Используем кеш, если файл не менялся
        current_mtime = path.stat().st_mtime
        if not force and self._cache is not None and current_mtime <= self._mtime:
            return self._cache

        try:
            with open(path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
            self._cache = data
            self._mtime = current_mtime
            log.debug("AIParameterProvider: loaded {} params from {}", len(data), path)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("AIParameterProvider: failed to load params: {}", exc)
            return {}

    def save(self, params: dict[str, Any]) -> None:
        """Сохранить AI-параметры в JSON-файл.

        Args:
            params: Словарь с параметрами для стратегии.
                    Ключи и значения зависят от стратегии, но
                    рекомендуется использовать:
                    - stoploss (float, напр. -0.025)
                    - trailing_stop_positive (float)
                    - minimal_roi (dict)
                    - position_size_pct (float)
                    - confidence_threshold (float)
                    - market_regime (str)
        """
        # Добавляем метаданные
        payload = {
            **params,
            "_updated_at": datetime.now(timezone.utc).isoformat(),
            "_version": 2,
        }

        path = self.params_path
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            self._cache = payload
            self._mtime = path.stat().st_mtime
            log.info(
                "AIParameterProvider: saved {} params to {}",
                len(params),
                path,
            )
        except OSError as exc:
            log.error("AIParameterProvider: failed to save params: {}", exc)

    def get(self, key: str, default: Any = None) -> Any:
        """Прочитать конкретный параметр.

        Args:
            key: Имя параметра.
            default: Значение по умолчанию.

        Returns:
            Значение параметра или default.
        """
        data = self.load()
        return data.get(key, default)

    def clear(self) -> None:
        """Очистить файл параметров (сброс к дефолтам стратегии)."""
        try:
            if self.params_path.exists():
                self.params_path.unlink()
            self._cache = None
            self._mtime = 0.0
            log.info("AIParameterProvider: params file cleared.")
        except OSError as exc:
            log.error("AIParameterProvider: failed to clear params: {}", exc)
