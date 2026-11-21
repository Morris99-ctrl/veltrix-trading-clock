# Veltrix Trading Clock v9.6 — Windows Desktop Edition

This package adds Phase 12 Causal Market Regime Research to the v9.5 Windows desktop-builder
application. It creates a standalone, windowed executable, installs it for the
current Windows user, and creates Desktop and Start-menu shortcuts. Once built,
Veltrix launches without opening VS Code and does not require a separate Python
installation to run.

## Important build note

PyInstaller cannot cross-compile a Windows executable from Linux. This package
therefore contains the Windows packaging configuration and one-click builder,
not a prebuilt `.exe`. Run `BUILD_AND_INSTALL.bat` on the target Windows 10/11
PC; it builds the executable locally and installs it automatically. Package
versions and hashes are pinned in the checked-in lock files.

## One-time installation

1. Extract the complete `veltrix_trading_clock_v9_6_regime_lab.zip` to a
   normal folder, for example `Documents\Veltrix Desktop Builder`.
2. Make sure 64-bit Python 3.10 or newer is installed. Python is needed only
   for the one-time build step. VS Code is not required.
3. Double-click `BUILD_AND_INSTALL.bat`. When prompted, enter the full path to
   your existing v9.5 project folder (containing `main.py`) or installed AppData folder (containing `config.json`) so
   your configuration, caches, `.env`, focus database, imported tick files and alarm
   audio can be migrated. Close the old Veltrix instance before copying its
   SQLite focus database. Press Enter only when there is no previous project data to
   migrate.
4. Allow the builder to finish. It creates an
   isolated `.venv-build`, installs hash-verified build/runtime dependencies,
   packages the app with PyInstaller, installs it under `%LOCALAPPDATA%\Programs`, and
   creates a Desktop shortcut plus a Start-menu entry.
5. Launch **Veltrix Trading Clock** from the Desktop or Start menu.

The build needs an internet connection once to retrieve Python packages. It
runs without administrator rights because it installs only for the current
Windows user. Keep the builder folder until the build has completed.

## Where the app and user data live

- Program files: `%LOCALAPPDATA%\Programs\Veltrix Trading Clock`
- Writable application data: `%LOCALAPPDATA%\Veltrix Trading Clock`
- API credentials: `%LOCALAPPDATA%\Veltrix Trading Clock\.env`
- Configuration, `alarm_state.json`, caches and `focus_goals.sqlite3`: the same writable application data folder
- Imported tick files: `%LOCALAPPDATA%\Veltrix Trading Clock\tick_data`

The app-data directory is intentionally separate from the executable. This
means that updating the program does not overwrite your settings, API keys,
research history, calendar/market caches, imported ticks or alarm audio.

Scheduled and snoozed alarms persist in `alarm_state.json` across application
restarts. Veltrix must be open to ring. If an alarm passes while the app is
closed, the next launch reports it as missed rather than ringing late.

## Phase 11 — Focus & Goals Center (v9.5)

The new **FOCUS & GOALS** workspace is a local-first personal productivity area:

- Stopwatch and countdown timers with start, pause, resume and stop controls. Countdown durations range from one second to 24 hours.
- The active timer is persisted in SQLite. A running stopwatch continues counting elapsed wall-clock time while the app is closed; a countdown expires at its stored deadline and is reconciled on the next launch. Paused time is excluded from focus totals.
- Daily focus totals use the configured IANA home timezone. Focus intervals are split at local midnight for daily reporting, including daylight-saving transitions.
- Goals support title, description, category, start date, deadline, status and manual progress. Each selected goal displays a live days/hours/minutes/seconds deadline countdown.
- Milestones can be added, completed, reopened and removed. When a goal has milestones, its displayed progress is calculated from completed milestones; otherwise manual progress is used.
- Recent focus sessions show their mode, label, duration and status.
- Data is stored in `focus_goals.sqlite3` under the writable application-data directory and is not placed in the executable bundle.

Use ISO dates (`YYYY-MM-DD`) for goal dates. The daily focus target defaults to four hours and can be adjusted in the workspace.

## Phase 12 — Causal Market Regime Research (v9.6)

The new **REGIME LAB** uses datasets already loaded into Research Lab. It does not trade. Each completed OHLC bar is classified using current and past data only; forward returns are calculated separately as historical outcome diagnostics. The workspace provides regime frequency, transition counts, price-path visualization, recent-bar diagnostics and CSV export. The new `regime_engine.py` module has no additional third-party runtime dependency.

The first-release thresholds are configurable research defaults, not an optimised strategy. Review feed semantics, interval, sample size and out-of-sample behaviour before interpreting results.

## API keys

The installer copies a `.env` file from the existing project folder you
selected during setup into the application data directory only if the
destination does not already exist.
If no `.env` was migrated, copy `.env.example` to `.env` in:

`%LOCALAPPDATA%\Veltrix Trading Clock`

Then add your keys:

```ini
MASSIVE_API_KEY=your_massive_key
TWELVE_DATA_API_KEY=your_twelve_data_key
```

Never put real API keys in the build scripts, source files, ZIP package, or
screenshots. Existing Windows user environment variables still take priority
over `.env` values.
On Windows, Veltrix protects a plaintext `.env` file with DPAPI for the current
Windows user the first time it loads the file. To rotate keys, delete the
protected `.env`, create a new text `.env`, and restart Veltrix; it will protect
the replacement. Non-Windows source runs leave `.env` as plaintext.

## Upgrading

Run `BUILD_AND_INSTALL.bat` from a newer source package. It replaces only the
installed program files. Existing data in `%LOCALAPPDATA%\Veltrix Trading Clock`
is preserved. The install script also migrates source-folder personal files on
first install, and never overwrites a file already present in the app-data
folder.

## Uninstalling

Close Veltrix, delete the `Veltrix Trading Clock` folder under
`%LOCALAPPDATA%\Programs`, and remove its Desktop/Start-menu shortcuts. Keep
`%LOCALAPPDATA%\Veltrix Trading Clock` if you want to preserve your user data.
Delete that data folder separately only when you deliberately want to remove
settings, caches, imported ticks and the local `.env` file.

## Security and Windows notices

- The app runs as a normal user; it does not need administrator privileges.
- The build does not embed `.env` or API credentials.
- On Windows, API keys in `.env` are encrypted at rest with the current user's
  DPAPI key. This does not protect against malware running as that user, and
  non-Windows source runs keep `.env` as plaintext.
- The executable is not code-signed. Windows SmartScreen or antivirus software
  may show a first-run reputation warning. Verify that the executable came from
  your own local build folder before allowing it.
- No background auto-start is enabled. The Desktop/Start-menu shortcut is the
  explicit launch mechanism; Windows login startup can be added separately if
  requested later.

## Packaging files

- `veltrix_windows.spec` — PyInstaller one-folder build configuration.
- `BUILD_AND_INSTALL.bat` — one-time Windows build and install launcher.
- `installer/Install-Veltrix.ps1` — user-level installation and shortcut setup.
- `assets/veltrix.ico` — multi-resolution Windows application icon.
- `app_paths.py` — separation of bundled resources from writable user data.
