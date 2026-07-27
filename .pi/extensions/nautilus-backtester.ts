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

async function readInventory(cwd: string, signal?: AbortSignal): Promise<DataInventory> {
  const python = resolve(cwd, ".venv/bin/python");
  const { stdout } = await execFileAsync(
    python,
    [
      "-c",
      "import json; from local_data import inventory; print(json.dumps(inventory()))",
    ],
    { cwd, signal },
  );
  return JSON.parse(stdout);
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
    name: "run_nautilus_backtest",
    label: "Run Nautilus Backtest",
    description:
      "Runs a generated Nautilus strategy against a discovered local dataset, optionally resampling finer bars into the strategy timeframe.",
    promptSnippet:
      "Run a Nautilus strategy using a validated local ticker, timeframe, date range, costs, and sizing.",
    promptGuidelines: [
      "Do not call until ticker, timeframe, start/end dates, entry/exit rules, position sizing, and commission assumptions are explicit.",
      "Use inspect_local_market_data first and never pass external data paths.",
      "If the requested timeframe has no exact file, choose a finer local source timeframe and resample it; never upsample coarse data.",
      "Supply verified instrument metadata instead of guessing tick size or contract multiplier.",
      "Strategy modules must expose a StrategyConfig and Strategy compatible with the shared runner.",
    ],
    parameters: Type.Object({
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
          'JSON keyed by ticker with instrument_type, venue, currency, price_increment, account_type, and type-specific fields such as contract_multiplier or base_currency',
      }),
      data_timezone: Type.String({
        description: "Timezone of naive timestamps in the source Parquet file",
        default: "America/Chicago",
      }),
      start: Type.String({ description: "Inclusive ISO-8601 backtest start" }),
      end: Type.String({ description: "Inclusive ISO-8601 backtest end" }),
      strategy_module: Type.String({
        description: "Python dotted module path",
        default: "strategy",
      }),
      strategy_class: Type.String({
        description: "Strategy class exported by the module",
        default: "EMACrossStrategy",
      }),
      config_class: Type.String({
        description: "StrategyConfig class exported by the module",
        default: "EMACrossConfig",
      }),
      strategy_params_json: Type.String({
        description: "JSON object containing strategy-specific config fields",
        default: "{}",
      }),
      trade_size: Type.Integer({
        description: "Whole futures contracts per entry",
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
          "--strategy-module",
          params.strategy_module || "strategy",
          "--strategy-class",
          params.strategy_class || "EMACrossStrategy",
          "--config-class",
          params.config_class || "EMACrossConfig",
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
        const { stdout, stderr } = await execFileAsync(
          python,
          runnerArgs,
          {
            cwd: ctx.cwd,
            signal,
            maxBuffer: 10 * 1024 * 1024,
          },
        );
        const resultsPath = join(ctx.cwd, "backtest_results.json");
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
          "Ask me for ticker, timeframe, date range, entry and exit rules, sizing, session, and trading costs before coding.",
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
          "Inspect local data first. Use an exact timeframe when present; otherwise resample a finer local source (for example Daily to Weekly). State unresolved ambiguity instead of inventing parameters. Then code the strategy against the shared runner and run it.",
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
      "│ Nautilus Agent: discovered local-data workflow               │",
      "│ /strategy: define a strategy   /backtest-data: inspect data  │",
      "└───────────────────────────────────────────────────────────────┘",
    ]);
    return;
  }

  const data = metrics.data || {};
  const pnl = Number(metrics.total_realized_pnl || 0);
  const pnlText = `${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}`;
  ctx.ui.setWidget("nautilus-widget", [
    "┌───────────────────────────────────────────────────────────────┐",
    `│ ${String(data.ticker || "?")} ${String(data.timeframe || "?")}  ${String(data.start || "").slice(0, 10)} → ${String(data.end || "").slice(0, 10)}`.padEnd(
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
