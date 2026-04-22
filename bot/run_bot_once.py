from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from strategy_core import (
    USE_MODELS,
    add_indicators,
    analyze_regime,
    build_primary_scenario,
    classify_market_state,
    get_session,
)


SYMBOL = "NQ=F"
STATE_FILE = "docs/bot_state.json"


# -------------------------
# GitHub store helpers
# -------------------------
class GitHubStore:
    def __init__(self) -> None:
        self.token = os.environ["GITHUB_TOKEN"]
        self.owner = os.environ["GITHUB_OWNER"]
        self.repo = os.environ["GITHUB_REPO"]
        self.branch = os.environ.get("GITHUB_BRANCH", "main")
        self.dashboard_dir = os.environ.get("GITHUB_DASHBOARD_DIR", "docs")

        import requests

        self.requests = requests
        self.base = f"https://api.github.com/repos/{self.owner}/{self.repo}/contents"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
        }

    def read_json(self, path: str, default):
        import base64

        url = f"{self.base}/{path}?ref={self.branch}"
        resp = self.requests.get(url, headers=self._headers(), timeout=30)

        if resp.status_code == 404:
            return default

        resp.raise_for_status()
        payload = resp.json()
        raw = base64.b64decode(payload["content"]).decode("utf-8")
        return json.loads(raw)

    def write_json(self, path: str, obj: dict | list, message: str):
        import base64

        url = f"{self.base}/{path}"
        raw = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
        content = base64.b64encode(raw.encode("utf-8")).decode("utf-8")

        get_resp = self.requests.get(
            f"{url}?ref={self.branch}",
            headers=self._headers(),
            timeout=30,
        )

        sha = None
        if get_resp.status_code == 200:
            sha = get_resp.json()["sha"]
        elif get_resp.status_code != 404:
            get_resp.raise_for_status()

        payload = {
            "message": message,
            "content": content,
            "branch": self.branch,
        }
        if sha:
            payload["sha"] = sha

        put_resp = self.requests.put(
            url,
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        put_resp.raise_for_status()


# -------------------------
# Data loading
# -------------------------
def load_ohlcv(symbol: str, interval: str, period: str) -> pd.DataFrame:
    df = yf.download(symbol, interval=interval, period=period, auto_adjust=False, progress=False)

    if df.empty:
        raise ValueError(f"No data returned for {symbol} {interval} {period}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename_axis("Datetime")
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    return df


def prepare_live_frame(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df_5m = add_indicators(load_ohlcv(symbol, "5m", "20d"))
    df_1h = add_indicators(load_ohlcv(symbol, "60m", "45d"))
    df_4h = add_indicators(load_ohlcv(symbol, "1h", "90d"))

    # resample to 4h from 1h for more stable yf behavior
    df_4h = (
        df_4h.resample("4h")
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna()
    )
    df_4h = add_indicators(df_4h)

    return df_5m, df_1h, df_4h


# -------------------------
# State
# -------------------------
def _default_state() -> dict:
    return {
        "open_trade": None,
        "closed_trades": [],
        "signals": [],
        "equity_curve": [],
        "trade_counter": 0,
    }


def _load_state(store: GitHubStore) -> dict:
    return store.read_json(STATE_FILE, _default_state())


def _save_state(store: GitHubStore, state: dict) -> None:
    store.write_json(STATE_FILE, state, "update bot state")


# -------------------------
# Helpers
# -------------------------
def _safe_float(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return round(float(value), 4)


def _regime_payload(regime: str, confidence: int | float) -> dict:
    return {
        "regime": regime,
        "confidence": int(confidence),
    }


def _build_latest_row(df_5m: pd.DataFrame, df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> pd.Series:
    row = df_5m.iloc[-1].copy()

    regime_5m, conf_5m = analyze_regime(df_5m.iloc[-1])
    regime_1h, conf_1h = analyze_regime(df_1h.iloc[-1])
    regime_4h, conf_4h = analyze_regime(df_4h.iloc[-1])

    row["regime_5m"] = regime_5m
    row["confidence_5m"] = conf_5m
    row["regime_1h"] = regime_1h
    row["confidence_1h"] = conf_1h
    row["regime_4h"] = regime_4h
    row["confidence_4h"] = conf_4h
    row["session"] = get_session(df_5m.index[-1])
    row["market_state"] = classify_market_state(row)

    return row


def _build_context_payload(row: pd.Series, symbol: str) -> dict:
    active_models = [name for name, enabled in USE_MODELS.items() if enabled]
    return {
        "last_update_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "session": row["session"],
        "market_state": row["market_state"],
        "price": _safe_float(row["Close"]),
        "regime_5m": row["regime_5m"],
        "confidence_5m": int(row["confidence_5m"]),
        "regime_1h": row["regime_1h"],
        "confidence_1h": int(row["confidence_1h"]),
        "regime_4h": row["regime_4h"],
        "confidence_4h": int(row["confidence_4h"]),
        "rsi": _safe_float(row["rsi"]),
        "atr": _safe_float(row["atr"]),
        "ema9": _safe_float(row["ema9"]),
        "ema21": _safe_float(row["ema21"]),
        "ema50": _safe_float(row["ema50"]),
        "close_vs_ema21_atr": _safe_float(row["close_vs_ema21_atr"]),
        "range_pct_atr": _safe_float(row["range_pct_atr"]),
        "active_models": active_models,
    }


def _build_price_chart_payload(df_5m: pd.DataFrame, bars: int = 120) -> list[dict]:
    tail = df_5m.tail(bars)
    out = []
    for idx, r in tail.iterrows():
        out.append(
            {
                "time": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                "close": _safe_float(r["Close"]),
                "ema9": _safe_float(r["ema9"]),
                "ema21": _safe_float(r["ema21"]),
            }
        )
    return out


def _current_unrealized_r(trade: dict, current_price: float) -> float | None:
    if not trade:
        return None
    if trade["side"] != "long":
        return None

    risk = trade["entry"] - trade["stop"]
    if risk <= 0:
        return None
    return round((current_price - trade["entry"]) / risk, 2)


def _update_open_trade(state: dict, current_price: float, latest_ts: str) -> None:
    open_trade = state.get("open_trade")
    if not open_trade:
        return

    side = open_trade["side"]
    stop = open_trade["stop"]
    tp = open_trade["tp"]
    entry = open_trade["entry"]

    close_reason = None
    result_r = None

    if side == "long":
        risk = entry - stop
        if current_price <= stop:
            close_reason = "stop"
            result_r = -1.0
        elif current_price >= tp:
            close_reason = "tp"
            result_r = round((tp - entry) / risk, 2)

    if close_reason:
        closed = open_trade.copy()
        closed["closed_at"] = latest_ts
        closed["close_reason"] = close_reason
        closed["exit_price"] = stop if close_reason == "stop" else tp
        closed["result_r"] = result_r

        state["closed_trades"].append(closed)

        prev_cum = state["equity_curve"][-1]["cum_r"] if state["equity_curve"] else 0.0
        new_cum = round(prev_cum + result_r, 2)
        state["equity_curve"].append(
            {
                "trade_id": closed["trade_id"],
                "cum_r": new_cum,
                "model": closed["model"],
                "result_r": result_r,
            }
        )
        state["open_trade"] = None


def _maybe_open_trade(state: dict, scenario: dict, current_price: float, latest_ts: str) -> None:
    if state.get("open_trade") is not None:
        return

    if scenario.get("status") != "conditional":
        return

    if scenario.get("side") != "long":
        return

    if scenario.get("entry") is None or scenario.get("stop") is None or scenario.get("tp") is None:
        return

    # simple paper fill: open when conditional setup exists on current bar
    state["trade_counter"] += 1
    state["open_trade"] = {
        "trade_id": state["trade_counter"],
        "opened_at": latest_ts,
        "model": scenario.get("entry_model"),
        "side": scenario.get("side"),
        "entry": float(current_price),
        "stop": float(scenario["stop"]),
        "tp": float(scenario["tp"]),
        "rr": float(scenario["rr"]) if scenario.get("rr") is not None else None,
        "bars_held": 0,
    }

    state["signals"].insert(
        0,
        {
            "time": latest_ts,
            "model": scenario.get("entry_model"),
            "status": "triggered",
            "side": scenario.get("side"),
            "market_state": scenario.get("market_state"),
        },
    )
    state["signals"] = state["signals"][:30]


def _build_open_trade_payload(state: dict, current_price: float) -> dict:
    open_trade = state.get("open_trade")
    if not open_trade:
        return {"has_open_trade": False}

    unrealized_r = _current_unrealized_r(open_trade, current_price)
    payload = {
        "has_open_trade": True,
        "model": open_trade["model"],
        "side": open_trade["side"],
        "entry": round(open_trade["entry"], 2),
        "stop": round(open_trade["stop"], 2),
        "tp": round(open_trade["tp"], 2),
        "rr": open_trade["rr"],
        "current_price": round(current_price, 2),
        "unrealized_r": unrealized_r,
        "bars_held": open_trade.get("bars_held", 0),
        "opened_at": open_trade.get("opened_at"),
    }
    return payload


def _increment_open_trade_bars(state: dict) -> None:
    if state.get("open_trade"):
        state["open_trade"]["bars_held"] = state["open_trade"].get("bars_held", 0) + 1


def _build_summary_payload(state: dict, context: dict) -> dict:
    closed = state.get("closed_trades", [])
    equity = state.get("equity_curve", [])

    total_trades = len(closed)
    wins = sum(1 for t in closed if t.get("result_r", 0) > 0)
    winrate = round((wins / total_trades) * 100, 1) if total_trades else 0.0

    net_r = round(sum(t.get("result_r", 0) for t in closed), 2)
    avg_r = round(net_r / total_trades, 2) if total_trades else 0.0

    peak = -math.inf
    max_dd = 0.0
    for point in equity:
        cum_r = point["cum_r"]
        peak = max(peak, cum_r)
        dd = peak - cum_r
        max_dd = max(max_dd, dd)

    return {
        "last_update_utc": context["last_update_utc"],
        "market": context["symbol"],
        "status": "running",
        "total_trades": total_trades,
        "winrate": winrate,
        "avg_r": avg_r,
        "net_r": net_r,
        "max_dd_r": round(max_dd, 2),
    }


def _build_models_payload(state: dict) -> list[dict]:
    closed = state.get("closed_trades", [])
    by_model: dict[str, list[dict]] = {}

    for trade in closed:
        by_model.setdefault(trade["model"], []).append(trade)

    out = []
    for model, trades in sorted(by_model.items()):
        total = len(trades)
        wins = sum(1 for t in trades if t.get("result_r", 0) > 0)
        net_r = round(sum(t.get("result_r", 0) for t in trades), 2)
        avg_r = round(net_r / total, 2) if total else 0.0
        winrate = round((wins / total) * 100, 1) if total else 0.0
        out.append(
            {
                "model": model,
                "trades": total,
                "winrate": winrate,
                "avg_r": avg_r,
                "net_r": net_r,
            }
        )

    return out


def main():
    print("ACTIVE MODELS:", USE_MODELS)

    store = GitHubStore()
    state = _load_state(store)

    df_5m, df_1h, df_4h = prepare_live_frame(SYMBOL)
    latest = _build_latest_row(df_5m, df_1h, df_4h)

    scenario = build_primary_scenario(latest)
    current_price = float(latest["Close"])
    latest_ts = df_5m.index[-1].isoformat()

    _update_open_trade(state, current_price, latest_ts)
    _increment_open_trade_bars(state)
    _maybe_open_trade(state, scenario, current_price, latest_ts)

    context_payload = _build_context_payload(latest, SYMBOL)
    price_chart_payload = _build_price_chart_payload(df_5m, bars=120)
    open_trade_payload = _build_open_trade_payload(state, current_price)
    summary_payload = _build_summary_payload(state, context_payload)
    models_payload = _build_models_payload(state)

    trades_payload = state.get("closed_trades", [])[-50:]
    signals_payload = state.get("signals", [])[:30]
    equity_payload = state.get("equity_curve", [])

    store.write_json("docs/context.json", context_payload, "update context")
    store.write_json("docs/scenario.json", scenario, "update scenario")
    store.write_json("docs/open_trade.json", open_trade_payload, "update open trade")
    store.write_json("docs/price_chart.json", price_chart_payload, "update price chart")
    store.write_json("docs/summary.json", summary_payload, "update summary")
    store.write_json("docs/models.json", models_payload, "update models")
    store.write_json("docs/trades.json", trades_payload, "update trades")
    store.write_json("docs/signals.json", signals_payload, "update signals")
    store.write_json("docs/equity.json", equity_payload, "update equity")

    _save_state(store, state)

    print("Live dashboard data updated successfully.")


if __name__ == "__main__":
    main()
