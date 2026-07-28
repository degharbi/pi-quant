from __future__ import annotations

import argparse
import importlib
import json
from decimal import Decimal
from typing import Any

import numpy as np

from local_data import load_bars
from local_data import make_instrument
from local_data import make_selection
from project_paths import project_root
from strategy_workspace import load_manifest
from strategy_workspace import load_strategy as load_workspace_strategy
from strategy_workspace import record_run
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FixedFeeModel
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money


def _load_strategy_module(
    *,
    workspace: str | None,
    strategy_module: str,
    strategy_class: str,
    config_class: str,
    config_values: dict[str, Any],
):
    if workspace:
        manifest = load_manifest(workspace)
        return load_workspace_strategy(
            workspace,
            strategy_class or manifest["strategy_class"],
            config_class or manifest["config_class"],
            config_values,
        )

    if not strategy_module.replace("_", "").replace(".", "").isalnum():
        raise ValueError("Strategy module must be a Python dotted module path")
    module = importlib.import_module(strategy_module)
    strategy_type = getattr(module, strategy_class)
    config_type = getattr(module, config_class)
    return strategy_type(config=config_type(**config_values))


def _pnl_value(value: Any) -> float:
    return float(str(value).split()[0].replace(",", ""))


def _metrics(engine: BacktestEngine, metadata: dict, request: dict) -> dict:
    positions = engine.trader.generate_positions_report()
    fills = engine.trader.generate_fills_report()
    commissions = (
        float(fills["commission"].map(_pnl_value).sum())
        if not fills.empty and "commission" in fills.columns
        else 0.0
    )
    base = {
        "status": "success",
        "request": request,
        "data": metadata,
        "total_trades": 0,
        "gross_position_pnl": 0.0,
        "total_commissions": round(commissions, 2),
        "total_realized_pnl": 0.0,
        "win_rate_pct": 0.0,
        "profit_factor": 0.0,
        "expectancy": 0.0,
        "max_drawdown": 0.0,
        "trade_sharpe": 0.0,
    }
    if positions.empty or "realized_pnl" not in positions.columns:
        return base

    gross_pnls = positions["realized_pnl"].map(_pnl_value)
    pnls = gross_pnls - (commissions / len(gross_pnls))
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    cumulative = pnls.cumsum()
    drawdown = cumulative - cumulative.cummax()
    deviation = float(pnls.std())
    gross_pnl = float(gross_pnls.sum())
    base.update(
        {
            "total_trades": int(len(pnls)),
            "gross_position_pnl": round(gross_pnl, 2),
            "total_realized_pnl": round(gross_pnl - commissions, 2),
            "win_rate_pct": round(float((pnls > 0).mean() * 100), 2),
            "profit_factor": (
                round(float(wins.sum() / abs(losses.sum())), 3)
                if not losses.empty and losses.sum() != 0
                else None
            ),
            "expectancy": round(float(pnls.mean()), 2),
            "average_win": round(float(wins.mean()), 2) if not wins.empty else 0.0,
            "average_loss": round(float(losses.mean()), 2) if not losses.empty else 0.0,
            "max_drawdown": round(float(drawdown.min()), 2),
            "trade_sharpe": (
                round(float((pnls.mean() / deviation) * np.sqrt(len(pnls))), 3)
                if deviation > 0
                else 0.0
            ),
        },
    )
    return base


def run_backtest(
    *,
    ticker: str,
    timeframe: str,
    start: str,
    end: str,
    workspace: str | None = None,
    strategy_module: str = "examples.ema_cross",
    strategy_class: str | None = None,
    config_class: str | None = None,
    strategy_params: dict[str, Any] | None = None,
    instrument_specs: dict[str, dict[str, Any]] | None = None,
    source_timeframe: str | None = None,
    data_timezone: str = "America/Chicago",
    trade_size: int = 1,
    starting_balance: Decimal = Decimal("100000"),
    commission: Decimal = Decimal("2.50"),
) -> dict:
    if trade_size <= 0:
        raise ValueError("trade_size must be positive")
    if starting_balance <= 0:
        raise ValueError("starting_balance must be positive")
    if commission < 0:
        raise ValueError("commission cannot be negative")

    manifest = load_manifest(workspace) if workspace else None
    if workspace:
        strategy_class_name = strategy_class or manifest["strategy_class"]
        config_class_name = config_class or manifest["config_class"]
    else:
        strategy_class_name = strategy_class or "EMACrossStrategy"
        config_class_name = config_class or "EMACrossConfig"

    tickers = [value.strip() for value in ticker.split(",") if value.strip()]
    if not tickers:
        raise ValueError("At least one local-data ticker is required")
    instrument_specs = instrument_specs or {}
    specs_by_ticker = {key.casefold(): value for key, value in instrument_specs.items()}
    missing_specs = [value for value in tickers if value.casefold() not in specs_by_ticker]
    if missing_specs:
        raise ValueError(
            "Instrument metadata is required for every ticker; missing specs for "
            f"{missing_specs}. Include instrument_type, venue, currency, "
            "price_increment, and type-specific fields.",
        )
    venues = {specs_by_ticker[value.casefold()].get("venue", "GLBX") for value in tickers}
    currencies = {specs_by_ticker[value.casefold()].get("currency", "USD") for value in tickers}
    account_types = {
        str(specs_by_ticker[value.casefold()].get("account_type", "MARGIN")).upper()
        for value in tickers
    }
    if len(venues) != 1 or len(currencies) != 1 or len(account_types) != 1:
        raise ValueError(
            "One backtest run currently requires a common venue, currency, and account type",
        )
    venue_name = venues.pop()
    currency_code = currencies.pop()
    account_type = AccountType[account_types.pop()]
    currency = Currency.from_str(currency_code)
    selections = [
        make_selection(
            value,
            timeframe,
            start,
            end,
            source_timeframe=source_timeframe,
            venue=venue_name,
            data_timezone=data_timezone,
        )
        for value in tickers
    ]
    engine = BacktestEngine(
        config=BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")),
    )
    venue_options = {
        "venue": Venue(venue_name),
        "oms_type": OmsType.NETTING,
        "account_type": account_type,
        "starting_balances": [Money(starting_balance, currency)],
        "base_currency": currency,
    }
    if commission > 0:
        venue_options["fee_model"] = FixedFeeModel(
            commission=Money(commission, currency),
            charge_commission_once=True,
        )
    engine.add_venue(**venue_options)

    metadata_list = []
    for selection in selections:
        spec = specs_by_ticker[selection.ticker.casefold()]
        price_increment = Decimal(str(spec["price_increment"]))
        price_precision = max(0, -price_increment.normalize().as_tuple().exponent)
        bars, metadata = load_bars(selection, price_precision=price_precision)
        instrument = make_instrument(
            selection.ticker,
            spec=spec,
        )
        engine.add_instrument(instrument)
        engine.add_data(bars)
        metadata_list.append(metadata)

    primary_meta = metadata_list[0] if len(metadata_list) == 1 else {
        "source": f"Multi-ticker ({', '.join(tickers)})",
        "ticker": ",".join(tickers),
        "timeframe": timeframe,
        "start": metadata_list[0]["start"],
        "end": metadata_list[0]["end"],
        "bars": sum(m["bars"] for m in metadata_list),
        "rejected_rows": sum(m["rejected_rows"] for m in metadata_list),
        "contracts": sum(m["contracts"] for m in metadata_list),
    }

    config_values = {
        "instrument_id": selections[0].instrument_id,
        "bar_type": selections[0].bar_type,
        "trade_size": Decimal(trade_size),
        **(strategy_params or {}),
    }
    strategy = _load_strategy_module(
        workspace=workspace,
        strategy_module=strategy_module,
        strategy_class=strategy_class_name,
        config_class=config_class_name,
        config_values=config_values,
    )
    engine.add_strategy(strategy)
    engine.run()

    request = {
        "workspace": workspace,
        "strategy_module": strategy_module if not workspace else f"strategies/{workspace}/strategy.py",
        "strategy_class": strategy_class_name,
        "config_class": config_class_name,
        "strategy_params": strategy_params or {},
        "instrument_specs": instrument_specs,
        "source_timeframe": source_timeframe,
        "data_timezone": data_timezone,
        "trade_size": trade_size,
        "starting_balance": str(starting_balance),
        "commission_per_order": str(commission),
    }
    result = _metrics(engine, primary_meta, request)
    if workspace:
        record_run(workspace, result)
    else:
        legacy = project_root() / "backtest_results.json"
        legacy.write_text(json.dumps(result, indent=2), encoding="utf-8")
    engine.dispose()
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Nautilus backtest using only project-local Parquet data.",
    )
    parser.add_argument("--workspace", help="UUID strategy workspace under ./strategies")
    parser.add_argument("--ticker", required=True, help="Discovered ticker or comma-separated tickers")
    parser.add_argument("--timeframe", required=True, help="Requested strategy timeframe")
    parser.add_argument("--source-timeframe", help="Optional finer local timeframe to resample")
    parser.add_argument("--data-timezone", default="America/Chicago")
    parser.add_argument(
        "--instrument-specs",
        required=True,
        help="JSON object keyed by ticker with instrument metadata",
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--strategy-module", default="examples.ema_cross")
    parser.add_argument("--strategy-class")
    parser.add_argument("--config-class")
    parser.add_argument("--strategy-params", default="{}")
    parser.add_argument("--trade-size", type=int, default=1)
    parser.add_argument("--starting-balance", default="100000")
    parser.add_argument("--commission", default="2.50")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    results = run_backtest(
        ticker=args.ticker,
        timeframe=args.timeframe,
        start=args.start,
        end=args.end,
        workspace=args.workspace,
        strategy_module=args.strategy_module,
        strategy_class=args.strategy_class,
        config_class=args.config_class,
        strategy_params=json.loads(args.strategy_params),
        instrument_specs=json.loads(args.instrument_specs),
        source_timeframe=args.source_timeframe,
        data_timezone=args.data_timezone,
        trade_size=args.trade_size,
        starting_balance=Decimal(args.starting_balance),
        commission=Decimal(args.commission),
    )
    print(json.dumps(results, indent=2))
