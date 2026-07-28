# NautilusTrader API Notes

## Version rule

The official `latest` documentation currently describes the recommended high-level `BacktestNode` workflow and may require Python 3.12+. This project currently runs its installed package from a Python 3.10 virtual environment. Treat installed source signatures as authoritative for executable code.

## Strategy lifecycle

- Config: subclass `nautilus_trader.config.StrategyConfig` with `frozen=True`.
- Strategy: subclass `nautilus_trader.trading.strategy.Strategy`.
- `on_start`: register indicators, subscribe to bars, initialize runtime state.
- `on_bar`: process only completed bars delivered by the engine.
- `on_stop`: apply the explicitly selected end-of-run position policy.
- Orders: create with `self.order_factory` and submit with `self.submit_order`.
- Portfolio: check net position state before creating a new order.

## Backtest APIs

Official guidance:

- `BacktestNode`: high-level, config-driven, streams Nautilus-native data from `ParquetDataCatalog`, and is preferred for production-shaped workflows.
- `BacktestEngine`: low-level, direct component/data access, useful for custom loaders, quick experiments, and repeated optimization with `reset()`.

This project uses `BacktestEngine` because the existing files are ordinary OHLCV Parquet tables, not a Nautilus `ParquetDataCatalog`. `local_data.py` converts selected rows into Nautilus `Bar` objects. A future migration can build a separate derived catalog, but the raw `./data` files must remain the only market-data source.

## Shared runner contract

`run_backtest.py`:

1. validates ticker, timeframe, and dates through `local_data.py`;
2. creates continuous research instruments from explicitly supplied instrument metadata;
3. creates a GLBX margin/netting venue;
4. charges fixed commission per order;
5. dynamically imports a strategy and config;
6. injects `instrument_id`, `bar_type`, and `trade_size`;
7. passes strategy-specific JSON fields;
8. writes results into the workspace (`strategies/{uuid}/results/`) or `backtest_results.json` for legacy non-workspace runs.

Generated configs must accept every injected field. Class and module names are explicit tool arguments.

## Official references

- Documentation home: https://nautilustrader.io/docs/latest/
- Backtesting concepts: https://nautilustrader.io/docs/latest/concepts/backtesting/
- High-level backtest tutorial: https://nautilustrader.io/docs/latest/getting_started/backtest_high_level/
- Strategy concepts: https://nautilustrader.io/docs/latest/concepts/strategies/
- Loading data: https://nautilustrader.io/docs/latest/concepts/data/
- Upstream repository: https://github.com/nautechsystems/nautilus_trader
- High-level Python example: https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/getting_started/backtest_high_level.py
- Backtest examples: https://github.com/nautechsystems/nautilus_trader/tree/develop/examples/backtest
- Strategy examples: https://github.com/nautechsystems/nautilus_trader/tree/develop/nautilus_trader/examples/strategies

Before copying an upstream example, compare its imports and constructor signatures with the installed package.
