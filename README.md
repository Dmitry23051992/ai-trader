# 🤖 AI Trader

![License](https://img.shields.io/badge/license-MIT-blue)
[![CI](https://github.com/Dmitry23051992/ai-trader/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/Dmitry23051992/ai-trader/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20|%203.12-blue)

**Автономная AI-система для разработки, тестирования и исполнения торговых стратегий на Binance через Freqtrade.**

Система работает в двух режимах, которые можно использовать независимо или вместе:

1. **Orchestrator Pipeline** — многоагентный пайплайн на Python: анализ рынка → принятие решения → управление риском → генерация стратегии → бэктест → обучение.
2. **AI Daemon** — непрерывный процесс, который каждые 15 минут анализирует рынок через локальную LLM (Ollama) и управляет параметрами живой стратегии Freqtrade через JSON-файл.

---

## 🏗 Архитектура

```
┌────────────────────────────────────────────────────────────────────┐
│                     AI Trader System                               │
│                                                                    │
│  ┌─────────────────────┐        ┌──────────────────────────────┐   │
│  │ Orchestrator Pipeline│        │      AI Daemon (ai_agent.py) │   │
│  │ (main.py)           │        │  systemd, каждые 15 мин      │   │
│  │                     │        │                              │   │
│  │ Market → Decision   │        │  Freqtrade API ─┐            │   │
│  │ → Risk → Execution  │        │  Binance OHLCV ─┤            │   │
│  │ → Strategy → Valid. │        │       ↓         │            │   │
│  │ → Backtest → Learn  │        │  Ollama (Qwen2.5:3B)         │   │
│  └─────────────────────┘        │       ↓                       │   │
│                                 │  ai_params.json ──→ Freqtrade │   │
│  ┌─────────────────────┐        └──────────────────────────────┘   │
│  │ Freqtrade (Docker)  │                                           │
│  │ AI_AdaptiveStrategy │◄── читает ai_params.json                  │
│  │ + healthcheck       │                                           │
│  └─────────────────────┘                                           │
└────────────────────────────────────────────────────────────────────┘
```

---

## 🧠 Компоненты

### Orchestrator Pipeline (main.py)

Последовательный пайплайн из 8 агентов:

| Агент | Назначение |
|---|---|
| **MarketAgent** | Анализирует рынок: свечи из DuckDB, тренд, волатильность, режим |
| **DecisionAgent** | Принимает решение: `buy` / `sell` / `wait` на основе MarketState |
| **RiskAgent** | Вычисляет размер позиции, стоп-лосс, уровень риска |
| **ExecutionAgent** | Формирует ордер (paper/live), пишет в журнал сделок |
| **StrategyAgent** | Генерирует код стратегии через LLM (OpenRouter) |
| **StrategyValidator** | Проверяет синтаксис сгенерированной стратегии |
| **BacktestAgent** | Запускает бэктест в Docker через Freqtrade |
| **LearningAgent** | Анализирует результаты закрытых сделок и бэктестов |

### AI Decision Feedback Loop

AI-агент теперь оценивает качество своих прошлых решений — **система Reward/Learning**:

1. **Логирование решений** — каждое решение AI (regime, signal, stoploss, pairs) записывается в `ai_decision_log.jsonl` с временной меткой и снапшотом рынка
2. **Оценка результатов** — перед каждым новым анализом агент сопоставляет прошлые решения с закрытыми сделками через Freqtrade API
3. **Метрики**:
   - Winrate по `ai_signal` (buy/hold/sell)
   - Winrate по `market_regime` (bullish/bearish/neutral/panic)
   - Эффективность рекомендованных пар (recommended_vs_avoid)
   - Общий P&L, лучшая/худшая сделка
4. **Feedback в промпт** — метрики включаются в system prompt, чтобы LLM видела свои ошибки и успехи

### Multi-LLM Совет Директоров

Вместо одного запроса к LLM, AI-агент может запускать **совет из 3 советников**:

| Советник | Роль |
|---|---|
| **Бычий аналитик** | Ищет возможности, агрессивный, рекомендует buy |
| **Медвежий аналитик** | Управляет рисками, консервативный, рекомендует hold/sell |
| **Главный стратег** | Балансирует риск и доходность, голос разума |

**Как это работает:**
1. Каждый советник получает те же рыночные данные, но с разным system prompt
2. Каждый голосует: `ai_signal`, `market_regime`, `position_size`, `stoploss`
3. Голоса агрегируются: weighted voting (buy=+1, hold=0, sell=-1)
4. Результаты голосования сохраняются в `ai_params.json` как `_council_votes`

**Управление:** `AI_USE_COUNCIL=true` (по умолчанию) / `AI_USE_COUNCIL=false` (один запрос)

> ⚠️ На RPi 4 с Qwen2.5:3B совет из 3 советников занимает ~3-7 минут. Это укладывается в 15-минутный таймфрейм.

### AI Daemon (ai_agent.py)

Непрерывный фоновый процесс (systemd), запущенный на Raspberry Pi:

- Каждые 15 минут (синхронизировано с закрытием свечей) собирает:
  - **OHLCV данные** с Binance API для 14 торговых пар (24 свечи = 6 часов)
  - **Состояние бота** через Freqtrade REST API (баланс, открытые сделки, прибыль, заблокированные пары)
- Формирует структурированный промпт и отправляет в локальный **Ollama** (модель Qwen2.5:3B)
- Парсит JSON-ответ и записывает параметры в `ai_params.json`:
  - `market_regime` — bullish / neutral / bearish / panic
  - `ai_signal` — buy / hold / sell
  - `position_size_pct` — размер позиции (0.5–1.0)
  - `stoploss` — от -0.02 до -0.06
  - `confidence_threshold` — порог уверенности (0.2–0.8)
  - `recommended_pairs` / `avoid_pairs` — рекомендации по парам

### Стратегия Freqtrade (AI_AdaptiveStrategy.py)

Freqtrade-стратегия, работающая на таймфрейме **15 минут**:

- **Вход** — управляется AI:
  - `ai_signal = "buy"`: минимальные технические фильтры (тренд, моментум, объём, RSI ≥ 35)
  - `ai_signal = "hold"`: умеренные условия (скоринг + тренд + моментум)
  - `ai_signal = "sell"`: вход запрещён
  - recommended_pairs получают бонус к скоринговой системе
- **Выход** — AI-независимый, только по:
  - **ROI** (1% → 0.8% → 0.5% → 0.2%)
  - **Стоп-лоссу** (динамический, -2.5%..-4.8%)
  - **Трейлингу** (0.8% после достижения 2.5%)
  - **Перекупленности** (RSI > 81)
- **Размер позиции** — адаптивный: AI-размер × коэффициент режима, бонус для рекомендованных пар, уменьшение при высокой волатильности
- Скоринговая система (0–12 баллов) из 8 компонентов: тренд, моментум, ADX, объём, RSI, положение у EMA20, MACD, моментум RSI

### Конфигурация

Проект использует двухуровневую конфигурацию:

1. **YAML** (`configs/ai_trader.yaml`) — основная конфигурация пайплайна (биржа, риск, исполнение, LLM, пути)
2. **Pydantic-схема** (`configs/schema.py`) — валидация и единый источник конфигурации
3. **Freqtrade config** (`server_config.json`) — конфигурация Freqtrade с API-ключами (**.gitignored**, шаблон в `server_config.template.json`)

---

## 📦 Технологический стек

| Компонент | Технология |
|---|---|
| **Торговая платформа** | [Freqtrade](https://github.com/freqtrade/freqtrade) 2026.5.1 |
| **Биржа** | Binance Spot |
| **LLM** | Ollama + Qwen2.5:3B (локально на RPi) |
| **Контейнеризация** | Docker Compose + autoheal |
| **База данных** | DuckDB (рыночные данные + журнал сделок) |
| **Язык** | Python 3.11+ |
| **REST API** | Freqtrade API (Basic Auth) |
| **Аппаратура** | Raspberry Pi 4 (4GB) |
| **CI/Тесты** | pytest, ruff, mypy, pre-commit |

---

## 🚀 Быстрый старт

### Локальная разработка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/Dmitry23051992/ai-trader.git
cd ai-trader

# 2. Виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# или .venv\Scripts\activate  # Windows

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Создать .env с API-ключами
echo "OPENROUTER_API_KEY=your_key" >> .env
echo "OPENROUTER_MODEL=openai/gpt-4o-mini" >> .env

# 5. Настроить конфигурацию (опционально)
# Отредактировать configs/ai_trader.yaml под свои нужды

# 6. Запустить пайплайн
python main.py                         # 3 итерации, paper mode
python main.py --iterations 5          # 5 итераций
python main.py --live                  # live execution mode
python main.py --fail-fast             # остановка при первой ошибке
```

### Docker (Freqtrade + AI Agent)

```bash
# Убедиться, что docker-compose.yml настроен
# Запустить Freqtrade с AI-стратегией
cd freqtrade
docker compose up -d
```

---

## 🥧 Развёртывание на Raspberry Pi

Проект предназначен для работы на **Raspberry Pi 4 (4GB)** с установленными Docker, Ollama и Python.

### 1. Установка зависимостей на RPi

```bash
# Docker (если ещё не установлен)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b

# Python + зависимости
sudo apt install python3-pip
pip install -r requirements.txt
```

### 2. Настройка Freqtrade

```bash
# Использовать server_config.template.json как основу,
# вставить свои API-ключи Binance и сохранить как server_config.json
# (файл добавлен в .gitignore, не попадёт в git)
```

### 3. AI-агент как systemd-сервис

```bash
# Скопировать unit-файл
sudo cp ai-agent.service /etc/systemd/system/

# Включить и запустить
sudo systemctl daemon-reload
sudo systemctl enable ai-agent
sudo systemctl start ai-agent

# Проверить статус
sudo systemctl status ai-agent
sudo journalctl -u ai-agent -n 50 -f
```

Сервис автоматически запускается при загрузке системы и перезапускается при сбоях.

### 4. Синхронизация с RPi

```bash
# Из PowerShell (локально):
./sync_rpi.ps1                     # с прогоном тестов
./sync_rpi.ps1 -Fast               # без тестов
./sync_rpi.ps1 -DryRun             # тестовый прогон

# Через Makefile:
make sync-rpi                      # с тестами
make sync-rpi-fast                 # без тестов
```

### 5. SSH-туннель

```powershell
# Локальный доступ к API Freqtrade на RPi
./scripts/tunnel.ps1 -Start   # http://localhost:8080 → RPi
./scripts/tunnel.ps1 -Stop    # остановить туннель
./scripts/tunnel.ps1 -Status  # проверить статус
```

---

## 🧪 Разработка

### Команды Makefile

```bash
make install          # установка зависимостей
make test             # тесты с coverage
make lint             # ruff-линтер
make typecheck        # mypy
make format           # форматирование
make check            # линтинг + типы + тесты
make run              # запуск пайплайна (paper, 3 итерации)
make run-live         # запуск пайплайна (live)
make run-ci           # CI-режим (1 итерация, fail-fast)
make clean            # очистка временных файлов
make docker-backtest  # бэктест через Docker
make docker-hyperopt  # гипероптимизация через Docker
make push             # пуш в GitHub
```

### Структура проекта

```
ai-trader/
│
├── agents/                        # Агенты пайплайна
│   ├── decision/                  # Decision Engine (buy/sell/wait)
│   ├── execution/                 # Execution + backtest + Binance adapter
│   ├── learning/                  # Анализ результатов и обучение
│   ├── optimizer/                 # Hyperopt-оптимизация
│   ├── research/                  # MarketAgent (рыночные данные)
│   ├── risk/                      # RiskAgent (размер позиции, защита)
│   └── strategy/                  # StrategyAgent + Validator
│
├── ai/                            # AI-компоненты
│   ├── bot/                       # Parameter provider для стратегии
│   ├── learning/                  # ML-предикторы
│   ├── market/                    # Анализатор рынка + MarketState
│   └── trading/                   # Журнал сделок, парсер бэктестов
│
├── configs/                       # Конфигурация
│   ├── ai_trader.yaml             # Основной YAML-конфиг
│   ├── schema.py                  # Pydantic-схема конфигурации
│   └── settings.py                # Глобальный доступ к настройкам
│
├── core/                          # Ядро
│   ├── director.py                # Оркестратор пайплайна
│   ├── context.py                 # Контекст выполнения
│   ├── logger.py                  # Логирование
│   └── llm.py                     # LLM-клиент
│
├── docs/                          # Документация
│   ├── ARCHITECTURE.md            # Детальная архитектура
│   └── ROADMAP.md                 # План развития
│
├── scripts/                       # Скрипты автоматизации
│   ├── deploy_strategy.py         # Деплой лучшей стратегии
│   ├── check_markets.py           # Проверка рынков
│   ├── tunnel.ps1                 # SSH-туннель
│   ├── ai_controller.py           # Контроллер AI-агента
│   └── update_pairs.py            # Обновление списка пар
│
├── prompts/                       # Промпты для LLM
├── tests/                         # Тесты
├── freqtrade/                     # Freqtrade (submodule или клон)
│
├── ai_agent.py                    # AI Agent daemon
├── AI_AdaptiveStrategy.py         # Основная стратегия Freqtrade
├── main.py                        # Входная точка пайплайна
├── server_config.template.json    # Шаблон конфига Freqtrade
├── ai-agent.service               # systemd unit
├── docker-compose.yml             # Docker Compose Freqtrade + autoheal
├── sync_rpi.ps1                   # Синхронизация с Raspberry Pi
└── Makefile                       # Команды разработки
```

---

## 🔐 Безопасность

- API-ключи Binance, Telegram и пароль хранятся **только** в `server_config.json` (**.gitignored**)
- Шаблон конфига без секретов — `server_config.template.json`
- Пароль AI-агента берётся из переменной окружения `FREQTRADE_PASS`
- Binance adapter использует `BINANCE_API_KEY` / `BINANCE_API_SECRET` из переменных окружения
- Никакие секреты не попадают в git

---

## 📊 Мониторинг

- **Freqtrade Dashboard**: `http://localhost:8080` (или через SSH-туннель)
- **AI Agent логи**: `freqtrade/user_data/logs/ai_agent.log` и `ai_agent_daemon.log`
- **Docker healthcheck**: Freqtrade контейнер проверяется каждые 30 секунд
- **Autoheal**: при сбое контейнер автоматически перезапускается

---

## 🛣 План развития

Текущий фокус — фаза **Production Hardening**:

- [x] AI-управляемый вход с проверкой качества сигнала
- [x] AI-независимые выходы (ROI, стоп-лосс, трейлинг) — защита от паники
- [x] Динамический стоп-лосс с режимом рынка
- [x] Healthcheck + авто-восстановление Docker
- [x] Системный сервис ai-agent (systemd)
- [ ] Ограничение дневной просадки и серии убытков
- [ ] Ранжирование стратегий по метрикам
- [ ] Live execution с синхронизацией ордеров
- [ ] Telegram-алерты

Подробнее: [ROADMAP.md](docs/ROADMAP.md)

---

## 🤝 Вклад в проект

Хотите помочь? Смотрите [CONTRIBUTING.md](CONTRIBUTING.md) — там описаны правила, процесс создания PR и как запускать проверки.

## 📄 Лицензия

MIT — см. [LICENSE](LICENSE).
