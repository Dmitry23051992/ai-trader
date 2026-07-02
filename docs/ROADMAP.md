# Roadmap

## Цель

Сделать AI-трейдера, который на Binance сам анализирует рынок, определяет режим рынка, принимает решение `buy / sell / wait`, управляет риском и постепенно переходит от paper trading к live trading.

## Фаза 1. Market Intelligence

- Сбор свечей и биржевых данных из Binance.
- Вычисление MarketState: trend, volatility, regime, confidence.
- Определение торгового режима: trade, wait, protect.
- Поддержка нескольких таймфреймов: 15m, 1h, 4h.

## Фаза 2. Decision Engine

- Отдельный модуль для принятия решения на основе MarketState.
- Правила входа, подтверждения входа, отмены сделки и выхода.
- Поддержка стратегии "не торговать, если edge слабый".

## Фаза 3. Risk Engine

- Размер позиции от риска, а не от эмоций.
- Stop loss, take profit, trailing logic.
- Ограничения по дневной просадке и количеству сделок.
- Динамическая адаптация к confidence, volatility и regime.
- Защита от серии убыточных сделок и overtrading.

## Фаза 4. Execution Layer

- Адаптер для Binance spot/futures.
- Paper trading сначала, live trading потом.
- Execution intent планируется отдельно от стратегии и backtest.
- Журнал сделок и intents в DuckDB.
- Проверка статуса ордеров, частичное исполнение, retry logic.

## Фаза 5. Learning Loop

- Парсинг отчетов backtest и paper trading.
- Запись закрытых сделок в журнал и анализ их результатов.
- Выбор лучших стратегий по метрикам.
- Авто-улучшение промптов и параметров стратегии.

## Фаза 6. Production Hardening

- Логи, алерты, мониторинг.
- Тесты для критических модулей.
- CI для синтаксиса, unit tests и dry-run.

## Что делать дальше прямо сейчас

1. Добавить ограничения по серии убытков и дневной просадке.
2. Расширить execution до статусов ордеров, partial fills и live sync c биржей.
3. Добавить ранжирование стратегий по метрикам backtest и paper trading.
