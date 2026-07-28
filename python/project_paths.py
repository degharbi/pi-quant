from __future__ import annotations

import os
from pathlib import Path

# Directory containing this package's Python modules (shipped with the pi package).
PACKAGE_PYTHON_ROOT = Path(__file__).resolve().parent


def project_root() -> Path:
    """User project root: data/ and strategies/ live here.

    Prefer PI_QUANT_PROJECT_ROOT (set by the Pi extension). Fall back to cwd so
    CLI runs from a research project root keep working.
    """
    env = os.environ.get("PI_QUANT_PROJECT_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def data_root() -> Path:
    return (project_root() / "data").resolve()


def strategies_root() -> Path:
    return (project_root() / "strategies").resolve()


def pi_quant_root() -> Path:
    return (project_root() / ".pi-quant").resolve()


def data_profile_path() -> Path:
    return pi_quant_root() / "data_profile.json"


def data_adapter_path() -> Path:
    return pi_quant_root() / "data_adapter.py"
