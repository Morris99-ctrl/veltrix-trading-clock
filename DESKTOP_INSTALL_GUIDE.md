# Veltrix Trading Clock v10.6 — Core Edition

The Core Edition is a smaller standalone desktop clock for Windows 10/11. Global Sessions includes selectable market-hours profiles, editable custom local schedules, weekly scheduled-hours summaries and 7/30/90-day reconstructed overlap reports. The Global Sessions dashboard displays four timezone-aware instrument-style analog clocks with detailed bezels, hour numerals, graduated minute tracks, layered hands and smooth 50 ms second-hand sweeps, followed by a UTC-aligned 24-hour map of scheduled trading windows and market overlaps. It retains global sessions, alarms, alerts, calendar, volatility monitoring, the independent Regime Lab CSV workflow and Focus & Goals.

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

## Market Session Intelligence

In **Global Sessions**, use the Profile selector and **APPLY** to choose one of the built-in schedule templates:

- Current Configuration — the original session schedule saved as the baseline.
- Forex Standard — a weekday monitoring template for the four centres.
- Equities Cash — a cash-equity-hours template.
- Extended Monitoring — a wider monitoring-hours template.
- Custom — your own local open/close times and selected weekdays.

Use **EDIT CUSTOM** to change each market's open time, close time and active weekdays. All times are entered in that market's own IANA timezone. The selected profile, custom schedules and original baseline are saved in config.json and restored on restart. The presets are editable schedule templates, not official exchange calendars.

The Market Session Intelligence panel shows scheduled hours for each market's local Monday-Sunday week and a reconstructed overlap report for the prior 7, 30 or 90 days. The report is calculated from the currently selected profile and timezone rules. It does not know unconfigured public holidays, emergency closures or broker-specific hours, so it must not be interpreted as observed exchange history.

## Exchange Calendar Intelligence

The Global Sessions panel includes an optional **CASH EXCHANGE HOLIDAYS / EARLY CLOSES** switch. It applies the bundled published ASX cash-market, Tokyo Stock Exchange / JPX, London Stock Exchange and NYSE cash-market exceptions to the corresponding session cards, UTC timeline, alerts and session analytics.

The overlay is disabled by default. Enable it only when you intend the clocks to reflect the tracked cash-exchange venues; it does not convert a generic forex schedule into an official cash-market session. The selected session profile still determines the configured opening/closing hours.

The bundled data was checked on 23 November 2026. Coverage is venue-specific: ASX, JPX and NYSE have published 2026–2027 entries; the LSE entries begin on 31 August 2026 and run through 2027. Dates beyond the published coverage are labelled OUT OF PUBLISHED RANGE.

NYSE and ASX actual early-close times shorten the session state. For the LSE dates marked as half-days, the exchange says the closing process commences from 12:30 London time; Veltrix displays this as a closing-process marker and does not force the market closed at 12:30.

See [EXCHANGE_CALENDAR_SOURCES_10.4.md](EXCHANGE_CALENDAR_SOURCES_10.4.md) for source links, covered dates, product scope and limitations. The bundled snapshot is offline and does not receive automatic exchange amendments.

## Session Risk Awareness

Each of the four Global Sessions cards shows a session-risk label. NORMAL means no configured schedule risk flag is active. CAUTION may indicate an opening/closing window, a published early-close or closing-process event, a nearby holiday, or an unverified date outside calendar coverage. HIGH is used for a published full-day exchange holiday.

Open **Alerts & Events** to set independent pre-open and pre-close reminder lead times for Sydney, Tokyo, London and New York. Adjust the global reminder defaults first, then tune each session's override row. The risk controls independently enable/disable card flags, risk notifications and holiday-liquidity cautions, and set the opening, closing and pre-open warning windows. Click SAVE ALERT SETTINGS to persist the controls.

Holiday-liquidity messages are calendar-based cautions only. They do not measure actual volume, spread, order-book depth or market impact. Opening and closing warnings are time-window indicators, not forecasts of price volatility. Treat them as context for your own analysis, not trade instructions.

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
