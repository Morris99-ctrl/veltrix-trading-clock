# Veltrix Trading Clock — v10.0 Core Edition

Veltrix v10.0 is a deliberately smaller Windows desktop trading clock. It focuses on market-session awareness, alarms, economic-event reminders, volatility monitoring, a compact causal Regime Lab and personal focus tracking.

The former Research Lab, Strategy Lab, Tick Research and Data Center workspaces have been removed from the application. Their fetch, import, bar-construction, provider and backtesting workflows are no longer started or exposed by the Core Edition.

## Included workspaces

- **Global Sessions** — independent Sydney, Tokyo, London and New York clocks, open/closed status, next-transition countdowns and overlap summary.
- **Alerts & Events** — configurable session opening/closing alerts, overlap warnings and personal economic-event reminders.
- **Economic Calendar** — third-party public calendar feed, impact filters, cached results and high-impact reminders.
- **Volatility Lab** — indicative Yahoo Finance market monitoring, ATR, one-day historical expected move and session volatility observations.
- **Regime Lab** — import completed OHLC history from a CSV, classify bars as range, trend-up, trend-down, volatility shock or transition, inspect historical conditional outcomes and export classifications.
- **Focus & Goals** — restart-safe stopwatch/countdown timers, daily focus history, goals and milestones.
- **Alarm Clock** — the original seven-segment clock, alarm, snooze and theme system.

## Regime Lab data

Regime Lab now has its own **IMPORT OHLC CSV** workflow. It accepts timestamp plus Open, High, Low and Close columns, including common MT5-style separate Date/Time fields. Timestamps are normalised to UTC. Naive timestamps are interpreted using the configured home timezone (Africa/Nairobi by default).

Imported datasets are stored locally in regime_data.json in the application-data directory. No provider API key is needed. Regime classifications use completed bars and current/past observations only; forward returns are calculated separately as historical outcomes, not predictions or trading signals.

On first launch, the Core Edition attempts a one-time migration of compatible fixed-interval OHLC datasets from the previous research_cache.json. Legacy tick-derived/variable-interval datasets are excluded from the new Regime library. The old research cache and raw tick files are not deleted.

## Market-data and calendar limitations

The Volatility Lab retains its Yahoo Finance public chart integration. It is unofficial, may be delayed, rate-limited or unavailable, and has no uptime guarantee. Treat it as indicative monitoring data, not execution-grade market data. Verify important prices with your broker or a properly licensed provider.

Session schedules are configurable weekday conventions. Public holidays, special exchange closures and broker-specific trading hours are not fully modelled. The economic calendar is third-party data; verify critical releases against their official issuers.

The Core Edition does not connect to MT5, fetch provider history through Massive/Twelve Data, construct tick bars, backtest strategies or submit orders.

## Run from source

Requirements:
- Python 3.10+
- Tkinter
- Windows: tzdata and windows-toasts are installed through requirements.txt

    python -m pip install -r requirements.txt
    python main.py

On Windows, double-click run.bat to launch from source.

## Build and install the Windows desktop app

Run BUILD_AND_INSTALL.bat on the target Windows 10/11 PC. It creates an isolated build environment, packages a one-folder executable with PyInstaller, installs it under:

    %LOCALAPPDATA%\Programs\Veltrix Trading Clock

and creates Desktop and Start-menu shortcuts. Python 3.10+ is required for the one-time local build; the installed app does not require a separate Python installation or VS Code.

Writable user files live under:

    %LOCALAPPDATA%\Veltrix Trading Clock

Settings, alarm state, market/calendar caches, the Focus & Goals SQLite database and regime_data.json are kept outside the program folder so upgrades preserve them.

See DESKTOP_INSTALL_GUIDE.md for migration, upgrade and uninstall details.

## Tests

    python -m unittest discover -s tests -v

The automated suite covers session/DST handling, alerts, calendar parsing and reminders, market-data normalisation, volatility calculations, causal Regime Lab classification and data import, focus persistence, alarm persistence, app paths and theme behaviour.

A passing unit suite does not prove live provider uptime, native Windows rendering, data licensing or trading profitability.

## Project structure

- main.py — integrated Tkinter interface and orchestration.
- session_engine.py / alert_engine.py — timezone-aware session states and alert scheduling.
- calendar_engine.py — public calendar client, cache and reminders.
- market_data.py / volatility_engine.py — indicative market monitoring, ATR and expected-move calculations.
- regime_engine.py — causal OHLC regime classification and outcome summaries.
- regime_data.py — local OHLC CSV import, legacy-data migration and dataset persistence.
- focus_engine.py — local SQLite focus sessions, goals and milestones.
- app_paths.py / config_store.py — writable application paths and validated configuration.
- tests/ — automated regression tests.

Previous release notes remain in the repository as historical records.
