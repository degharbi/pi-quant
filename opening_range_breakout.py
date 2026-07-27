from decimal import Decimal

import pandas as pd
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy


class DualOpeningRangeBreakoutConfig(StrategyConfig, frozen=True):
    """
    Configuration for a two-market Opening Range Breakout confirmation strategy.

    Monitors the opening range for a primary and confirmation market. A trade in
    the primary market requires both markets to break in the same direction.
    Closes all positions at the end of the trading day (15:15 CT).
    """

    instrument_id: InstrumentId
    bar_type: BarType
    confirmation_instrument_id: str
    confirmation_bar_type: str
    trade_size: Decimal = Decimal("1")
    rth_open_time: str = "08:30"
    rth_breakout_time: str = "08:45"
    eod_close_time: str = "15:15"
    target_rr: float | None = None
    use_close_breakout: bool = False


class DualOpeningRangeBreakoutStrategy(Strategy):
    """Opening Range Breakout strategy confirmed by a second local market."""

    def __init__(self, config: DualOpeningRangeBreakoutConfig) -> None:
        super().__init__(config)
        self.primary_instrument_id = config.instrument_id
        self.confirmation_instrument_id = InstrumentId.from_str(
            config.confirmation_instrument_id,
        )
        self.primary_bar_type = config.bar_type
        self.confirmation_bar_type = BarType.from_str(config.confirmation_bar_type)

        self._current_date: str | None = None
        self._primary_first_bar: Bar | None = None
        self._confirmation_first_bar: Bar | None = None
        self._primary_second_bar: Bar | None = None
        self._confirmation_second_bar: Bar | None = None
        self._evaluated_today: bool = False
        self._eod_closed_today: bool = False

    def on_start(self) -> None:
        self.subscribe_bars(self.primary_bar_type)
        self.subscribe_bars(self.confirmation_bar_type)

    def on_bar(self, bar: Bar) -> None:
        """Process an opening-range bar from either configured market."""
        # Convert timestamp to America/Chicago time
        ts_dt = pd.Timestamp(bar.ts_event, unit="ns", tz="UTC").tz_convert("America/Chicago")
        date_str = ts_dt.strftime("%Y-%m-%d")
        time_str = ts_dt.strftime("%H:%M")

        # New trading day reset
        if self._current_date != date_str:
            self._current_date = date_str
            self._primary_first_bar = None
            self._confirmation_first_bar = None
            self._primary_second_bar = None
            self._confirmation_second_bar = None
            self._evaluated_today = False
            self._eod_closed_today = False

        # Store 1st bar (08:30 CT)
        if time_str == self.config.rth_open_time:
            if bar.bar_type == self.primary_bar_type:
                self._primary_first_bar = bar
            elif bar.bar_type == self.confirmation_bar_type:
                self._confirmation_first_bar = bar

        # Store 2nd bar (08:45 CT)
        elif time_str == self.config.rth_breakout_time:
            if bar.bar_type == self.primary_bar_type:
                self._primary_second_bar = bar
            elif bar.bar_type == self.confirmation_bar_type:
                self._confirmation_second_bar = bar

        # Evaluate signals once both 2nd bars are received on the breakout bar timestamp
        if (
            not self._evaluated_today
            and self._primary_first_bar
            and self._confirmation_first_bar
            and self._primary_second_bar
            and self._confirmation_second_bar
        ):
            self._evaluate_breakout()

        # End of Day Exit (15:15 CT)
        if time_str >= self.config.eod_close_time and not self._eod_closed_today:
            self._close_all_end_of_day()

    def _evaluate_breakout(self) -> None:
        """Trade when both configured markets break in the same direction."""
        self._evaluated_today = True

        if self.config.use_close_breakout:
            primary_break_up = self._primary_second_bar.close > self._primary_first_bar.high
            confirmation_break_up = (
                self._confirmation_second_bar.close > self._confirmation_first_bar.high
            )
            primary_break_down = self._primary_second_bar.close < self._primary_first_bar.low
            confirmation_break_down = (
                self._confirmation_second_bar.close < self._confirmation_first_bar.low
            )
        else:
            primary_break_up = self._primary_second_bar.high > self._primary_first_bar.high
            confirmation_break_up = (
                self._confirmation_second_bar.high > self._confirmation_first_bar.high
            )
            primary_break_down = self._primary_second_bar.low < self._primary_first_bar.low
            confirmation_break_down = (
                self._confirmation_second_bar.low < self._confirmation_first_bar.low
            )

        # Both break UP -> Go LONG
        if (
            primary_break_up
            and confirmation_break_up
            and not (primary_break_down and confirmation_break_down)
        ):
            self._enter_trade(
                instrument_id=self.primary_instrument_id,
                side=OrderSide.BUY,
                entry_bar=self._primary_second_bar,
                stop_price=self._primary_first_bar.low,
            )

        # Both break DOWN -> Go SHORT
        elif (
            primary_break_down
            and confirmation_break_down
            and not (primary_break_up and confirmation_break_up)
        ):
            self._enter_trade(
                instrument_id=self.primary_instrument_id,
                side=OrderSide.SELL,
                entry_bar=self._primary_second_bar,
                stop_price=self._primary_first_bar.high,
            )

    def _enter_trade(
        self,
        instrument_id: InstrumentId,
        side: OrderSide,
        entry_bar: Bar,
        stop_price: Price,
    ) -> None:
        """Submit a market entry order, stop-loss order, and optional take-profit order."""
        qty = Quantity.from_str(str(self.config.trade_size))

        # Market entry
        entry_order = self.order_factory.market(
            instrument_id=instrument_id,
            order_side=side,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(entry_order)

        # Stop loss order
        stop_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        stop_order = self.order_factory.stop_market(
            instrument_id=instrument_id,
            order_side=stop_side,
            quantity=qty,
            trigger_price=stop_price,
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self.submit_order(stop_order)

        # Optional Take Profit order
        if self.config.target_rr is not None and self.config.target_rr > 0:
            entry_px = float(entry_bar.close)
            stop_px = float(stop_price)
            risk = abs(entry_px - stop_px)
            if side == OrderSide.BUY:
                tp_px = entry_px + (risk * self.config.target_rr)
            else:
                tp_px = entry_px - (risk * self.config.target_rr)

            tp_price_obj = Price.from_str(f"{tp_px:.2f}")
            tp_order = self.order_factory.limit(
                instrument_id=instrument_id,
                order_side=stop_side,
                quantity=qty,
                price=tp_price_obj,
                time_in_force=TimeInForce.GTC,
                reduce_only=True,
            )
            self.submit_order(tp_order)

    def _close_all_end_of_day(self) -> None:
        """Cancel pending orders and close all open positions at end of day."""
        self._eod_closed_today = True
        for instrument_id in (
            self.primary_instrument_id,
            self.confirmation_instrument_id,
        ):
            self.cancel_all_orders(instrument_id)
            self.close_all_positions(instrument_id)

    def on_position_closed(self, event: PositionClosed) -> None:
        """Cancel remaining stop loss / take profit orders when position closes."""
        self.cancel_all_orders(event.instrument_id)

    def on_stop(self) -> None:
        """Cleanup positions on strategy stop."""
        for instrument_id in (
            self.primary_instrument_id,
            self.confirmation_instrument_id,
        ):
            self.cancel_all_orders(instrument_id)
            self.close_all_positions(instrument_id)
