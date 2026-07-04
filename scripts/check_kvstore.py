"""Проверяем KeyValueStore и hyperopt-данные в БД"""
import sqlite3, os

db_path = os.path.expanduser("~/ai-trader/freqtrade/user_data/tradesv3.sqlite")
conn = sqlite3.connect(db_path)
c = conn.cursor()

# KeyValueStore
c.execute("SELECT * FROM KeyValueStore")
rows = c.fetchall()
print(f"KeyValueStore ({len(rows)} rows):")
for r in rows:
    print(f"  {r}")

# Strategy info from trades
c.execute("SELECT id, pair, strategy, stop_loss_pct, initial_stop_loss_pct, is_stop_loss_trailing FROM trades WHERE is_open=1")
open_trades = c.fetchall()
print(f"\nOpen trades ({len(open_trades)}):")
for t in open_trades:
    print(f"  #{t[0]} {t[1]}: strategy={t[2]}, stop_loss={t[3]:+.4f}, init_sl={t[4]:+.4f}, trailing={t[5]}")

# Check if there are stored strategy configs
c.execute("SELECT * FROM trade_custom_data")
rows = c.fetchall()
print(f"\ntrade_custom_data ({len(rows)}):")
for r in rows:
    print(f"  {r}")

conn.close()
