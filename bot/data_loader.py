from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf


@dataclass
class MarketFrames:
    df_5m: pd.DataFrame
    df_1h: pd.DataFrame
    df_4h: pd.DataFrame


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out = out.rename(columns={c: c.title() for c in out.columns})
    required = ["Open", "High", "Low", "Close", "Volume"]
    for col in required:
        if col not in out.columns:
            out[col] = pd.NA
    out = out[required]
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    idx = out.index
    if idx.tz is None:
        out.index = idx.tz_localize("UTC")
    else:
        out.index = idx.tz_convert("UTC")
    return out


def fetch_market_frames(symbol: str = "NQ=F") -> MarketFrames:
    ticker = yf.Ticker(symbol)

    df_5m = _normalize(ticker.history(period="20d", interval="5m", auto_adjust=False, prepost=False))
    df_1h = _normalize(ticker.history(period="45d", interval="60m", auto_adjust=False, prepost=False))
    df_4h = _normalize(ticker.history(period="90d", interval="60m", auto_adjust=False, prepost=False))

    if df_4h.empty and not df_1h.empty:
        df_4h = df_1h.resample("4H").agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        ).dropna(subset=["Open", "High", "Low", "Close"])
    elif not df_1h.empty:
        df_4h = df_1h.resample("4H").agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        ).dropna(subset=["Open", "High", "Low", "Close"])

    return MarketFrames(df_5m=df_5m, df_1h=df_1h, df_4h=df_4h)
