# Veltrix Trading Clock v10.9 — Core Edition

The Core Edition is a smaller standalone desktop clock for Windows 10/11. Global Sessions includes four detailed timezone-aware instrument clocks, live session-progress rings, actual UTC-offset readouts, a concentric 24-hour World Session Dial and an interactive UTC session map with click-and-drag time probing. Alerts & Events now opens a Market Watch command centre with a 24-hour session map, current market status, a searchable FX reference watchlist and a filtered macro-news calendar. The new Session Performance workspace reuses Regime Lab's local OHLC datasets to measure per-session and pairwise-overlap behaviour. Existing alert rules remain available in an expandable settings area. The app retains selectable market-hours profiles, editable local schedules, weekly scheduled-hours summaries, historical overlap reconstruction, alarms, calendar, volatility monitoring, Regime Lab and Focus & Goals.

The Research Lab, Strategy Lab, Tick Research and Data Center workspaces are removed. No provider API keys, tick-bar construction, strategy backtesting, MT5 connection or order execution are required.

## Session Performance Intelligence (v10.9)

1. Open **Regime Lab** and select **IMPORT OHLC CSV**.
2. Import a fixed-interval OHLC CSV with timestamp (or date/time), open, high, low and close columns. Naive timestamps are interpreted in the selected home IANA timezone during import; timestamps containing UTC offsets are converted using those offsets.
3. Open **SESSION PERFORMANCE** and choose the imported dataset. No second import is needed.
4. Confirm the active session profile and set the minimum bars per session day and minimum estimated coverage. Defaults are 3 bars and 50%.
5. Select **RUN SESSION STUDY**. The computation runs in a background worker. Session rows and pairwise overlap rows show the qualifying sample count and summary metrics.
6. Select **EXPORT DAILY CSV** to export the daily session and overlap observations, including excluded rows and their exclusion reasons.

The analysis uses bar-open timestamps against each session's configured local [open, close) schedule and weekday list. Returns are gross observed historical returns; range is the observed high-low movement as a percentage of the first observed open; realised volatility is the root-sum-square of observed bar log returns and is not annualised. Pairwise overlap returns compound each selected OHLC bar's open-to-close return without stitching gaps. Coverage is an estimate based on observed versus expected bars using the dataset's median interval.

The active session profile is used. If the dataset or profile changes, previously displayed results are cleared. The study does not apply a separate exchange-holiday calendar, model broker-specific trading hours or adjust returns for transaction costs. It is descriptive research, not a signal, forecast or profitability claim. The source, interval, sample counts and limitations should be considered before comparing markets.

## Market Watch & Alerts (v10.8)

The **Alerts & Events** tab now opens the Market Watch command centre. The upper section shows the local control clock, the four configured market-session lanes on a UTC 24-hour map, and current OPEN/CLOSED states. The lower left is a searchable, sortable reference FX watchlist. The lower right is the economic calendar with previous/today/next date controls and high/medium/all-impact filtering. The news ticker highlights the next loaded high- or medium-impact event. The recent alert activity feed remains visible.

The reference watchlist contains 28 standard major/cross FX pairs. It is a schedule reference, not a broker quote feed. Its weekly reference is Sunday 17:00 to Friday 17:00 New York time (America/New_York). The countdown follows New York daylight-saving rules and calculates real elapsed seconds. Broker-specific hours, daily rollover breaks, bank holidays and symbol availability are not represented. Do not interpret OPEN as a live broker quote or a guarantee that an instrument can be traded at a particular broker.

The news calendar reuses the existing ShowMyTrades client. A fresh successful fetch is labelled as live for the current app run; older disk-cache data is labelled cached and should be checked before trading. The public feed's successful-fetch cache floor remains 15 minutes.

Expand **ALERT RULES / PREFERENCES** to edit session pre-open/pre-close alerts, notification channels, per-market lead times, session-risk settings and manual economic-event reminders. The previous alert rules and notification engine remain in place.

## Global Sessions Instrument Panels (v10.7)

Each market clock has a 24-hour session-window ring. A subdued arc shows the configured local open-to-close window; the highlighted portion advances with elapsed session time. Opening and closing markers remain distinct from the traditional 12-hour hands. The card also shows the current IANA timezone, its actual UTC offset and a DAY/NIGHT CYCLE label. DAY is defined as 06:00–17:59 local time and NIGHT as 18:00–05:59; this is a display convention, not a sunrise/sunset calculation.

The World Session Dial uses concentric UTC tracks for Sydney, Tokyo, London and New York, with a live UTC pointer. The horizontal timeline uses the same session definitions. Click or drag across it to place a time probe; the line and text below the map identify which configured sessions are open at the selected UTC minute. The probe is temporary and clears when the UTC calendar day changes. The visualisations inherit the selected session profile and optional exchange-calendar overlay; they do not add a market-data feed or infer unlisted venue closures.

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
