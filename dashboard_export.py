from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf


@dataclass
class MarketDataConfig:
    symbol: str = "NQ=F"
    interval: str = "5m"
    period: str = "20d"
    auto_adjust: bool = False
    prepost: bool = True


def download_ohlcv(config: MarketDataConfig) -> pd.DataFrame:
    df = yf.download(
        tickers=config.symbol,
        interval=config.interval,
        period=config.period,
        auto_adjust=config.auto_adjust,
        progress=False,
        prepost=config.prepost,
    )

    if df is None or df.empty:
        raise ValueError(f"No data returned for {config.symbol} {config.interval} {config.period}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename_axis("Datetime").reset_index()
    df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
    return df


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    x = df.copy()
    x = x.set_index("Datetime")
    out = x.resample(rule).agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    ).dropna()
    out = out.reset_index()
    out["Datetime"] = pd.to_datetime(out["Datetime"], utc=True)
    return out


def build_mtf_frames(df_5m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df_1h = _resample_ohlcv(df_5m, "1H")
    df_4h = _resample_ohlcv(df_5m, "4H")
    return df_5m.copy(), df_1h, df_4h
