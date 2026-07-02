# 🤝 Contributing to AI Trader

Спасибо за интерес к проекту! Это open-source AI-система для Freqtrade, и мы рады любой помощи.

## 📋 Правила

- **Не изменять код Freqtrade.** Все стратегии создаются только в `freqtrade/user_data/strategies/`.
- **Перед изменением стратегии** — сделать резервную копию.
- **После создания/изменения стратегии** — проверить синтаксис и запустить бэктест.
- **Никогда не пушить API-ключи, пароли и другие секреты** в git.

## 🐛 Как сообщать о багах

Создавайте [Issue](https://github.com/Dmitry23051992/ai-trader/issues) с пометкой:
- Краткое описание проблемы
- Шаги для воспроизведения
- Ожидаемое vs фактическое поведение
- Логи из `freqtrade/user_data/logs/` (если есть)

## 💡 Как предлагать идеи

Создавайте [Issue](https://github.com/Dmitry23051992/ai-trader/issues) с пометкой `enhancement`:
- Что хотите добавить/изменить
- Почему это полезно
- Пример использования (если есть)

## 🔧 Как внести изменения (PR)

1. Форкнуть репозиторий
2. Создать ветку от `develop`:
   ```bash
   git checkout develop
   git checkout -b feature/your-feature-name
   ```
3. Внести изменения
4. Убедиться, что проходят проверки:
   ```bash
   make check          # ruff + mypy + pytest
   make test           # тесты с coverage
   ```
5. Закоммитить и запушить:
   ```bash
   git push origin feature/your-feature-name
   ```
6. Открыть Pull Request в ветку `develop`

## 🧪 Запуск проверок

```bash
make lint        # ruff-линтер
make typecheck   # mypy
make test        # pytest с coverage
make format      # форматирование ruff
make check       # всё сразу
```

## 📁 Структура проекта

```
agents/     — агенты пайплайна (decision, execution, learning, risk, strategy)
ai/         — AI-компоненты (market analyzer, trading journal, ML)
configs/    — YAML-конфиг + Pydantic-схема
core/       — оркестратор, контекст, LLM-клиент
scripts/    — утилиты (деплой, туннель, проверка рынков)
tests/      — тесты
```

## 📄 Лицензия

MIT — см. [LICENSE](LICENSE).
