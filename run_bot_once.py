from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional

import pandas as pd

from strategy_core import add_indicators, analyze_regime, build_primary_scenario, get_session


@dataclass
class BacktestTrade:
    trade_id: int
    time: str
    model: str
    side: str
    session: str
    market_state: str
    entry: float
    stop: float
    tp: float
    rr: float
    result_r: float
    bars_held: int
    exit_reason: str
    status: str = "closed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EngineConfig:
    symbol: str = "NQ=F"
    max_hold_bars: int = 50
    slippage: float = 0.25


def _prepare_regime_features(df_5m: pd.DataFrame, df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> pd.DataFrame:
    f5 = add_indicators(df_5m.copy())
    f1 = add_indicators(df_1h.copy())
    f4 = add_indicators(df_4h.copy())

    reg1 = f1.apply(lambda row: analyze_regime(row), axis=1, result_type="expand")
    f1[["regime_1h_raw", "confidence_1h_raw"]] = reg1

    reg4 = f4.apply(lambda row: analyze_regime(row), axis=1, result_type="expand")
    f4[["regime_4h_raw", "confidence_4h_raw"]] = reg4

    reg5 = f5.apply(lambda row: analyze_regime(row), axis=1, result_type="expand")
    f5[["regime_5m", "confidence_5m"]] = reg5
    f5["session"] = f5["Datetime"].dt.tz_convert("UTC").apply(get_session)

    f1_small = f1[["Datetime", "regime_1h_raw", "confidence_1h_raw"]].rename(
        columns={"Datetime": "ts_1h"}
    )
    f4_small = f4[["Datetime", "regime_4h_raw", "confidence_4h_raw"]].rename(
        columns={"Datetime": "ts_4h"}
    )

    merged = pd.merge_asof(
        f5.sort_values("Datetime"),
        f1_small.sort_values("ts_1h"),
        left_on="Datetime",
        right_on="ts_1h",
        direction="backward",
    )
    merged = pd.merge_asof(
        merged.sort_values("Datetime"),
        f4_small.sort_values("ts_4h"),
        left_on="Datetime",
        right_on="ts_4h",
        direction="backward",
    )
    merged["regime_1h"] = merged["regime_1h_raw"]
    merged["confidence_1h"] = merged["confidence_1h_raw"]
    merged["regime_4h"] = merged["regime_4h_raw"]
    merged["confidence_4h"] = merged["confidence_4h_raw"]
    return merged


def _simulate_trade(df: pd.DataFrame, start_idx: int, scenario: dict[str, Any], max_hold_bars: int, slippage: float) -> Optional[BacktestTrade]:
    if scenario.get("side") != "long":
        return None

    entry = float(scenario["entry"]) + slippage
    stop = float(scenario["stop"]) - slippage
    tp = float(scenario["tp"])
    risk = entry - stop
    if risk <= 0:
        return None

    exit_reason = "timeout"
    exit_price = float(df.iloc[min(start_idx + max_hold_bars, len(df) - 1)]["Close"])
    bars_held = 0

    for j in range(start_idx + 1, min(start_idx + max_hold_bars + 1, len(df))):
        row = df.iloc[j]
        bars_held = j - start_idx
        low = float(row["Low"])
        high = float(row["High"])

        if low <= stop:
            exit_price = stop
            exit_reason = "stop"
            break
        if high >= tp:
            exit_price = tp
            exit_reason = "tp"
            break

    result_r = round((exit_price - entry) / risk, 4)
    opened = df.iloc[start_idx]
    return BacktestTrade(
        trade_id=0,
        time=opened["Datetime"].isoformat(),
        model=str(scenario["entry_model"]),
        side="long",
        session=str(opened["session"]),
        market_state=str(scenario["market_state"]),
        entry=round(entry, 2),
        stop=round(stop, 2),
        tp=round(tp, 2),
        rr=float(scenario["rr"]),
        result_r=result_r,
        bars_held=bars_held,
        exit_reason=exit_reason,
    )


def run_backtest(df_5m: pd.DataFrame, df_1h: pd.DataFrame, df_4h: pd.DataFrame, config: EngineConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    df = _prepare_regime_features(df_5m, df_1h, df_4h)

    trades: list[BacktestTrade] = []
    equity: list[dict[str, Any]] = []
    cum_r = 0.0
    trade_id = 0
    next_available_idx = 0

    for i in range(len(df)):
        if i < next_available_idx:
            continue

        row = df.iloc[i]
        scenario = build_primary_scenario(row)
        if scenario.get("status") == "stand aside" or scenario.get("side") is None:
            continue

        trade = _simulate_trade(df, i, scenario, config.max_hold_bars, config.slippage)
        if trade is None:
            continue

        trade_id += 1
        trade.trade_id = trade_id
        trades.append(trade)
        cum_r = round(cum_r + trade.result_r, 4)
        equity.append(
            {
                "trade_id": trade_id,
                "time": trade.time,
                "model": trade.model,
                "result_r": trade.result_r,
                "cum_r": cum_r,
            }
        )
        next_available_idx = i + max(1, trade.bars_held)

    trade_dicts = [t.to_dict() for t in trades]
    summary = build_summary(config.symbol, trade_dicts)
    return trade_dicts, equity, summary


def build_summary(symbol: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "market": symbol,
            "status": "no_trades",
            "total_trades": 0,
            "winrate": 0.0,
            "avg_r": 0.0,
            "net_r": 0.0,
            "max_dd_r": 0.0,
            "last_update_utc": pd.Timestamp.utcnow().isoformat(),
        }

    results = pd.Series([float(t["result_r"]) for t in trades], dtype="float64")
    cum = results.cumsum()
    dd = cum - cum.cummax()
    return {
        "market": symbol,
        "status": "running",
        "total_trades": int(len(trades)),
        "winrate": round(float((results > 0).mean() * 100), 2),
        "avg_r": round(float(results.mean()), 4),
        "net_r": round(float(results.sum()), 4),
        "max_dd_r": round(float(abs(dd.min())), 4),
        "last_update_utc": pd.Timestamp.utcnow().isoformat(),
    }


def build_model_stats(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not trades:
        return []
    df = pd.DataFrame(trades)
    out = []
    for model, grp in df.groupby("model"):
        results = grp["result_r"].astype(float)
        out.append(
            {
                "model": model,
                "trades": int(len(grp)),
                "winrate": round(float((results > 0).mean() * 100), 2),
                "avg_r": round(float(results.mean()), 4),
                "net_r": round(float(results.sum()), 4),
            }
        )
    return sorted(out, key=lambda x: x["net_r"], reverse=True)
