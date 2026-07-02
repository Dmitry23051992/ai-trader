#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Sync local project changes to the Raspberry Pi via tar+ssh.
.DESCRIPTION
    Uses SSH key authentication (already configured) to push
    project files to the Pi. Skips venv, git, cache, and large dirs.
.PARAMETER Host
    SSH host alias or user@host (default: ai-trader).
.PARAMETER RemotePath
    Remote project path (default: ~/ai-trader).
.PARAMETER DryRun
    Show what would be synced without transferring.
.PARAMETER Fast
    Skip tests before syncing.
.EXAMPLE
    ./sync_rpi.ps1
    ./sync_rpi.ps1 -Host user@100.109.236.50
    ./sync_rpi.ps1 -DryRun
#>

param(
    [string]$HostName = "ai-trader",
    [string]$RemotePath = "~/ai-trader",
    [switch]$DryRun,
    [switch]$Fast
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = Get-Location }

Write-Host "=== AI Trader → Raspberry Pi Sync ===" -ForegroundColor Cyan
Write-Host "Local:  $ProjectRoot"
Write-Host "Remote: user@$HostName`:$RemotePath"
Write-Host ""

# 1. Run tests locally first (unless --fast)
if (-not $Fast) {
    Write-Host ">>> Running local tests..." -ForegroundColor Yellow
    $testResult = & "$ProjectRoot\.venv\Scripts\python.exe" -m pytest tests/ -q 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "!!! Tests FAILED. Aborting sync." -ForegroundColor Red
        Write-Host $testResult
        exit 1
    }
    Write-Host "Tests PASSED. Proceeding with sync." -ForegroundColor Green
} else {
    Write-Host "Skipping tests (--fast mode)." -ForegroundColor Magenta
}

# 2. Build exclude list
$excludes = @(
    "--exclude=.venv",
    "--exclude=__pycache__",
    "--exclude=.git",
    "--exclude=.opencode",
    "--exclude=.pytest_cache",
    "--exclude=.mypy_cache",
    "--exclude=freqtrade/.git",
    "--exclude=freqtrade/.venv",
    "--exclude=freqtrade/build",
    "--exclude=freqtrade/node_modules",
    "--exclude=ai/database",
    "--exclude=*.duckdb",
    "--exclude=*.wal",
    "--exclude=*.joblib",
    "--exclude=*.log",
    "--exclude=reports",
    "--exclude=logs",
    "--exclude=training_cache.jsonl"
)

# 3. Execute sync
Write-Host ">>> Syncing files..." -ForegroundColor Yellow

$excludeStr = $excludes -join " "

if ($DryRun) {
    Write-Host "[DRY-RUN] Would tar from: $ProjectRoot" -ForegroundColor Magenta
    $cmd = "tar -C `"$ProjectRoot`" -cf - $excludeStr ."
    Invoke-Expression "$cmd | ssh $HostName 'cd $RemotePath && tar tvf -'"
} else {
    $cmd = "tar -C `"$ProjectRoot`" -cf - $excludeStr ."
    $output = Invoke-Expression "$cmd | ssh $HostName 'cd $RemotePath && tar xvf -'" 2>&1
}

$fileCount = ($output | Where-Object { $_ -match '\.\/' } | Measure-Object).Count
Write-Host "Synced $fileCount files." -ForegroundColor Green

# 4. If not dry-run, install deps and run tests remotely
if (-not $DryRun) {
    Write-Host ">>> Installing dependencies on Pi..." -ForegroundColor Yellow
    ssh $HostName "cd $RemotePath && .venv/bin/pip install -q -r requirements.txt" 2>&1 | Out-Null
    
    if (-not $Fast) {
        Write-Host ">>> Running tests on Pi..." -ForegroundColor Yellow
        $piTest = ssh $HostName "cd $RemotePath && .venv/bin/python -m pytest tests/ -q" 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "!!! Pi tests FAILED:" -ForegroundColor Red
            Write-Host $piTest
            exit 1
        }
        Write-Host "Pi tests PASSED." -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "=== Sync complete! ===" -ForegroundColor Cyan
Write-Host "Quick run on Pi: ssh $HostName 'cd $RemotePath && .venv/bin/python main.py --iterations 1'" -ForegroundColor Cyan
