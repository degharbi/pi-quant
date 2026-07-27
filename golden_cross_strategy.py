from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators.average.sma import SimpleMovingAverage
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


class GoldenCrossConfig(StrategyConfig, frozen=True):
    """Configuration for the Golden Cross strategy."""

    instrument_id: InstrumentId
    bar_type: BarType
    fast_period: int = 50
    slow_period: int = 200
    trade_size: Decimal = Decimal("1")
    allow_short: bool = False


class GoldenCrossStrategy(Strategy):
    """
    Golden Cross Strategy (50-day / 200-day Simple Moving Average crossover).

    Generates BUY signals when fast SMA crosses above slow SMA (Golden Cross).
    When fast SMA crosses below slow SMA (Death Cross), closes long positions
    and optionally opens a SHORT position if allow_short is True.
    """

    def __init__(self, config: GoldenCrossConfig) -> None:
        super().__init__(config)
        self.fast_sma = SimpleMovingAverage(config.fast_period)
        self.slow_sma = SimpleMovingAverage(config.slow_period)
        self.instrument_id = config.instrument_id
        self._previous_fast: float | None = None
        self._previous_slow: float | None = None

    def on_start(self) -> None:
        """Called when strategy starts. Registers indicators and subscribes to bars."""
        if self.config.fast_period >= self.config.slow_period:
            raise ValueError("fast_period must be lower than slow_period")
        self.register_indicator_for_bars(self.config.bar_type, self.fast_sma)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_sma)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        """Called on every new bar event."""
        if not self.fast_sma.initialized or not self.slow_sma.initialized:
            return

        is_long = self.portfolio.is_net_long(self.instrument_id)
        is_short = self.portfolio.is_net_short(self.instrument_id)

        fast_val = self.fast_sma.value
        slow_val = self.slow_sma.value

        if self._previous_fast is None or self._previous_slow is None:
            self._previous_fast = fast_val
            self._previous_slow = slow_val
            return

        # Crossover detection
        golden_cross = self._previous_fast <= self._previous_slow and fast_val > slow_val
        death_cross = self._previous_fast >= self._previous_slow and fast_val < slow_val

        self._previous_fast = fast_val
        self._previous_slow = slow_val

        if golden_cross:
            if is_short:
                self.close_all_positions(self.instrument_id)
            if not is_long:
                self._submit_order(OrderSide.BUY)

        elif death_cross:
            if is_long:
                self.close_all_positions(self.instrument_id)
            if self.config.allow_short and not is_short:
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
