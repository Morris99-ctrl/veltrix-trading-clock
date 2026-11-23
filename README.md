# Veltrix Trading Clock — v10.11 Core Edition

Veltrix v10.10 is a deliberately smaller Windows desktop trading clock. It focuses on market-session awareness, alarms, economic-event reminders, volatility monitoring, a compact causal Regime Lab and personal focus tracking.

The former Research Lab, Strategy Lab, Tick Research and Data Center workspaces have been removed from the application. Their fetch, import, bar-construction, provider and backtesting workflows are no longer started or exposed by the Core Edition.

## Included workspaces

- **Global Sessions** — four instrument-style analog clocks with session-progress rings, opening/closing markers, local UTC offsets and day/night-cycle labels; a concentric world-session dial; and an interactive UTC map with click-and-drag time probing, live overlap summaries and optional official cash-exchange holiday/early-close overlays.
- **Alerts & Events / Market Watch** — a terminal-style dashboard with a 24-hour UTC market-hours map, current-session status, searchable 28-pair FX reference watchlist, weekend countdowns, news ticker and high/medium impact calendar; all existing alert rules remain available in an expandable preferences area.
- **Economic Calendar** — third-party public calendar feed, impact filters, cached results and high-impact reminders.
- **Volatility Lab** — indicative Yahoo Finance market monitoring, ATR, one-day historical expected move and session volatility observations.
- **Regime Lab** — import completed OHLC history from a CSV, classify bars as range, trend-up, trend-down, volatility shock or transition, inspect historical conditional outcomes and export classifications.
- **Session Performance** — reuse the same local OHLC datasets to measure returns, observed ranges, realised volatility, positive-day rate, sample counts, estimated coverage and pairwise session-overlap behaviour; v10.10 adds rolling return/drawdown, sample-gated consistency rankings and performance grouped by causal market regime; v10.11 adds chronological training/holdout validation.
- **Focus & Goals** — restart-safe stopwatch/countdown timers, daily focus history, goals and milestones.
- **Alarm Clock** — the original seven-segment clock, alarm, snooze and theme system.

## Global Sessions clock interface

The Global Sessions dashboard presents four separate analog dials in a two-by-two layout. Each dial uses the timezone of its own market centre and has a mini digital clock directly beneath it, so the time can be read precisely without losing the visual character of an analog face.

The dials use a layered instrument-style case and glass bezel, a recessed minute track, all 60 graduated minute marks, clear 1–12 hour numerals, diagonal bezel fasteners and a small Veltrix dial signature. Layered hour and minute hands use shadow and highlight strokes; the seconds hand has a rear counterweight and raised centre hub. A 24-hour session-window ring marks the configured opening and closing positions and fills as the session progresses. Faces are rendered once per size/theme/schedule and their retained Canvas objects are reused.

A dedicated 50 ms animation loop advances each dial using sub-second local time. That makes the seconds hand sweep smoothly and lets the minute/hour hands progress continuously, independently of the slower session-status refresh. The four dials still use their own IANA timezones and retain the existing digital readout, status, countdown and risk information. Each card also displays the actual UTC offset for that instant, including daylight-saving changes, and a DAY/NIGHT CYCLE label based on a 06:00–18:00 local wall-clock convention. The cycle label is not a sunrise/sunset or astronomical daylight calculation. A published early-close time shortens the progress calculation when the exchange-calendar overlay supplies one.

Each card also shows its city, timezone, OPEN/CLOSED state and the countdown to its next scheduled opening or closing. An open session receives a highlighted card border. The six application themes recolour the dials and hands consistently.

## Global Session Intelligence

The 24-hour UTC map sits beneath the four market clocks. It is generated from the same `SessionDefinition` objects used by the live clock cards and alert engine, rather than maintaining a second set of market hours.

Each market has its own lane showing its scheduled local trading window converted into UTC. The map starts at 00:00 UTC and ends at 24:00 UTC, with a live current-time marker. The separate overlap lane highlights periods when at least two configured sessions are scheduled open. The summary underneath lists the overlap participants and UTC times, total overlap duration, and the next three market transitions.

The map honours each session's IANA timezone and weekday schedule, including daylight-saving changes. It represents configured weekday hours only; exchange holidays, emergency closures, broker-specific hours and overnight schedules are not inferred. It is a schedule visualisation, not a live exchange-status feed.

The Global Sessions page is vertically scrollable so the clock cards, world dial, 24-hour map and footer remain accessible on shorter displays. The World Session Dial plots Sydney, Tokyo, London and New York windows as four concentric UTC tracks and rotates a live UTC pointer around the 24-hour face. The horizontal timeline accepts click-and-drag probing: select any minute in the current UTC day to inspect which configured sessions are open at that instant. The probe is temporary and resets when the UTC day changes. The dial and timeline use the same session definitions and optional exchange-calendar overlay.

## Session Performance Intelligence (v10.11)

Session Performance reuses datasets already imported in Regime Lab. Import an OHLC CSV once; the same local dataset appears in the Session Performance selector. The analysis uses the active session profile and each session's own IANA timezone. Changing the selected dataset or session profile invalidates old output.

A bar belongs to a session when its **bar-open timestamp** falls inside the configured local [open, close) window on one of that session's configured weekdays. Session-day return is the first observed bar open to the last observed close. Session range is the observed high-to-low range divided by the first observed open. Realised volatility is the root-sum-square of observed bar log returns, expressed as a percentage and **not annualised**. Pairwise overlap return compounds each selected bar's open-to-close return and does not stitch unobserved gaps.

**v10.10 rolling performance and rankings:** each accepted session day receives trailing metrics calculated from the current and earlier qualifying session observations only. The rolling window defaults to 20 session observations. The dashboard reports rolling mean return, positive-observation rate, compounded return and maximum peak-to-trough drawdown. The rolling window counts accepted session observations, not calendar days. The same trailing calculations are applied to overlap observations.

The **signed consistency score** is defined as:

`50 + 50 × mean(return) / mean(abs(return))`

It is bounded from 0 to 100. A score above 50 indicates positive mean return; 50 is neutral; below 50 indicates negative mean return. All-positive returns yield 100 and all-negative returns yield 0. When every return is exactly zero, the score is 50. It is a transparent directional consistency measure, **not** a Sharpe ratio, risk-adjusted return, forecast or profitability probability. The ranking table uses the latest rolling-window score and withholds ranks until the configured minimum rolling sample is met (default 10 observations). Sample size, compounded return and maximum drawdown are shown alongside the score.

**v10.10 regime breakdown:** the existing causal Regime Lab classifier is run over the same imported OHLC dataset using the current Regime Lab parameters. Only its bar-level regime labels are used; its separate forward-return outcome field is ignored. Each session day is assigned to the most frequent classified regime among its bars. Ties are resolved by the latest classified bar. The default minimum regime coverage is 50% of bars in that session day; rows below the threshold, or with only WARMUP bars, do not enter the regime breakdown. The underlying session-day observations remain available in the daily export with their attribution and coverage fields.

The base quality filters still require at least 3 bars per session day and estimated coverage of at least 50%. Coverage is observed bars divided by expected bars estimated from the dataset's median interval, capped at 100%. It is a count-based estimate, not proof that every scheduled minute is present. Excluded days remain in the export with an exclusion reason but do not enter summary averages. The minimum rolling sample and minimum regime coverage can be adjusted before each study.

The export contains session and pairwise-overlap rows, including rolling metrics and regime attribution on session rows. Timestamps are stored/exported in UTC. The importer's configured IANA timezone is used only for source timestamps that had no explicit timezone/UTC offset; explicit timestamps are normalised to UTC during import.

**v10.11 chronological holdout validation:** accepted session-day observations are sorted by date and split once into an earliest training segment (default 70%) and a later holdout segment (default 30%). The training segment must meet the configured minimum ranking sample; the holdout must meet its separate minimum sample (default 5 observations). Session rank is calculated from the training segment's signed consistency score, then training mean return. The later holdout is never used to determine that rank. The table reports holdout mean return, positive-day rate, compounded gross return and maximum drawdown alongside training sample, score and holdout sample. The CSV labels each accepted day as TRAIN or HOLDOUT and includes the summary metrics. When either segment is too small, the validation status is INSUFFICIENT_SAMPLE and the rank and segment metrics are withheld. This is a single chronological holdout check of session returns, not a strategy backtest, rolling walk-forward process, forecast or proof of predictive edge.

This is descriptive historical analysis, not a trading signal or forecast. It uses the current configured weekday session schedules and does not independently remove exchange holidays, early closes, broker-specific hours or maintenance breaks. Results depend on symbol, source, bar interval, timestamp convention, missing observations and data quality. Returns are gross of spreads, commissions, slippage, financing and execution effects. No historical observations are generated automatically when the dataset is empty.

## Market Watch & Alerts (v10.8)

The Alerts & Events workspace has been reorganised as a compact Market Watch terminal. Its upper strip combines the local system clock, a UTC-aligned map of the four configured trading centres and a live OPEN/CLOSED status list. A search/control row and next-news ticker sit above a split lower workspace: the FX reference watchlist on the left and a date/impact-filtered economic calendar on the right.

The symbol table contains 28 standard USD majors and non-USD crosses. It deliberately shows a **reference trading-week schedule**, not broker quotes or execution availability. The reference week is Sunday 17:00 to Friday 17:00 in America/New_York; countdowns use the IANA timezone and calculate elapsed seconds in UTC so New York daylight-saving transitions do not distort the remaining time. Broker trading hours, daily rollover/maintenance breaks, symbol availability, holidays and liquidity conditions can differ.

The calendar panel displays events already loaded by the existing ShowMyTrades public economic-calendar client. It supports local-date navigation, high/medium or all-impact filters and combined symbol/event search. A cached snapshot is clearly labelled as cached; the dashboard does not silently call old data live. The ticker highlights the next loaded high/medium event. The provider still observes its 15-minute successful-fetch cache floor.

The previous session pre-open/open/pre-close/close/overlap rules, sound and Windows notification switches, independent per-market lead times, session-risk controls and manual event reminders remain available under **ALERT RULES / PREFERENCES**. The recent alert activity feed stays visible below the market board.

## Market Session Intelligence (v10.3)

The session dashboard now includes selectable market-hours profiles and a custom profile editor. Built-in profiles are **Current Configuration**, **Forex Standard**, **Equities Cash** and **Extended Monitoring**. The custom editor lets the user set each market's local open/close time and active weekdays. Profile changes update the four clocks, live timeline, transition countdowns and overlap calculations together. The selected profile, original base schedule and custom hours are saved in the application configuration so switching profiles does not overwrite the starting schedule.

The weekly-hours report calculates the Monday-Sunday schedule in each market's own local timezone. It reports scheduled hours and active weekdays for Sydney, Tokyo, London and New York, applying the relevant IANA timezone and daylight-saving offset for each local date.

The historical overlap report supports 7, 30 and 90-day lookbacks. It reconstructs scheduled overlap intervals from the currently selected profile, reports total and average daily overlap time, busiest UTC date and overlap hours by market pair. This is a **schedule reconstruction**, not an observation of actual historical exchange openings. Public holidays, emergency closures, special sessions and broker-specific hours are not known unless represented in the configured schedule.

## Exchange Calendar Intelligence (v10.4)

An opt-in **CASH EXCHANGE HOLIDAYS / EARLY CLOSES** switch overlays published cash-market exceptions for ASX, Tokyo Stock Exchange / JPX, London Stock Exchange and NYSE on the four Global Sessions clocks, UTC timeline and session alerts. It is disabled by default so generic forex schedules are not silently treated as local cash-equity exchange hours.

When enabled, a full exchange holiday marks the venue HOLIDAY, skips it in the 24-hour map and suppresses the normal open/close alerts for that date. Published actual early-close times shorten the venue clock state and timeline and are used by pre-close/close alerts. The weekly-hours and 7/30/90-day overlap summaries use the same exception overlay while it is enabled.

The bundled calendar snapshot was checked on 23 November 2026 and currently covers ASX, Tokyo Stock Exchange and NYSE dates in 2026–2027, plus London Stock Exchange dates from 31 August 2026 through 2027. Dates outside a venue's published coverage are labelled OUT OF PUBLISHED RANGE rather than assumed to be verified normal days.

**London half-day nuance:** LSE's published notice says its closing process commences from 12:30 on the listed Christmas Eve and year-end half-days. Veltrix displays and alerts on that closing-process start; it does not falsely claim that continuous trading definitely ends at 12:30. ASX's 14:10 normal-trading cessation and NYSE's 13:00 early close are modelled as actual early-close times.

The calendar dataset is an offline, source-attributed snapshot, not a live exchange API. Venue/product scope, sources, dates and limitations are documented in [EXCHANGE_CALENDAR_SOURCES_10.4.md](EXCHANGE_CALENDAR_SOURCES_10.4.md). The ASX 24 derivatives calendar, JPX derivatives holiday-trading programme, NYSE extended sessions, London OTC/SI reporting, exchange amendments, emergency halts and broker-specific hours are not included.

## Session Risk Awareness (v10.5)

Each Global Sessions card now includes a schedule-based risk assessment with NORMAL, CAUTION or HIGH severity. Flags distinguish an exchange holiday, published early close, exchange closing-process marker, opening window, near-close window, pre-open window, holiday-ahead caution, post-holiday caution and dates outside published venue-calendar coverage.

The **Alerts & Events** page adds separate pre-open and pre-close lead times for Sydney, Tokyo, London and New York. Each session's reminder can be adjusted independently from the global default. The Session Risk Awareness panel configures whether flags and notifications are enabled, the opening/closing caution windows, the pre-open flag window and holiday-liquidity cautions.

Holiday-adjacent flags are transparent calendar heuristics: they indicate that participation *may* be thinner before or after a published cash-exchange holiday. They are not measured liquidity, volume, spread, market depth or a forecast. Opening and closing windows are likewise time-based context flags, not volatility predictions. The risk panel does not submit trades or size positions.

Session risk preferences and reminder overrides are stored locally in config.json. The risk flags use the currently selected session profile and respect the optional v10.4 exchange-calendar overlay. When the exchange overlay is disabled, exchange-specific holiday-liquidity flags are not inferred.

## Regime Lab data

Regime Lab now has its own **IMPORT OHLC CSV** workflow. It accepts timestamp plus Open, High, Low and Close columns, including common MT5-style separate Date/Time fields. Timestamps are normalised to UTC. Naive timestamps are interpreted using the configured home timezone (Africa/Nairobi by default).

Imported datasets are stored locally in regime_data.json in the application-data directory. No provider API key is needed. Regime classifications use completed bars and current/past observations only; forward returns are calculated separately as historical outcomes, not predictions or trading signals.

On first launch, the Core Edition attempts a one-time migration of compatible fixed-interval OHLC datasets from the previous research_cache.json. Legacy tick-derived/variable-interval datasets are excluded from the new Regime library. The old research cache and raw tick files are not deleted.

## Market-data and calendar limitations

The Volatility Lab retains its Yahoo Finance public chart integration. It is unofficial, may be delayed, rate-limited or unavailable, and has no uptime guarantee. Treat it as indicative monitoring data, not execution-grade market data. Verify important prices with your broker or a properly licensed provider.

Session schedules are configurable weekday conventions. The optional v10.4 cash-exchange overlay applies only the bundled published dates and venue scope described in EXCHANGE_CALENDAR_SOURCES_10.4.md; it is not a live exchange-status feed or a substitute for broker-specific trading hours. The economic calendar is third-party data; verify critical releases against their official issuers.

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

Run the local suite with:

    python -m compileall -q .
    python -m unittest discover -s tests -v

GitHub Actions runs the same compile and unit-test checks on Python 3.10, 3.11 and 3.12 for pushes and pull requests. Once the test matrix passes, a Windows runner builds the standalone desktop package and uploads it as a workflow artifact.

Workflow details and build artifacts are available in the [GitHub Actions page](https://github.com/Morris99-ctrl/veltrix-trading-clock/actions/workflows/core-edition-ci.yml).

The v10.9 baseline passed 208 tests. The v10.10 release passed **214 tests** on Python 3.10, 3.11 and 3.12; the Windows PyInstaller build, executable verification and artifact upload also succeeded in [workflow run 45271034244](https://github.com/Morris99-ctrl/veltrix-trading-clock/actions/runs/45271034244). Manual native Windows GUI review remains required. See RELEASE_VALIDATION_10.10.txt.

The automated suite covers session/DST handling, analog-clock hand geometry, UTC session timeline, weekly session hours, historical overlap calculations, profile validation, exchange holidays, early closes, session risk flags, liquidity cautions and per-session reminder overrides, alerts, calendar parsing and reminders, market-data normalisation, volatility calculations, causal Regime Lab classification and data import, rolling session metrics, compounded return, maximum drawdown, sample-gated rankings, dominant-regime attribution and score behaviour, focus persistence, alarm persistence, app paths and theme behaviour.

A passing unit suite does not prove live provider uptime, native Windows rendering, data licensing or trading profitability.

## Project structure

- main.py — integrated Tkinter interface and orchestration.
- alerts_dashboard.py / market_watch.py — Market Watch UI, FX reference-week schedule and economic-news panel.
- session_performance.py / session_performance_ui.py — historical session and pairwise-overlap OHLC analysis, trailing statistics, sample-gated ranking and causal regime attribution.
- session_engine.py / session_clock.py / session_timeline.py / session_intelligence.py / session_profiles.py / exchange_calendar.py / risk_engine.py / alert_engine.py — timezone-aware session states, analog-hand geometry, UTC session windows, historical overlap analytics, selectable profiles, exchange exceptions, session-risk flags and alert scheduling.
- calendar_engine.py — public calendar client, cache and reminders.
- market_data.py / volatility_engine.py — indicative market monitoring, ATR and expected-move calculations.
- regime_engine.py — causal OHLC regime classification and outcome summaries.
- regime_data.py — local OHLC CSV import, legacy-data migration and dataset persistence.
- focus_engine.py — local SQLite focus sessions, goals and milestones.
- app_paths.py / config_store.py — writable application paths and validated configuration.
- tests/ — automated regression tests.

Previous release notes remain in the repository as historical records.
