#!/usr/bin/env python3
"""
AI-Trader sync tool: двусторонняя синхронизация между локальной машиной и Raspberry Pi.
Использует SSH и git для синхронизации.
"""

import subprocess
import sys
from pathlib import Path


def run_cmd(cmd, cwd=None, shell=False):
    """Выполняет команду и возвращает результат."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=shell,
            timeout=30
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


class SyncManager:
    def __init__(
        self,
        local_path="c:\\Users\\Professional\\Documents\\PlatformIO\\Projects\\ai-trader",
        remote_user="user",
        remote_host="100.109.236.50",
        remote_path="/home/user/ai-trader"
    ):
        self.local_path = Path(local_path)
        self.remote_user = remote_user
        self.remote_host = remote_host
        self.remote_path = remote_path
        self.remote_url = f"{remote_user}@{remote_host}"

    def ssh_cmd(self, cmd):
        """Выполняет команду на Raspberry Pi через SSH."""
        full_cmd = f'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 {self.remote_url} "{cmd}"'
        return run_cmd(full_cmd, shell=True)

    def local_cmd(self, cmd):
        """Выполняет команду локально."""
        return run_cmd(cmd, cwd=self.local_path, shell=True)

    def sync_from_rpi(self):
        """Синхронизирует изменения с Raspberry Pi на локальную машину."""
        print("\n[1] Синхронизация с Raspberry Pi...")
        
        # Добавляем remote если его нет
        code, _, _ = self.local_cmd("git remote | findstr /I rpi")
        if code != 0:
            print("  Добавляю remote для Raspberry Pi...")
            self.local_cmd(
                f'git remote add rpi ssh://{self.remote_url}{self.remote_path}'
            )
        
        # Fetch с Raspberry Pi
        print("  Загружаю изменения с малины...")
        code, stdout, stderr = self.local_cmd("git fetch rpi")
        if code == 0:
            print(f"  ✓ Fetch успешен")
        else:
            print(f"  ✗ Ошибка fetch: {stderr}")
            return False
        
        return True

    def sync_to_rpi(self):
        """Синхронизирует локальные изменения на Raspberry Pi."""
        print("\n[2] Отправка изменений на Raspberry Pi...")
        
        code, stdout, stderr = self.local_cmd("git status -s")
        if code == 0 and stdout.strip():
            print("  Локальные изменения найдены:")
            for line in stdout.strip().split('\n'):
                print(f"    {line}")
            
            # Коммитим локальные изменения
            print("  Коммитю изменения...")
            self.local_cmd('git add -A')
            code, _, _ = self.local_cmd(
                'git commit -m "Sync from Windows: ' + 
                'update from main development environment"'
            )
            if code != 0:
                print("  ℹ Нет новых изменений для коммита")
        
        # Пушим на малину
        print("  Отправляю на малину...")
        code, stdout, stderr = self.local_cmd("git push -u rpi main --force")
        if code == 0:
            print(f"  ✓ Push успешен")
        else:
            print(f"  ⚠ Push: {stderr[:200]}")
        
        return True

    def pull_on_rpi(self):
        """Делает pull на Raspberry Pi."""
        print("\n[3] Обновляю код на Raspberry Pi...")
        
        code, stdout, stderr = self.ssh_cmd(
            f"cd {self.remote_path} && git pull origin main 2>&1"
        )
        if code == 0:
            print(f"  ✓ Pull на малине успешен")
        else:
            print(f"  ℹ Pull результат: {stdout}")
        
        return True

    def status(self):
        """Проверяет статус синхронизации."""
        print("\n[STATUS] Локальный статус:")
        code, stdout, _ = self.local_cmd("git status")
        print(stdout)
        
        print("\n[STATUS] Статус на Raspberry Pi:")
        code, stdout, _ = self.ssh_cmd(
            f"cd {self.remote_path} && git status 2>&1 | head -20"
        )
        print(stdout)

    def run_full_sync(self):
        """Выполняет полную двусторонню синхронизацию."""
        print("=" * 60)
        print("AI-TRADER SYNC: Windows <-> Raspberry Pi")
        print("=" * 60)
        
        self.sync_from_rpi()
        self.sync_to_rpi()
        self.pull_on_rpi()
        
        print("\n" + "=" * 60)
        print("✓ Синхронизация завершена!")
        print("=" * 60)
        
        self.status()


if __name__ == "__main__":
    manager = SyncManager()
    
    if len(sys.argv) > 1:
        action = sys.argv[1]
        if action == "from-rpi":
            manager.sync_from_rpi()
        elif action == "to-rpi":
            manager.sync_to_rpi()
        elif action == "status":
            manager.status()
        else:
            print("Usage: sync.py [from-rpi|to-rpi|status]")
    else:
        manager.run_full_sync()
