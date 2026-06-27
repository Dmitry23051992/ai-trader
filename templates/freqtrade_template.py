from freqtrade.strategy import IStrategy
from pandas import DataFrame
import talib.abstract as ta


class TEMPLATE(IStrategy):

    INTERFACE_VERSION = 3

    timeframe = "15m"

    minimal_roi = {
        "0": 0.03
    }

    stoploss = -0.10

    trailing_stop = False

    process_only_new_candles = True

    startup_candle_count = 200

    use_exit_signal = True
    exit_profit_only = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)

        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        dataframe["enter_long"] = 0

        dataframe.loc[
            (
                (dataframe["ema50"] > dataframe["ema200"])
                &
                (dataframe["close"] > dataframe["ema50"])
                &
                (dataframe["rsi"] > 55)
            ),
            "enter_long"
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        dataframe["exit_long"] = 0

        dataframe.loc[
            (
                (dataframe["ema50"] < dataframe["ema200"])
                |
                (dataframe["rsi"] < 45)
            ),
            "exit_long"
        ] = 1

        return dataframe
