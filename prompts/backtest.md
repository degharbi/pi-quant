---
description: Define, implement, and evaluate a local-data Nautilus strategy in a UUID workspace
---

Apply the `nautilus-trader` skill.

Runtime setup (venv + deps) is automatic — never ask the user to pip install or activate a virtualenv.

First call `inspect_local_market_data`. Use only market data under `./data`.

If the user has not specified all items below, ask for them in one compact intake:

- requested market present in the discovered inventory
- strategy timeframe and, if needed, a finer local source timeframe for resampling
- start/end dates and optional out-of-sample dates
- long/short direction
- exact entry and exit rules
- position size and risk limits
- trading session and timezone
- commission, slippage, and starting balance
- verified instrument type, venue, currency, tick size, source timezone, and type-specific metadata

Do not invent missing values and do not generate synthetic or external data.

After the brief is complete:

1. Call `create_strategy_workspace` and store the confirmed brief in the manifest.
2. Implement the strategy only in `strategies/{uuid}/strategy.py`.
3. Save any charts, notes, or exports to `strategies/{uuid}/artifacts/`.
4. Use the exact requested timeframe if stored locally. Otherwise aggregate a finer local source into the coarser strategy timeframe; daily-to-weekly and daily-to-monthly are valid. Never upsample.
5. Run a short smoke backtest with `run_nautilus_backtest`.
6. Run the full requested range in the same workspace.
7. Analyze `strategies/{uuid}/results/latest.json`, clearly labeling `trade_sharpe` and whether bars were resampled.
8. State continuous-contract, timestamp, roll, fill, and cost limitations.
9. Suggest robustness tests, not parameter changes chosen only to increase in-sample profit.

Never create new strategy code in the project root or `python/examples/`.
