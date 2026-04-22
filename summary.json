from __future__ import annotations

from pathlib import Path

from backtest_engine import EngineConfig, build_model_stats, run_backtest
from dashboard_export import export_dashboard
from data_loader import MarketDataConfig, build_mtf_frames, download_ohlcv


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "docs" / "dashboard_data"

    market = MarketDataConfig(symbol="NQ=F", interval="5m", period="20d")
    df_5m = download_ohlcv(market)
    f5, f1, f4 = build_mtf_frames(df_5m)

    config = EngineConfig(symbol=market.symbol, max_hold_bars=50, slippage=0.25)
    trades, equity, summary = run_backtest(f5, f1, f4, config)
    models = build_model_stats(trades)
    signals = trades[-10:]

    export_dashboard(
        data_dir=data_dir,
        summary=summary,
        trades=trades,
        equity=equity,
        models=models,
        signals=signals,
    )

    print(f"Exported dashboard data to {data_dir}")
    print(summary)


if __name__ == "__main__":
    main()
