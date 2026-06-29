#!/usr/bin/env python3
"""
AI-Trader Sync: Синхронизация Windows <-> Raspberry Pi через GitHub
Автоматически pull/push изменения с обеих машин
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime


def run_cmd(cmd, cwd=None):
    """Выполняет команду и возвращает результат."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            shell=True
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


class GitSync:
    def __init__(self, project_path, remote_user="user", remote_host="100.109.236.50", remote_path="/home/user/ai-trader"):
        self.local_path = Path(project_path)
        self.remote_url = f"{remote_user}@{remote_host}"
        self.remote_path = remote_path
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log(self, msg):
        """Выводит сообщение с временной меткой."""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def git_cmd(self, cmd):
        """Выполняет git команду локально."""
        full_cmd = f"git -C {self.local_path} {cmd}"
        return run_cmd(full_cmd)

    def ssh_cmd(self, cmd):
        """Выполняет команду на Raspberry Pi через SSH."""
        full_cmd = f'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 {self.remote_url} "{cmd}"'
        return run_cmd(full_cmd)

    def sync_local(self, branch="main"):
        """Синхронизирует локальные изменения."""
        self.log(f"📦 Локальная машина ({branch})...")
        
        # Проверяем статус
        code, stdout, _ = self.git_cmd("status --porcelain")
        if stdout.strip():
            self.log(f"  ℹ Найдены локальные изменения:")
            for line in stdout.strip().split('\n')[:5]:
                self.log(f"    {line}")
            if len(stdout.strip().split('\n')) > 5:
                self.log(f"    ... и ещё {len(stdout.strip().split('\n')) - 5} файлов")
            
            # Коммитим
            self.log(f"  🔄 Коммитю изменения...")
            code, _, err = self.git_cmd(f'commit -am "Auto-sync from Windows [{self.timestamp}]"')
            if code != 0 and "nothing to commit" not in err:
                self.log(f"  ⚠ Ошибка: {err[:100]}")
            else:
                self.log(f"  ✓ Коммит успешен")
        
        # Пушим
        self.log(f"  🚀 Отправляю на GitHub...")
        code, stdout, err = self.git_cmd(f"push origin {branch}")
        if code == 0:
            self.log(f"  ✓ Push успешен")
            return True
        else:
            # Возможно, нужен pull сначала
            self.log(f"  ⚠ Push требует pull, пытаюсь...")
            code, _, _ = self.git_cmd(f"pull origin {branch}")
            if code == 0:
                code, _, _ = self.git_cmd(f"push origin {branch}")
                if code == 0:
                    self.log(f"  ✓ Push успешен после pull")
                    return True
        
        return False

    def sync_rpi(self, branch="main"):
        """Синхронизирует Raspberry Pi."""
        self.log(f"🍓 Raspberry Pi ({branch})...")
        
        # Проверяем статус на малине
        code, stdout, _ = self.ssh_cmd(f"cd {self.remote_path} && git status --porcelain")
        if code == 0:
            if stdout.strip():
                self.log(f"  ℹ Изменения на малине найдены ({len(stdout.strip().split(chr(10)))} файлов)")
                # Коммитим на малине
                self.log(f"  🔄 Коммитю на малине...")
                self.ssh_cmd(f'cd {self.remote_path} && git commit -am "Auto-sync from RPi [{self.timestamp}]"')
                
                # Пушим с малины
                self.log(f"  🚀 Отправляю с малины...")
                code, out, err = self.ssh_cmd(f"cd {self.remote_path} && git push origin {branch}")
                if code == 0:
                    self.log(f"  ✓ Push с малины успешен")
                else:
                    self.log(f"  ⚠ Push результат: {err[:100] if err else 'OK'}")
        
        # Пулим на малину
        self.log(f"  ⬇️  Загружаю обновления на малину...")
        code, out, err = self.ssh_cmd(f"cd {self.remote_path} && git pull origin {branch}")
        if code == 0:
            self.log(f"  ✓ Pull на малине успешен")
        else:
            self.log(f"  ⚠ Pull результат: {out[:100] if out else err[:100]}")

    def show_status(self):
        """Показывает текущий статус обеих машин."""
        self.log("\n📊 СТАТУС")
        self.log("=" * 50)
        
        # Локально
        self.log("\n💻 Локальная машина:")
        code, stdout, _ = self.git_cmd("log -1 --oneline")
        if code == 0:
            self.log(f"  Последний коммит: {stdout.strip()}")
        
        code, stdout, _ = self.git_cmd("branch -v")
        if code == 0:
            for line in stdout.strip().split('\n')[:3]:
                self.log(f"  {line}")
        
        # На малине
        self.log("\n🍓 Raspberry Pi:")
        code, stdout, _ = self.ssh_cmd(f"cd {self.remote_path} && git log -1 --oneline")
        if code == 0:
            self.log(f"  Последний коммит: {stdout.strip()}")
        
        code, stdout, _ = self.ssh_cmd(f"cd {self.remote_path} && git branch -v")
        if code == 0:
            for line in stdout.strip().split('\n')[:3]:
                self.log(f"  {line}")

    def run(self, branch="main"):
        """Запускает полную синхронизацию."""
        self.log("\n" + "=" * 50)
        self.log("🔄 AI-TRADER SYNC: Windows <-> Raspberry Pi")
        self.log("=" * 50)
        
        try:
            self.sync_local(branch)
            self.sync_rpi(branch)
            self.show_status()
            
            self.log("\n" + "=" * 50)
            self.log("✅ Синхронизация завершена успешно!")
            self.log("=" * 50 + "\n")
            return 0
        except Exception as e:
            self.log(f"\n❌ Ошибка: {e}")
            return 1


if __name__ == "__main__":
    project_path = r"c:\Users\Professional\Documents\PlatformIO\Projects\ai-trader"
    
    branch = sys.argv[1] if len(sys.argv) > 1 else "main"
    
    syncer = GitSync(project_path)
    exit_code = syncer.run(branch)
    sys.exit(exit_code)
