# Veltrix Trading Clock v10.1 — Core Edition

The Core Edition is a smaller standalone desktop clock for Windows 10/11. The Global Sessions dashboard displays four timezone-aware neon analog clocks with compact digital local-time readouts beneath each dial. It retains global sessions, alarms, alerts, calendar, volatility monitoring, the independent Regime Lab CSV workflow and Focus & Goals.

The Research Lab, Strategy Lab, Tick Research and Data Center workspaces are removed. No provider API keys, tick-bar construction, strategy backtesting, MT5 connection or order execution are required.

## One-time Windows installation

1. Extract the complete source package to a normal folder.
2. Install 64-bit Python 3.10 or newer. Python is required only for the one-time build.
3. Double-click BUILD_AND_INSTALL.bat.
4. When prompted, enter the path to your previous Veltrix project folder or the existing %LOCALAPPDATA%\Veltrix Trading Clock data folder. The installer migrates settings, calendar/market caches, the legacy OHLC research cache (for Regime Lab migration), the Regime dataset file, alarm state, Focus & Goals database and alarm audio when the destination does not already exist.
5. Launch **Veltrix Trading Clock** using the new Desktop or Start-menu shortcut.

The build creates a standalone one-folder executable under:

    %LOCALAPPDATA%\Programs\Veltrix Trading Clock

No administrator rights, VS Code or separate Python installation are required to run the installed application.

## User data and migration

Writable application data is stored separately under:

    %LOCALAPPDATA%\Veltrix Trading Clock

The installer preserves existing destination files and copies legacy files only when the destination does not already exist. The main files include:

- config.json
- calendar_cache.json
- market_cache.json
- research_cache.json (read once to migrate compatible fixed-interval OHLC datasets)
- regime_data.json
- alarm_state.json
- focus_goals.sqlite3
- alarm.mp3 (when present)

The migration does not delete the previous research_cache.json, raw tick-data folders or old source project. Tick-derived datasets are not imported into the Core Edition's Regime Lab library. Existing old .env files are not copied or read by the Core Edition; the app no longer needs provider API credentials.

## Regime Lab

Open **REGIME LAB** and choose **IMPORT OHLC CSV**. Name the dataset when prompted. Naive timestamps are interpreted in the configured home timezone, Africa/Nairobi by default, then stored as UTC.

Imported datasets are saved locally in regime_data.json. The first Core Edition launch can migrate compatible regular OHLC datasets from the previous research_cache.json. Tick-derived and variable-interval datasets are deliberately excluded.

Regime labels are causal: each completed bar uses only current and previous data. Forward returns are separate historical outcome diagnostics, not forecasts or trading signals.

## Market monitoring limitations

The Volatility Lab retains the unofficial public Yahoo Finance chart integration. Data may be delayed, limited or unavailable. Confirm important market prices with your broker or a licensed data provider.

Session hours are configurable weekday conventions, not complete exchange calendars. Verify important economic releases with official issuers.

## Upgrading

Run BUILD_AND_INSTALL.bat from the newer source package. The installer replaces the program files while preserving existing application-data files. Your imported Regime datasets, settings, alarms and focus history remain outside the executable folder.

## Uninstalling

Close Veltrix, delete the Veltrix Trading Clock program folder under %LOCALAPPDATA%\Programs, and remove the Desktop/Start-menu shortcuts. Keep %LOCALAPPDATA%\Veltrix Trading Clock to preserve settings, Regime datasets, caches, alarms and focus history. Delete the data folder separately only when you deliberately want to remove that information.
