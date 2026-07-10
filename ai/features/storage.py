from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from configs.settings import DB_PATH


class FeatureStorage:
    """
    Хранилище рассчитанных признаков.

    Все признаки сохраняются в таблицу `features`.
    Каждая запись соответствует одной свече.
    """

    TABLE_NAME = "features"

    def __init__(self, db_path: Path | str = DB_PATH) -> None:
        self.db = duckdb.connect(str(db_path))

    def create(self, dataframe: pd.DataFrame) -> None:
        """
        Создает таблицу features по структуре DataFrame,
        если она еще не существует.
        """

        self.db.register("features_df", dataframe.head(0))

        self.db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} AS
            SELECT *
            FROM features_df
            WHERE FALSE
            """
        )

        self.db.unregister("features_df")

    def replace(
        self,
        dataframe: pd.DataFrame,
    ) -> None:
        """
        Полностью заменяет содержимое таблицы features.
        """

        if dataframe.empty:
            return

        self.create(dataframe)

        self.db.execute(
            f"DELETE FROM {self.TABLE_NAME}"
        )

        self.db.register("features_df", dataframe)

        self.db.execute(
            f"""
            INSERT INTO {self.TABLE_NAME}
            SELECT *
            FROM features_df
            """
        )

        self.db.unregister("features_df")

    def append(
        self,
        dataframe: pd.DataFrame,
    ) -> None:
        """
        Добавляет новые признаки в таблицу.
        """

        if dataframe.empty:
            return

        self.create(dataframe)

        self.db.register("features_df", dataframe)

        self.db.execute(
            f"""
            INSERT INTO {self.TABLE_NAME}
            SELECT *
            FROM features_df
            """
        )

        self.db.unregister("features_df")

    def load(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        """
        Загружает признаки.
        """

        sql = f"SELECT * FROM {self.TABLE_NAME}"

        params = []

        where = []

        if symbol is not None:
            where.append("symbol = ?")
            params.append(symbol)

        if timeframe is not None:
            where.append("timeframe = ?")
            params.append(timeframe)

        if where:
            sql += " WHERE " + " AND ".join(where)

        sql += " ORDER BY timestamp"

        return self.db.execute(
            sql,
            params,
        ).fetchdf()

    def count(self) -> int:
        """
        Количество строк.
        """

        try:
            return self.db.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.TABLE_NAME}
                """
            ).fetchone()[0]

        except duckdb.Error:
            return 0

    def exists(self) -> bool:
        """
        Проверяет существование таблицы.
        """

        row = self.db.execute(
            """
            SELECT COUNT(*)

            FROM information_schema.tables

            WHERE table_name = ?
            """,
            [self.TABLE_NAME],
        ).fetchone()

        return row[0] > 0

    def drop(self) -> None:
        """
        Удаляет таблицу features.
        """

        self.db.execute(
            f"DROP TABLE IF EXISTS {self.TABLE_NAME}"
        )

    def close(self) -> None:
        """
        Закрывает соединение.
        """

        self.db.close()
