# pi-quant

A local research lab that pairs **[Pi](https://pi.dev)** (an agentic coding assistant) with **[NautilusTrader](https://nautilustrader.io/)** for strategy development and backtesting.

Pi discovers what market data you have, asks for strategy details, writes Nautilus `Strategy` code, and runs backtests against **your local Parquet files only**. No synthetic data, no external downloads, no hardcoded ticker list.

---

## What this repo gives you

| Layer | Purpose |
|-------|---------|
| **`.pi/`** | Pi skills, prompts, knowledge base, and a TypeScript extension with backtest tools and `/strategy` intake |
| **`local_data.py`** | Scans `./data`, loads OHLCV Parquet, optional resampling (e.g. Daily → Weekly) |
| **`strategy_workspace.py`** | Creates UUID workspaces, loads workspace strategies, records results |
| **`strategies/`** | One UUID folder per strategy: code, results, artifacts (gitignored) |
| **`examples/`** | Reference strategies only; do not use for new user work |

Each new strategy gets an isolated folder:

```text
strategies/{uuid}/
├── manifest.json
├── strategy.py
├── results/
│   ├── latest.json
│   └── {timestamp}.json
└── artifacts/
```

---

## Prerequisites

- **Python 3.10+** (tested with 3.10)
- **[Pi coding agent](https://pi.dev/docs/latest/)** (`@earendil-works/pi-coding-agent`)
- **Git**

Market data is **not** included in the repository (it is gitignored). You provide your own files under `./data`.

---

## Setup from scratch

### 1. Clone the repository

```bash
git clone https://github.com/degharbi/pi-quant.git
cd pi-quant
```

### 2. Create a virtual environment and install NautilusTrader

```bash
python3.10 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install nautilus_trader pandas pyarrow
```

Verify the install:

```bash
python -c "import nautilus_trader; print(nautilus_trader.__version__)"
```

### 3. Add your market data

Create a `data/` folder and place Parquet files there:

```text
data/
  ES_Daily.parquet
  ES_5min.parquet
  ^EURUSD_Daily.parquet
  ...
```

**Naming convention:** `{TICKER}_{TIMEFRAME}.parquet`

Examples: `ES_Daily`, `NQ_5min`, `^EURUSD_Daily`, `GC_60min`

**Required columns:**

| Column | Description |
|--------|-------------|
| `Date` | Bar timestamp (timezone-naive; interpreted as exchange local time, default `America/Chicago`) |
| `Open`, `High`, `Low`, `Close` | OHLC prices |
| `Volume` | Volume |
| `Symbol` | Underlying contract or symbol per row |

List what Pi can see:

```bash
python -c "from local_data import inventory; import json; print(json.dumps(inventory(), indent=2))"
```

### 4. Install and run Pi from the project root

Pi auto-loads `.pi/extensions`, `.pi/skills`, and `.pi/prompts` when started in this directory.

Follow the [Pi installation docs](https://pi.dev/docs/latest/) for your platform, then:

```bash
cd pi-quant
pi
```

You should see the Nautilus status widget and have access to `/strategy` and `/backtest-data`.

---

## Using Pi (recommended workflow)

### Step 1 — Discover data

Ask Pi to inspect local data, or run:

```text
/backtest-data
```

Pi calls the `inspect_local_market_data` tool and lists tickers, timeframes, date ranges, and row counts.

### Step 2 — Define a strategy brief

Run the interactive wizard:

```text
/strategy
```

Or describe your idea in chat. Pi will ask for market, timeframe, rules, sizing, session, costs, and instrument metadata.

### Step 3 — Create a UUID workspace

Pi calls `create_strategy_workspace`, which creates:

```text
strategies/{uuid}/
├── manifest.json      # brief, class names, last run
├── strategy.py        # your strategy code
├── results/           # backtest outputs
└── artifacts/         # charts, notes, exports
```

All code and outputs for that strategy stay inside this folder.

### Step 4 — Implement and backtest

Pi will:

1. Read `.pi/skills/nautilus-trader.md` and `.pi/knowledge/*`
2. Implement `strategies/{uuid}/strategy.py`
3. Run smoke and full backtests via `run_nautilus_backtest`
4. Read `strategies/{uuid}/results/latest.json` and summarize metrics

Example prompts:

- *"Backtest a 10/20 EMA cross on ES daily bars from 2020 to 2024."*
- *"Build a weekly golden cross on ES using daily data resampled to weekly."*
- *"Code an opening range breakout on 15-minute bars with a stop at the opening range low."*

### Pi tools and commands

| Command / tool | Description |
|----------------|-------------|
| `/strategy` | Collect a full strategy + backtest brief |
| `/backtest-data` | Summarize discovered `./data` inventory |
| `create_strategy_workspace` | Create `strategies/{uuid}/` before coding |
| `list_strategy_workspaces` | List existing UUID workspaces |
| `inspect_local_market_data` | LLM tool: list local datasets |
| `run_nautilus_backtest` | LLM tool: backtest a workspace strategy |

---

## Running backtests manually (CLI)

Create a workspace first:

```bash
python strategy_workspace.py create "EMA Cross ES Daily" '{}'
```

Implement `strategies/{uuid}/strategy.py`, then run:

```bash
source .venv/bin/activate

python run_backtest.py \
  --workspace YOUR-UUID-HERE \
  --ticker ES \
  --timeframe Daily \
  --start 2020-01-01 \
  --end 2024-01-01 \
  --instrument-specs '{
    "ES": {
      "instrument_type": "future",
      "venue": "GLBX",
      "exchange": "XCME",
      "currency": "USD",
      "price_increment": "0.25",
      "contract_multiplier": 50,
      "account_type": "MARGIN"
    }
  }' \
  --strategy-params '{"fast_period": 10, "slow_period": 20}' \
  --trade-size 1 \
  --commission 2.50
```

Results land in `strategies/{uuid}/results/latest.json`.

List workspaces:

```bash
python strategy_workspace.py list
```

### Reference examples (no workspace)

To run bundled examples without a workspace:

### Resampling example (Daily → Weekly)

When no `ES_Weekly.parquet` exists, aggregate from daily bars:

```bash
python run_backtest.py \
  --ticker ES \
  --timeframe Weekly \
  --source-timeframe Daily \
  --start 2020-01-01 \
  --end 2024-01-01 \
  --instrument-specs '{"ES":{"instrument_type":"future","venue":"GLBX","exchange":"XCME","currency":"USD","price_increment":"0.25","contract_multiplier":50,"account_type":"MARGIN"}}' \
  --strategy-params '{"fast_period": 5, "slow_period": 10}'
```

Rules:

- **Allowed:** finer → coarser (e.g. `1min` → `15min`, `Daily` → `Weekly`)
- **Not allowed:** upsampling coarse data into finer bars

### FX example

```bash
python run_backtest.py \
  --ticker '^EURUSD' \
  --timeframe Daily \
  --start 2020-01-01 \
  --end 2021-01-01 \
  --instrument-specs '{
    "^EURUSD": {
      "instrument_type": "currency_pair",
      "venue": "SIM",
      "currency": "USD",
      "base_currency": "EUR",
      "price_increment": "0.00001",
      "size_increment": "1",
      "lot_size": "1000",
      "account_type": "MARGIN"
    }
  }' \
  --trade-size 1000
```

Supported `instrument_type` values: `future`, `currency_pair`, `equity`.

---

## Writing your own strategy

Every strategy must expose:

1. A **`StrategyConfig`** subclass (`frozen=True`) with at least:
   - `instrument_id: InstrumentId`
   - `bar_type: BarType`
   - `trade_size: Decimal`
2. A **`Strategy`** subclass that uses that config.

The runner injects `instrument_id`, `bar_type`, and `trade_size`. Pass everything else via `--strategy-params` / `strategy_params_json`.

Minimal pattern (see `examples/ema_cross.py` for a full example):

```python
from decimal import Decimal
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

class MyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal
    lookback: int = 20

class MyStrategy(Strategy):
    def __init__(self, config: MyConfig) -> None:
        super().__init__(config)
        # register indicators, state, etc.

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar) -> None:
        ...
```

Place new strategy modules in `strategies/{uuid}/strategy.py`. Use `examples/` only as reference.

Run reference examples without a workspace:

```bash
python run_backtest.py \
  --strategy-module examples.my_strategy \
  --strategy-class MyStrategy \
  --config-class MyConfig \
  --strategy-params '{"lookback": 30}' \
  ... # plus ticker, timeframe, dates, instrument-specs
```

### Bundled examples

| Module | Strategy | Description |
|--------|----------|-------------|
| `examples.ema_cross` | `EMACrossStrategy` | Fast/slow EMA crossover with optional RTH filter |
| `examples.golden_cross` | `GoldenCrossStrategy` | 50/200 SMA golden cross / death cross |
| `examples.opening_range_breakout` | `DualOpeningRangeBreakoutStrategy` | ORB with dual-market confirmation |

---

## Project layout

```text
pi-quant/
├── .pi/
│   ├── extensions/nautilus-backtester.ts
│   ├── skills/nautilus-trader.md
│   ├── prompts/backtest.md
│   └── knowledge/
├── data/                                   # Your Parquet files (not in git)
├── strategies/                             # UUID workspaces (not in git)
│   └── {uuid}/
│       ├── manifest.json
│       ├── strategy.py
│       ├── results/
│       └── artifacts/
├── examples/                               # Reference strategies only
│   ├── ema_cross.py
│   ├── golden_cross.py
│   └── opening_range_breakout.py
├── local_data.py
├── strategy_workspace.py
└── run_backtest.py
```

---

## Output metrics

`strategies/{uuid}/results/latest.json` includes:

- **data** — source file, ticker, timeframes, whether bars were resampled, bar count, date range
- **total_realized_pnl**, **gross_position_pnl**, **total_commissions**
- **total_trades**, **win_rate_pct**, **profit_factor**, **expectancy**
- **max_drawdown**, **trade_sharpe** (per-trade Sharpe, not annualized return Sharpe)

Treat single backtests as research simulations, not proof of live profitability.

---

## Important limitations

- **Local data only** — backtests read from `./data`; nothing is fetched from the internet.
- **Continuous series** — rolled futures and multi-symbol files are modeled as one research instrument; roll gaps are not fully simulated unless you implement roll logic.
- **Instrument metadata is manual** — tick size, multiplier, and venue must be supplied; they cannot be inferred from OHLCV alone.
- **Timezone** — naive timestamps default to `America/Chicago`; set `--data-timezone` if your vendor uses another convention.
- **Bar safety limit** — selections above ~1M bars require a narrower date range.

More detail: `.pi/knowledge/data-contract.md`, `.pi/knowledge/quant-research.md`.

---

## Further reading

- [NautilusTrader docs](https://nautilustrader.io/docs/latest/)
- [Pi extensions docs](https://pi.dev/docs/latest/extensions)
- [NautilusTrader GitHub examples](https://github.com/nautechsystems/nautilus_trader/tree/develop/examples)

---

## License

Use and adapt for your own research. Verify strategy logic, data quality, and execution assumptions before any live trading.
