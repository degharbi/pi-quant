---
description: Define, implement, and evaluate a local-data Nautilus strategy
---

Apply the `nautilus-trader` skill.

First call `inspect_local_market_data`. Discover compatible files dynamically and use only market data under `./data`.

If the user has not specified all items below, ask for them in one compact intake:

- requested market present in the discovered inventory
- strategy timeframe and, if needed, a finer local source timeframe for resampling
- start/end dates and optional out-of-sample dates
- long/short direction
- exact entry and exit rules
- whole-contract sizing and risk limits
- trading session and timezone
- commission, slippage, and starting balance
- verified instrument type, venue, currency, tick size, source timezone, and type-specific metadata such as contract multiplier or base currency
- success criteria

Do not invent missing values and do not generate synthetic or external data.

After the brief is complete:

1. Use the exact requested timeframe if stored locally. Otherwise aggregate a finer local source into the coarser strategy timeframe; daily-to-weekly and daily-to-monthly are valid. Never upsample.
2. Code a Nautilus `StrategyConfig` and `Strategy` compatible with `run_backtest.py`.
3. Run a short smoke range.
4. Run the requested range with `run_nautilus_backtest`.
5. Analyze `backtest_results.json`, clearly labeling `trade_sharpe` and whether bars were resampled.
6. State continuous-contract, timestamp, roll, fill, and cost limitations.
7. Suggest robustness tests, not parameter changes chosen only to increase in-sample profit.
