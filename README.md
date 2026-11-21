# Veltrix Trading Clock — v9.6 Desktop Edition / Phase 12

**Phase 12 causal Market Regime Research release.** Phase 12 adds a dedicated Regime Lab that classifies completed OHLC bars as range, trend-up, trend-down, volatility shock or transition, and measures subsequent historical outcomes without feeding future data into the classifications. Phase 11 adds a persistent Focus & Goals Center with restart-safe stopwatch/countdown timers, long-term goal deadlines, milestones and local daily focus history. Phase 10 adds a provider-neutral acquisition, registry, quality-audit and cross-provider comparison layer on top of the Phase 8 multi-resolution research engine. Version 9.5 builds on the v9.4 Windows desktop edition and adds the local SQLite focus database. Version 9.4 adds a custom Windows application icon, one-click PyInstaller build/install scripts, Desktop and Start-menu shortcuts, and a separate per-user data directory so upgrades preserve settings and credentials. Existing Yahoo-based monitoring remains available as a clearly labelled legacy fallback; it is not silently replaced. Version 9.3 applies one shared theme system throughout the application, including classic Tk controls, ttk selectors, tables, headings, menus, scrollbars, tabs and popup widgets. See `CHANGELOG_9.3.txt` for the current theme release and the earlier changelogs for prior phases.

A resizable Python/Tkinter desktop application combining the original retro-futuristic alarm clock with global trading-session clocks, configurable session alerts, a public economic calendar, Windows desktop notifications, and a quantitative volatility workspace.

## Version 9.5 — Focus & Goals Center / Phase 11

The **FOCUS & GOALS** workspace adds a stopwatch, countdown timer, personal goal register, goal milestones, live deadline countdowns, daily focus tracking and recent session history. Goals and focus sessions are stored in `focus_goals.sqlite3` inside the writable application-data folder, separate from the executable. The database is created automatically on first launch.

- Stopwatch sessions can be paused, resumed and stopped. A running stopwatch continues to accrue elapsed wall-clock time across application restarts.
- Countdown timers support up to 24 hours. Their deadline is stored, so a timer that expires while Veltrix is closed is marked complete on the next launch.
- Paused intervals are excluded from recorded focus time. Sessions that cross midnight are allocated to the correct local days using the configured IANA timezone.
- Goals can be created, edited, deleted and archived/completed. Milestones provide checklist-based progress; otherwise manual progress is used.
- The daily focus target defaults to four hours and can be adjusted.

The current timer is a wall-clock focus tracker, not an operating-system foreground-activity monitor. It cannot determine whether the user was actually working while a stopwatch remained running. Stop or pause the timer when focus work ends.

## Version 9.6 — Causal Market Regime Research / Phase 12

The new **REGIME LAB** works from the OHLC datasets already registered in Research Lab, including broker CSV, provider history and constructed fixed-tick / Tick Imbalance Bar datasets. It does not fetch a second copy of market data, create trade signals or submit orders.

- Classifies each completed bar as `RANGE`, `TREND_UP`, `TREND_DOWN`, `VOLATILITY_SHOCK` or `TRANSITION`; early bars without sufficient lookback are marked `WARMUP`.
- Uses a causal efficiency ratio (net close displacement divided by total absolute close path), an OLS regression slope normalised by slow Wilder ATR, fast/slow ATR ratio and current true range relative to the prior slow ATR.
- Every label at bar *t* is computed only from bars at or before *t*. No centred windows, future indicators or backward-filled regime labels are used.
- Displays historical regime frequency, a transition-count matrix and conditional forward returns over a user-selected horizon. Forward outcomes are calculated only after classifications are fixed; they are descriptive historical measurements, not forecasts or trade signals.
- Provides a price-path chart with regime-coloured segments, a recent-bar diagnostics table and CSV export.
- Runs analysis on a background worker so the Tkinter interface remains responsive. Parameters and selected dataset are stored in `config.json` under `regime_lab`.

Default parameters (lookback 20, fast/slow ATR 14/50, range/trend ER thresholds 0.25/0.35, normalised slope 0.20 ATR, volatility shock thresholds 1.80 ATR ratio / 2.50 prior-ATR true-range multiple, forward horizon 10 bars) are transparent research starting points, not optimised gold settings. They must be tested for sensitivity by instrument, feed and bar construction before being used in any strategy.

## Version 9.4 — Windows desktop application

The Windows desktop builder produces a standalone one-folder executable using PyInstaller. Run `BUILD_AND_INSTALL.bat` once on the target Windows 10/11 PC. It creates the executable, installs it under `%LOCALAPPDATA%\Programs\Veltrix Trading Clock`, and creates Desktop and Start-menu shortcuts. After installation, double-click the shortcut; neither VS Code nor a separate Python installation is required to run the packaged application. Python 3.10+ and an internet connection are required only for the one-time local build.

Writable files are separated from program binaries and live under `%LOCALAPPDATA%\Veltrix Trading Clock`: `config.json`, `alarm_state.json`, `.env`, caches, `focus_goals.sqlite3`, `tick_data\` and `alarm.mp3`. The installer migrates personal files from a project folder or existing AppData folder only when a destination file does not already exist; it merges tick files without overwriting AppData copies. The real `.env` is never bundled in the executable.

PyInstaller cannot cross-compile a Windows executable from Linux, so this package includes a Windows-native one-click builder rather than a prebuilt `.exe`. The builder verifies package hashes using the checked-in lock files. See `DESKTOP_INSTALL_GUIDE.md`.

## Version 9.3 — Application-wide theme consistency

Version 9.3 extends the v9.2 Data Center colour correction into a single application-wide theme pass. Changing any of the six themes updates all current workspaces and standard controls rather than relying only on manually maintained page-specific widget lists.

- Classic Tk widgets are walked recursively so unregistered buttons, entries, spinboxes, checkboxes, radio controls, listboxes, text areas, menus, canvases and popup children receive the active palette. Widgets registered with a semantic page role retain their intended background and foreground roles.
- Shared ttk styles cover default labels, frames, buttons, entries, spinboxes, checkboxes, radio buttons, label frames, notebook tabs, separators, progress bars, scales and scrollbars.
- Every Treeview style used by Calendar, Volatility, Research, Strategy and Data Center has theme-aware rows and column headings.
- All Combobox styles use the same palette for normal, readonly, disabled, active and selected states. Native Tk dropdown listboxes and menus are themed through the option database.
- CYAN, AMBER, MATRIX, VIOLET, ICE and LIGHT remain supported. The LIGHT theme retains its light surfaces; the five dark themes no longer leave bright white selection panels or headers behind.
- The update changes presentation only. It does not alter market-data acquisition, provider credentials, tick construction, research calculations, backtests, alerts, alarms or persisted datasets.

### Historical upgrade instructions: v9.3 from v9.2
For the historical v9.3 source upgrade, the release ZIP was extracted into a **new, separate folder** and personal files were copied from v9.2: `config.json`, `research_cache.json` (if present), `calendar_cache.json` (if present), `market_cache.json` (if present), the complete `tick_data/` folder (if present), `alarm.mp3` (if present), and your private `.env` file. Do not copy old Python source files, old tests or the old `requirements.txt` over the new release. Install dependencies using the v9.3 `requirements.txt`. The ZIP excludes `.env`, caches, imported tick data and alarm audio.

### Theme validation
The release includes unit tests for the six palettes, global ttk styles, all Treeview and Combobox style names, recursive classic-widget styling, preservation of registered semantic surfaces and safe handling of unsupported widgets. A GUI smoke test should still be performed on the target Windows machine because native Tk rendering can vary by Windows/Tk build.

## Phase 10 — Provider-independent Market Data Gateway (v9.0)

Phase 10 adds the **DATA CENTER** workspace. It does not replace the existing Yahoo feed or connect to a broker by default. The aim is to acquire independently sourced historical datasets, preserve their provenance, inspect quality and compare like-for-like series before promoting a provider.

### Providers and current adapter status
- **Massive — adapter enabled:** historical aggregates for forex, indices and exchange-traded futures, subject to symbol coverage, account plan and entitlement. Use provider-native symbols: for example `C:XAUUSD` for its XAUUSD forex product, `C:EURUSD` for EUR/USD, `I:SPX` for an index, and an exact dated futures contract ticker for futures. Do not assume the continuous symbol or a different product's ticker is accepted.
- **Twelve Data — adapter enabled:** historical `/time_series` requests for supported symbols, including the XAU/USD spot candidate. The app requests UTC for intraday bars; daily and higher bars are returned in exchange-local time by the provider and then normalised to UTC. The current request is bounded by the provider's 5,000-record per-request maximum. A result at that limit is flagged as potentially truncated.
- **Databento — catalog candidate only:** displayed as a potential exchange-data provider for futures research. No Databento SDK/API adapter is enabled in v9.0. Do not treat its connection status as tested or supported by this release.
- **Yahoo Finance — legacy fallback:** the existing volatility monitor and historical workflow remain in place while replacement providers are validated. Its public chart endpoint remains unofficial and is not upgraded to a licensed service by this release.
- **MT5 — optional broker-specific source:** not part of the live provider adapters in this release. Broker exports can continue to be imported through CSV. MT5 is a possible later validation/collection adapter, not a universal market-data source.

### Historical upgrade notes: v9.1 to v9.2
The following instructions are retained for reference when upgrading specifically to v9.2. For v9.4 desktop installation, use `BUILD_AND_INSTALL.bat` and its migration prompt, as described in `DESKTOP_INSTALL_GUIDE.md`. The v9.2 ZIP was extracted into a **new, separate folder** and personal data files were copied from v9.1, replacing the default `config.json` when prompted:

- `config.json`
- `research_cache.json` (if present)
- `calendar_cache.json` (if present)
- `market_cache.json` (if present)
- the complete `tick_data/` folder (if present)
- `alarm.mp3` (if present)
- your existing `.env` file (if you already created one; otherwise copy `.env.example` to `.env` and add your keys)

For that historical v9.2 upgrade, old `.py` files, the old `tests/` directory and the old `requirements.txt` were not copied over the new release. The v9.2 ZIP excluded local caches, imported raw tick files, personal alarm audio and real API credentials.

### Configure API credentials with `.env` (recommended)
The gateway supports a project-local `.env` file and process/Windows environment variables. In source/development mode, `.env` sits beside `main.py`. In the packaged Windows desktop app, it sits in `%LOCALAPPDATA%\Veltrix Trading Clock\.env`. Process environment variables take precedence over values in `.env`, so existing Windows user variables continue to work. Credentials are loaded at application startup and are never saved to `config.json`, `research_cache.json`, logs, or dataset metadata.

1. In source mode, copy the template beside `main.py`: `Copy-Item .env.example .env`. In the desktop build, copy `.env.example` to `%LOCALAPPDATA%\Veltrix Trading Clock\.env`.
2. Open `.env` in a text editor and add your provider keys:

```ini
MASSIVE_API_KEY=your_massive_key_here
TWELVE_DATA_API_KEY=your_twelve_data_key_here
```

3. Save the file and restart Veltrix. No quotes are needed around ordinary API keys. Keep the `.env` file private; `.gitignore` excludes it from Git while allowing the safe `.env.example` template to be tracked.

The older Windows environment-variable method is still supported. For example, in PowerShell:

```powershell
[Environment]::SetEnvironmentVariable("MASSIVE_API_KEY", "YOUR_KEY_HERE", "User")
[Environment]::SetEnvironmentVariable("TWELVE_DATA_API_KEY", "YOUR_KEY_HERE", "User")
```

Use the API provider's account portal to manage or revoke keys. Do not paste live credentials into source code, screenshots, chats, or exported reports. The connection-test buttons perform small API smoke tests. Twelve Data's `/api_usage` authentication check consumes one API credit. These checks do not prove that every instrument, history range, real-time product or commercial display entitlement is included in the account.

### Fetch and register a dataset
1. Open **DATA CENTER** and confirm the provider's credential status.
2. Choose a provider, provider-native symbol, canonical instrument ID, interval and UTC date range.
3. Use separate canonical IDs for economically different products. For example, `XAUUSD_SPOT` and `GC_FUTURES` must not be compared as if they were the same instrument. A canonical ID is a user-controlled grouping label, not proof of fungibility.
4. Fetch and register the dataset. It becomes selectable in Research Lab and Strategy Lab without replacing existing CSV, Yahoo or tick-derived datasets.
5. Run the audit and inspect the requested period, returned timestamps, invalid rows skipped, duplicate timestamps removed and gap candidates before research use.

All provider requests and audits run in background workers so network delays do not block the Tkinter event loop. Provider fetches are stored in the existing research cache with source, provider symbol, canonical instrument ID, interval, UTC timestamp basis, price-basis notes and a flag showing that commercial licensing has not yet been reviewed.

### Data semantics that must not be confused
- Massive's forex aggregate bars are built from **bid quotes**. Its forex `volume` field is a quote count, not executed trading volume; the OHLC is not a midpoint. Treat these bars as a bid-quote series, not a trade tape. The provider interprets forex and index date-window path parameters in Eastern Time, while returned epoch timestamps are UTC.
- Massive futures aggregate bars are built from exchange trades and have futures trade-volume semantics. They are a different data product from OTC spot Gold or FX quotes.
- Massive index aggregates are index values, not trade prints.
- Twelve Data XAU/USD is an OTC spot-price series supplied by the provider. It is not a consolidated global gold transaction tape. Confirm the exact instrument, plan entitlement, price construction and permitted usage with the provider.
- Spot XAU/USD, COMEX Gold futures (`GC`) and an MT5 broker's XAUUSD CFD/OTC symbol are related but not identical products. Preserve source and instrument identity; do not combine their returns into one continuous history without an explicit basis/roll methodology.
- Providers can use different quote aggregation, timestamp boundaries, session definitions and corrections. Small price differences are not automatically data errors.

### Quality checks and cross-provider comparison
The Data Center records OHLC structural issues, invalid provider rows skipped during parsing, duplicate timestamps removed, and large elapsed-time gaps as review candidates. A gap is not automatically a missing bar: sessions, holidays, provider schedules and instrument trading hours must be considered.

The comparison tool requires the same user-assigned canonical instrument ID and bar interval. It aligns exact UTC bar timestamps and reports matched coverage, mean and 95th-percentile absolute close difference in basis points, and correlation of matched one-bar close returns. It does not resample, interpolate, roll futures, reconcile bid/ask conventions or certify either feed as correct. Compare only economically equivalent instruments and matching price bases.

Twelve Data currently returns at most 5,000 records per request. When both `start_date` and `end_date` are specified, the adapter omits `outputsize` so it does not impose an additional row cap; a response reaching the provider limit is still marked potentially truncated. Narrow the requested dates or use a provider workflow that explicitly pages/chunks the required range. Massive pagination follows `next_url` with a five-page safety cap; the dataset metadata reports whether pagination completed. A cap warning means coverage should not be assumed complete. Massive futures request filters use UTC dates; Massive forex and index path dates use Eastern Time. All returned timestamps are stored in UTC.

### Commercial and operational limitations
- API account access and data entitlements vary by asset class, exchange, symbol, history depth and subscription. A successful authentication request is not proof of access to a desired instrument.
- Personal/research use, internal business display, external display, redistribution and derived-data use can have different licence conditions. The app marks provider datasets `commercial_licence_reviewed: false`; that flag must remain false until the applicable written terms are checked for the intended use.
- No live streaming adapter, automatic provider failover, vendor consensus feed, order-book reconstruction or trading/order execution is included in v9.0.
- The gateway does not currently fetch Databento datasets or automatically connect to MT5.
- No live provider credentials were supplied for development testing. Provider parsing, request construction, UI navigation and error handling were tested with mocked responses; live symbol availability, account entitlements, rate limits and prices must be verified with the user's own provider account.

## Phase 7 — Strategy Research & Backtesting Lab

### Strategy available in v7
- **SMA crossover:** configurable fast and slow simple moving averages. A bullish crossover targets long exposure; a bearish crossover targets short exposure or flat exposure depending on the selected direction (`both`, `long_only`, `short_only`).
- **ATR protection:** Wilder ATR is sampled from the signal bar. Stop distance is `ATR × stop multiple`; target distance is `stop distance × target R multiple`.
- **Position sizing:** planned risk budget is current realised equity × risk percentage. Quantity is the smaller of risk-budget sizing and maximum-notional-leverage sizing, rounded down to the configured quantity step. A position is skipped if the result is smaller than one quantity step.
- One position at a time; no pyramiding. Direction reversals close and reverse at the next bar open.

### Execution assumptions (read before interpreting a backtest)
- Signals are evaluated only after a bar closes and can fill no earlier than the **next bar open**. The signal timestamp, entry timestamp and exit timestamp are separately stored in each trade.
- Entry and exit slippage are applied adversely using basis points per side. Commission basis points and optional fixed commission per unit are also charged on both sides.
- Stops and targets are tested against OHLC after a next-open fill. If both are touched within a single bar and the intrabar path is unknown, the engine assumes the **stop was hit first**. This is a conservative convention, not proof of the historical tick sequence.
- If price gaps beyond a stop or target, the reference exit is the bar open, then adverse slippage is applied. Stops do not guarantee the planned maximum loss.
- The final open position is closed at the final bar close for each test window. No trades or positions are carried across holdout or walk-forward boundaries.
- Maximum drawdown uses the bar-level marked-to-market equity curve, including estimated costs to liquidate an open position. Daily Sharpe is calculated from observed UTC daily equity observations and annualised using the conventional `sqrt(252)` factor. It may be `N/A` when too few daily observations or no return variation exists.
- Win rate is based on positive **net** trade P&L. Profit factor is positive net trade P&L divided by the absolute value of negative net trade P&L. Expectancy is mean net P&L per trade; expectancy R is mean net P&L divided by each trade's planned stop-risk amount.
- Quantity, point value, contract multiplier, lot step, commission and slippage must match the instrument and broker. The defaults are illustrative and are not a broker margin model.

### Out-of-sample and walk-forward evaluation
- **Chronological holdout:** default 70% initial in-sample / 30% out-of-sample split. User parameters remain unchanged on both sides. Earlier bars are available only as indicator warm-up for the holdout; no position is carried into the holdout.
- **Walk-forward:** default 50% initial history and three subsequent, non-overlapping test folds. Each fold uses the preceding history for indicator warm-up, starts flat, and ends by closing any open position at the final test-bar close.
- These are **fixed-parameter validation runs**, not parameter fitting or optimisation. The engine does not choose the best SMA periods or stop/target values from the training data. Do not describe them as an optimised walk-forward strategy.
- Each walk-forward fold starts with the configured initial capital, so fold returns are independent and are not compounded into one continuous portfolio.

### Data requirements and exports
- The Strategy Lab uses the currently selected instrument dataset in **RESEARCH LAB**. Fetch provider history, import broker OHLC CSV data, or construct fixed-tick / TIB bars from raw tick CSV. The source and sampling method are displayed with each result.
- Use intraday OHLC bars where practical. Hourly provider bars can test a slower signal but are not equivalent to five-minute broker bars. Data quality, missing bars, session gaps and the selected timezone can materially change results.
- **EXPORT OOS TRADES CSV** exports the holdout trade log. **EXPORT HTML REPORT** exports parameters, in-sample and holdout metrics, trade log, walk-forward folds and methodology.
- For the standard CME E-mini S&P 500 contract, CME lists a $50 multiplier per index point; Micro E-mini S&P 500 uses $5 per point. The configuration defaults the `ES=F` proxy to point value 50 and quantity step 1, but the actual broker product, contract month and position size must be confirmed. Source: [CME Group E-mini and Micro E-mini contract comparison](https://www.cmegroup.com/markets/equities/sp-500-and-nasdaq-100-futures.html).

### Explicit exclusions
The current engine does not model bid/ask spread separately from slippage, order-book depth, market impact, partial fills, exchange fees by contract schedule, futures roll/expiry, funding, borrow costs, dividends, corporate actions, FX conversion, margin calls, liquidation rules or tax. It is a transparent educational research simulator, not execution-grade portfolio accounting or evidence of future profitability.

## Phase 7.3 — Custom broker instruments

The Research Lab supports two CSV workflows:

- **IMPORT CSV TO SELECTED** replaces the historical dataset for the currently selected built-in or custom instrument.
- **IMPORT AS NEW INSTRUMENT** imports the CSV first, asks for an instrument name (for example, `Spot Gold · Broker A`), and registers it as a separate research dataset. The new instrument appears in the Research Lab selector and the Strategy Lab selector.
- Custom instrument datasets are stored in `research_cache.json`, so they remain selectable after restarting the application. Re-importing the same instrument name updates that custom dataset rather than creating duplicate entries.
- Custom CSV datasets are intentionally not added to live Yahoo Finance market instruments. They are historical broker datasets and do not claim a live provider symbol.
- For strategy testing, custom datasets start with illustrative `point_value=1.0` and `quantity_step=0.01`. Confirm the broker's contract size, point value, quantity step, costs, account currency and margin rules before running or interpreting a backtest. These defaults are not broker specifications.

## Phase 7.2 — Research Lab responsiveness and background processing

The Research Lab previously performed historical session aggregation and statistics synchronously in Tkinter callbacks. On larger broker CSV imports or persisted caches this could delay window repainting and make the application appear frozen. Version 7.2 changes that execution model:

- **Background cache loading:** `research_cache.json` is read and decoded by a dedicated worker after the interface is constructed. Other pages remain available while the Research Lab reports that the cache is loading.
- **Background research calculations:** OHLC records are parsed and Sydney/Tokyo/London/New York session observations and 30/60/90-day statistics are calculated on a worker thread. Results return through a thread-safe queue; only compact table updates happen on Tk's main thread.
- **Revision-based result caching:** navigating back to Research Lab or changing the selected instrument/window reuses the completed calculations. A new fetch, CSV import or provider-data restore invalidates the result and starts a new background calculation. Obsolete calculations are discarded if the dataset changes while they are running.
- **Background cache persistence:** JSON serialization and disk writes are handled by one writer thread. Pending snapshots are coalesced so the newest dataset is saved without accumulating a queue of obsolete full-cache writes.
- **Lighter aggregation:** chronologically ordered bars are no longer sorted repeatedly, and per-session groups retain their chronological order.
- **Export safety:** summary, daily-observation and HTML exports use the latest completed analysis cache. Export buttons remain disabled while data are loading or being analysed, rather than blocking the interface to recalculate synchronously.

During initial loading or after a dataset change, the Research Lab shows a status message such as `LOADING HISTORICAL CACHE IN BACKGROUND` or `ANALYSING ... HISTORICAL BARS IN BACKGROUND`. The export buttons become available after the current dataset's analysis finishes. Very large datasets still consume CPU and memory, but the main Tkinter event loop is no longer responsible for parsing and aggregating all their bars.

## Phase 6 — Historical Research Lab

### Historical data
- The Research Lab can request up to three months of hourly OHLC bars for each configured instrument from the existing Yahoo Finance public chart endpoint (`interval=1h`, `range=3mo`). It retries with a one-month range if the three-month request fails.
- Historical retrieval is user-initiated from **RESEARCH LAB → FETCH 90D HISTORY**; it does not run automatically at startup.
- Provider history is cached separately in `research_cache.json`. Broker CSV imports are kept distinct from provider datasets and are not silently overwritten by a later provider refresh. **RESTORE PROVIDER DATA** switches the selected instrument back to the provider cache.
- Provider history is best-effort and unofficial. A successful HTTP response does not guarantee complete exchange coverage, exact 90-day coverage or licensed real-time prices. Check the displayed coverage dates and bar interval.

### Broker CSV import
- To replace the currently selected instrument, choose it first, set the IANA timezone for timestamps without an offset, then select **IMPORT CSV TO SELECTED**. To add a new broker symbol such as a separately labelled Spot Gold feed, select **IMPORT AS NEW INSTRUMENT**, choose the CSV, and give the dataset a name. The import is then available in both Research Lab and Strategy Lab.
- Required columns: a combined `timestamp` / `datetime` field, or separate `date` and `time` fields, plus `open`, `high`, `low` and `close`. `volume` is optional.
- Common broker/MetaTrader headers are supported, including `<DATE>`, `<TIME>`, `<OPEN>`, `<HIGH>`, `<LOW>`, `<CLOSE>` and `<TICKVOL>`. Comma, semicolon, tab and pipe delimiters are detected.
- ISO timestamps, Unix seconds/milliseconds and common dotted/slash date formats are supported. Naive timestamps are interpreted in the selected timezone and then stored in UTC.
- Invalid OHLC rows are skipped and counted. Duplicate timestamps use the last row in the file. Files are limited to 100 MB and 2,000,000 data rows.
- CSV import is treated as the research dataset for that instrument. Use **RESTORE PROVIDER DATA** to switch back where a provider dataset is cached.
- Import intraday bars for session analysis. Daily-only OHLC files do not contain enough time-of-day detail to assign bars reliably to Sydney, Tokyo, London or New York.

### Research outputs and methodology
- One observation is calculated per instrument, session and local session date using the configured Sydney, Tokyo, London and New York session windows.
- Rolling windows are 30, 60 and 90 **calendar days**, ending at the latest valid observation date for the instrument. Weekends and sessions with no valid bars naturally have no observation.
- **Session realised volatility:** `sqrt(sum(log_return²)) × 100`, including the first sampled bar's open-to-close return followed by adjacent close-to-close returns inside each local session. A close-to-close return is excluded when the time gap is greater than 1.6 times the inferred or configured bar interval (with a 2-minute tolerance); overnight and large missing-data gaps are not bridged.
- **Session range:** `(session_high − session_low) / first_session_open × 100`.
- **Session return:** `(last_session_close / first_session_open − 1) × 100`.
- Distribution statistics include sample count, mean, median, P75, P90, sample standard deviation, min/max, median range, mean/median session return and positive-session win rate.
- **Latest percentile rank** locates the latest valid completed session RV within the selected rolling window. Ties use mid-ranks. It is a descriptive rank, not a forecast.
- An in-progress current local session is visible in the daily-observation table as **PARTIAL** and is excluded from rolling distributions, percentile ranks and win-rate statistics until it has closed.
- Different bar intervals produce different realised-volatility estimates. Do not compare 5-minute broker data with hourly provider data as if their sampling were identical. The selected dataset's interval is shown in the Research Lab and included in reports.
- Missing or insufficient data is reported as `N/A`, never coerced to zero.

### Exports
- **EXPORT SUMMARY CSV:** per-instrument, per-session 30/60/90-day distribution statistics.
- **EXPORT DAILY CSV:** the underlying dated session observations used in the summary.
- **EXPORT HTML REPORT:** a standalone report with summary tables, daily observations and the methodology used.

The exported figures are descriptive research statistics, not trade signals, forecasts or investment advice. Validate source permissions, timestamps, timezone assumptions and bar quality before using results in a backtest.

## Phase 5 — Volatility Lab

### Instruments
- **Spot Gold — `XAUUSD=X`:** Yahoo Finance's spot-gold symbol where intraday/daily bars are available.
- **S&P 500 cash index — `^GSPC`:** cash-index reference. Its meaningful intraday observations are generally confined to the New York cash market; no Tokyo/London/Sydney volatility is fabricated when bars are absent.
- **E-mini S&P 500 futures — `ES=F`:** separate futures proxy for overnight/session-by-session analysis. It is not the same instrument as the cash index; continuous-futures roll behaviour can affect historical comparisons.

Instrument symbols and labels can be changed in `config.json`.

### Measures
- **Session realised volatility:** close-to-close realised volatility from 5-minute bars, calculated as `sqrt(sum(log_return²)) × 100` for each configured session window. Gaps longer than 12.5 minutes are not bridged, avoiding synthetic overnight returns.
- **Session range:** `(session_high − session_low) / first_session_open × 100`.
- **ATR(14):** daily Wilder Average True Range, calculated from daily OHLC bars.
- **One-day expected move:** rolling 20-observation sample standard deviation of daily close-to-close log returns. The display reports the one-standard-deviation absolute move and percentage relative to the latest daily close. It is a statistical estimate, not a forecast or guarantee.
- **Volatility expansion/contraction:** for an active session, current realised volatility so far is compared with the median of prior sessions over the same elapsed portion of the session. By default, at least three prior sessions are required. Default thresholds are 1.50× for expansion and 0.67× for contraction.

### Session interpretation
Session windows use the existing configurable Sydney, Tokyo, London and New York local-time conventions. They are not exchange calendars or instrument-specific trading hours. A cash index may return `N/A` for sessions in which it has no traded bars. `N/A` means unavailable, not zero volatility.

### Data provider and limitations
Phase 5 uses the Yahoo Finance public chart endpoint (`/v8/finance/chart/{symbol}`) with no API key. Its JSON chart response contains Unix timestamps and OHLCV arrays. The endpoint is a public, unofficial integration rather than a licensed data contract or a guaranteed real-time feed. Data availability, delays, symbol coverage and rate limits can change. The app refreshes automatically every five minutes, allows a 60-second minimum between manual attempts, and stores a local snapshot in `market_cache.json` for offline display.

- Source: [Yahoo Finance](https://finance.yahoo.com/)
- Chart endpoint background: [Yahoo Finance chart API example and response structure](https://cors.dev/guides/yahoo-finance-api-cors)
- The application does not claim execution-grade, exchange-direct or guaranteed real-time data.
- Confirm prices and release-sensitive decisions with your broker or a licensed market-data provider.

If the endpoint is unavailable, cached observations remain visible and are labelled stale; volatility-regime alerts are paused until a successful fetch in the current app run. A partially successful fetch retains successful instruments and reports individual asset errors.

## Phase 4 — Economic calendar and Windows notifications

### Live economic calendar
- Public ShowMyTrades calendar feed; no API key is required.
- Covers USD, EUR, GBP, JPY, AUD, NZD, CAD, CHF and CNY.
- Shows high-, medium- and low-impact releases and market holidays.
- Displays scheduled time in the configured home timezone (Nairobi / EAT by default), currency, event name, impact, previous, forecast, actual, schedule status and source-confidence label.
- Search and impact filters for the event list.
- High-impact release reminders with a configurable lead time.
- Last successful response is cached locally in `calendar_cache.json`.
- Automatic refresh has a 15-minute minimum interval after a successful response, matching the provider's documented cache window.
- Network requests use a 25-second timeout and one bounded retry for transient connection failures.
- Failed fetches use a separate retry backoff (30 seconds, 1, 2, 4, 8, then 15 minutes); a timeout no longer imposes the successful-fetch 15-minute cooldown.
- Timeout, DNS-resolution and TLS errors are reported with more actionable status text.
- Tentative and cancelled releases remain visible where supplied but are not used for timed high-impact alerts.

### Calendar connection troubleshooting
If the live calendar reports a timeout, the app keeps the last cached snapshot and marks it offline. On Windows, test the same HTTPS endpoint outside the app in PowerShell:

```powershell
nslookup showmytrades.com
Test-NetConnection showmytrades.com -Port 443
curl.exe -L --max-time 35 -sS "https://showmytrades.com/api/public/calendar/v1?impact=all&days=7&format=json"
```

- If `nslookup` fails, check DNS or the network connection.
- If DNS works but `TcpTestSucceeded` is `False`, check firewall, VPN, proxy, antivirus HTTPS inspection or ISP restrictions on port 443.
- If `curl.exe` returns JSON but the app still times out, check Python-specific proxy/antivirus rules and update to this build's `calendar_engine.py` and `main.py`.
- If both PowerShell and the app time out, the issue is likely on the route between the PC and the provider, or a temporary provider-side delay. Try another trusted network before concluding the provider is down.
- Do not disable TLS verification or switch to plain HTTP to work around a timeout. Calendar release times are trading-critical data and should stay on HTTPS.

**Calendar source:** [ShowMyTrades public economic calendar](https://showmytrades.com/tools/economic-calendar) · [API documentation](https://showmytrades.com/docs/api/economic-calendar).
The calendar is a third-party data feed, not an exchange, central-bank or statistical-agency source. Verify critical release times and values against the relevant official issuer before trading.

### Windows desktop notifications
- Uses `windows-toasts` for Windows 10/11 toast notifications.
- Session opening/closing, overlap and economic-event alerts can appear while the app is running, including when minimized.
- The app has a test-notification control.
- Notification failures are isolated from clock, alarm and calendar logic.

**Important:** the app must remain running for notifications. Minimizing is fine; fully closing stops its schedulers. Windows permissions and Focus Assist / Do Not Disturb can affect delivery.

## Phase 3 — Session alerts
- Configurable pre-open and pre-close warnings (defaults: 15 and 10 minutes).
- Optional exact session-open and session-close alerts.
- Alerts when a second scheduled centre opens and an overlap begins.
- In-app activity feed and configurable system-bell sound.
- Manually scheduled economic-event reminders.

## Trading-session dashboard
- Independent Sydney, Tokyo, London and New York clocks.
- OPEN/CLOSED status and countdown to each session's next transition.
- Automatic timezone and daylight-saving handling using Python `zoneinfo`.
- Active-session overlap indicator and next global transition.
- Nairobi (`Africa/Nairobi`) control time by default.
- Session hours and home timezone are configurable in `config.json`.

Default session conventions:

| Centre | Local schedule | IANA time zone |
|---|---:|---|
| Sydney | 07:00–16:00 | Australia/Sydney |
| Tokyo | 09:00–18:00 | Asia/Tokyo |
| London | 08:00–17:00 | Europe/London |
| New York | 08:00–17:00 | America/New_York |

These are configurable market-session conventions, not universal exchange or broker hours. Public holidays, special closures, broker-specific hours and instrument-specific hours are not modelled.

## Original alarm clock retained
- Seven-segment digital clock display.
- Single alarm with time validation and absolute datetime scheduling.
- Scheduled and snoozed alarms are saved across restarts. Veltrix must be running to ring; an alarm that elapsed while closed is reported as missed and is not replayed.
- Five-minute snooze and dismiss controls.
- Alarm popup that stays on top while ringing.
- Optional `alarm.mp3` playback through `pygame`.
- Repeating Tk system-bell fallback if pygame or the MP3 file is unavailable.
- Six themes: CYAN, AMBER, MATRIX, VIOLET, ICE and LIGHT.
- Resizable desktop window and safe callback/audio shutdown.

## Requirements
- Python 3.10 or newer.
- Tkinter (included with most standard Windows Python installations).
- `tzdata` for IANA timezones on Windows.
- `windows-toasts` is installed on Windows by `requirements.txt` for desktop toast notifications.
- `python-dotenv` loads API credentials from the project-local `.env` file.
- Phase 5 market data uses Python's standard-library `urllib`; no extra data package or API key is required.
- Optional: install pygame for MP3 alarm playback: `python -m pip install pygame==2.6.1`.

Place `alarm.mp3` beside `main.py`. Without pygame or the MP3 file, the system bell is used.

## Run on Windows

Double-click `run.bat`, or open a terminal in the project directory and run:

```bash
python -m pip install -r requirements.txt
python main.py
```

## Tests

Run the automated tests with:

```bash
python -m unittest discover -s tests -v
```

The current regression suite contains 159 automated tests, including the new Phase 12 regime-engine tests. Coverage includes session/DST calculations, alerts, calendar handling, provider/data-gateway parsing, OHLC and tick-bar validation, quality audits, backtesting and walk-forward logic, volatility calculations, causal regime classification, CSV exports, application paths and UI theme behaviour. The Phase 12 GUI smoke test opens Regime Lab, renders synthetic classifications and diagnostics, redraws the regime chart, cycles all six themes, and verifies that stale results clear when the dataset changes. Automated tests do not prove live provider uptime, feed timeliness, native Windows rendering or trading profitability.

## Project structure
- `main.py` — integrated Tkinter interface, clock, alarm and UI scheduling.
- `session_engine.py` — timezone-aware session states and countdowns.
- `alert_engine.py` — deterministic, timezone-aware session alert scheduler.
- `calendar_engine.py` — public economic-calendar client, parsing, local cache and event reminders.
- `market_data.py` — legacy Yahoo chart adapter, OHLCV normalisation and local market-data cache.
- `data_gateway.py` — provider-neutral Massive and Twelve Data historical adapters, `.env` credential loading, UTC normalisation, data-quality audits and exact-timestamp dataset comparisons.
- `volatility_engine.py` — realised volatility, ATR, expected-move and session-volatility calculations.
- `regime_engine.py` — causal OHLC regime classification, transitions, conditional forward-outcome statistics and CSV export.
- `research_engine.py` — broker CSV import, custom instrument registration/selector choices, session observations, 30/60/90-day distributions, percentile ranks and CSV/HTML exports.
- `research_cache.json` — separate cached provider and broker-import datasets (created when the Research Lab is used).
- `desktop_notifications.py` — best-effort Windows toast integration.
- `themes.py` — six colour themes retained from the original alarm clock.
- `ui_theme.py` — cross-platform ttk selection-control and dropdown styling.
- `.env.example` — safe API-key configuration template; copy it to a private `.env` file.
- `.env` — local provider API keys; never share or commit this file.
- `config.json` — sessions, instruments and user preferences.
- `tests/` — automated test suite.
- `run.bat` — Windows launcher.

## Known limitations
- The market-data integration uses an unofficial public Yahoo Finance chart endpoint; it can be delayed, rate-limited or unavailable and has no uptime guarantee. The historical 1h / 3mo request may return less than 90 calendar days for some symbols.
- Spot-gold intraday coverage depends on whether Yahoo supplies bars for `XAUUSD=X` at request time.
- `ES=F` is a continuous futures proxy, not the S&P 500 cash index; contract-roll behaviour can affect comparisons.
- Cash-index data is not available during every global session. Missing session rows are shown as `N/A`.
- Session volatility baselines are based on the provider's five-day intraday window. Three completed comparison sessions are required before expansion/contraction classification; early-week or sparse data may show `NORMAL` / no classification until enough history exists.
- The one-day expected move is a historical one-standard-deviation estimate, not a directional prediction.
- ATR and expected-move estimates use daily bars and require sufficient provider history.
- Public holidays and special closures are not modelled in the session scheduler.
- The economic-calendar feed is third-party; verify high-impact events with official issuers.
- Windows toast notifications work while the application process remains running; closing the app stops notifications.
- The Regime Lab is descriptive research only. A regime label is not a trade signal, and conditional forward-return summaries are not forecasts. No broker order execution or portfolio advice is provided.

## Phase 8 — Multi-Resolution and Information-Driven Bar Engine

Phase 8 keeps the existing time-based OHLC workflow intact and adds a separate raw-tick path. All constructed bars use the application's existing `OHLCBar` schema, so the Research Lab and Strategy Lab can consume them without a second indicator or backtest stack.

### Raw tick import
- **IMPORT RAW TICK CSV** copies the source file into the local `tick_data/` directory, validates it in a worker thread, and registers the source in `research_cache.json`. The original broker export is retained locally so alternate bar constructions can be built later without asking the broker for the same file again.
- The importer supports a combined timestamp or separate Date/Time columns; naive timestamps use the Research Lab timezone selector captured at import time and reused on every rebuild. It preserves duplicate timestamps, sorts out-of-order rows stably, and reports invalid rows. Files are limited to 250 MB and 5,000,000 source rows. A separate 250,000-output-bar safety cap prevents tiny bar settings from exhausting the application cache; increase the tick count per bar or reduce the sample if it is reached.
- If usable Last/Price values are available on at least half of the rows, the importer uses that Last-price stream. Otherwise it uses the Bid/Ask midpoint where both sides exist. The latter is explicitly labelled a **quote-midpoint proxy**, not exchange trade prints or true aggressive buyer/seller flow.
- The tick rule infers direction from price changes. Unchanged prices inherit the last non-zero direction; the first tick's direction is unknown and contributes zero. This is inferred direction, not an exchange-provided aggressor-side flag.
- Broker volume fields are retained as supplied metadata and are not used to classify ticks or form volume bars. In particular, an MT5 `tick_volume` field must not be assumed to represent traded contract volume.

### Bar constructors
- **Fixed Tick Bars:** closes a bar after a configured number of tick observations (default 500). A trailing incomplete bar is excluded by default and its tick count is reported.
- **Tick Imbalance Bars (TIB):** uses the signed tick rule and closes a bar when cumulative signed ticks exceed the expected imbalance threshold. The first configured seed window (default 250 ticks) is retained as a clearly labelled calibration bar. For subsequent bars, expected tick count is an EWMA of completed-bar lengths (span measured in bars), while expected signed imbalance is a separate EWMA updated tick by tick from individual signed tick-rule observations (span measured in ticks). Their spans are independently configurable because they operate on different sampling units. Each new bar's threshold is fixed when it opens and is not recalculated using future ticks.
- The bar-length EWMA span and tick-imbalance EWMA span are separate controls (both default 20, measured in bars and ticks respectively). A configurable minimum expected-imbalance fraction (default 0.05) is a stability floor. It prevents a near-zero directional estimate from collapsing the threshold to zero or one tick. It is an explicit implementation safeguard, so parameter choices must be tested for sensitivity rather than treated as a universal constant.
- The TIB expected threshold follows the information-bar framework described by Marcos López de Prado, *Advances in Financial Machine Learning* (2018), §2.3.2.1. The seed bar and minimum floor are documented engineering choices for stable initialization.
- Output timestamps represent each bar's final tick (bar end). Per-bar tick count, duration, mean observed spread when available, signed imbalance, expected tick count at bar open, expected imbalance fraction, threshold and calibration status are retained in dataset metadata.
- Both constructors create variable-elapsed-time bars. Session research therefore retains adjacent within-session returns instead of applying the fixed-interval missing-bar filter. The displayed median elapsed minutes is descriptive, not a constant interval.

### Strategy Lab interpretation and limitations
- A constructed fixed-tick or TIB dataset appears as a separate instrument in both Research Lab and Strategy Lab. The original time-based OHLC dataset is not replaced.
- The Strategy Lab continues to use the same indicators, next-bar-open execution, ATR risk controls, costs, chronological holdout and walk-forward framework. The source and bar construction are shown in the validation status and HTML export.
- TIBs do not improve profitability by definition. Compare them with time bars using the same underlying tick source, same time span, same trading rules, realistic costs, chronological out-of-sample testing and parameter-sensitivity checks.
- The current backtester is still an OHLC simulator. It does not replay the raw ticks inside a bar, reconstruct order-book state, or know the true sequence when both stop and target fall inside one bar. The conservative stop-first convention still applies. This is not execution-grade tick replay.
- Tick-derived data are only as representative as the broker feed. Spot Gold traded OTC through a broker is a broker-specific quote/trade stream, not a consolidated global gold tape. Validate the price field and feed semantics before interpreting imbalance as informed trading.
- Raw source CSV files live under `tick_data/`; copy this folder when migrating an installation that has imported tick sources. The registry and generated OHLC datasets remain in `research_cache.json`.

### Recommended research sequence
1. Keep the existing broker time bars as the baseline.
2. Construct one fixed-tick dataset and one TIB dataset from the same raw tick source.
3. Check bar counts, median elapsed time, spread statistics, tick counts and coverage by session before strategy tests.
4. Run the same fixed strategy parameters over each dataset, then compare out-of-sample performance, trade frequency, holding time, turnover, costs and drawdown.
5. Use walk-forward and parameter-neighbourhood tests. Do not select the best-looking bar size from the same holdout period used to report performance.

## Phase 8.0 — Implementation notes
- Fixed-tick and TIB construction run on background workers; Tk's main event loop is not responsible for parsing multi-million-row tick files.
- Raw tick files are stored separately from the JSON research cache to avoid embedding large source data inside `research_cache.json`.
- Existing time-based OHLC datasets, custom OHLC imports, research statistics, session clocks, alerts, calendar, themes and alarm remain supported.

## Phase 9.2 — Cross-platform selection-control and header styling

- Selects the ttk `clam` theme when available because native Windows `vista` controls can ignore the configured dark field and Treeview heading colours. The platform default remains as a fallback when `clam` is unavailable.
- Applies the active Veltrix palette to all calendar, research, strategy and Data Center Comboboxes, including readonly, active and disabled states.
- Themes the native Combobox dropdown Listbox with the active entry, selection and highlight colours. Existing explicitly styled event/alert Listboxes retain their own palette.
- Updates on every theme switch, covering all six built-in themes without changing market data, provider settings or research calculations.
- Adds focused unit tests for ttk theme selection, state maps, palette switching and safe option-database fallback.
