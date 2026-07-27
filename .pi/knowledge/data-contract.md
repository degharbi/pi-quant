# Local Market Data Contract

## Allowed source

All backtests must resolve data through `local_data.py`. The only allowed root is:

`<project>/data`

`discover_datasets()` scans compatible `*.parquet` files, derives market and source timeframe from each filename, and validates the required OHLCV schema. Do not add arbitrary data-path parameters to agent tools or the runner.

## Dynamic discovery

- Columns: `Date`, `Open`, `High`, `Low`, `Close`, `Volume`, `Symbol`

Use `inspect_local_market_data` for the current market list, source timeframes, row counts, and exact coverage. Never copy the current inventory into a static allowlist.

Instrument metadata is not derivable from OHLCV alone. The run must supply verified instrument type, venue, currency, price increment, account type, and type-specific fields for every selected market.

## Semantics and caveats

- Timestamps may be timezone-naive. Confirm the source timezone from dataset/session evidence or the user, pass it explicitly when the default is wrong, and convert to UTC before creating Nautilus bars.
- A file may contain multiple individual symbols over time while being modeled as one continuous research instrument. Inspect `Symbol` behavior and disclose roll limitations.
- Roll transitions can create artificial gaps and PnL. Do not claim contract-accurate execution without implementing explicit roll handling.
- The loader sorts timestamps, keeps the last duplicate timestamp, rejects malformed OHLC rows, and reports rejected rows.
- The loader enforces a one-million-bar limit. Narrow the date range rather than bypassing it.
- Do not resample one local timeframe into another when an exact file exists.

## Timeframe selection and resampling

- Prefer the exact requested timeframe when a matching local file exists.
- If no exact file exists, aggregate a finer local timeframe into the requested coarser timeframe.
- Calendar strategies can use daily data to build weekly or monthly bars.
- Never create finer bars from coarser data.
- Standard OHLCV aggregation is: open first, high maximum, low minimum, close last, volume sum, symbol last.
- Resampling happens after timezone localization and before Nautilus `Bar` creation.
- Result metadata must include `source_timeframe`, `timeframe`, and `resampled`.

## Selection requirements

Every run must specify:

- ticker
- strategy timeframe
- optional finer source timeframe
- inclusive start
- inclusive end

The requested range must fit the selected source file's metadata coverage. Empty, invalid, oversized, and coarse-to-fine selections fail instead of falling back to external data.
