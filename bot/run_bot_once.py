from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from data_loader import fetch_market_frames
from dashboard_export import build_equity, build_models, build_summary
from github_store import GitHubStore
from strategy_core import add_indicators, analyze_regime, build_primary_scenario, get_session


STATE_FILE = "bot_state.json"
SUMMARY_FILE = "summary.json"
TRADES_FILE = "trades.json"
SIGNALS_FILE = "signals.json"
EQUITY_FILE = "equity.json"
MODELS_FILE = "models.json"


def _regime_df(df: pd.DataFrame, label: str) -> pd.DataFrame:
    df = add_indicators(df)
    regimes = df.apply(analyze_regime, axis=1, result_type="expand")
    df[f"regime_{label}"] = regimes[0]
    df[f"confidence_{label}"] = regimes[1]
    keep = [f"regime_{label}", f"confidence_{label}"]
    if label == "5m":
        keep += ["Close", "High", "Low", "Open", "ema21", "atr"]
    return df


def _build_live_row() -> tuple[pd.Series, pd.DataFrame]:
    frames = fetch_market_frames("NQ=F")
    if frames.df_5m.empty or frames.df_1h.empty or frames.df_4h.empty:
        raise RuntimeError("Missing market data for one or more timeframes")

    df5 = _regime_df(frames.df_5m, "5m")
    df1 = _regime_df(frames.df_1h, "1h")[["regime_1h", "confidence_1h"]]
    df4 = _regime_df(frames.df_4h, "4h")[["regime_4h", "confidence_4h"]]

    df = df5.copy()
    df.index = pd.to_datetime(df.index, utc=True)
    df1.index = pd.to_datetime(df1.index, utc=True)
    df4.index = pd.to_datetime(df4.index, utc=True)

    df = pd.merge_asof(df.sort_index(), df1.sort_index(), left_index=True, right_index=True, direction="backward")
    df = pd.merge_asof(df.sort_index(), df4.sort_index(), left_index=True, right_index=True, direction="backward")
    df["session"] = [get_session(ts) for ts in df.index]

    row = df.iloc[-1].copy()
    row.name = df.index[-1]
    return row, df


def _signal_id(ts: str, model: str, entry: float, stop: float, tp: float) -> str:
    raw = f"{ts}|{model}|{entry:.2f}|{stop:.2f}|{tp:.2f}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _load_state(store: GitHubStore) -> dict[str, Any]:
    state = store.read_json(
        STATE_FILE,
        {
            "market": "NQ=F",
            "period": "live paper trading",
            "signals": [],
            "trades": [],
            "open_trades": [],
        },
    )
    state.setdefault("signals", [])
    state.setdefault("trades", [])
    state.setdefault("open_trades", [])
    state.setdefault("market", "NQ=F")
    state.setdefault("period", "live paper trading")
    return state


def _update_open_trades(state: dict[str, Any], latest_bar: pd.Series) -> None:
    still_open = []
    high = float(latest_bar["High"])
    low = float(latest_bar["Low"])
    now_iso = datetime.now(timezone.utc).isoformat()

    for trade in state.get("open_trades", []):
        side = trade.get("side")
        entry = float(trade["entry"])
        stop = float(trade["stop"])
        tp = float(trade["tp"])
        closed = False

        if side == "long":
            if low <= stop:
                exit_price = stop
                result_r = -1.0
                reason = "stop"
                closed = True
            elif high >= tp:
                risk = entry - stop
                exit_price = tp
                result_r = round((tp - entry) / risk, 2) if risk > 0 else 0.0
                reason = "tp"
                closed = True
            else:
                still_open.append(trade)
        else:
            still_open.append(trade)

        if closed:
            state["trades"].append(
                {
                    **trade,
                    "exit_price": round(exit_price, 2),
                    "exit_time": now_iso,
                    "result_r": result_r,
                    "close_reason": reason,
                }
            )

    state["open_trades"] = still_open


def _maybe_open_trade(state: dict[str, Any], row: pd.Series, scenario: dict[str, Any]) -> None:
    if scenario.get("status") != "conditional" or scenario.get("side") != "long":
        return

    ts = row.name.isoformat() if hasattr(row.name, "isoformat") else str(row.name)
    model = scenario.get("entry_model") or "unknown"
    entry = float(scenario["entry"])
    stop = float(scenario["stop"])
    tp = float(scenario["tp"])
    sig_id = _signal_id(ts, model, entry, stop, tp)

    known_signal_ids = {s.get("signal_id") for s in state.get("signals", [])}
    open_ids = {t.get("signal_id") for t in state.get("open_trades", [])}
    trade_ids = {t.get("signal_id") for t in state.get("trades", [])}
    if sig_id in known_signal_ids or sig_id in open_ids or sig_id in trade_ids:
        return

    signal = {
        "signal_id": sig_id,
        "time": ts,
        "model": model,
        "side": scenario.get("side"),
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "tp": round(tp, 2),
        "rr": scenario.get("rr"),
        "market_state": scenario.get("market_state"),
        "session": row.get("session"),
        "status": "opened",
    }
    state["signals"].insert(0, signal)
    state["signals"] = state["signals"][:100]

    state["open_trades"].append(
        {
            **signal,
            "open_time": datetime.now(timezone.utc).isoformat(),
        }
    )


def _persist(store: GitHubStore, state: dict[str, Any]) -> None:
    summary = build_summary(state)
    equity = build_equity(state)
    models = build_models(state)
    signals = state.get("signals", [])[:25]
    trades = list(reversed(state.get("trades", [])[-50:]))

    store.write_json(STATE_FILE, state, "update bot state")
    store.write_json(SUMMARY_FILE, summary, "update dashboard summary")
    store.write_json(EQUITY_FILE, equity, "update dashboard equity")
    store.write_json(TRADES_FILE, trades, "update dashboard trades")
    store.write_json(SIGNALS_FILE, signals, "update dashboard signals")
    store.write_json(MODELS_FILE, models, "update dashboard models")


def main() -> None:
    store = GitHubStore()
    state = _load_state(store)
    row, df = _build_live_row()
    _update_open_trades(state, row)
    scenario = build_primary_scenario(row)
    _maybe_open_trade(state, row, scenario)
    _persist(store, state)

    print(json.dumps({
        "time": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario,
        "open_trades": len(state.get("open_trades", [])),
        "closed_trades": len(state.get("trades", [])),
    }, indent=2))


if __name__ == "__main__":
    main()
