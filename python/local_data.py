from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair, Equity, FuturesContract
from nautilus_trader.model.objects import Price, Quantity

from project_paths import data_root, project_root

DEFAULT_DATA_TIMEZONE = "America/Chicago"
REQUIRED_COLUMNS = {"Date", "Open", "High", "Low", "Close", "Volume", "Symbol"}
_TIMEFRAME_PATTERN = re.compile(
    r"^(?P<count>\d+)?\s*(?P<unit>min|minute|m|h|hour|d|day|daily|w|week|weekly|mo|month|monthly)s?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Timeframe:
    canonical: str
    bar_spec: str
    pandas_rule: str
    approximate_seconds: int
    calendar_unit: str | None = None


@dataclass(frozen=True)
class LocalDataset:
    ticker: str
    timeframe: str
    path: Path


@dataclass(frozen=True)
class MarketDataSelection:
    ticker: str
    timeframe: Timeframe
    source: LocalDataset
    start: pd.Timestamp
    end: pd.Timestamp
    venue: str
    data_timezone: str

    @property
    def instrument_id(self) -> InstrumentId:
        return InstrumentId(Symbol(self.ticker), Venue(self.venue))

    @property
    def bar_type(self) -> BarType:
        return BarType.from_str(
            f"{self.instrument_id}-{self.timeframe.bar_spec}-LAST-EXTERNAL",
        )


def parse_timeframe(value: str) -> Timeframe:
    cleaned = value.strip()
    match = _TIMEFRAME_PATTERN.fullmatch(cleaned)
    if not match:
        raise ValueError(
            f"Unsupported timeframe {value!r}; use values such as 5min, 4h, Daily, Weekly, or Monthly",
        )

    count = int(match.group("count") or 1)
    if count <= 0:
        raise ValueError("Timeframe count must be positive")
    unit = match.group("unit").lower()

    if unit in {"min", "minute", "m"}:
        return Timeframe(
            canonical=f"{count}min",
            bar_spec=f"{count}-MINUTE",
            pandas_rule=f"{count}min",
            approximate_seconds=count * 60,
        )
    if unit in {"h", "hour"}:
        return Timeframe(
            canonical=f"{count}h",
            bar_spec=f"{count}-HOUR",
            pandas_rule=f"{count}h",
            approximate_seconds=count * 3_600,
        )
    if unit in {"d", "day", "daily"}:
        return Timeframe(
            canonical="Daily" if count == 1 else f"{count}d",
            bar_spec=f"{count}-DAY",
            pandas_rule=f"{count}D",
            approximate_seconds=count * 86_400,
            calendar_unit="day",
        )
    if unit in {"w", "week", "weekly"}:
        return Timeframe(
            canonical="Weekly" if count == 1 else f"{count}w",
            bar_spec=f"{count}-WEEK",
            pandas_rule=f"{count}W-MON",
            approximate_seconds=count * 7 * 86_400,
            calendar_unit="week",
        )
    return Timeframe(
        canonical="Monthly" if count == 1 else f"{count}mo",
        bar_spec=f"{count}-MONTH",
        pandas_rule=f"{count}MS",
        approximate_seconds=count * 31 * 86_400,
        calendar_unit="month",
    )


def discover_datasets() -> list[LocalDataset]:
    datasets: list[LocalDataset] = []
    root = data_root()
    if not root.is_dir():
        return datasets

    for path in sorted(root.glob("*.parquet")):
        parts = path.stem.rsplit("_", 1)
        if len(parts) != 2:
            continue
        ticker, timeframe = parts
        try:
            parse_timeframe(timeframe)
            parquet = pq.ParquetFile(path)
        except (ValueError, OSError):
            continue
        if not REQUIRED_COLUMNS.issubset(parquet.schema.names):
            continue
        datasets.append(LocalDataset(ticker=ticker, timeframe=timeframe, path=path.resolve()))
    return datasets


def datasets_for(ticker: str) -> list[LocalDataset]:
    matches = [item for item in discover_datasets() if item.ticker.casefold() == ticker.casefold()]
    if not matches:
        available = sorted({item.ticker for item in discover_datasets()})
        raise ValueError(f"No local data for {ticker!r}; discovered markets: {available}")
    return matches


def resolve_dataset(
    ticker: str,
    timeframe: str,
    source_timeframe: str | None = None,
) -> tuple[LocalDataset, Timeframe]:
    target = parse_timeframe(timeframe)
    available = datasets_for(ticker)

    if source_timeframe:
        source_key = parse_timeframe(source_timeframe).canonical
        for dataset in available:
            if parse_timeframe(dataset.timeframe).canonical == source_key:
                source = dataset
                break
        else:
            choices = [item.timeframe for item in available]
            raise ValueError(
                f"Source timeframe {source_timeframe!r} is unavailable for {ticker}; choose from {choices}",
            )
    else:
        exact = [
            item
            for item in available
            if parse_timeframe(item.timeframe).canonical == target.canonical
        ]
        if exact:
            source = exact[0]
        else:
            finer = [
                item
                for item in available
                if parse_timeframe(item.timeframe).approximate_seconds
                < target.approximate_seconds
            ]
            if target.calendar_unit in {"week", "month"}:
                daily = [
                    item
                    for item in finer
                    if parse_timeframe(item.timeframe).canonical == "Daily"
                ]
                if daily:
                    finer = daily
            if not finer:
                choices = [item.timeframe for item in available]
                raise ValueError(
                    f"Cannot build {timeframe!r} for {ticker} from local data; available: {choices}",
                )
            source = max(
                finer,
                key=lambda item: parse_timeframe(item.timeframe).approximate_seconds,
            )

    source_interval = parse_timeframe(source.timeframe)
    if source_interval.approximate_seconds > target.approximate_seconds:
        raise ValueError(
            f"Cannot create {target.canonical} bars from coarser {source_interval.canonical} data",
        )
    return source, target


def make_selection(
    ticker: str,
    timeframe: str,
    start: str,
    end: str,
    *,
    source_timeframe: str | None = None,
    venue: str = "GLBX",
    data_timezone: str = DEFAULT_DATA_TIMEZONE,
) -> MarketDataSelection:
    source, target = resolve_dataset(ticker, timeframe, source_timeframe)
    start_ts = _as_utc(start, data_timezone)
    end_ts = _as_utc(end, data_timezone)
    if start_ts >= end_ts:
        raise ValueError("Backtest start must be earlier than end")

    selection = MarketDataSelection(
        ticker=source.ticker,
        timeframe=target,
        source=source,
        start=start_ts,
        end=end_ts,
        venue=venue,
        data_timezone=data_timezone,
    )
    available = inspect_file(source.path)
    available_start = _as_utc(available["start"], data_timezone)
    available_end = _as_utc(available["end"], data_timezone)
    if start_ts < available_start or end_ts > available_end:
        raise ValueError(
            "Requested range is outside local data coverage "
            f"[{available_start.isoformat()}, {available_end.isoformat()}]",
        )
    return selection


def _as_utc(value: str, data_timezone: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(data_timezone).tz_convert("UTC")
    return timestamp.tz_convert("UTC")


def inspect_file(path: Path) -> dict:
    parquet = pq.ParquetFile(path)
    date_index = parquet.schema.names.index("Date")
    stats = parquet.metadata.row_group(0).column(date_index).statistics
    if stats is None or not stats.has_min_max:
        dates = pd.read_parquet(path, columns=["Date"])["Date"]
        start, end = dates.min(), dates.max()
    else:
        start, end = stats.min, stats.max
    return {
        "file": path.name,
        "rows": parquet.metadata.num_rows,
        "start": str(start),
        "end": str(end),
        "size_mb": round(path.stat().st_size / 1_048_576, 2),
    }


def inventory() -> dict:
    datasets = [
        {
            "ticker": dataset.ticker,
            "timeframe": dataset.timeframe,
            **inspect_file(dataset.path),
        }
        for dataset in discover_datasets()
    ]
    return {
        "data_root": str(data_root()),
        "tickers": sorted({item["ticker"] for item in datasets}),
        "datasets": datasets,
        "resampling": {
            "supported": True,
            "examples": ["Daily to Weekly", "Daily to Monthly", "1min to 15min"],
            "rule": "Only aggregate a finer local timeframe into a coarser requested timeframe.",
        },
    }


def _resample(
    frame: pd.DataFrame,
    timeframe: Timeframe,
    data_timezone: str,
) -> pd.DataFrame:
    local = frame.copy()
    local["date"] = local["date"].dt.tz_convert(data_timezone)
    indexed = local.set_index("date")
    resampled = indexed.resample(
        timeframe.pandas_rule,
        label="left",
        closed="left",
        origin="start_day",
    ).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "symbol": "last",
        },
    )
    resampled = resampled.dropna(subset=["open", "high", "low", "close"]).reset_index()
    resampled["date"] = resampled["date"].dt.tz_convert("UTC")
    return resampled


def load_bars(
    selection: MarketDataSelection,
    *,
    price_precision: int,
    max_rows: int = 1_000_000,
) -> tuple[list[Bar], dict]:
    local_start = selection.start.tz_convert(selection.data_timezone).tz_localize(None)
    local_end = selection.end.tz_convert(selection.data_timezone).tz_localize(None)
    frame = pd.read_parquet(
        selection.source.path,
        columns=["Date", "Open", "High", "Low", "Close", "Volume", "Symbol"],
        filters=[
            ("Date", ">=", local_start.to_pydatetime()),
            ("Date", "<=", local_end.to_pydatetime()),
        ],
    ).rename(columns=str.lower)
    frame["date"] = (
        pd.to_datetime(frame["date"])
        .dt.tz_localize(
            selection.data_timezone,
            ambiguous=False,
            nonexistent="shift_forward",
        )
        .dt.tz_convert("UTC")
    )
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    valid = (
        frame[["open", "high", "low", "close"]].notna().all(axis=1)
        & (frame["volume"] >= 0)
        & (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
    )
    rejected_rows = int((~valid).sum())
    frame = frame.loc[valid]
    source_interval = parse_timeframe(selection.source.timeframe)
    was_resampled = source_interval.canonical != selection.timeframe.canonical
    if was_resampled:
        frame = _resample(frame, selection.timeframe, selection.data_timezone)
        frame = frame[
            (frame["date"] >= selection.start) & (frame["date"] <= selection.end)
        ]
    if frame.empty:
        raise ValueError("No valid local bars exist for the requested range")
    if len(frame) > max_rows:
        raise ValueError(
            f"Selection contains {len(frame):,} bars; narrow the date range below "
            f"the {max_rows:,}-bar safety limit",
        )

    bars = [
        Bar(
            bar_type=selection.bar_type,
            open=Price.from_str(f"{row.open:.{price_precision}f}"),
            high=Price.from_str(f"{row.high:.{price_precision}f}"),
            low=Price.from_str(f"{row.low:.{price_precision}f}"),
            close=Price.from_str(f"{row.close:.{price_precision}f}"),
            volume=Quantity.from_int(int(row.volume)),
            ts_event=int(row.date.value),
            ts_init=int(row.date.value),
        )
        for row in frame.itertuples(index=False)
    ]
    metadata = {
        "source": str(selection.source.path.relative_to(project_root())),
        "ticker": selection.ticker,
        "source_timeframe": source_interval.canonical,
        "timeframe": selection.timeframe.canonical,
        "resampled": was_resampled,
        "start": frame.iloc[0]["date"].isoformat(),
        "end": frame.iloc[-1]["date"].isoformat(),
        "bars": len(bars),
        "rejected_rows": rejected_rows,
        "contracts": int(frame["symbol"].nunique()),
        "data_timezone": selection.data_timezone,
    }
    return bars, metadata


def make_instrument(
    ticker: str,
    *,
    spec: dict,
):
    venue = str(spec["venue"])
    currency = str(spec["currency"])
    price_increment = Decimal(str(spec["price_increment"]))
    if price_increment <= 0:
        raise ValueError("price_increment must be positive")
    price_precision = max(0, -price_increment.normalize().as_tuple().exponent)
    instrument_type = str(spec["instrument_type"]).casefold()
    instrument_id = InstrumentId(Symbol(ticker), Venue(venue))
    raw_symbol = Symbol(str(spec.get("raw_symbol", ticker)))

    if instrument_type in {"future", "futures"}:
        contract_multiplier = int(spec["contract_multiplier"])
        if contract_multiplier <= 0:
            raise ValueError("contract_multiplier must be positive")
        return FuturesContract(
            instrument_id=instrument_id,
            raw_symbol=raw_symbol,
            asset_class=AssetClass[str(spec.get("asset_class", "INDEX")).upper()],
            exchange=str(spec.get("exchange", venue)),
            currency=Currency.from_str(currency),
            price_precision=price_precision,
            price_increment=Price.from_str(str(price_increment)),
            multiplier=Quantity.from_int(contract_multiplier),
            lot_size=Quantity.from_int(int(spec.get("lot_size", 1))),
            underlying=str(spec.get("underlying", ticker)),
            activation_ns=0,
            expiration_ns=pd.Timestamp("2100-01-01", tz="UTC").value,
            ts_event=0,
            ts_init=0,
        )
    if instrument_type in {"currency_pair", "fx", "spot_fx"}:
        size_increment = Decimal(str(spec.get("size_increment", "1")))
        size_precision = max(0, -size_increment.normalize().as_tuple().exponent)
        return CurrencyPair(
            instrument_id=instrument_id,
            raw_symbol=raw_symbol,
            base_currency=Currency.from_str(str(spec["base_currency"])),
            quote_currency=Currency.from_str(currency),
            price_precision=price_precision,
            size_precision=size_precision,
            price_increment=Price.from_str(str(price_increment)),
            size_increment=Quantity.from_str(str(size_increment)),
            lot_size=Quantity.from_str(str(spec["lot_size"])) if spec.get("lot_size") else None,
            max_quantity=None,
            min_quantity=Quantity.from_str(str(spec.get("min_quantity", size_increment))),
            max_notional=None,
            min_notional=None,
            max_price=None,
            min_price=None,
            margin_init=Decimal(str(spec.get("margin_init", "0.03"))),
            margin_maint=Decimal(str(spec.get("margin_maint", "0.03"))),
            maker_fee=Decimal("0"),
            taker_fee=Decimal("0"),
            ts_event=0,
            ts_init=0,
        )
    if instrument_type == "equity":
        return Equity(
            instrument_id=instrument_id,
            raw_symbol=raw_symbol,
            currency=Currency.from_str(currency),
            price_precision=price_precision,
            price_increment=Price.from_str(str(price_increment)),
            lot_size=Quantity.from_int(int(spec.get("lot_size", 1))),
            isin=spec.get("isin"),
            ts_event=0,
            ts_init=0,
        )
    raise ValueError(
        f"Unsupported instrument_type {spec['instrument_type']!r}; "
        "supported values are future, currency_pair, and equity",
    )
