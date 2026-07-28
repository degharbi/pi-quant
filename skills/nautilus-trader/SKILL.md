---
name: nautilus-trader
description: Designs, codes, and evaluates NautilusTrader strategies using project-local market data with agent-learned adapters. Use for strategy ideation, implementation, backtesting, optimization, or analysis.
---

# Nautilus Strategy Workflow

## Runtime (automatic)

The pi-quant extension creates `.venv`, installs Python deps, and ensures `./data` / `./strategies` exist. Never ask the user to activate a venv or run `pip install`. If setup fails, report the error and that Python 3.10+ on PATH is required.

## Non-negotiable data contract

- Use only files already present under `./data`.
- Call `inspect_local_market_data` before proposing tickers, timeframes, or dates.
- If `needs_adapter` is true, explore `./data`, write `.pi-quant/data_adapter.py` and `.pi-quant/data_profile.json`, then re-inspect until `adapter_status` is `ready`.
- Discover markets and source timeframes from the adapter inventory; never encode a fixed market allowlist in skills or scripts.
- The strategy timeframe can differ from the stored timeframe. Aggregate finer local bars into coarser bars when needed.
- Never download data, generate synthetic data, silently resample data, or read an arbitrary path.
- Always inspect coverage before selecting dates.
- Inspect the `Symbol` column and user request to identify instrument type. If symbols roll through contracts, treat the file as a continuous research series and disclose roll limitations.
- Read [./references/data-contract.md](./references/data-contract.md) and [./references/data-adapter-template.md](./references/data-adapter-template.md) before changing data-loading code.

## Workspace contract

Every new strategy starts in its own UUID folder under `./strategies/`.

1. Call `create_strategy_workspace` after the brief is confirmed.
2. Implement code only in `strategies/{uuid}/strategy.py`.
3. Save charts, notes, exports, and diagnostics in `strategies/{uuid}/artifacts/`.
4. Run backtests with `run_nautilus_backtest` and the same `workspace_id`.
5. Do not create new strategies in the project root or `python/examples/`.

Read [./references/workspace.md](./references/workspace.md) before creating or editing strategy workspaces.

## Intake gate

Before writing code, obtain explicit answers for:

1. Market requested by the user and confirmed by local data discovery.
2. Strategy timeframe and the exact local source timeframe, if resampling is required.
3. In-sample date range and, when evaluating robustness, separate out-of-sample range.
4. Long-only, short-only, or both.
5. Entry rules with exact indicators, lookbacks, thresholds, and signal timing.
6. Exit rules: stop, target, trailing stop, time exit, opposite signal, end-of-session behavior.
7. Position size in valid instrument units and portfolio limits.
8. Trading days/hours and timezone.
9. Commission and slippage assumptions.
10. Starting balance and performance objective or acceptance criteria.

Do not invent missing trading parameters. Ask one compact set of questions, or direct the user to `/strategy`.

## Implementation contract

- Subclass `StrategyConfig` with `frozen=True`.
- Every generated config must include `instrument_id: InstrumentId`, `bar_type: BarType`, and `trade_size: Decimal`.
- Subclass `Strategy` and accept only the config object in `__init__`.
- Register indicators and subscribe to bars in `on_start`.
- Avoid look-ahead: make decisions only from the current and prior completed bars.
- Detect crossings with prior values; do not treat a persistent inequality as a new signal.
- Check current portfolio state and pending/open orders before submitting.
- Obtain instrument type, tick size, price precision, contract multiplier, venue, exchange, and currency from reliable metadata or the user; never infer a contract multiplier from OHLCV prices.
- Make session filters and risk controls explicit config fields.
- Close or preserve end-of-run positions according to the user's stated policy.
- Keep strategy-specific values in config so parameter sweeps do not require code edits.

The shared runner loads `strategies/{uuid}/strategy.py` when `--workspace` / `workspace_id` is provided. Pass strategy-only fields through `strategy_params_json`; it supplies `instrument_id`, `bar_type`, and `trade_size`.

Use `python/examples/` only as reference patterns. Never write new user strategies there.

## Backtest workflow

1. Call `inspect_local_market_data`. If `needs_adapter`, explore `./data` and write `.pi-quant/` memory first.
2. Confirm the strategy brief with the user.
3. Call `create_strategy_workspace`.
4. Implement `strategies/{uuid}/strategy.py`.
5. Select the requested market. Prefer an exact stored timeframe; otherwise select a finer source and resample to the coarser strategy timeframe.
6. Never upsample coarse bars into finer bars. Never resample from external data.
7. Read [./references/nautilus-api.md](./references/nautilus-api.md) and [./references/strategy-patterns.md](./references/strategy-patterns.md).
8. Run a short smoke backtest on the requested dataset and range.
9. Run the full requested range only after the smoke run succeeds.
10. Read results from `strategies/{uuid}/results/latest.json`.
11. Report workspace id, source and resulting timeframes, resampling status, dates, bar count, costs, sizing, PnL, trades, win rate, profit factor, expectancy, drawdown, and trade Sharpe.
12. Read [./references/quant-research.md](./references/quant-research.md) before interpreting or optimizing results.

## Optimization rules

- Never optimize on the test/out-of-sample period.
- Prefer a small hypothesis-driven parameter grid over broad brute force.
- Include costs in every run.
- Reject parameter sets with too few trades for the claimed conclusion.
- Compare neighboring parameter values; isolated peaks are unstable.
- Use walk-forward or anchored splits for final assessment.
- Never claim profitability or production readiness from one backtest.

## API source priority

When API behavior is uncertain, use this order:

1. Installed package source under `./.venv` (`site-packages/nautilus_trader`).
2. Curated local notes under this skill's `references/`.
3. Current official docs and upstream GitHub examples linked in those notes.

The website's `latest` docs can target a newer Python/package generation than the installed environment. Verify imports and constructor signatures locally before coding.
