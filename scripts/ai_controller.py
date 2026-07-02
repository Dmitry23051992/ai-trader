#!/usr/bin/env python3
"""
AI Controller — запускает AI пайплайн и обновляет параметры Freqtrade бота.

Использование:
    python scripts/ai_controller.py --iterations 3
    python scripts/ai_controller.py --iterations 5 --bootstrap

Этот скрипт:
1. Запускает AI пайплайн (main.py)
2. Извлекает адаптивные параметры из LearningAgent
3. Записывает их в ai_params.json
4. Стратегия AI_AdaptiveStrategy подхватывает их на следующей свече
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


# Путь к ai_params.json (монтируется в /freqtrade/user_data/ в контейнере)
AI_PARAMS_PATH = Path(__file__).parent.parent / "freqtrade" / "user_data" / "ai_params.json"


def run_pipeline(iterations: int, bootstrap: bool) -> dict:
    """Запустить AI пайплайн и извлечь адаптивные параметры."""
    main_py = Path(__file__).parent.parent / "main.py"
    cmd = [
        sys.executable,
        str(main_py),
        "--iterations", str(iterations),
    ]
    if bootstrap:
        cmd.append("--bootstrap")

    print(f"🚀 Running AI pipeline: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        print(f"❌ Pipeline failed (exit {result.returncode})")
        print(result.stderr[:2000])
        return {}

    # Ищем последнюю строку с LearningAgent params в stdout
    params = {}
    for line in result.stdout.splitlines():
        if "[Learning]" in line and "adaptive" in line:
            # Парсим JSON из лога
            # Пример: [Learning] Using ML-predicted adaptive params: {...}
            if "{" in line:
                try:
                    json_str = line[line.index("{"):line.rindex("}") + 1]
                    params = json.loads(json_str)
                except (ValueError, json.JSONDecodeError):
                    pass

    return params


def save_params(params: dict) -> None:
    """Сохранить параметры в ai_params.json."""
    if not params:
        print("⚠️  No params to save.")
        return

    # Читаем существующие параметры, чтобы не потерять ручные настройки
    existing = {}
    if AI_PARAMS_PATH.exists():
        try:
            existing = json.loads(AI_PARAMS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Объединяем (новые параметры имеют приоритет)
    merged = {**existing, **params}

    AI_PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    AI_PARAMS_PATH.write_text(json.dumps(merged, indent=2))
    print(f"✅ Saved {len(merged)} params to {AI_PARAMS_PATH}")


def show_status() -> None:
    """Показать текущие AI-параметры."""
    if not AI_PARAMS_PATH.exists():
        print("📭 No AI params file found.")
        return

    try:
        params = json.loads(AI_PARAMS_PATH.read_text())
        print("📊 Current AI Parameters:")
        for key, value in params.items():
            print(f"   • {key}: {value}")
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  Error reading params: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Controller for Freqtrade")
    parser.add_argument("--iterations", type=int, default=1, help="Number of pipeline iterations")
    parser.add_argument("--bootstrap", action="store_true", help="Bootstrap mode (force strategy gen)")
    parser.add_argument("--status", action="store_true", help="Show current AI params and exit")
    parser.add_argument("--dry-run", action="store_true", help="Run pipeline but don't save params")

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    params = run_pipeline(args.iterations, args.bootstrap)

    if params:
        print(f"\n📈 Pipeline generated params: {json.dumps(params, indent=2)}")
        if not args.dry_run:
            save_params(params)
    else:
        print("\n⚠️  No params extracted from pipeline output.")
        print("   The strategy will use default parameters.")


if __name__ == "__main__":
    main()
