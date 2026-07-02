# AI Trader

AI-пайплайн для генерации, проверки, исполнения и бэктеста торговых решений для Binance.

## Что уже работает

- Оркестратор запускает агентов по шагам: `Market -> Decision -> Risk -> Execution -> Strategy -> Validator -> Backtest -> Learning`.
- Стратегия генерируется через LLM и сохраняется в `freqtrade/user_data/strategies`.
- Перед бэктестом выполняется синтаксическая проверка Python.
- Бэктест запускается через `docker compose` из папки `freqtrade`.
- LearningAgent читает экспортированный backtest report из `freqtrade/user_data/backtest_results`.
- MarketAgent уже анализирует свечи из DuckDB и строит торговый режим по данным рынка Binance.
- DecisionAgent выбирает `buy / sell / wait`, а RiskAgent считает размер позиции и защитные уровни.
- ExecutionAgent формирует paper/live intent для Binance и по умолчанию работает в paper mode.
- ExecutionAgent пишет каждое исполнение в DuckDB-журнал сделок и хранит open positions.
- При закрытии позиции ExecutionAgent автоматически записывает outcome сделки в journal.
- LearningAgent анализирует закрытые сделки и сохраняет adaptive decision/risk параметры по winrate и profit factor.
- LearningAgent также парсит backtest artifacts Freqtrade из `json` и `zip` форматов.

## Быстрый старт

1. Установить зависимости Python (рекомендуется venv):

```bash
pip install requests python-dotenv
```

2. Создать `.env` в корне проекта:

```env
OPENROUTER_API_KEY=your_key
OPENROUTER_MODEL=your_model
```

3. Подготовить каталог `freqtrade` (рядом с этим README) и рабочую docker-конфигурацию Freqtrade.

4. Запустить оркестратор:

```bash
python main.py
```

## Важные правила проекта

- Не изменять исходный код Freqtrade.
- Стратегии хранить только в `freqtrade/user_data/strategies`.
- После изменения стратегии выполнять валидацию и бэктест.

## Ближайшие шаги развития

- Ввести отдельный Decision Engine, который будет выдавать `buy / sell / wait` на основе MarketState.
- Подключить Binance paper trading и затем live trading через execution adapter.
- Усилить RiskEngine: дневной лимит сделок, защита от серии убытков, адаптация к режиму рынка.
- Подключить live execution только после стабильного paper trading и положительной статистики.
- Ввести метрики качества (profit, drawdown, winrate) и авто-ранжирование стратегий.
- Добавить тесты для агентов и CI-проверки.
