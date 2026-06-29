# ✅ Синхронизация готова к использованию!

## 🎯 Что я сделал

1. **Подключил VS Code Remote SSH** для Raspberry Pi
   - Расширение уже установлено: `Remote - SSH`
   - SSH конфиг создан в `~/.ssh/config`

2. **Создал PowerShell скрипты синхронизации**
   - `sync.ps1` — основной скрипт для синхронизации
   - `sync_github.py` — альтернативный Python вариант
   - Поддерживают все основные действия (pull/push/status)

3. **Настроил GitHub как центральный репозиторий**
   - Windows: HTTPS подключение
   - Raspberry Pi: SSH подключение
   - Оба синхронизируют через GitHub

4. **Создал документацию**
   - `SYNC-QUICK.md` — быстрый старт (начни отсюда!)
   - `SYNC.md` — полная документация
   - `README.md` — описание проекта

---

## 🚀 Как начать работать

### Шаг 1: Убедись, что всё работает

```bash
# Проверь статус локального проекта
git status
git log -3 --oneline

# Проверь синхронизацию с Raspberry Pi
.\\sync.ps1 -Action status
```

### Шаг 2: Выбери метод работы

**Вариант A (для большинства): Remote-SSH в VS Code**
1. Ctrl+Shift+P → Remote-SSH: Connect to Host...
2. Выбери `raspberry-pi` или введи `user@100.109.236.50`
3. Пароль: `user`
4. Работай прямо на RPi через VS Code!
5. Все изменения синхронизируются автоматически

**Вариант B: Локальная разработка + ручная синхронизация**
1. Редактируй файлы на Windows
2. Перед завершением: `.\\sync.ps1 -Action sync`
3. Это синхронизирует Windows → GitHub → Raspberry Pi

**Вариант C: Командная строка (для опытных)**
```bash
git add .
git commit -m "My changes"
git push origin main
```

---

## 📋 Файлы синхронизации

| Файл | Назначение | Используй когда |
|------|-----------|----------------|
| `SYNC-QUICK.md` | 📖 Краткая инструкция | Нужна быстрая справка |
| `SYNC.md` | 📚 Полная документация | Нужна подробная информация |
| `sync.ps1` | ⚡ PowerShell автоматизация | Хочешь автоматический sync |
| `sync_github.py` | 🐍 Python альтернатива | Предпочитаешь Python |

---

## 🔗 Подключение к Raspberry Pi

### Способ 1: VS Code Remote-SSH (рекомендуется)
```
Ctrl+Shift+P → Remote-SSH: Connect to Host... → raspberry-pi
Пароль: user
```

### Способ 2: Командная строка
```bash
ssh user@100.109.236.50
# Пароль: user
cd ~/ai-trader
```

### Способ 3: PowerShell скрипт
```powershell
.\\sync.ps1 -Action sync  # Полная синхронизация
```

---

## 🎮 Примеры использования

### Я отредактировал файл на Windows, как отправить на Raspberry Pi?

```powershell
# Автоматически через скрипт
.\\sync.ps1 -Action sync

# Или вручную
git add .
git commit -m "My changes"
git push origin main

# На Raspberry Pi
ssh user@100.109.236.50 "cd ~/ai-trader && git pull origin main"
```

### Я работаю на Raspberry Pi через Remote-SSH, как всё сохранится?

- VS Code автоматически синхронизирует файлы
- Git видит все изменения в Source Control панели (Ctrl+Shift+G)
- Коммитишь/пушишь прямо из VS Code
- Windows автоматически получит обновления после `git pull origin main`

### На обеих машинах есть изменения, как не потерять?

```bash
# На Windows
git add .
git commit -m "Windows changes"
git push origin main

# На Raspberry Pi
git add .
git commit -m "RPi changes"  
git pull origin main  # Получи Windows изменения
git push origin main  # Отправь свои

# На Windows
git pull origin main  # Получи RPi изменения
```

---

## 🛡️ Важные правила

✅ **ДА:**
- Часто коммитить небольшими порциями
- Использовать понятные сообщения коммитов
- Синхронизировать перед большой сессией работы
- Проверять статус перед push'ем

❌ **НЕТ:**
- Не редактировать один файл одновременно на двух машинах
- Не забывать commit'ить перед переключением между машинами
- Не игнорировать ошибки конфликтов merge

---

## 📞 Помощь

Если что-то не работает:

1. Проверь [SYNC-QUICK.md](SYNC-QUICK.md) — там решения типичных проблем
2. Проверь статус: `.\\sync.ps1 -Action status`
3. Проверь SSH: `ping 100.109.236.50`
4. Проверь git: `git status` и `git log`

---

## 🎉 Готово!

**Теперь ты можешь:**
- ✅ Работать на Windows и Raspberry Pi одновременно
- ✅ Синхронизировать код между машинами в один клик
- ✅ Использовать VS Code на обеих машинах
- ✅ Видеть изменения на обеих машинах в реальном времени

**Начни с:** [SYNC-QUICK.md](SYNC-QUICK.md)

*Создано: 2026-06-29*
