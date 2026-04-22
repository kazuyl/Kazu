from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def export_dashboard(data_dir: Path, summary: dict, trades: list[dict], equity: list[dict], models: list[dict], signals: list[dict]) -> None:
    write_json(data_dir / "summary.json", summary)
    write_json(data_dir / "trades.json", trades)
    write_json(data_dir / "equity.json", equity)
    write_json(data_dir / "models.json", models)
    write_json(data_dir / "signals.json", signals)
