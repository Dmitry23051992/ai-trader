#!/usr/bin/env pwsh
<#
.SYNOPSIS
    SSH тунель к Freqtrade API на Raspberry Pi
.DESCRIPTION
    Создаёт SSH тунель от локального порта 8080 к Freqtrade API на Pi.
    После запуска Freqtrade будет доступен по адресу http://localhost:8080
.PARAMETER Start
    Запустить тунель (по умолчанию)
.PARAMETER Stop
    Остановить тунель (найти и завершить процесс SSH)
.PARAMETER Status
    Проверить статус тунеля
.PARAMETER Restart
    Перезапустить тунель
#>

param(
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [switch]$Restart
)

$LocalPort = 8080
$RemoteHost = "ai-trader"
$RemotePort = 8080

function Start-Tunnel {
    Write-Host "🔌 Запуск SSH тунеля к Freqtrade API..." -ForegroundColor Cyan
    Write-Host "   Локальный адрес: http://localhost:$LocalPort" -ForegroundColor Green
    Write-Host "   Удалённый хост:  $RemoteHost" -ForegroundColor Gray

    # Запускаем SSH тунель в фоне
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "ssh"
    $psi.Arguments = "-N -L ${LocalPort}:localhost:${RemotePort} $RemoteHost -v"
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $p = [System.Diagnostics.Process]::Start($psi)

    Start-Sleep -Seconds 2

    if (!$p.HasExited) {
        Write-Host "✅ Тунель запущен! PID: $($p.Id)" -ForegroundColor Green
        Write-Host "   Открой в браузере: http://localhost:$LocalPort" -ForegroundColor Yellow
        Write-Host "   Для остановки используй: ./scripts/tunnel.ps1 -Stop" -ForegroundColor Gray
        
        # Сохраняем PID для последующей остановки
        $p.Id | Out-File -FilePath "$PSScriptRoot\.tunnel_pid" -Force
        return $p
    } else {
        Write-Host "❌ Ошибка запуска тунеля!" -ForegroundColor Red
        Write-Host "   Вывод ошибки: $($p.StandardError.ReadToEnd())" -ForegroundColor Red
        return $null
    }
}

function Stop-Tunnel {
    $tunnelPidFile = "$PSScriptRoot\.tunnel_pid"
    if (Test-Path $tunnelPidFile) {
        $tunnelPid = Get-Content $tunnelPidFile -Raw | ForEach-Object { $_.Trim() }
        if ($tunnelPid -and $tunnelPid -match '^\d+$') {
            try {
                $process = Get-Process -Id $tunnelPid -ErrorAction Stop
                if ($process.ProcessName -eq "ssh") {
                    $process.Kill()
                    Write-Host "🛑 Тунель остановлен (PID: $tunnelPid)" -ForegroundColor Yellow
                }
            } catch {
                Write-Host "⚠️ Процесс с PID $tunnelPid не найден, возможно уже остановлен" -ForegroundColor Yellow
            }
        }
        Remove-Item $tunnelPidFile -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "ℹ️ PID файл не найден, ищем процессы SSH..." -ForegroundColor Gray
        $sshProcesses = Get-Process -Name ssh -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -match "8080:localhost:8080"
        }
        if ($sshProcesses) {
            $sshProcesses | ForEach-Object {
                $_.Kill()
                Write-Host "🛑 Остановлен процесс SSH PID: $($_.Id)" -ForegroundColor Yellow
            }
        } else {
            Write-Host "❌ Активных тунелей не найдено" -ForegroundColor Red
        }
    }
}

function Get-TunnelStatus {
    $tunnelPidFile = "$PSScriptRoot\.tunnel_pid"
    $running = $false
    
    if (Test-Path $tunnelPidFile) {
        $tunnelPid = Get-Content $tunnelPidFile -Raw | ForEach-Object { $_.Trim() }
        if ($tunnelPid -and $tunnelPid -match '^\d+$') {
            try {
                $process = Get-Process -Id $tunnelPid -ErrorAction Stop
                if ($process.ProcessName -eq "ssh") {
                    $running = $true
                }
            } catch {}
        }
    }
    
    # Проверяем через curl
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8080/api/v1/ping" -TimeoutSec 2 -ErrorAction Stop
        if ($response.Content -match '"status":"pong"') {
            Write-Host "✅ Тунель АКТИВЕН — Freqtrade API отвечает на localhost:8080" -ForegroundColor Green
            return
        }
    } catch {}
    
    if ($running) {
        Write-Host "⚠️ Тунель запущен, но API не отвечает (возможно загрузка)" -ForegroundColor Yellow
    } else {
        Write-Host "❌ Тунель НЕ запущен" -ForegroundColor Red
        Write-Host "   Запусти: ./scripts/tunnel.ps1 -Start" -ForegroundColor Gray
    }
}

# Главная логика
if ($Stop -or $Restart) {
    Stop-Tunnel
}

if ($Restart -or $Start -or (!$Stop -and !$Status -and !$Restart)) {
    # Проверяем не запущен ли уже
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8080/api/v1/ping" -TimeoutSec 2 -ErrorAction Stop
        if ($response.Content -match '"status":"pong"') {
            Write-Host "✅ Тунель уже активен! Freqtrade отвечает на http://localhost:8080" -ForegroundColor Green
            exit 0
        }
    } catch {}
    
    Start-Tunnel
} elseif ($Status) {
    Get-TunnelStatus
}
