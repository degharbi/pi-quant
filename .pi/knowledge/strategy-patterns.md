# Nautilus Strategy Patterns

## Required config shape

```python
from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId


class MyStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal
    lookback: int
```

Keep all tunable strategy, session, and risk values in config fields.

## Initialization

Create indicators in `__init__`. In `on_start`, validate parameter relationships, register each indicator against `bar_type`, and subscribe to that bar type.

Do not manually update an indicator that was registered for bars; the engine updates it before `on_bar`.

## Signals

- Wait for every required indicator to be initialized.
- A crossover requires previous and current values:
  - bullish: previous fast <= previous slow and current fast > current slow
  - bearish: previous fast >= previous slow and current fast < current slow
- A breakout based on N prior bars must exclude the current bar from its reference range.
- A signal calculated from a completed bar can fill no earlier than the engine's next executable event under the chosen order semantics.
- Persist signal state on the strategy instance, not in config.

## Orders and position state

- Futures quantities are whole contracts.
- Check net-long/net-short/flat state before entry.
- Avoid issuing an entry while a close or prior entry remains open.
- Reversal semantics must be deliberate: close then reverse, reduce-only, or one net order.
- Market orders use `TimeInForce.GTC` unless the strategy requires another supported policy.
- Stop and target order behavior must account for gaps; do not assume fills exactly at trigger prices.

## Session controls

Represent trading windows and timezone explicitly. Define:

- allowed weekdays;
- entry start and cutoff;
- forced-flat time;
- overnight permission;
- holiday handling;
- daylight-saving convention.

The loader interprets local file timestamps as `America/Chicago` and converts them to UTC before creating bars. Define strategy sessions with explicit timezone conversion and daylight-saving behavior.

## Risk controls

At minimum consider:

- initial stop;
- maximum contracts;
- one-position or pyramiding policy;
- maximum daily loss;
- maximum trades per session;
- cooldown after losses;
- stale/pending order cancellation;
- end-of-run position handling.

Do not add controls the user did not request without identifying them as proposed assumptions.
