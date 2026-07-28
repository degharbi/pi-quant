from decimal import Decimal
import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators.average.ema import ExponentialMovingAverage
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


class EMACrossConfig(StrategyConfig, frozen=True):
    """Configuration for the EMA crossover strategy with optional session filter."""
    instrument_id: InstrumentId
    bar_type: BarType
    fast_period: int = 10
    slow_period: int = 20
    trade_size: Decimal = Decimal("1")
    use_rth_filter: bool = True
    rth_start_hour: int = 8
    rth_start_minute: int = 30
    rth_end_hour: int = 15
    rth_end_minute: int = 15


class EMACrossStrategy(Strategy):
    """
    Exponential Moving Average (EMA) Crossover Strategy.
    
    Generates BUY signals when fast EMA crosses above slow EMA,
    and SELL signals when fast EMA crosses below slow EMA.
    Optionally restricts new entry signals to Regular Trading Hours (RTH).
    """

    def __init__(self, config: EMACrossConfig) -> None:
        super().__init__(config)
        self.fast_ema = ExponentialMovingAverage(config.fast_period)
        self.slow_ema = ExponentialMovingAverage(config.slow_period)
        self.instrument_id = config.instrument_id
        self._previous_fast: float | None = None
        self._previous_slow: float | None = None

    def on_start(self) -> None:
        """Called when strategy starts. Registers indicators and subscribes to bars."""
        if self.config.fast_period >= self.config.slow_period:
            raise ValueError("fast_period must be lower than slow_period")
        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
        self.subscribe_bars(self.config.bar_type)

    def _is_in_rth(self, ts_ns: int) -> bool:
        if not self.config.use_rth_filter:
            return True
        # Convert nanoseconds to pandas Timestamp in America/Chicago timezone
        dt = pd.Timestamp(ts_ns, unit="ns", tz="UTC").tz_convert("America/Chicago")
        if dt.weekday() > 4:
            return False
        time_val = dt.time()
        start_time = pd.Timestamp(2000, 1, 1, self.config.rth_start_hour, self.config.rth_start_minute).time()
        end_time = pd.Timestamp(2000, 1, 1, self.config.rth_end_hour, self.config.rth_end_minute).time()
        return start_time <= time_val <= end_time

    def on_bar(self, bar: Bar) -> None:
        """Called on every new bar event."""
        # Wait until indicators have sufficient historical data
        if not self.fast_ema.initialized or not self.slow_ema.initialized:
            return

        is_long = self.portfolio.is_net_long(self.instrument_id)
        is_short = self.portfolio.is_net_short(self.instrument_id)

        fast_val = self.fast_ema.value
        slow_val = self.slow_ema.value
        if self._previous_fast is None or self._previous_slow is None:
            self._previous_fast = fast_val
            self._previous_slow = slow_val
            return

        crossed_above = self._previous_fast <= self._previous_slow and fast_val > slow_val
        crossed_below = self._previous_fast >= self._previous_slow and fast_val < slow_val
        self._previous_fast = fast_val
        self._previous_slow = slow_val

        in_rth = self._is_in_rth(bar.ts_event)

        if crossed_above and not is_long:
            if is_short:
                self.close_all_positions(self.instrument_id)
            if in_rth:
                self._submit_order(OrderSide.BUY)

        elif crossed_below and not is_short:
            if is_long:
                self.close_all_positions(self.instrument_id)
            if in_rth:
                self._submit_order(OrderSide.SELL)

    def _submit_order(self, side: OrderSide) -> None:
        order = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=Quantity.from_str(str(self.config.trade_size)),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

    def on_stop(self) -> None:
        """Cleanup positions on strategy stop."""
        self.close_all_positions(self.instrument_id)
