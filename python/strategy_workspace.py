from __future__ import annotations

import importlib.util
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from project_paths import project_root, strategies_root

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

STRATEGY_TEMPLATE = '''from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy


class {config_class}(StrategyConfig, frozen=True):
    """Configuration for this strategy workspace."""

    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal = Decimal("1")


class {strategy_class}(Strategy):
    """Replace with your strategy logic."""

    def __init__(self, config: {config_class}) -> None:
        super().__init__(config)
        self.instrument_id = config.instrument_id

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        pass

    def on_stop(self) -> None:
        self.close_all_positions(self.instrument_id)
'''


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_workspace_id(workspace_id: str) -> str:
    value = workspace_id.strip()
    if not UUID_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid workspace id {workspace_id!r}")
    return value


def workspace_dir(workspace_id: str) -> Path:
    workspace_id = validate_workspace_id(workspace_id)
    root = strategies_root()
    path = (root / workspace_id).resolve()
    if path.parent != root:
        raise ValueError("Workspace path escapes strategies root")
    if not path.is_dir():
        raise FileNotFoundError(f"Strategy workspace not found: {workspace_id}")
    return path


def strategy_file(workspace_id: str) -> Path:
    path = workspace_dir(workspace_id) / "strategy.py"
    if not path.is_file():
        raise FileNotFoundError(f"Missing strategy.py in workspace {workspace_id}")
    return path


def manifest_path(workspace_id: str) -> Path:
    return workspace_dir(workspace_id) / "manifest.json"


def results_dir(workspace_id: str) -> Path:
    return workspace_dir(workspace_id) / "results"


def artifacts_dir(workspace_id: str) -> Path:
    return workspace_dir(workspace_id) / "artifacts"


def latest_results_path(workspace_id: str) -> Path:
    return results_dir(workspace_id) / "latest.json"


def load_manifest(workspace_id: str) -> dict[str, Any]:
    path = manifest_path(workspace_id)
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(workspace_id: str, manifest: dict[str, Any]) -> None:
    manifest_path(workspace_id).write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def create_workspace(
    name: str,
    *,
    brief: dict[str, Any] | None = None,
    strategy_class: str = "WorkspaceStrategy",
    config_class: str = "WorkspaceStrategyConfig",
    write_template: bool = True,
) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("Workspace name is required")

    strategies = strategies_root()
    strategies.mkdir(parents=True, exist_ok=True)
    workspace_id = str(uuid.uuid4())
    root = (strategies / workspace_id).resolve()
    if root.parent != strategies:
        raise ValueError("Workspace path escapes strategies root")
    root.mkdir(parents=True)
    (root / "results").mkdir()
    (root / "artifacts").mkdir()

    project = project_root()
    manifest = {
        "id": workspace_id,
        "name": name.strip(),
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "brief": brief or {},
        "strategy_class": strategy_class,
        "config_class": config_class,
        "paths": {
            "root": str(root.relative_to(project)),
            "strategy": "strategy.py",
            "results": "results/",
            "artifacts": "artifacts/",
        },
        "last_run": None,
    }
    save_manifest(workspace_id, manifest)

    if write_template:
        (root / "strategy.py").write_text(
            STRATEGY_TEMPLATE.format(
                strategy_class=strategy_class,
                config_class=config_class,
            ),
            encoding="utf-8",
        )

    return {
        "id": workspace_id,
        "path": str(root.relative_to(project)),
        "manifest": manifest,
    }


def list_workspaces() -> list[dict[str, Any]]:
    strategies = strategies_root()
    if not strategies.is_dir():
        return []
    project = project_root()
    workspaces: list[dict[str, Any]] = []
    for path in sorted(strategies.iterdir()):
        if not path.is_dir():
            continue
        manifest_file = path / "manifest.json"
        if not manifest_file.is_file():
            continue
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        workspaces.append(
            {
                "id": manifest.get("id", path.name),
                "name": manifest.get("name", path.name),
                "created_at": manifest.get("created_at"),
                "last_run": manifest.get("last_run"),
                "path": str(path.relative_to(project)),
            },
        )
    return workspaces


def load_strategy_module(workspace_id: str):
    path = strategy_file(workspace_id)
    module_name = f"strategy_workspace_{workspace_id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load strategy module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_strategy(
    workspace_id: str,
    strategy_class: str,
    config_class: str,
    config_values: dict[str, Any],
):
    module = load_strategy_module(workspace_id)
    strategy_type = getattr(module, strategy_class)
    config_type = getattr(module, config_class)
    return strategy_type(config=config_type(**config_values))


def record_run(workspace_id: str, result: dict[str, Any]) -> Path:
    root = results_dir(workspace_id)
    root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_path = root / f"{run_id}.json"
    latest_path = root / "latest.json"
    payload = json.dumps(result, indent=2)
    run_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")

    manifest = load_manifest(workspace_id)
    manifest["updated_at"] = _utc_now()
    manifest["last_run"] = {
        "at": _utc_now(),
        "run_id": run_id,
        "results_file": str(run_path.relative_to(workspace_dir(workspace_id))),
        "latest_file": "results/latest.json",
        "status": result.get("status"),
        "total_realized_pnl": result.get("total_realized_pnl"),
        "total_trades": result.get("total_trades"),
    }
    save_manifest(workspace_id, manifest)
    return latest_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "create":
        name = sys.argv[2] if len(sys.argv) > 2 else "Untitled Strategy"
        brief = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        strategy_class = sys.argv[4] if len(sys.argv) > 4 else "WorkspaceStrategy"
        config_class = sys.argv[5] if len(sys.argv) > 5 else "WorkspaceStrategyConfig"
        print(
            json.dumps(
                create_workspace(
                    name,
                    brief=brief,
                    strategy_class=strategy_class,
                    config_class=config_class,
                ),
                indent=2,
            ),
        )
    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        print(json.dumps(list_workspaces(), indent=2))
    else:
        raise SystemExit("Usage: strategy_workspace.py create <name> [brief_json] | list")
