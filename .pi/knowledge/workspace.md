# Strategy Workspace Contract

Every new user strategy must live in an isolated UUID folder under `./strategies/`.

## When to create a workspace

Call `create_strategy_workspace` once at the beginning of every new strategy effort, before writing code.

Do not place new strategies in the repo root or under `examples/`. The `examples/` folder is reference-only.

## Folder layout

```text
strategies/{uuid}/
├── manifest.json      # id, name, brief, class names, last_run
├── strategy.py        # StrategyConfig + Strategy implementation
├── results/
│   ├── latest.json    # most recent backtest output
│   └── {timestamp}.json
└── artifacts/         # charts, notes, exports, diagnostics
```

## Agent rules

1. Create the workspace with the confirmed brief stored in `manifest.json`.
2. Edit only `strategies/{uuid}/strategy.py` for strategy logic.
3. Put non-code outputs in `strategies/{uuid}/artifacts/`.
4. Run backtests with `run_nautilus_backtest` and the workspace id.
5. Never write results to the repo root.
6. Update `manifest.json` class names if you rename the strategy or config classes.

## Class names

Default scaffold classes:

- `WorkspaceStrategyConfig`
- `WorkspaceStrategy`

Rename them in both `strategy.py` and the workspace creation call when the strategy has a meaningful name, for example `GoldenCrossConfig` / `GoldenCrossStrategy`.

## Results

Each backtest run writes:

- `results/latest.json`
- `results/{UTC_TIMESTAMP}.json`

The workspace `manifest.json` `last_run` field is updated automatically.

## Listing workspaces

Use `list_strategy_workspaces` to inspect existing UUID folders before creating duplicates for the same user request.
