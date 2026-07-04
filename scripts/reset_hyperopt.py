"""Сброс hyperopt-результатов в БД Freqtrade.
Удаляет сохранённые hyperopt-значения, чтобы стратегия использовала свои defaults.
"""
import sqlite3, os, sys

db_path = os.path.expanduser("~/ai-trader/freqtrade/user_data/tradesv3.sqlite")
if not os.path.exists(db_path):
    print(f"DB not found: {db_path}")
    sys.exit(1)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# Смотрим структуру
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print(f"Tables: {tables}")

# Freqtrade хранит hyperopt в таблице trades (столбцы sell_reason, stoploss, 
# trailing_stop, trailing_stop_positive, trailing_stop_positive_offset, 
# minimal_roi, buy_strategy, etc.)
# Самый простой способ сбросить hyperopt — удалить записи о стратегии из БД

# Поищем hyperopt-related колонки
for table in tables:
    c.execute(f"PRAGMA table_info(\"{table}\")")
    cols = [r[1] for r in c.fetchall()]
    hyper_cols = [col for col in cols if 'hyper' in col.lower() or 'stoploss' in col.lower() or 'roi' in col.lower()]
    if hyper_cols:
        print(f"\n{table} hyperopt columns: {hyper_cols}")

# Смотрим trades — если у trades есть hyperopt параметры
if 'trades' in tables:
    c.execute("PRAGMA table_info(\"trades\")")
    cols = [r[1] for r in c.fetchall()]
    print(f"\nTrades columns: {cols}")

conn.close()
print("\nDone")
