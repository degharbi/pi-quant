import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execFile } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

type Metrics = Record<string, any>;
type DataInventory = {
  tickers: string[];
  datasets: Array<{ ticker: string; timeframe: string }>;
};

async function runPython(
  cwd: string,
  args: string[],
  signal?: AbortSignal,
): Promise<string> {
  const python = resolve(cwd, ".venv/bin/python");
  const { stdout } = await execFileAsync(python, args, { cwd, signal });
  return stdout;
}

async function readInventory(cwd: string, signal?: AbortSignal): Promise<DataInventory> {
  const stdout = await runPython(
    cwd,
    ["-c", "import json; from local_data import inventory; print(json.dumps(inventory()))"],
    signal,
  );
  return JSON.parse(stdout);
}

function workspaceResultsPath(cwd: string, workspaceId: string): string {
  return join(cwd, "strategies", workspaceId, "results", "latest.json");
}

export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    updateWidget(ctx, null);
  });

  pi.registerTool({
    name: "inspect_local_market_data",
    label: "Inspect Local Market Data",
    description:
      "Discovers project-local Parquet datasets under ./data, including markets, source timeframes, coverage, and resampling support.",
    promptSnippet: "Inspect available local data before proposing or running a backtest.",
    promptGuidelines: [
      "Call this before coding a strategy when ticker, timeframe, or date coverage is unknown.",
      "Never download, generate, substitute, or load market data outside ./data.",
    ],
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal, _onUpdate, ctx) {
      const inventory = await readInventory(ctx.cwd, signal);
      return {
        content: [{ type: "text", text: JSON.stringify(inventory, null, 2) }],
        details: inventory,
      };
    },
  });

  pi.registerTool({
    name: "create_strategy_workspace",
    label: "Create Strategy Workspace",
    description:
      "Creates a new UUID folder under ./strategies with strategy.py, manifest.json, results/, and artifacts/. Use this before writing any new strategy.",
    promptSnippet: "Create an isolated UUID workspace for a new strategy and its artifacts.",
    promptGuidelines: [
      "Call once at the start of every new strategy before creating or editing strategy code.",
      "Write and edit strategy code only inside the returned workspace path.",
      "Store notes, charts, exports, and auxiliary files in that workspace's artifacts/ directory.",
      "Do not create strategy files in the repo root or examples/ for new user strategies.",
    ],
    parameters: Type.Object({
      name: Type.String({ description: "Human-readable strategy name" }),
      brief_json: Type.String({
        description: "JSON object capturing the confirmed strategy brief",
        default: "{}",
      }),
      strategy_class: Type.String({
        description: "Strategy class name to scaffold in strategy.py",
        default: "WorkspaceStrategy",
      }),
      config_class: Type.String({
        description: "StrategyConfig class name to scaffold in strategy.py",
        default: "WorkspaceStrategyConfig",
      }),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      JSON.parse(params.brief_json || "{}");
      const stdout = await runPython(
        ctx.cwd,
        [
          "strategy_workspace.py",
          "create",
          params.name,
          params.brief_json || "{}",
          params.strategy_class || "WorkspaceStrategy",
          params.config_class || "WorkspaceStrategyConfig",
        ],
        signal,
      );
      const workspace = JSON.parse(stdout);
      ctx.ui.notify(`Created workspace ${workspace.id}`, "info");
      return {
        content: [{ type: "text", text: JSON.stringify(workspace, null, 2) }],
        details: workspace,
      };
    },
  });

  pi.registerTool({
    name: "list_strategy_workspaces",
    label: "List Strategy Workspaces",
    description: "Lists UUID strategy workspaces under ./strategies with names and last-run metadata.",
    promptSnippet: "List existing strategy workspaces.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal, _onUpdate, ctx) {
      const stdout = await runPython(ctx.cwd, ["strategy_workspace.py", "list"], signal);
      const workspaces = JSON.parse(stdout);
      return {
        content: [{ type: "text", text: JSON.stringify(workspaces, null, 2) }],
        details: workspaces,
      };
    },
  });

  pi.registerTool({
    name: "run_nautilus_backtest",
    label: "Run Nautilus Backtest",
    description:
      "Runs a workspace strategy from ./strategies/{uuid}/strategy.py and writes results into that workspace.",
    promptSnippet:
      "Run a workspace strategy using a validated local ticker, timeframe, date range, costs, and sizing.",
    promptGuidelines: [
      "Require a workspace created by create_strategy_workspace.",
      "Do not call until ticker, timeframe, start/end dates, entry/exit rules, position sizing, and commission assumptions are explicit.",
      "Use inspect_local_market_data first and never pass external data paths.",
      "If the requested timeframe has no exact file, choose a finer local source timeframe and resample it; never upsample coarse data.",
      "Supply verified instrument metadata instead of guessing tick size or contract multiplier.",
    ],
    parameters: Type.Object({
      workspace_id: Type.String({
        description: "UUID workspace id returned by create_strategy_workspace",
      }),
      ticker: Type.String({
        description: "Ticker discovered by inspect_local_market_data; comma-separated is supported",
      }),
      timeframe: Type.String({
        description: "Strategy bar timeframe; may be resampled from finer local data",
      }),
      source_timeframe: Type.Optional(
        Type.String({
          description: "Optional finer local source timeframe selected for resampling",
        }),
      ),
      instrument_specs_json: Type.String({
        description:
          "JSON keyed by ticker with instrument_type, venue, currency, price_increment, account_type, and type-specific fields",
      }),
      data_timezone: Type.String({
        description: "Timezone of naive timestamps in the source Parquet file",
        default: "America/Chicago",
      }),
      start: Type.String({ description: "Inclusive ISO-8601 backtest start" }),
      end: Type.String({ description: "Inclusive ISO-8601 backtest end" }),
      strategy_class: Type.Optional(
        Type.String({ description: "Override strategy class; defaults to manifest.json" }),
      ),
      config_class: Type.Optional(
        Type.String({ description: "Override config class; defaults to manifest.json" }),
      ),
      strategy_params_json: Type.String({
        description: "JSON object containing strategy-specific config fields",
        default: "{}",
      }),
      trade_size: Type.Integer({
        description: "Position size in valid instrument units",
        default: 1,
      }),
      starting_balance: Type.Number({
        description: "Starting account balance in the instrument spec currency",
        default: 100000,
      }),
      commission: Type.Number({
        description: "Commission in the instrument spec currency charged per order",
        default: 2.5,
      }),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const python = resolve(ctx.cwd, ".venv/bin/python");
      const runner = resolve(ctx.cwd, "run_backtest.py");
      const fastLabel = `${params.ticker} ${params.timeframe}`;
      ctx.ui.setStatus("nautilus", `Running ${fastLabel} backtest...`);

      try {
        JSON.parse(params.strategy_params_json || "{}");
        JSON.parse(params.instrument_specs_json);
        const runnerArgs = [
          runner,
          "--workspace",
          params.workspace_id,
          "--ticker",
          params.ticker,
          "--timeframe",
          params.timeframe,
          "--start",
          params.start,
          "--end",
          params.end,
          "--instrument-specs",
          params.instrument_specs_json,
          "--data-timezone",
          params.data_timezone || "America/Chicago",
          "--strategy-params",
          params.strategy_params_json || "{}",
          "--trade-size",
          String(params.trade_size || 1),
          "--starting-balance",
          String(params.starting_balance || 100000),
          "--commission",
          String(params.commission ?? 2.5),
        ];
        if (params.source_timeframe) {
          runnerArgs.push("--source-timeframe", params.source_timeframe);
        }
        if (params.strategy_class) {
          runnerArgs.push("--strategy-class", params.strategy_class);
        }
        if (params.config_class) {
          runnerArgs.push("--config-class", params.config_class);
        }
        const { stdout, stderr } = await execFileAsync(python, runnerArgs, {
          cwd: ctx.cwd,
          signal,
          maxBuffer: 10 * 1024 * 1024,
        });
        const resultsPath = workspaceResultsPath(ctx.cwd, params.workspace_id);
        const metrics = existsSync(resultsPath)
          ? JSON.parse(readFileSync(resultsPath, "utf-8"))
          : { stdout, stderr };
        ctx.ui.setStatus("nautilus", `${fastLabel} backtest complete`);
        updateWidget(ctx, metrics);
        return {
          content: [{ type: "text", text: JSON.stringify(metrics, null, 2) }],
          details: metrics,
        };
      } catch (error: any) {
        ctx.ui.setStatus("nautilus", "Backtest error");
        return {
          content: [
            {
              type: "text",
              text: `Backtest failed: ${error.stderr || error.message}`,
            },
          ],
          details: { error: error.message, stderr: error.stderr },
          isError: true,
        };
      }
    },
  });

  pi.registerCommand("strategy", {
    description: "Collect a complete Nautilus strategy and backtest brief",
    handler: async (_args, ctx) => {
      if (!ctx.hasUI) {
        await ctx.sendUserMessage(
          "Ask me for ticker, timeframe, date range, entry and exit rules, sizing, session, and trading costs. Then create a UUID strategy workspace before coding.",
        );
        return;
      }

      const inventory = await readInventory(ctx.cwd);
      if (!inventory.tickers.length) {
        ctx.ui.notify("No compatible local Parquet datasets found in ./data", "error");
        return;
      }
      const ticker = await ctx.ui.select("Local market", inventory.tickers);
      if (!ticker) return;
      const sourceTimeframes = inventory.datasets
        .filter((dataset) => dataset.ticker === ticker)
        .map((dataset) => dataset.timeframe);
      const timeframeChoice = await ctx.ui.select("Strategy bar timeframe", [
        ...sourceTimeframes,
        "Custom / resampled timeframe…",
      ]);
      if (!timeframeChoice) return;
      const timeframe =
        timeframeChoice === "Custom / resampled timeframe…"
          ? await ctx.ui.input("Strategy bar timeframe", "e.g. 4h, Weekly, Monthly")
          : timeframeChoice;
      if (!timeframe) return;
      const start = await ctx.ui.input("Backtest start", "YYYY-MM-DD");
      if (!start) return;
      const end = await ctx.ui.input("Backtest end", "YYYY-MM-DD");
      if (!end) return;
      const thesis = await ctx.ui.input(
        "Strategy thesis",
        "e.g. trend following, breakout, mean reversion",
      );
      if (!thesis) return;
      const entries = await ctx.ui.input(
        "Entry rules",
        "Exact indicators, thresholds, and long/short conditions",
      );
      if (!entries) return;
      const exits = await ctx.ui.input(
        "Exit rules",
        "Stops, targets, trailing logic, time exits, opposite signals",
      );
      if (!exits) return;
      const sizing = await ctx.ui.input(
        "Risk and sizing",
        "Contracts or risk per trade; max positions/daily loss",
      );
      if (!sizing) return;
      const session = await ctx.ui.input(
        "Trading session",
        "Timezone and allowed days/hours; include overnight policy",
      );
      if (!session) return;
      const costs = await ctx.ui.input(
        "Execution assumptions",
        "Commission per order and slippage assumptions",
      );
      if (!costs) return;
      const instrument = await ctx.ui.input(
        "Instrument metadata",
        "Type, venue, currency, tick size, multiplier/base currency, account type",
      );
      if (!instrument) return;

      await ctx.sendUserMessage(
        [
          "Create a Nautilus strategy and backtest from this confirmed brief:",
          `- Local market: ${ticker}`,
          `- Requested strategy timeframe: ${timeframe}`,
          `- Available source timeframes: ${sourceTimeframes.join(", ")}`,
          `- Range: ${start} through ${end}`,
          `- Thesis: ${thesis}`,
          `- Entries: ${entries}`,
          `- Exits: ${exits}`,
          `- Risk/sizing: ${sizing}`,
          `- Session: ${session}`,
          `- Costs: ${costs}`,
          `- Instrument metadata: ${instrument}`,
          "Workflow:",
          "1. Call create_strategy_workspace with this brief.",
          "2. Implement strategy.py only inside the returned strategies/{uuid}/ folder.",
          "3. Save any charts, notes, or exports to that workspace's artifacts/ directory.",
          "4. Run run_nautilus_backtest with the workspace id.",
          "Inspect local data first. Use an exact timeframe when present; otherwise resample a finer local source. State unresolved ambiguity instead of inventing parameters.",
        ].join("\n"),
      );
    },
  });

  pi.registerCommand("backtest-data", {
    description: "Show dynamically discovered local datasets",
    handler: async (_args, ctx) => {
      await ctx.sendUserMessage(
        "Use inspect_local_market_data and summarize the available local tickers, timeframes, and date coverage.",
      );
    },
  });
}

function updateWidget(ctx: any, metrics: Metrics | null) {
  if (!metrics) {
    ctx.ui.setStatus("nautilus", "Nautilus: local data ready");
    ctx.ui.setWidget("nautilus-widget", [
      "┌───────────────────────────────────────────────────────────────┐",
      "│ Pi Quant: Research assistant                                  │",
      "│ /strategy: define brief   /backtest-data: inspect data        │",
      "└───────────────────────────────────────────────────────────────┘",
    ]);
    return;
  }

  const data = metrics.data || {};
  const request = metrics.request || {};
  const pnl = Number(metrics.total_realized_pnl || 0);
  const pnlText = `${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}`;
  const workspace = String(request.workspace || "?").slice(0, 8);
  ctx.ui.setWidget("nautilus-widget", [
    "┌───────────────────────────────────────────────────────────────┐",
    `│ ws ${workspace}  ${String(data.ticker || "?")} ${String(data.timeframe || "?")}`.padEnd(
      64,
      " ",
    ) + "│",
    `│ PnL ${pnlText}  Trades ${metrics.total_trades ?? 0}  Win ${metrics.win_rate_pct ?? 0}%  PF ${metrics.profit_factor ?? "n/a"}`.padEnd(
      64,
      " ",
    ) + "│",
    "└───────────────────────────────────────────────────────────────┘",
  ]);
}
