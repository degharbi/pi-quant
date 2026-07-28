import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execFile } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { platform } from "node:os";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PYTHON_DIR = join(PACKAGE_ROOT, "python");
const REQUIREMENTS = join(PYTHON_DIR, "requirements.txt");
const LARGE_BUFFER = 32 * 1024 * 1024;

type Metrics = Record<string, any>;
type DataInventory = {
  tickers: string[];
  datasets: Array<{ ticker: string; timeframe: string }>;
};
type RuntimeState = {
  python: string;
  createdVenv: boolean;
  installedDeps: boolean;
  parquetCount: number;
};

const runtimeByCwd = new Map<string, Promise<RuntimeState>>();

function isWindows(): boolean {
  return platform() === "win32";
}

function venvPython(cwd: string): string | null {
  const candidates = isWindows()
    ? [join(cwd, ".venv", "Scripts", "python.exe"), join(cwd, ".venv", "Scripts", "python")]
    : [join(cwd, ".venv", "bin", "python"), join(cwd, ".venv", "bin", "python3")];
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

function pythonEnv(cwd: string): NodeJS.ProcessEnv {
  const sep = isWindows() ? ";" : ":";
  const existing = process.env.PYTHONPATH;
  return {
    ...process.env,
    PYTHONPATH: existing ? `${PYTHON_DIR}${sep}${existing}` : PYTHON_DIR,
    PI_QUANT_PROJECT_ROOT: cwd,
    PIP_DISABLE_PIP_VERSION_CHECK: "1",
  };
}

async function execCapture(
  command: string,
  args: string[],
  options: {
    cwd?: string;
    env?: NodeJS.ProcessEnv;
    signal?: AbortSignal;
  } = {},
): Promise<{ stdout: string; stderr: string }> {
  return execFileAsync(command, args, {
    cwd: options.cwd,
    env: options.env,
    signal: options.signal,
    maxBuffer: LARGE_BUFFER,
    windowsHide: true,
  });
}

async function findBootstrapPython(): Promise<{ command: string; prefixArgs: string[] }> {
  const attempts = isWindows()
    ? [
        { command: "py", prefixArgs: ["-3"] },
        { command: "python", prefixArgs: [] },
        { command: "python3", prefixArgs: [] },
      ]
    : [
        { command: "python3", prefixArgs: [] },
        { command: "python", prefixArgs: [] },
      ];

  for (const attempt of attempts) {
    try {
      const { stdout } = await execCapture(attempt.command, [
        ...attempt.prefixArgs,
        "-c",
        "import sys; assert sys.version_info[:2] >= (3, 10); print(sys.executable)",
      ]);
      if (stdout.trim()) return attempt;
    } catch {
      // try next candidate
    }
  }

  throw new Error(
    "Python 3.10+ was not found on PATH. Install Python, then restart Pi — pi-quant will create the venv and install dependencies automatically.",
  );
}

async function depsReady(python: string, cwd: string, signal?: AbortSignal): Promise<boolean> {
  try {
    await execCapture(
      python,
      ["-c", "import nautilus_trader, pandas, pyarrow, numpy"],
      { cwd, env: pythonEnv(cwd), signal },
    );
    return true;
  } catch {
    return false;
  }
}

function countParquet(cwd: string): number {
  const dataDir = join(cwd, "data");
  if (!existsSync(dataDir)) return 0;
  try {
    return readdirSync(dataDir).filter((name) => name.toLowerCase().endsWith(".parquet")).length;
  } catch {
    return 0;
  }
}

function setBusy(ctx: any, message: string) {
  ctx.ui?.setStatus?.("nautilus", message);
  ctx.ui?.setWidget?.("nautilus-widget", [
    "┌───────────────────────────────────────────────────────────────┐",
    `│ ${message}`.padEnd(64, " ").slice(0, 64) + "│",
    "│ First run may take a few minutes (NautilusTrader install).    │",
    "└───────────────────────────────────────────────────────────────┘",
  ]);
}

async function ensureRuntime(
  cwd: string,
  ctx?: any,
  signal?: AbortSignal,
): Promise<RuntimeState> {
  const existing = runtimeByCwd.get(cwd);
  if (existing) return existing;

  const setup = (async (): Promise<RuntimeState> => {
    mkdirSync(join(cwd, "data"), { recursive: true });
    mkdirSync(join(cwd, "strategies"), { recursive: true });

    let createdVenv = false;
    let python = venvPython(cwd);
    if (!python) {
      setBusy(ctx, "Creating Python virtualenv (.venv)...");
      const boot = await findBootstrapPython();
      await execCapture(boot.command, [...boot.prefixArgs, "-m", "venv", ".venv"], {
        cwd,
        signal,
      });
      python = venvPython(cwd);
      if (!python) {
        throw new Error("Created .venv but could not find its Python executable.");
      }
      createdVenv = true;
    }

    let installedDeps = false;
    if (!(await depsReady(python, cwd, signal))) {
      setBusy(ctx, "Installing NautilusTrader + deps into .venv...");
      await execCapture(python, ["-m", "pip", "install", "--upgrade", "pip"], {
        cwd,
        env: pythonEnv(cwd),
        signal,
      });
      await execCapture(python, ["-m", "pip", "install", "-r", REQUIREMENTS], {
        cwd,
        env: pythonEnv(cwd),
        signal,
      });
      if (!(await depsReady(python, cwd, signal))) {
        throw new Error(
          `Failed to install Python dependencies from ${REQUIREMENTS}. Check network access and Python 3.10+ compatibility.`,
        );
      }
      installedDeps = true;
    }

    return {
      python,
      createdVenv,
      installedDeps,
      parquetCount: countParquet(cwd),
    };
  })();

  runtimeByCwd.set(cwd, setup);
  try {
    return await setup;
  } catch (error) {
    runtimeByCwd.delete(cwd);
    throw error;
  }
}

async function runPython(
  cwd: string,
  args: string[],
  signal?: AbortSignal,
  ctx?: any,
): Promise<string> {
  const runtime = await ensureRuntime(cwd, ctx, signal);
  const { stdout } = await execCapture(runtime.python, args, {
    cwd,
    env: pythonEnv(cwd),
    signal,
  });
  return stdout;
}

async function readInventory(cwd: string, signal?: AbortSignal, ctx?: any): Promise<DataInventory> {
  const stdout = await runPython(
    cwd,
    ["-c", "import json; from local_data import inventory; print(json.dumps(inventory()))"],
    signal,
    ctx,
  );
  return JSON.parse(stdout);
}

function workspaceResultsPath(cwd: string, workspaceId: string): string {
  return join(cwd, "strategies", workspaceId, "results", "latest.json");
}

function toolError(message: string) {
  return {
    content: [{ type: "text", text: message }],
    details: { error: message },
    isError: true as const,
  };
}

export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    try {
      setBusy(ctx, "Preparing pi-quant runtime...");
      const runtime = await ensureRuntime(ctx.cwd, ctx);
      updateWidget(ctx, null, runtime);
      if (runtime.parquetCount === 0) {
        ctx.ui.notify(
          "Add Parquet files under ./data (e.g. ES_Daily.parquet), then ask for a strategy.",
          "warning",
        );
      } else if (runtime.createdVenv || runtime.installedDeps) {
        ctx.ui.notify("pi-quant runtime ready", "info");
      }
    } catch (error: any) {
      ctx.ui.setStatus("nautilus", "Setup failed");
      ctx.ui.setWidget("nautilus-widget", [
        "┌───────────────────────────────────────────────────────────────┐",
        "│ pi-quant setup failed                                         │",
        `│ ${(error.message || String(error)).slice(0, 60)}`.padEnd(64, " ").slice(0, 64) + "│",
        "└───────────────────────────────────────────────────────────────┘",
      ]);
      ctx.ui.notify(error.message || String(error), "error");
    }
  });

  pi.registerTool({
    name: "inspect_local_market_data",
    label: "Inspect Local Market Data",
    description:
      "Discovers project-local Parquet datasets under ./data, including markets, source timeframes, coverage, and resampling support. Ensures the local Python runtime is ready first.",
    promptSnippet: "Inspect available local data before proposing or running a backtest.",
    promptGuidelines: [
      "Call this before coding a strategy when ticker, timeframe, or date coverage is unknown.",
      "Never download, generate, substitute, or load market data outside ./data.",
      "Do not ask the user to create a venv or pip install — the extension does that automatically.",
    ],
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal, _onUpdate, ctx) {
      try {
        const inventory = await readInventory(ctx.cwd, signal, ctx);
        return {
          content: [{ type: "text", text: JSON.stringify(inventory, null, 2) }],
          details: inventory,
        };
      } catch (error: any) {
        return toolError(`Runtime/data inspection failed: ${error.stderr || error.message}`);
      }
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
      "Do not create strategy files in the project root or python/examples/ for new user strategies.",
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
      try {
        JSON.parse(params.brief_json || "{}");
        const stdout = await runPython(
          ctx.cwd,
          [
            join(PYTHON_DIR, "strategy_workspace.py"),
            "create",
            params.name,
            params.brief_json || "{}",
            params.strategy_class || "WorkspaceStrategy",
            params.config_class || "WorkspaceStrategyConfig",
          ],
          signal,
          ctx,
        );
        const workspace = JSON.parse(stdout);
        ctx.ui.notify(`Created workspace ${workspace.id}`, "info");
        return {
          content: [{ type: "text", text: JSON.stringify(workspace, null, 2) }],
          details: workspace,
        };
      } catch (error: any) {
        return toolError(`Workspace creation failed: ${error.stderr || error.message}`);
      }
    },
  });

  pi.registerTool({
    name: "list_strategy_workspaces",
    label: "List Strategy Workspaces",
    description: "Lists UUID strategy workspaces under ./strategies with names and last-run metadata.",
    promptSnippet: "List existing strategy workspaces.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal, _onUpdate, ctx) {
      try {
        const stdout = await runPython(
          ctx.cwd,
          [join(PYTHON_DIR, "strategy_workspace.py"), "list"],
          signal,
          ctx,
        );
        const workspaces = JSON.parse(stdout);
        return {
          content: [{ type: "text", text: JSON.stringify(workspaces, null, 2) }],
          details: workspaces,
        };
      } catch (error: any) {
        return toolError(`Listing workspaces failed: ${error.stderr || error.message}`);
      }
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
      const fastLabel = `${params.ticker} ${params.timeframe}`;
      try {
        const runtime = await ensureRuntime(ctx.cwd, ctx, signal);
        const runner = join(PYTHON_DIR, "run_backtest.py");
        ctx.ui.setStatus("nautilus", `Running ${fastLabel} backtest...`);

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
        const { stdout, stderr } = await execCapture(runtime.python, runnerArgs, {
          cwd: ctx.cwd,
          env: pythonEnv(ctx.cwd),
          signal,
        });
        const resultsPath = workspaceResultsPath(ctx.cwd, params.workspace_id);
        const metrics = existsSync(resultsPath)
          ? JSON.parse(readFileSync(resultsPath, "utf-8"))
          : { stdout, stderr };
        ctx.ui.setStatus("nautilus", `${fastLabel} backtest complete`);
        updateWidget(ctx, metrics, runtime);
        return {
          content: [{ type: "text", text: JSON.stringify(metrics, null, 2) }],
          details: metrics,
        };
      } catch (error: any) {
        ctx.ui.setStatus("nautilus", "Backtest error");
        return toolError(`Backtest failed: ${error.stderr || error.message}`);
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

      try {
        await ensureRuntime(ctx.cwd, ctx);
      } catch (error: any) {
        ctx.ui.notify(error.message || String(error), "error");
        return;
      }

      const inventory = await readInventory(ctx.cwd, undefined, ctx);
      if (!inventory.tickers.length) {
        ctx.ui.notify(
          "No compatible Parquet datasets in ./data. Add files like ES_Daily.parquet, then retry /strategy.",
          "error",
        );
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

function updateWidget(ctx: any, metrics: Metrics | null, runtime?: RuntimeState) {
  if (!metrics) {
    const files = runtime?.parquetCount ?? 0;
    const dataLine =
      files > 0
        ? `│ ${files} Parquet file(s) in ./data — ready for /strategy`.padEnd(64, " ").slice(0, 64) +
          "│"
        : "│ Drop Parquet files into ./data, then ask for a strategy      │";
    ctx.ui.setStatus("nautilus", files > 0 ? "Nautilus: ready" : "Nautilus: waiting for data");
    ctx.ui.setWidget("nautilus-widget", [
      "┌───────────────────────────────────────────────────────────────┐",
      "│ Pi Quant: Research assistant                                  │",
      dataLine,
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
