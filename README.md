# pi-quant

A [Pi](https://pi.dev) package for designing and backtesting [NautilusTrader](https://nautilustrader.io/) strategies on **your local market data**.

You install Pi + this package, drop data in `./data`, and ask for strategies. The agent explores your file layout once, writes project-local memory under `.pi-quant/`, then reuses that adapter on later runs. It also creates the Python environment, installs dependencies, scaffolds workspaces, and runs backtests.

---

## Quick start

**1. Install Pi and this package**

```bash
pi install git:github.com/degharbi/pi-quant
# or when published: pi install npm:pi-quant
# project-local:     pi install git:github.com/degharbi/pi-quant -l
```

**2. Put market data in the project**

```text
your-project/
└── data/
    ES_Daily.csv
    ES_5min.parquet
    EURUSD_Daily.csv
```

Any tabular OHLCV layout works. Helpful naming: `{TICKER}_{TIMEFRAME}.ext`  
Normalized columns (via adapter): `Date`, `Open`, `High`, `Low`, `Close`, `Volume`, `Symbol`

**3. Start Pi and ask**

```bash
cd your-project
pi
```

Examples:

- *“What data do I have?”* → `/backtest-data`
- *“Build a 10/20 EMA cross on ES daily from 2020–2024.”* → `/strategy` or free-form chat

On first use, pi-quant automatically:

- creates `./data` and `./strategies` if missing
- creates `./.venv` with Python 3.10+
- installs `nautilus_trader`, `pandas`, `pyarrow`, `numpy`

On first data inspect, the agent explores `./data` and writes:

```text
.pi-quant/
├── data_profile.json
└── data_adapter.py
```

Later sessions reuse that memory until files change.

Prerequisite: **Python 3.10+** available on `PATH` (the agent uses it only to bootstrap the venv).

Add `.pi-quant/` to your project `.gitignore` unless you want to share the learned adapter.

---

## Using Pi

| Command / tool | Description |
|----------------|-------------|
| `/strategy` | Collect a full strategy + backtest brief |
| `/backtest-data` | Summarize discovered `./data` inventory |
| `create_strategy_workspace` | Create `strategies/{uuid}/` |
| `list_strategy_workspaces` | List UUID workspaces |
| `inspect_local_market_data` | List local datasets or raw probe when adapter missing |
| `run_nautilus_backtest` | Backtest a workspace strategy |

Each strategy lives in:

```text
strategies/{uuid}/
├── manifest.json
├── strategy.py
├── results/
└── artifacts/
```

---

## Developing this repository

```bash
git clone https://github.com/degharbi/pi-quant.git
cd pi-quant
# add files under data/
pi
```

`.pi/settings.json` loads the package from the repo root. Runtime setup is still automatic.

---

## What the package ships

| Path | Purpose |
|------|---------|
| `extensions/` | Auto-setup + backtest tools + `/strategy` |
| `skills/nautilus-trader/` | Workflow skill + references |
| `prompts/` | `/backtest` prompt |
| `python/` | Loaders, workspace helpers, runner, examples |

Project cwd (managed for you): `data/`, `strategies/`, `.venv/`, `.pi-quant/` (agent-written)

---

## Limitations

- Local data only — nothing is fetched as market data
- Backtests require a ready project data adapter under `.pi-quant/`
- Continuous futures are one research series; rolls are not fully simulated
- Instrument metadata (tick, multiplier, venue) must be supplied in the brief
- Naive timestamps default to `America/Chicago`
- Selections above ~1M bars need a narrower date range
- First-run dependency install can take several minutes

---

## Further reading

- [Pi packages](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md)
- [NautilusTrader docs](https://nautilustrader.io/docs/latest/)
- Skill references under `skills/nautilus-trader/references/`
