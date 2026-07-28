# Project Data Adapter Template

The agent writes these files under `<project>/.pi-quant/` after exploring `./data`.

## data_profile.json

```json
{
  "version": 1,
  "updated_at": "2026-07-28T12:00:00+00:00",
  "files": [
    {
      "path": "ES_Daily.csv",
      "format": "csv",
      "ticker": "ES",
      "timeframe": "Daily",
      "timezone": "America/Chicago",
      "column_map": {
        "Date": "Date",
        "Open": "Open",
        "High": "High",
        "Low": "Low",
        "Close": "Close",
        "Volume": "Volume",
        "Symbol": "Symbol"
      },
      "fingerprint": {
        "mtime_ns": 0,
        "size": 0
      }
    }
  ]
}
```

Store paths relative to `./data`. Copy live `mtime_ns` and `size` from `inspect_local_market_data` raw probe output.

## data_adapter.py

Minimal CSV example:

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
CANONICAL = ["Date", "Open", "High", "Low", "Close", "Volume", "Symbol"]


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else DATA_ROOT / candidate


def list_datasets() -> list[dict]:
    return [
        {"ticker": "ES", "timeframe": "Daily", "path": "ES_Daily.csv"},
    ]


def inspect(path: str | Path) -> dict:
    resolved = _resolve(path)
    frame = pd.read_csv(resolved, usecols=CANONICAL, parse_dates=["Date"])
    return {
        "file": resolved.name,
        "rows": len(frame),
        "start": str(frame["Date"].min()),
        "end": str(frame["Date"].max()),
        "size_mb": round(resolved.stat().st_size / 1_048_576, 2),
    }


def load_ohlcv(path, columns, start=None, end=None) -> pd.DataFrame:
    resolved = _resolve(path)
    frame = pd.read_csv(resolved, usecols=columns, parse_dates=["Date"])
    if start is not None:
        frame = frame[frame["Date"] >= start]
    if end is not None:
        frame = frame[frame["Date"] <= end]
    return frame[CANONICAL]
```

Parquet, JSON, or mixed layouts follow the same three-function contract; only the read logic changes.

## Workflow

1. Call `inspect_local_market_data`.
2. If `needs_adapter` is true, read `raw_files` previews and file metadata.
3. Write `.pi-quant/data_adapter.py` and `.pi-quant/data_profile.json`.
4. Re-inspect until `adapter_status` is `ready`.
5. Proceed with strategy workspace creation and backtests.
