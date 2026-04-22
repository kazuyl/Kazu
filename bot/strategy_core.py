from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd


@dataclass
class Scenario:
    scenario_label: str
    side: Optional[str]
    market_state: str
    playbook: str
    entry_model: Optional[str]
    entry: Optional[float]
    stop: Optional[float]
    tp: Optional[float]
    rr: Optional[float]
    invalidation: str
    confirmation: str
    status: str

    def to_dict(self) -> dict:
        return asdict(self)


USE_MODELS = {
    "breakout_retest": False,
    "ema_pullback": False,
    "ema_reject": False,
    "overextension_fade": False,
    "rb_long": False,
    "rb_short": False,
    "aggr_pullback": True,
    "ifvg_long": False,
    "london_breakout_long": False,
    "london_sweep_reclaim_long": True,
    "london_sweep_reclaim_short": True,
}
print("ACTIVE MODELS:", USE_MODELS)

CONFIG = {
    "preferred_sessions": ["ny_open", "power_hour", "london"],
    "backtest_5m_period": "60d",
    "backtest_1h_period": "180d",
    "backtest_4h_period": "240d",
    "live_5m_period": "20d",
    "live_1h_period": "45d",
    "live_4h_period": "90d",
    "max_entry_bars": 6,
    "max_hold_bars": 50,
    "slippage": 0.25,
    "account_size": 50_000,
    "risk_percent": 0.5,
}


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.copy()

    df["ema9"] = df["Close"].ewm(span=9).mean()
    df["ema21"] = df["Close"].ewm(span=21).mean()
    df["ema50"] = df["Close"].ewm(span=50).mean()

    df["candle_range"] = df["High"] - df["Low"]
    df["body_size"] = (df["Close"] - df["Open"]).abs()
    df["lower_wick"] = df[["Open", "Close"]].min(axis=1) - df["Low"]
    df["upper_wick"] = df["High"] - df[["Open", "Close"]].max(axis=1)

    df["close_position"] = (
        (df["Close"] - df["Low"]) / df["candle_range"]
    ).replace([float("inf"), -float("inf")], pd.NA)

    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi_slope"] = df["rsi"].diff(3)

    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(14).mean()
    df["atr_ma"] = df["atr"].rolling(50).mean()

    df["range_pct_atr"] = (df["High"] - df["Low"]) / df["atr"]
    df["close_vs_ema21_atr"] = (df["Close"] - df["ema21"]) / df["atr"]
    df["ema_spread_atr"] = (df["ema9"] - df["ema21"]) / df["atr"]
    df["breakout_level_20"] = df["High"].rolling(20).max().shift(1)
    df["breakdown_level_20"] = df["Low"].rolling(20).min().shift(1)

    # ---------- IFVG / imbalance features ----------
    df["high_2_back"] = df["High"].shift(2)
    df["low_2_back"] = df["Low"].shift(2)

    df["bull_fvg_exists"] = df["Low"] > df["High"].shift(2)
    df["bull_fvg_top"] = df["Low"].where(df["bull_fvg_exists"])
    df["bull_fvg_bottom"] = df["High"].shift(2).where(df["bull_fvg_exists"])

    df["active_bull_fvg_top"] = df["bull_fvg_top"].ffill()
    df["active_bull_fvg_bottom"] = df["bull_fvg_bottom"].ffill()

    df["active_bull_fvg_mid"] = (
        df["active_bull_fvg_top"] + df["active_bull_fvg_bottom"]
    ) / 2

    df["bull_fvg_tapped"] = (
        (df["Low"] <= df["active_bull_fvg_top"]) &
        (df["High"] >= df["active_bull_fvg_bottom"])
    )

    df["bull_fvg_reclaim"] = df["Close"] > df["active_bull_fvg_mid"]
    df["bull_fvg_width"] = df["active_bull_fvg_top"] - df["active_bull_fvg_bottom"]
    df["bull_fvg_width_atr"] = df["bull_fvg_width"] / df["atr"]

    # ---------- Session features ----------
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    df["session"] = [get_session(ts) for ts in df.index]
    df["day_key"] = df.index.floor("D")

    asia_mask = df["session"] == "asia"

    asia_high = (
        df["High"]
        .where(asia_mask)
        .groupby(df["day_key"])
        .transform("max")
    )

    asia_low = (
        df["Low"]
        .where(asia_mask)
        .groupby(df["day_key"])
        .transform("min")
    )

    df["asia_high"] = asia_high.groupby(df["day_key"]).ffill()
    df["asia_low"] = asia_low.groupby(df["day_key"]).ffill()

    df["above_asia_high"] = df["High"] > df["asia_high"]
    df["asia_range"] = df["asia_high"] - df["asia_low"]
    df["asia_range_atr"] = df["asia_range"] / df["atr"]
    
    df["hour_utc"] = pd.to_datetime(df.index).tz_convert("UTC").hour if df.index.tz is not None else pd.to_datetime(df.index).tz_localize("UTC").hour

        # recent sweep below Asia low in the last 5 bars
    df["swept_asia_low"] = df["Low"] < df["asia_low"]
    df["recent_sweep_asia_low"] = (
        df["swept_asia_low"]
        .shift(1)
        .rolling(8)
        .max()
        .fillna(0)
        .astype(bool)
    )

    df["swept_asia_high"] = df["High"] > df["asia_high"]
    df["recent_sweep_asia_high"] = (
        df["swept_asia_high"]
        .shift(1)
        .rolling(8)
        .max()
        .fillna(0)
        .astype(bool)
    )

    return df
def analyze_regime(row: pd.Series):
    if pd.isna(row["ema9"]) or pd.isna(row["ema21"]) or pd.isna(row["rsi"]):
        return "unknown", 0

    score = 0
    score += 1 if row["Close"] > row["ema21"] else -1
    if row["rsi"] > 55:
        score += 1
    elif row["rsi"] < 45:
        score -= 1
    score += 1 if row["ema9"] > row["ema21"] else -1

    if score >= 2:
        return "bull", score
    if score <= -2:
        return "bear", score
    return "chop", score


def get_session(ts) -> str:
    # force UTC for consistent session logic
    ts = pd.Timestamp(ts)

    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")

    minutes = ts.hour * 60 + ts.minute

    if 0 <= minutes < 7 * 60:
        return "asia"
    if 7 * 60 <= minutes < 13 * 60 + 30:
        return "london"
    if 13 * 60 + 30 <= minutes < 15 * 60:
        return "ny_open"
    if 15 * 60 <= minutes < 18 * 60:
        return "midday"
    if 18 * 60 <= minutes < 20 * 60:
        return "power_hour"
    return "off_hours"

def calculate_contracts(account_size: float, risk_percent: float, entry: float, stop: float) -> int:
    risk_amount = account_size * (risk_percent / 100)
    stop_distance = abs(entry - stop)
    dollar_risk_per_contract = stop_distance * 20
    if dollar_risk_per_contract == 0:
        return 0
    return max(0, int(risk_amount / dollar_risk_per_contract))


def classify_market_state(row: pd.Series) -> str:
    r5, r1, r4 = row["regime_5m"], row["regime_1h"], row["regime_4h"]
    c5, c1, c4 = row["confidence_5m"], row["confidence_1h"], row["confidence_4h"]
    rsi = row["rsi"]

    if pd.isna(row["atr"]) or pd.isna(row["atr_ma"]):
        return "unknown"
    if row["atr"] <= row["atr_ma"]:
        return "low_vol_chop"

    if r4 == "bull" and c4 >= 2 and r1 == "bull" and c1 >= 2 and rsi >= 70:
        return "overextended_bull"
    if r4 == "bear" and c4 <= -2 and r1 == "bear" and c1 <= -2 and rsi <= 30:
        return "overextended_bear"
    if r4 == "bull" and c4 >= 2 and r1 == "bull" and c1 >= 2 and r5 == "bull" and c5 >= 1:
        return "bull_trend"
    if r4 == "bear" and c4 <= -2 and r1 == "bear" and c1 <= -2 and r5 == "bear" and c5 <= -1:
        return "bear_trend"
    if r4 == "bull" and r1 == "bull" and r5 in ["chop", "bear"]:
        return "bull_pullback"
    if r4 == "bear" and r1 == "bear" and r5 in ["chop", "bull"]:
        return "bear_pullback"
    return "transition"


def _base_setup(
    side: str,
    market_state: str,
    playbook: str,
    entry_model: str,
    entry: float,
    stop: float,
    tp: float,
    invalidation: str,
    confirmation: str,
    scenario_label: str = "Primary Scenario",
) -> Optional[dict]:
    if entry is None or stop is None or tp is None:
        return None
    risk = abs(entry - stop)
    if risk == 0:
        return None
    rr = round(abs(tp - entry) / risk, 2)
    return Scenario(
        scenario_label=scenario_label,
        side=side,
        market_state=market_state,
        playbook=playbook,
        entry_model=entry_model,
        entry=round(float(entry), 2),
        stop=round(float(stop), 2),
        tp=round(float(tp), 2),
        rr=rr,
        invalidation=invalidation,
        confirmation=confirmation,
        status="conditional",
    ).to_dict()


# -------------------
# Entry models
# -------------------

def model_aggressive_pullback_long(row, market_state):
    if market_state not in ["bull_trend", "bull_pullback"]:
        return None

    if row["session"] not in CONFIG["preferred_sessions"]:
        return None

    if row["regime_1h"] != "bull":
        return None

    # weniger streng als ema_pullback
    if row["Close"] < row["ema21"]:
        return None

    if row["close_vs_ema21_atr"] < -0.1 or row["close_vs_ema21_atr"] > 0.5:
        return None

    if row["rsi"] < 48:
        return None

    entry = row["Close"]
    stop = row["Low"] - row["atr"] * 0.2

    if stop >= entry:
        return None

    tp = entry + (entry - stop) * 1.8

    return _base_setup(
        "long",
        market_state,
        "aggressive_pullback_long",
        "aggr_pullback",
        entry,
        stop,
        tp,
        "break below local low",
        "early buyers step in during pullback",
    )

def model_ifvg_long(row: pd.Series, market_state: str):
    if market_state not in ["bull_trend", "bull_pullback"]:
        return None

    if row["session"] not in CONFIG["preferred_sessions"]:
        return None

    if row["regime_1h"] != "bull":
        return None

    if row["regime_4h"] not in ["bull", "chop"]:
        return None

    if pd.isna(row["atr"]) or pd.isna(row["ema21"]):
        return None

    if row["close_vs_ema21_atr"] < 0:
        return None

    if pd.isna(row["active_bull_fvg_top"]) or pd.isna(row["active_bull_fvg_bottom"]):
        return None

    # only use reasonably sized FVGs
    if pd.isna(row["bull_fvg_width_atr"]):
        return None
    if row["bull_fvg_width_atr"] < 0.08 or row["bull_fvg_width_atr"] > 0.8:
        return None

    # trend structure should still be intact
    if row["Close"] < row["ema21"]:
        return None

    # candle must actually interact with the zone
    if not bool(row["bull_fvg_tapped"]):
        return None
   
    # muss mindestens midpoint oder tiefer getappt haben
    if row["Low"] > row["active_bull_fvg_mid"]:
        return None

    # reclaim logic: close back above midpoint
    if not bool(row["bull_fvg_reclaim"]):
        return None

    # momentum not dead / not too hot
    if row["rsi"] < 50 or row["rsi"] > 72:
        return None

    # avoid tiny dead candles
    if row["range_pct_atr"] < 0.3:
        return None

    if row["close_vs_ema21_atr"] > 1.2:
        return None

    entry = row["active_bull_fvg_mid"]
    stop = row["active_bull_fvg_bottom"] - row["atr"] * 0.15

    if stop >= entry:
        return None

    tp = entry + (entry - stop) * 1.9

    return _base_setup(
        "long",
        market_state,
        "ifvg_reclaim_long",
        "ifvg_long",
        entry,
        stop,
        tp,
        "price loses the FVG bottom and fails reclaim",
        "price taps the bullish FVG and closes back above its midpoint",
    )

def model_rejection_block_long(row: pd.Series, market_state: str):
    if market_state not in ["bull_trend", "bull_pullback"]:
        return None

    if row["session"] not in CONFIG["preferred_sessions"]:
        return None

    if row["regime_1h"] != "bull" or row["confidence_1h"] < 2:
        return None

    if pd.isna(row["atr"]) or pd.isna(row["ema21"]) or pd.isna(row["candle_range"]):
        return None

    if row["candle_range"] <= 0:
        return None

    # Preis soll nicht unter Trendstruktur brechen
    if row["Close"] < row["ema21"]:
        return None

    # Bullish rejection block:
    # großer unterer Wick, Close weit oben, vernünftige Candle-Größe
    if row["lower_wick"] < row["body_size"] * 1.2:
        return None

    if row["close_position"] < 0.65:
        return None

    if row["range_pct_atr"] < 0.5:
        return None

    if row["rsi"] < 50 or row["rsi"] > 68:
        return None

    entry = row["High"] + row["atr"] * 0.02
    stop = row["Low"] - row["atr"] * 0.08

    if stop >= entry:
        return None

    tp = entry + (entry - stop) * 2.0

    return _base_setup(
        "long",
        market_state,
        "rejection_block_long",
        "rb_long",
        entry,
        stop,
        tp,
        "bullish rejection fails and candle low gets taken",
        "buyers defend rejection block and price breaks candle high",
    )

def model_rejection_block_short(row: pd.Series, market_state: str):
    if market_state not in ["bear_trend", "bear_pullback"]:
        return None

    if row["session"] not in CONFIG["preferred_sessions"]:
        return None

    if row["regime_1h"] != "bear" or row["confidence_1h"] > -2:
        return None

    if pd.isna(row["atr"]) or pd.isna(row["ema21"]) or pd.isna(row["candle_range"]):
        return None

    if row["candle_range"] <= 0:
        return None

    if row["Close"] > row["ema21"]:
        return None

    if row["upper_wick"] < row["body_size"] * 1.2:
        return None

    # close tief in der candle
    close_position_from_top = (row["High"] - row["Close"]) / row["candle_range"]
    if close_position_from_top < 0.65:
        return None

    if row["range_pct_atr"] < 0.5:
        return None

    if row["rsi"] > 50 or row["rsi"] < 32:
        return None

    entry = row["Low"] - row["atr"] * 0.02
    stop = row["High"] + row["atr"] * 0.08

    if stop <= entry:
        return None

    tp = entry - (stop - entry) * 2.0

    return _base_setup(
        "short",
        market_state,
        "rejection_block_short",
        "rb_short",
        entry,
        stop,
        tp,
        "bearish rejection fails and candle high gets taken",
        "sellers defend rejection block and price breaks candle low",
    )

def model_breakout_retest_long(row: pd.Series, market_state: str):
    if market_state not in ["bull_trend", "bull_pullback"]:
        return None

    if row["session"] not in ["ny_open", "power_hour"]:
        return None

    if row["regime_1h"] != "bull" or row["confidence_1h"] < 2:
        return None

    if pd.isna(row["breakout_level_20"]) or pd.isna(row["atr"]) or pd.isna(row["ema21"]):
        return None

    if row["ema9"] <= row["ema21"]:
        return None

    # Preis darf nicht klar unter dem Breakout-Level liegen
    if row["Close"] < row["breakout_level_20"] - row["atr"] * 0.15:
        return None

    if row["Close"] < row["ema21"]:
        return None

    if row["close_vs_ema21_atr"] < 0.10 or row["close_vs_ema21_atr"] > 1.4:
        return None

    if row["range_pct_atr"] < 0.45:
        return None

    entry = row["breakout_level_20"]
    stop = row["breakout_level_20"] - row["atr"] * 0.7

    # optional EMA21 als tieferer technischer Schutz
    ema_stop = row["ema21"] - row["atr"] * 0.15
    stop = min(stop, ema_stop)

    if stop >= entry:
        stop = entry - row["atr"] * 0.8

    tp = entry + (entry - stop) * 2.0

    return _base_setup(
        "long",
        market_state,
        "breakout_retest_long",
        "breakout_retest",
        entry,
        stop,
        tp,
        "5m closes back below breakout level and loses acceptance",
        "buyers hold the retest area and defend the breakout level",
    )


def model_trend_ema_pullback_long(row: pd.Series, market_state: str):
    
    if market_state not in ["bull_trend", "bull_pullback"]:
        return None

    if row["session"] not in CONFIG["preferred_sessions"]:
        return None

    # stärkeren Trend erzwingen
    if row["regime_1h"] != "bull":
        return None

    if row["regime_4h"] not in ["bull", "chop"]:
        return None

    if row["confidence_5m"] < 2:
        return None

    if row["regime_4h"] == "bear":
        return None

    if pd.isna(row["atr"]) or pd.isna(row["ema21"]):
        return None

    # Preis muss über EMA21 bleiben (kein Trendbruch)
    if row["Close"] < row["ema21"]:
        return None

    # echter Pullback: nicht zu weit weg, nicht zu nah
    if row["close_vs_ema21_atr"] < 0.05 or row["close_vs_ema21_atr"] > 0.9:
        return None

    # kein extremes Overextension
    if row["rsi"] > 68:
        return None

    # etwas Momentum muss noch da sein
    if row["rsi"] < 52:
        return None

    # Candle darf nicht tot sein
    if row["range_pct_atr"] < 0.4:
        return None

    # Entry: nicht blind, leicht über aktuellem Preis
    entry = row["Close"] + row["atr"] * 0.05

    stop = row["ema21"] - row["atr"] * 0.35

    if stop >= entry:
        stop = entry - row["atr"] * 0.8

    tp = entry + (entry - stop) * 2.2

    return _base_setup(
        "long",
        market_state,
        "trend_pullback_long",
        "ema_pullback",
        entry,
        stop,
        tp,
        "5m closes below EMA21 and structure breaks",
        "buyers defend pullback and push price higher",
    )

def model_trend_ema_reject_short(row: pd.Series, market_state: str):
    if market_state != "bear_trend":
        return None
    if row["session"] not in CONFIG["preferred_sessions"]:
        return None
    if row["regime_1h"] != "bear" or row["confidence_1h"] > -2:
        return None
    if row["rsi"] <= 35 or row["rsi"] >= 50:
        return None

    entry = row["ema9"] + row["atr"] * 0.05
    stop = row["ema21"] + row["atr"] * 0.45
    if stop <= entry:
        stop = entry + row["atr"] * 0.8
    tp = entry - (stop - entry) * 2.0

    return _base_setup(
        "short",
        market_state,
        "trend_follow_short",
        "ema_reject",
        entry,
        stop,
        tp,
        "5m closes back above EMA21",
        "sellers reject bounce into EMA zone",
    )

def model_london_breakout_long(row, market_state):

    if row["session"] != "london":
        return None

    if pd.isna(row["asia_high"]) or pd.isna(row["atr"]):
        return None

    # ONLY condition: breakout
    if row["High"] <= row["asia_high"]:
        return None

    entry = row["Close"]
    stop = row["asia_high"] - row["atr"] * 0.3
    tp = entry + (entry - stop) * 2.0

    if stop >= entry:
        return None

    if row["Close"] < row["ema21"]:
        return None

    return _base_setup(
        "long",
        market_state,
        "london_breakout_raw",
        "london_breakout_long",
        entry,
        stop,
        tp,
        "fails back below asia high",
        "simple breakout",
    )

def debug_london_breakout(df: pd.DataFrame):
    checks = {
        "total_rows": len(df),
        "session_london": 0,
        "market_state_ok": 0,
        "regime_1h_ok": 0,
        "regime_4h_ok": 0,
        "asia_ready": 0,
        "asia_range_ok": 0,
        "above_asia_high": 0,
        "rsi_ok": 0,
        "range_pct_atr_ok": 0,
        "close_vs_ema21_ok": 0,
        "all_conditions": 0,
    }

def model_london_sweep_reclaim_long(row: pd.Series, market_state: str):
    # Session: nur London
    if row["session"] != "london":
        return None

    # Asia levels müssen existieren
    if pd.isna(row["asia_high"]) or pd.isna(row["asia_low"]) or pd.isna(row["atr"]):
        return None

    # HTF leicht bullish
    if row["regime_1h"] != "bull":
        return None

    if row["regime_4h"] not in ["bull", "chop"]:
        return None

    # Sweep muss in den letzten 5 Bars passiert sein
    if not bool(row["recent_sweep_asia_low"]):
        return None

    # Reclaim passiert jetzt
    if row["Close"] <= row["asia_low"]:
        return None

    # Candle sollte nicht komplett tot sein
    if row["range_pct_atr"] < 0.2:
        return None

    # Momentum Filter
    if row["rsi"] < 43 or row["rsi"] > 78:
        return None

    entry = row["Close"]
    stop = row["Low"] - row["atr"] * 0.15

    if stop >= entry:
        return None

    tp = entry + (entry - stop) * 2.0

    return _base_setup(
        "long",
        market_state,
        "london_sweep_reclaim_long",
        "london_sweep_reclaim_long",
        entry,
        stop,
        tp,
        "fails back below Asia low after reclaim",
        "Asia low gets swept and price reclaims above it",
    )

def model_london_sweep_reclaim_short(row: pd.Series, market_state: str):
    if row["session"] != "london":
        return None

    if pd.isna(row["asia_high"]) or pd.isna(row["asia_low"]) or pd.isna(row["atr"]):
        return None

    if row["regime_1h"] != "bear":
        return None

    if row["regime_4h"] not in ["bear", "chop"]:
        return None

    # recent sweep ABOVE asia high
    if not bool(row["recent_sweep_asia_high"]):
        return None

    # reclaim back below
    if row["Close"] >= row["asia_high"]:
        return None

    if row["range_pct_atr"] < 0.2:
        return None

    if row["rsi"] < 22 or row["rsi"] > 57:
        return None

    entry = row["Close"]
    stop = row["High"] + row["atr"] * 0.15

    if stop <= entry:
        return None

    tp = entry - (stop - entry) * 2.0

    return _base_setup(
        "short",
        market_state,
        "london_sweep_reclaim_short",
        "london_sweep_reclaim_short",
        entry,
        stop,
        tp,
        "fails back above Asia high",
        "Asia high gets swept and price reclaims below it",
    )

    for _, row in df.iterrows():
        checks["total_rows"] += 0  # keeps key visible

        session_ok = row.get("session") == "london"
        market_ok = row.get("market_state") in ["bull_trend", "bull_pullback"]
        regime_1h_ok = row.get("regime_1h") == "bull" and row.get("confidence_1h", 0) >= 2
        regime_4h_ok = row.get("regime_4h") == "bull" and row.get("confidence_4h", 0) >= 2

        asia_ready = not pd.isna(row.get("asia_high")) and not pd.isna(row.get("asia_low")) and not pd.isna(row.get("atr"))
        asia_range_ok = asia_ready and not pd.isna(row.get("asia_range_atr")) and 0.25 <= row.get("asia_range_atr") <= 2.5
        breakout_ok = asia_ready and bool(row.get("above_asia_high", False))
        rsi_ok = not pd.isna(row.get("rsi")) and 50 <= row.get("rsi") <= 72
        range_ok = not pd.isna(row.get("range_pct_atr")) and row.get("range_pct_atr") >= 0.4
        ema_ok = not pd.isna(row.get("close_vs_ema21_atr")) and row.get("close_vs_ema21_atr") <= 1.8

        if session_ok:
            checks["session_london"] += 1
        if session_ok and market_ok:
            checks["market_state_ok"] += 1
        if session_ok and market_ok and regime_1h_ok:
            checks["regime_1h_ok"] += 1
        if session_ok and market_ok and regime_1h_ok and regime_4h_ok:
            checks["regime_4h_ok"] += 1
        if session_ok and market_ok and regime_1h_ok and regime_4h_ok and asia_ready:
            checks["asia_ready"] += 1
        if session_ok and market_ok and regime_1h_ok and regime_4h_ok and asia_ready and asia_range_ok:
            checks["asia_range_ok"] += 1
        if session_ok and market_ok and regime_1h_ok and regime_4h_ok and asia_ready and asia_range_ok and breakout_ok:
            checks["above_asia_high"] += 1
        if session_ok and market_ok and regime_1h_ok and regime_4h_ok and asia_ready and asia_range_ok and breakout_ok and rsi_ok:
            checks["rsi_ok"] += 1
        if session_ok and market_ok and regime_1h_ok and regime_4h_ok and asia_ready and asia_range_ok and breakout_ok and rsi_ok and range_ok:
            checks["range_pct_atr_ok"] += 1
        if session_ok and market_ok and regime_1h_ok and regime_4h_ok and asia_ready and asia_range_ok and breakout_ok and rsi_ok and range_ok and ema_ok:
            checks["close_vs_ema21_ok"] += 1

        if (
            session_ok and market_ok and regime_1h_ok and regime_4h_ok and
            asia_ready and asia_range_ok and breakout_ok and
            rsi_ok and range_ok and ema_ok
        ):
            checks["all_conditions"] += 1

    print("\n=== LONDON MODEL DEBUG ===")
    for k, v in checks.items():
        print(f"{k}: {v}")

ENTRY_MODELS = []
if USE_MODELS["ema_pullback"]:
    ENTRY_MODELS.append(model_trend_ema_pullback_long)
if USE_MODELS["rb_long"]:
    ENTRY_MODELS.append(model_rejection_block_long)
if USE_MODELS["rb_short"]:
    ENTRY_MODELS.append(model_rejection_block_short)
if USE_MODELS["ema_reject"]:
    ENTRY_MODELS.append(model_trend_ema_reject_short)
if USE_MODELS["aggr_pullback"]:
    ENTRY_MODELS.append(model_aggressive_pullback_long)
if USE_MODELS["ifvg_long"]:
    ENTRY_MODELS.append(model_ifvg_long)
if USE_MODELS["london_breakout_long"]:
    ENTRY_MODELS.append(model_london_breakout_long)
if USE_MODELS["london_sweep_reclaim_long"]:
    ENTRY_MODELS.append(model_london_sweep_reclaim_long)
if USE_MODELS["london_sweep_reclaim_short"]:
    ENTRY_MODELS.append(model_london_sweep_reclaim_short)


def choose_best_setup(candidates: list[dict]):
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (x["rr"], x["entry_model"]), reverse=True)[0]

print("\n=== COLUMN CHECK ===")
needed_cols = [
    "session",
    "asia_high",
    "asia_low",
    "above_asia_high",
    "asia_range_atr",
    "regime_1h",
    "confidence_1h",
    "regime_4h",
    "confidence_4h",
    "range_pct_atr",
    "close_vs_ema21_atr",
    "rsi",
]

    



def build_primary_scenario(row: pd.Series) -> dict:
    market_state = classify_market_state(row)
    if row["session"] not in CONFIG["preferred_sessions"]:
        return Scenario(
            scenario_label="Primary Scenario",
            side=None,
            market_state=market_state,
            playbook="stand_aside",
            entry_model=None,
            entry=None,
            stop=None,
            tp=None,
            rr=None,
            invalidation="Outside preferred session",
            confirmation="Wait for London, NY open, or power hour",
            status="stand aside",
        ).to_dict()

    candidates = []
    for model in ENTRY_MODELS:
        setup = model(row, market_state)
        if setup is not None:
            candidates.append(setup)

    best = choose_best_setup(candidates)
    if best is not None:
        return best

    return Scenario(
        scenario_label="Primary Scenario",
        side=None,
        market_state=market_state,
        playbook="stand_aside",
        entry_model=None,
        entry=None,
        stop=None,
        tp=None,
        rr=None,
        invalidation="No valid entry model",
        confirmation="Wait for cleaner alignment or breakout structure",
        status="stand aside",
    ).to_dict()


def safe_number(value, digits: int = 2):
    if pd.isna(value):
        return None
    return round(float(value), digits)


