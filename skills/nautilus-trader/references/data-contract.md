# Local Market Data Contract

## Allowed source

All backtests must resolve data through `local_data.py` and the project-local adapter under `.pi-quant/`. The only allowed raw data root is:

`<project>/data`

Do not add arbitrary data-path parameters to agent tools or the runner.

## Agent-driven adapter memory

On first use (or when files change), the agent explores `./data`, infers layout, and writes:

- `<project>/.pi-quant/data_profile.json` — inventory, column maps, file fingerprints
- `<project>/.pi-quant/data_adapter.py` — project-specific loader with:
  - `list_datasets() -> list[dict]`
  - `inspect(path) -> dict`
  - `load_ohlcv(path, columns, start=None, end=None) -> DataFrame`

`load_ohlcv()` must return canonical columns: `Date`, `Open`, `High`, `Low`, `Close`, `Volume`, `Symbol`.

Raw files stay in `./data`. Do not silently convert or fetch external data.

When `inspect_local_market_data` returns `needs_adapter: true`, explore files, write or update `.pi-quant/` memory, then re-inspect until `adapter_status` is `ready`.

## Staleness

`data_profile.json` stores `{path, mtime_ns, size}` per tracked file. The adapter is stale when:

- a tracked file's fingerprint changed
- a new file appeared under `./data`
- a tracked file disappeared

On stale: update adapter/profile, then re-inspect.

## Dynamic discovery

After the adapter is ready, `discover_datasets()` uses `list_datasets()` output. Ticker and timeframe come from the profile/adapter, not from a hardcoded filename pattern.

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

## Local memory guidance

Add `.pi-quant/` to the project `.gitignore` unless the team explicitly wants to share adapter code. It is machine-local learned layout, not strategy code.

See [./data-adapter-template.md](./data-adapter-template.md) for the adapter/profile shape.
