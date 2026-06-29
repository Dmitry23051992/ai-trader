# Синхронизация: Windows <-> Raspberry Pi через GitHub

## Текущее состояние

- ✅ Windows: подключен к `https://github.com/Dmitry23051992/ai-trader.git`
- ✅ Raspberry Pi: подключена к `git@github.com:Dmitry23051992/ai-trader.git`
- ✅ Оба репозитория синхронизированы через GitHub

## Быстрый старт синхронизации

### 📌 Самый простой способ: PowerShell скрипт

Запусти в PowerShell из папки проекта:

```powershell
# Полная синхронизация (Windows -> GitHub -> RPi)
.\sync.ps1 -Action sync

# Только проверить статус обеих машин
.\sync.ps1 -Action status

# Только отправить изменения с Windows на GitHub
.\sync.ps1 -Action push-local

# Только загрузить изменения на RPi с GitHub
.\sync.ps1 -Action pull-rpi
```

**Примечание:** Скрипт запросит пароль для SSH (введи `user`)

### 🔗 Вариант 2: Через GitHub вручную

#### На Windows:

```bash
git add .
git commit -m "Update from Windows"
git push origin main
```

#### На Raspberry Pi:

```bash
cd ~/ai-trader
git pull origin main
```

### 🖥️ Вариант 3: VS Code Remote SSH (самый удобный)

1. **Установи расширение**: `Remote - SSH` (ms-vscode-remote.remote-ssh)
   - ✓ Уже установлено в твоём VS Code

2. **Подключись к RPi**:
   - Открой Command Palette (`Ctrl+Shift+P`)
   - Введи: `Remote-SSH: Connect to Host...`
   - Выбери **raspberry-pi** (или введи `user@100.109.236.50`)
   - Введи пароль: `user`

3. **Все изменения синхронизируются автоматически**:
   - Когда ты сохраняешь файл (Ctrl+S), он меняется и на RPi
   - Git-изменения видны в VS Code Source Control
   - Можешь коммитить и пушить прямо из VS Code

### 📊 Проверить статус синхронизации

```bash
# Windows: текущее состояние локального репозитория
git status
git log -5 --oneline

# Raspberry Pi: состояние через SSH
ssh user@100.109.236.50 "cd ~/ai-trader && git status"
ssh user@100.109.236.50 "cd ~/ai-trader && git log -5 --oneline"
```

## 🚀 Рекомендуемый Workflow

### Для разработки на Windows:

```bash
# 1. Сделай свои изменения в файлах
# (редактируй .py, .md и т.д.)

# 2. Сохрани файлы (Ctrl+S)

# 3. Когда закончил, синхронизируй с малиной:
.\sync.ps1 -Action sync

# 4. Или вручную через git:
git add .
git commit -m "Описание что сделал"
git push origin main
```

### Для тестирования на Raspberry Pi:

```bash
# Логинься на малину
ssh user@100.109.236.50

# Обновись
cd ~/ai-trader
git pull origin main

# Запусти тесты
python main.py
```

### Если нужны изменения с малины обратно:

```bash
# На Windows, загрузи последние изменения
git pull origin main

# Или используй скрипт:
.\sync.ps1 -Action pull-rpi
```

## 🔧 Решение проблем

### Ошибка: "Permission denied (publickey, password)"

- **Решение 1**: Убедись, что пароль `user` правильный
- **Решение 2**: Проверь IP адрес: `ping 100.109.236.50`
- **Решение 3**: На RPi проверь SSH сервер: `ssh user@100.109.236.50 "sudo service ssh status"`

### Конфликты при merge

1. Открой конфликтные файлы в VS Code
2. VS Code покажет визуальный редактор конфликтов
3. Выбери нужный вариант (Accept Current / Accept Incoming / Accept Both)
4. Сохрани и коммитай

### Когда .ps1 скрипт просит пароль

- Это нормально! Введи пароль от user на RPi: `user`
- SSH просит его для каждого подключения
- Если хочешь избежать этого, настрой SSH ключи (см. раздел ниже)

## 🔐 Опционально: Настройка SSH ключей (без пароля)

Если часто синхронизируешь, можно настроить SSH ключи для автоматизации:

```bash
# На Windows (PowerShell)
ssh-keygen -t rsa -b 4096 -f $env:USERPROFILE\.ssh\id_rsa

# Скопируй публичный ключ на RPi
cat $env:USERPROFILE\.ssh\id_rsa.pub | ssh user@100.109.236.50 "cat >> .ssh/authorized_keys"

# Теперь можешь подключаться без пароля
ssh user@100.109.236.50 "echo 'Success'"
```
