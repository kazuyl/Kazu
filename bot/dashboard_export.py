from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_summary(state: dict[str, Any]) -> dict[str, Any]:
    trades = state.get("trades", [])
    wins = [t for t in trades if t.get("result_r", 0) > 0]
    net_r = round(sum(float(t.get("result_r", 0)) for t in trades), 2)
    avg_r = round(net_r / len(trades), 2) if trades else 0.0
    winrate = round((len(wins) / len(trades)) * 100, 1) if trades else 0.0
    model_counts = {}
    for trade in trades:
        model = trade.get("model", "unknown")
        model_counts[model] = model_counts.get(model, 0) + 1

    return {
        "market": state.get("market", "NQ=F"),
        "status": "running",
        "total_trades": len(trades),
        "winrate": winrate,
        "avg_r": avg_r,
        "net_r": net_r,
        "open_trades": len(state.get("open_trades", [])),
        "last_update_utc": datetime.now(timezone.utc).isoformat(),
        "period": state.get("period", "live paper trading"),
        "model_counts": model_counts,
    }


def build_equity(state: dict[str, Any]) -> list[dict[str, Any]]:
    cum_r = 0.0
    points = []
    for i, trade in enumerate(state.get("trades", []), start=1):
        cum_r += float(trade.get("result_r", 0))
        points.append(
            {
                "trade_id": i,
                "cum_r": round(cum_r, 2),
                "time": trade.get("exit_time") or trade.get("time"),
            }
        )
    return points


def build_models(state: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trade in state.get("trades", []):
        grouped.setdefault(trade.get("model", "unknown"), []).append(trade)

    rows = []
    for model, trades in grouped.items():
        net_r = round(sum(float(t.get("result_r", 0)) for t in trades), 2)
        wins = [t for t in trades if float(t.get("result_r", 0)) > 0]
        rows.append(
            {
                "model": model,
                "trades": len(trades),
                "winrate": round((len(wins) / len(trades)) * 100, 1) if trades else 0.0,
                "avg_r": round(net_r / len(trades), 2) if trades else 0.0,
                "net_r": net_r,
            }
        )
    rows.sort(key=lambda x: x["net_r"], reverse=True)
    return rows
