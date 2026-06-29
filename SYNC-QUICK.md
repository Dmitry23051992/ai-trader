# 🔄 AI-Trader: Синхронизация Windows <-> Raspberry Pi

## 📍 Текущее состояние

- **Windows (локально)**: c:/Users/Professional/Documents/PlatformIO/Projects/ai-trader
- **Raspberry Pi**: user@100.109.236.50:/home/user/ai-trader  
- **GitHub**: https://github.com/Dmitry23051992/ai-trader.git
- **Пароль RPi**: `user`

**✅ Оба проекта синхронизированы через один GitHub репозиторий**

---

## ⚡ Быстрый старт синхронизации

### 🟢 Вариант 1: Автоматическая синхронизация (рекомендуется)

Открой PowerShell в папке проекта и выполни:

```powershell
# Полная двусторонняя синхронизация: Windows ↔ GitHub ↔ Raspberry Pi
.\\sync.ps1 -Action sync

# Проверить статус обеих машин
.\\sync.ps1 -Action status

# Только отправить изменения с Windows на GitHub
.\\sync.ps1 -Action push-local

# Только загрузить обновления на Raspberry Pi
.\\sync.ps1 -Action pull-rpi
```

### 🟡 Вариант 2: Встроенное Remote-SSH в VS Code (очень удобно)

1. Откройка **Command Palette** (Ctrl+Shift+P)
2. Введи: **"Remote-SSH: Connect to Host..."**
3. Выбери **raspberry-pi** (или введи `user@100.109.236.50`)
4. Введи пароль: **user**
5. VS Code откроет окно с подключением к малине
6. Все изменения синхронизируются **автоматически** при сохранении файла

### 🔴 Вариант 3: Ручная синхронизация через git

```bash
# На Windows: отправить свои изменения
git add .
git commit -m "Описание что сделал"
git push origin main

# На Raspberry Pi (через SSH): получить обновления  
ssh user@100.109.236.50
cd ~/ai-trader
git pull origin main
exit
```

---

## 📊 Проверка синхронизации

### На Windows
```bash
git status                  # Текущий статус
git log -5 --oneline       # Последние 5 коммитов
git branch -v              # Текущая ветка и удалённые ветки
```

### На Raspberry Pi
```bash
ssh user@100.109.236.50 "cd ~/ai-trader && git status"
ssh user@100.109.236.50 "cd ~/ai-trader && git log -5 --oneline"
```

---

## ✅ Workflow для разработки

### Цикл разработки

1. **На Windows:**
   ```bash
   # Редактируй файлы в VS Code
   # Сохраняй (Ctrl+S)
   
   # Когда готов отправить:
   .\\sync.ps1 -Action sync
   ```

2. **На Raspberry Pi (тестирование):**
   ```bash
   ssh user@100.109.236.50
   cd ~/ai-trader
   
   # Обновись с GitHub
   git pull origin main
   
   # Запусти тесты
   python main.py
   ```

3. **Если нужны изменения с Raspberry Pi обратно на Windows:**
   ```bash
   # На Windows: загрузи обновления
   git pull origin main
   # или
   .\\sync.ps1 -Action sync
   ```

---

## 🐛 Решение проблем

### Ошибка: "Permission denied"
- Проверь IP: `ping 100.109.236.50`
- Проверь пароль: должен быть `user`
- Проверь SSH на RPi: `ssh user@100.109.236.50 "echo 'OK'"`

### Конфликты при merge
1. VS Code покажет визуальный редактор конфликтов
2. Выбери нужный вариант (Accept Current / Accept Incoming)
3. Сохрани и сделай коммит

### Скрипт .ps1 зависает
- Это нормально - он ждёт пароля для SSH
- Введи: **user** и нажми Enter
- Для автоматизации без пароля установи SSH ключи (см. SYNC.md)

---

## 🔧 Полная документация

Подробная документация находится в файле [SYNC.md](SYNC.md)

Там описаны:
- Все методы синхронизации
- Настройка SSH ключей для автоматизации
- Решение типичных проблем
- Advanced workflow'ы

---

## 💡 Быстрые советы

- **Сохраняй часто** - используй `Ctrl+S` после каждого улучшения
- **Коммитай регулярно** - делай небольшие логичные коммиты
- **Синхронизируй перед началом работы** - убедись что у тебя последняя версия
- **Проверяй статус** - используй `git status` перед push'ем

---

*Последнее обновление: 2026-06-29*
