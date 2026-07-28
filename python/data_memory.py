from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from project_paths import data_adapter_path, data_profile_path, data_root, project_root

PROFILE_VERSION = 1
REQUIRED_ADAPTER_FUNCTIONS = ("list_datasets", "inspect", "load_ohlcv")
CANONICAL_COLUMNS = ("Date", "Open", "High", "Low", "Close", "Volume", "Symbol")
PEEK_BYTES = 4_096


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_fingerprint(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}


def list_data_files() -> list[Path]:
    root = data_root()
    if not root.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        files.append(path.resolve())
    return files


def _relative_data_path(path: Path) -> str:
    root = data_root()
    resolved = path.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.relative_to(project_root()).as_posix()


def _resolve_data_path(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    root = data_root()
    direct = (root / candidate).resolve()
    if direct.exists():
        return direct
    return (project_root() / candidate).resolve()


def _load_profile() -> dict[str, Any] | None:
    path = data_profile_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_adapter_module():
    path = data_adapter_path()
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("pi_quant_project_data_adapter", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in REQUIRED_ADAPTER_FUNCTIONS:
        if not callable(getattr(module, name, None)):
            return None
    return module


def _profile_tracked_files(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tracked: dict[str, dict[str, Any]] = {}
    for entry in profile.get("files", []):
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("path", "")).strip()
        if rel:
            tracked[rel] = entry
    return tracked


def _current_fingerprints() -> dict[str, dict[str, int]]:
    return {_relative_data_path(path): file_fingerprint(path) for path in list_data_files()}


def adapter_status() -> dict[str, Any]:
    profile = _load_profile()
    adapter_exists = data_adapter_path().is_file()
    current = _current_fingerprints()

    if not current:
        return {
            "status": "missing",
            "adapter_exists": adapter_exists,
            "profile_exists": profile is not None,
            "needs_adapter": False,
            "changed_paths": [],
            "data_file_count": 0,
        }

    if not profile or not adapter_exists:
        return {
            "status": "missing",
            "adapter_exists": adapter_exists,
            "profile_exists": profile is not None,
            "needs_adapter": True,
            "changed_paths": sorted(current),
            "data_file_count": len(current),
        }

    tracked = _profile_tracked_files(profile)
    changed: list[str] = []
    for rel, fingerprint in current.items():
        entry = tracked.get(rel)
        if entry is None:
            changed.append(rel)
            continue
        stored = entry.get("fingerprint") or {}
        if (
            int(stored.get("mtime_ns", -1)) != fingerprint["mtime_ns"]
            or int(stored.get("size", -1)) != fingerprint["size"]
        ):
            changed.append(rel)

    for rel in tracked:
        if rel not in current:
            changed.append(rel)

    if changed:
        return {
            "status": "stale",
            "adapter_exists": True,
            "profile_exists": True,
            "needs_adapter": True,
            "changed_paths": sorted(set(changed)),
            "data_file_count": len(current),
            "updated_at": profile.get("updated_at"),
        }

    adapter = _load_adapter_module()
    if adapter is None:
        return {
            "status": "missing",
            "adapter_exists": True,
            "profile_exists": True,
            "needs_adapter": True,
            "changed_paths": [".pi-quant/data_adapter.py"],
            "data_file_count": len(current),
        }

    return {
        "status": "ready",
        "adapter_exists": True,
        "profile_exists": True,
        "needs_adapter": False,
        "changed_paths": [],
        "data_file_count": len(current),
        "updated_at": profile.get("updated_at"),
    }


def require_adapter_ready() -> None:
    state = adapter_status()
    if state["status"] == "ready":
        return
    if state["data_file_count"] == 0:
        raise ValueError(
            "No market data files found under ./data. Add OHLCV files, then call inspect_local_market_data.",
        )
    if state["status"] == "stale":
        changed = ", ".join(state["changed_paths"])
        raise ValueError(
            "Project data adapter is stale. Explore ./data, update .pi-quant/data_adapter.py and "
            f".pi-quant/data_profile.json (changed: {changed}), then re-inspect before backtesting.",
        )
    raise ValueError(
        "Project data adapter is missing. Explore ./data, write .pi-quant/data_adapter.py and "
        ".pi-quant/data_profile.json with list_datasets(), inspect(), and load_ohlcv(), then re-inspect.",
    )


def get_adapter():
    require_adapter_ready()
    module = _load_adapter_module()
    if module is None:
        raise ValueError(
            "Project data adapter is invalid. Ensure .pi-quant/data_adapter.py defines "
            "list_datasets(), inspect(), and load_ohlcv().",
        )
    return module


def _peek_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    info: dict[str, Any] = {"extension": suffix or "(none)"}
    try:
        if suffix == ".parquet":
            import pyarrow.parquet as pq

            parquet = pq.ParquetFile(path)
            info["columns"] = parquet.schema.names
            info["rows"] = parquet.metadata.num_rows
        elif suffix in {".csv", ".txt", ".tsv"}:
            text = path.read_text(encoding="utf-8", errors="replace")[:PEEK_BYTES]
            lines = [line for line in text.splitlines() if line.strip()]
            info["preview_lines"] = lines[:5]
            if lines:
                delimiter = "\t" if suffix == ".tsv" else ","
                info["preview_columns"] = [part.strip() for part in lines[0].split(delimiter)]
        elif suffix in {".json", ".jsonl"}:
            text = path.read_text(encoding="utf-8", errors="replace")[:PEEK_BYTES]
            info["preview_lines"] = [line for line in text.splitlines() if line.strip()][:5]
        else:
            info["note"] = "No built-in preview for this extension; inspect file contents manually."
    except OSError as exc:
        info["peek_error"] = str(exc)
    return info


def probe_raw_inventory() -> dict[str, Any]:
    files = list_data_files()
    raw_files = []
    for path in files:
        rel = _relative_data_path(path)
        fingerprint = file_fingerprint(path)
        raw_files.append(
            {
                "path": rel,
                "file": path.name,
                "size_mb": round(path.stat().st_size / 1_048_576, 2),
                "fingerprint": fingerprint,
                **_peek_file(path),
            },
        )

    profile = _load_profile()
    return {
        "data_root": str(data_root()),
        "adapter_status": adapter_status()["status"],
        "needs_adapter": adapter_status()["needs_adapter"],
        "adapter_paths": {
            "profile": str(data_profile_path()),
            "adapter": str(data_adapter_path()),
        },
        "profile": profile,
        "raw_files": raw_files,
        "tickers": [],
        "datasets": [],
        "resampling": {
            "supported": True,
            "examples": ["Daily to Weekly", "Daily to Monthly", "1min to 15min"],
            "rule": "Only aggregate a finer local timeframe into a coarser requested timeframe.",
        },
        "adapter_contract": {
            "profile_version": PROFILE_VERSION,
            "required_functions": list(REQUIRED_ADAPTER_FUNCTIONS),
            "canonical_columns": list(CANONICAL_COLUMNS),
            "profile_fields": [
                "version",
                "updated_at",
                "files[].path",
                "files[].fingerprint",
                "files[].ticker",
                "files[].timeframe",
            ],
        },
    }


def adapter_inventory() -> dict[str, Any]:
    adapter = get_adapter()
    datasets = adapter.list_datasets()
    normalized = []
    tickers: set[str] = set()
    for item in datasets:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).strip()
        timeframe = str(item.get("timeframe", "")).strip()
        rel_path = str(item.get("path", "")).strip()
        if not ticker or not timeframe or not rel_path:
            continue
        path = _resolve_data_path(rel_path)
        details = adapter.inspect(path)
        tickers.add(ticker)
        normalized.append(
            {
                "ticker": ticker,
                "timeframe": timeframe,
                "path": rel_path,
                **details,
            },
        )

    status = adapter_status()
    return {
        "data_root": str(data_root()),
        "adapter_status": status["status"],
        "needs_adapter": False,
        "adapter_paths": {
            "profile": str(data_profile_path()),
            "adapter": str(data_adapter_path()),
        },
        "profile_updated_at": status.get("updated_at"),
        "tickers": sorted(tickers),
        "datasets": normalized,
        "resampling": {
            "supported": True,
            "examples": ["Daily to Weekly", "Daily to Monthly", "1min to 15min"],
            "rule": "Only aggregate a finer local timeframe into a coarser requested timeframe.",
        },
    }


def inventory() -> dict[str, Any]:
    status = adapter_status()
    if status["status"] == "ready":
        return adapter_inventory()
    payload = probe_raw_inventory()
    payload["adapter_status"] = status["status"]
    payload["needs_adapter"] = status["needs_adapter"]
    if status["changed_paths"]:
        payload["changed_paths"] = status["changed_paths"]
    return payload


def adapter_load_ohlcv(
    path: Path,
    *,
    columns: list[str],
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    adapter = get_adapter()
    frame = adapter.load_ohlcv(str(path), columns, start=start, end=end)
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("load_ohlcv() must return a pandas DataFrame")
    missing = set(CANONICAL_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(
            f"Adapter load_ohlcv() must return canonical columns; missing: {sorted(missing)}",
        )
    return frame


def adapter_inspect(path: Path) -> dict[str, Any]:
    adapter = get_adapter()
    details = adapter.inspect(path)
    if not isinstance(details, dict):
        raise ValueError("inspect() must return a dict")
    return details


def write_profile_template(files: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = {
        "version": PROFILE_VERSION,
        "updated_at": _utc_now(),
        "files": files or [],
    }
    root = data_profile_path().parent
    root.mkdir(parents=True, exist_ok=True)
    data_profile_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
