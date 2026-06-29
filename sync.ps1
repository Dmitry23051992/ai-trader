#!/usr/bin/env pwsh
# AI-Trader Sync: Двусторонняя синхронизация Windows <-> GitHub <-> Raspberry Pi
# Использование:
#   .\sync.ps1 -Action sync              # Полная синхронизация
#   .\sync.ps1 -Action status            # Показать статус обеих машин
#   .\sync.ps1 -Action push-local        # Отправить с Windows на GitHub
#   .\sync.ps1 -Action pull-rpi          # Загрузить на Raspberry Pi с GitHub
# AI-Trader Sync: PowerShell скрипт для синхронизации Windows <-> Raspberry Pi

param(
    [string]$Action = "sync",
    [string]$Branch = "main",
    [string]$RpiHost = "100.109.236.50",
    [string]$RpiUser = "user",
    [string]$RpiPath = "/home/user/ai-trader",
    [string]$LocalPath = "c:\Users\Professional\Documents\PlatformIO\Projects\ai-trader"
)

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "HH:mm:ss"
    $prefix = switch($Level) {
        "ERROR" { "❌" }
        "WARN"  { "⚠️ " }
        "OK"    { "✓ " }
        "INFO"  { "ℹ️ " }
        "DEBUG" { "🔧" }
        default { "→ " }
    }
    Write-Host "[$timestamp] $prefix $Message"
}

function Invoke-LocalGit {
    param([string]$Command)
    $fullCmd = "git -C $LocalPath $Command"
    Write-Log "Выполняю: $fullCmd" "DEBUG"
    
    $output = & cmd /c "$fullCmd 2>&1"
    $exitCode = $LASTEXITCODE
    
    return @{
        ExitCode = $exitCode
        Output   = $output
    }
}

function Invoke-RpiCommand {
    param([string]$Command)
    
    # Используем plink из Putty если доступен, иначе ssh
    $sshCmd = "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 ${RpiUser}@${RpiHost} `"$Command`" 2>&1"
    Write-Log "На RPi: $Command" "DEBUG"
    
    $output = & cmd /c $sshCmd
    $exitCode = $LASTEXITCODE
    
    return @{
        ExitCode = $exitCode
        Output   = $output
    }
}

function Sync-LocalToGithub {
    Write-Log "📦 Локальная машина -> GitHub ($Branch)" "INFO"
    
    $result = Invoke-LocalGit "status --porcelain"
    if ($result.Output) {
        Write-Log "  ℹ️ Локальные изменения найдены" "INFO"
        
        # Показываем изменения
        $changes = $result.Output -split "`n" | Select-Object -First 5
        foreach ($change in $changes) {
            if ($change) { Write-Log "    $change" "DEBUG" }
        }
        
        # Коммитим
        Write-Log "  🔄 Коммитю изменения..." "INFO"
        $result = Invoke-LocalGit "commit -am `"Auto-sync from Windows ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))`""
        
        if ($result.ExitCode -eq 0) {
            Write-Log "  ✓ Коммит успешен" "OK"
        } else {
            if ($result.Output -notmatch "nothing to commit") {
                Write-Log "  ⚠️ Предупреждение: $($result.Output[0])" "WARN"
            }
        }
    }
    
    # Пушим
    Write-Log "  🚀 Отправляю на GitHub..." "INFO"
    $result = Invoke-LocalGit "push origin $Branch"
    
    if ($result.ExitCode -eq 0) {
        Write-Log "  ✓ Push успешен" "OK"
        return $true
    } else {
        # Пробуем pull сначала
        Write-Log "  ⚠️ Нужен pull, пытаюсь..." "WARN"
        $result = Invoke-LocalGit "pull origin $Branch"
        if ($result.ExitCode -eq 0) {
            $result = Invoke-LocalGit "push origin $Branch"
            if ($result.ExitCode -eq 0) {
                Write-Log "  ✓ Push успешен после pull" "OK"
                return $true
            }
        }
    }
    
    return $false
}

function Sync-RpiToGithub {
    Write-Log "🍓 Raspberry Pi -> GitHub ($Branch)" "INFO"
    
    # Проверяем статус на RPi
    $cmd = "cd $RpiPath && git status --porcelain"
    $result = Invoke-RpiCommand $cmd
    
    if ($result.Output -and $result.ExitCode -eq 0) {
        Write-Log "  ℹ️ Изменения на RPi найдены" "INFO"
        
        # Коммитим на RPi
        $cmd = "cd $RpiPath && git commit -am `"Auto-sync from RPi ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))`""
        $result = Invoke-RpiCommand $cmd
        
        # Пушим с RPi
        $cmd = "cd $RpiPath && git push origin $Branch"
        $result = Invoke-RpiCommand $cmd
        if ($result.ExitCode -eq 0) {
            Write-Log "  ✓ Push с RPi успешен" "OK"
        } else {
            Write-Log "  ⚠️ Push результат: $($result.Output[0])" "WARN"
        }
    }
    
    # Пулим на RPi
    Write-Log "  ⬇️ Загружаю обновления на RPi..." "INFO"
    $cmd = "cd $RpiPath && git pull origin $Branch"
    $result = Invoke-RpiCommand $cmd
    
    if ($result.ExitCode -eq 0) {
        Write-Log "  ✓ Pull на RPi успешен" "OK"
    } else {
        Write-Log "  ⚠️ Pull результат: $($result.Output[0])" "WARN"
    }
}

function Show-Status {
    Write-Log "`n📊 СТАТУС" "INFO"
    Write-Log "=" * 50 "INFO"
    
    # Локально
    Write-Log "`n💻 Локальная машина:" "INFO"
    $result = Invoke-LocalGit "log -1 --oneline"
    if ($result.ExitCode -eq 0) {
        Write-Log "  Последний: $($result.Output[0])" "DEBUG"
    }
    
    $result = Invoke-LocalGit "status -sb"
    $lines = $result.Output -split "`n" | Select-Object -First 3
    foreach ($line in $lines) {
        if ($line) { Write-Log "  $line" "DEBUG" }
    }
    
    # На RPi
    Write-Log "`n🍓 Raspberry Pi:" "INFO"
    $cmd = "cd $RpiPath && git log -1 --oneline"
    $result = Invoke-RpiCommand $cmd
    if ($result.ExitCode -eq 0) {
        Write-Log "  Последний: $($result.Output[0])" "DEBUG"
    }
    
    $cmd = "cd $RpiPath && git status -sb"
    $result = Invoke-RpiCommand $cmd
    $lines = $result.Output -split "`n" | Select-Object -First 3
    foreach ($line in $lines) {
        if ($line) { Write-Log "  $line" "DEBUG" }
    }
}

# Главная логика
Write-Log "`n" + ("=" * 50) "INFO"
Write-Log "🔄 AI-TRADER SYNC: Windows <-> GitHub <-> Raspberry Pi" "INFO"
Write-Log ("=" * 50) "INFO"

try {
    if ($Action -eq "sync" -or $Action -eq "all") {
        Sync-LocalToGithub
        Sync-RpiToGithub
        Show-Status
        
        Write-Log "`n" + ("=" * 50) "INFO"
        Write-Log "✅ Синхронизация завершена успешно!" "OK"
        Write-Log ("=" * 50) "INFO"
    }
    elseif ($Action -eq "status") {
        Show-Status
    }
    elseif ($Action -eq "pull-rpi") {
        Sync-RpiToGithub
    }
    elseif ($Action -eq "push-local") {
        Sync-LocalToGithub
    }
    else {
        Write-Log "Неизвестное действие: $Action" "ERROR"
        Write-Log "Доступные: sync, status, pull-rpi, push-local" "INFO"
    }
}
catch {
    Write-Log "Ошибка: $_" "ERROR"
    exit 1
}
