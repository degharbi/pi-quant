# Quant Research Guardrails

## Research design

- Write the economic or behavioral hypothesis before inspecting optimized results.
- Separate training, validation, and final test periods chronologically.
- Use walk-forward evaluation when parameters are expected to adapt.
- Keep the final test period untouched until strategy and parameter choices are frozen.
- Compare against simple benchmarks: buy-and-hold where meaningful, always-flat, and a basic trend or mean-reversion baseline.

## Biases to check

- Look-ahead and same-bar execution.
- Survivorship and selection bias.
- Continuous-futures roll artifacts.
- Timestamp/session misalignment.
- Reusing a test period during iteration.
- Multiple-testing and parameter-mining bias.
- Ignoring commissions, spread, slippage, latency, and market impact.
- Unrealistic fills for stops, limits, and gaps.

## Metrics

Always report:

- data source, timeframe, range, and bar count;
- starting balance, contract size, and costs;
- total and average trade PnL;
- trade count and exposure when available;
- win rate, average win/loss, profit factor, and expectancy;
- maximum drawdown;
- a risk-adjusted metric with its sampling convention;
- in-sample versus out-of-sample results.

`trade_sharpe` from the shared runner is based on per-trade PnL and is not an annualized return Sharpe. Label it accurately.

## Robustness

- Require enough independent trades for the claim being made.
- Inspect parameter neighborhoods, not only the best point.
- Stress commissions and slippage above the base case.
- Test subperiods and market regimes.
- Compare different discovered markets only if the hypothesis reasonably transfers.
- Prefer stable performance across nearby values and periods over maximum backtest PnL.

## Interpretation

A backtest is a simulation under explicit assumptions, not evidence of guaranteed profitability. State material assumptions and limitations next to the result. Do not recommend live deployment without out-of-sample validation, execution stress tests, and paper trading.
