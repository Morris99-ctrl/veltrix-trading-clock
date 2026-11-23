

"""VELTRIX Trading Clock - global trading sessions plus the original alarm clock."""

from __future__ import annotations

import math
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from zoneinfo import ZoneInfo
from typing import Any

from alert_engine import due_session_alerts
from market_data import fetch_market_snapshot, load_market_cache, save_market_cache
from volatility_engine import instrument_summary, session_volatility_report, evaluate_volatility_regimes
from calendar_engine import (
    calendar_is_due,
    calendar_retry_delay_seconds,
    due_calendar_reminders,
    fetch_calendar,
    load_calendar_cache,
    save_calendar_cache,
)
from desktop_notifications import send_desktop_notification
from session_engine import format_countdown, get_session_state, load_session_definitions
from themes import THEMES
from ui_theme import (
    apply_veltrix_classic_widget_palette, apply_veltrix_ttk_palette, prepare_veltrix_ttk_theme,
)
from app_paths import APP_DATA_DIR, initialize_app_data, resource_path
from focus_engine import FocusError, FocusStore, format_duration
from regime_engine import RegimeConfig, analyse_market_regimes, export_regime_analysis_csv
from regime_data import import_ohlc_csv, infer_bar_interval_minutes, load_regime_datasets, save_regime_datasets
from session_clock import session_clock_hand_endpoints
from session_visuals import (
    session_window_progress, session_window_arc_angles, utc_offset_label,
    local_day_phase, timeline_probe_from_x, session_calendar_close_override,
)
from session_timeline import build_session_timeline
from session_intelligence import historical_overlap_report, weekly_session_hours
from session_profiles import PROFILE_NAMES, apply_session_profile as build_profile_sessions, validate_session_schedule
from exchange_calendar import EXCHANGE_CALENDARS, get_exchange_aware_session_state, upcoming_exchange_events
from risk_engine import assess_session_risk, due_session_risk_alerts
from alerts_dashboard import (
    build_alerts_dashboard, refresh_alerts_dashboard,
    apply_alerts_tree_theme, update_recent_alerts, toggle_alert_settings,
)
from session_performance import analyse_session_performance, export_session_performance_csv
from session_performance_ui import (
    build_session_performance_page, refresh_session_performance_dataset_choices,
    render_session_performance_result, apply_session_performance_theme,
)
from alarm_persistence import load_alarm_state, save_alarm_state
from config_store import load_config, save_config

try:
    import pygame
except ImportError:  # Audio remains available through Tk's system bell.
    pygame = None

initialize_app_data()
BASE_DIR = APP_DATA_DIR
CONFIG_PATH = BASE_DIR / "config.json"
CALENDAR_CACHE_PATH = BASE_DIR / "calendar_cache.json"
MARKET_CACHE_PATH = BASE_DIR / "market_cache.json"
REGIME_DATA_PATH = BASE_DIR / "regime_data.json"
LEGACY_RESEARCH_CACHE_PATH = BASE_DIR / "research_cache.json"
ALARM_SOUND_FILE = BASE_DIR / "alarm.mp3"
ALARM_STATE_PATH = BASE_DIR / "alarm_state.json"
SNOOZE_MINUTES = 5
APP_VERSION = "10.9"
UI_QUEUE_POLL_MS = 500
SESSION_CLOCK_FRAME_MS = 50

DIGIT_SEGMENTS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abged",
    "3": "abgcd",
    "4": "fgbc",
    "5": "afgcd",
    "6": "afgecd",
    "7": "abc",
    "8": "abcdefg",
    "9": "abfgcd",
}


class VeltrixTradingClock:
    IDLE = "idle"
    SCHEDULED = "scheduled"
    SNOOZED = "snoozed"
    RINGING = "ringing"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = self._load_config()
        # Drop retired workspace preferences when an existing v9.x config is reused.
        self.config.pop("research", None)
        self.config.pop("backtest", None)
        if isinstance(self.config.get("regime_lab"), dict):
            self.config["regime_lab"].pop("selected_asset", None)
        profile_settings = self.config.get("session_profiles", {})
        if not isinstance(profile_settings, dict):
            profile_settings = {}
        raw_base_sessions = profile_settings.get("base_sessions")
        if not isinstance(raw_base_sessions, list) or not raw_base_sessions:
            raw_base_sessions = self.config["sessions"]
        self.session_profile_base_sessions = [
            dict(item) for item in raw_base_sessions if isinstance(item, dict)
        ]
        raw_custom_schedules = profile_settings.get("custom", {})
        if not isinstance(raw_custom_schedules, dict):
            raw_custom_schedules = {}
        self.custom_session_schedules = {
            str(key): dict(value)
            for key, value in raw_custom_schedules.items()
            if isinstance(value, dict)
        }
        self.active_session_profile = str(
            profile_settings.get("selected", "Current Configuration")
        )
        try:
            applied_schedules = build_profile_sessions(
                self.session_profile_base_sessions,
                self.active_session_profile,
                self.custom_session_schedules,
            )
        except (ValueError, TypeError):
            self.active_session_profile = "Current Configuration"
            applied_schedules = build_profile_sessions(
                self.session_profile_base_sessions, "Current Configuration"
            )
        self.config["sessions"] = applied_schedules
        self.config["session_profiles"] = {
            "selected": self.active_session_profile,
            "base_sessions": [dict(item) for item in self.session_profile_base_sessions],
            "custom": {key: dict(value) for key, value in self.custom_session_schedules.items()},
        }
        self.sessions = load_session_definitions(applied_schedules)
        self.home_zone = ZoneInfo(self.config.get("home_timezone", "Africa/Nairobi"))
        self.refresh_ms = max(1000, min(5000, int(self.config.get("refresh_milliseconds", 1000))))
        self.theme_name = self.config.get("theme", "CYAN")
        if self.theme_name not in THEMES:
            self.theme_name = "CYAN"

        self.root.title(f"VELTRIX | Trading Clock v{APP_VERSION}")
        icon_file = resource_path(Path("assets") / "veltrix.ico")
        if icon_file.is_file():
            try:
                self.root.iconbitmap(default=str(icon_file))
            except tk.TclError:
                # Some non-Windows Tk builds do not support .ico window icons.
                pass
        self.root.geometry("1160x1020")
        self.root.minsize(900, 760)
        self.root.configure(bg=THEMES[self.theme_name]["bg"])
        # Use a ttk theme that honours Veltrix's palette on Windows as well as
        # Linux/macOS. Native Windows "vista" controls can remain white even
        # when fieldbackground and Treeview heading colours are configured.
        self.ttk_style = ttk.Style(self.root)
        self.ttk_theme_name = prepare_veltrix_ttk_theme(self.ttk_style)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Original alarm-clock state and callbacks.
        self.alarm_state = self.IDLE
        self.alarm_datetime: datetime | None = None
        self.ringing_time: datetime | None = None
        self.alarm_restore = load_alarm_state(ALARM_STATE_PATH, self.home_zone)
        self.alarm_state = self.alarm_restore.state
        self.alarm_datetime = self.alarm_restore.alarm_datetime
        self.startup_alarm_warning = self.alarm_restore.warning
        if self.alarm_restore.clear_saved_state:
            try:
                save_alarm_state(ALARM_STATE_PATH, self.IDLE, None)
            except OSError as exc:
                self.startup_alarm_warning = (
                    f"{self.startup_alarm_warning} Could not clear saved state: {exc}"
                )
        self.alarm_window: tk.Toplevel | None = None
        self.clock_job: str | None = None
        self.session_animation_job: str | None = None
        self.alarm_job: str | None = None
        self.bell_job: str | None = None
        self.audio_available = False
        self.status_message = self.startup_alarm_warning or "SYSTEM READY: NO ALARM SET"
        self.status_kind = "warning" if self.startup_alarm_warning else "muted"

        self.hour_var = tk.StringVar(value="07")
        self.minute_var = tk.StringVar(value="00")
        self.period_var = tk.StringVar(value="AM")
        self.theme_var = tk.StringVar(value=self.theme_name)
        self.session_profile_var = tk.StringVar(value=self.active_session_profile)
        self.session_history_period_var = tk.StringVar(value="30")
        exchange_settings = self.config.get("exchange_calendar", {})
        if not isinstance(exchange_settings, dict):
            exchange_settings = {}
        self.exchange_calendar_enabled_var = tk.BooleanVar(
            value=bool(exchange_settings.get("enabled", False))
        )
        self.session_intelligence_cache_key: tuple | None = None
        self.cards: dict[str, dict[str, tk.Widget]] = {}
        self.latest_session_states: list = []
        self.session_probe_utc: datetime | None = None
        self.session_timeline_plot: tuple[float, float, datetime] | None = None
        self.world_dial_signature: tuple | None = None
        self.theme_items: list[tuple[tk.Widget, str, str | None]] = []
        self.clock_canvas_signature: tuple[int, int, str] | None = None

        # Phase 3/4 market-alert, economic-calendar and notification state.
        self.alert_settings = {
            "notify_pre_open": True,
            "notify_open": True,
            "notify_pre_close": True,
            "notify_close": True,
            "notify_overlap": True,
            "sound_enabled": True,
            "desktop_notifications_enabled": True,
            "pre_open_minutes": 15,
            "pre_close_minutes": 10,
            **self.config.get("alerts", {}),
        }
        self.alert_vars: dict[str, tk.BooleanVar] = {}
        self.session_lead_vars: dict[str, dict[str, tk.StringVar]] = {}
        self.session_lead_spins: list[tk.Spinbox] = []
        self.risk_checkbuttons: list[tk.Checkbutton] = []
        raw_risk_settings = self.config.get("session_risk", {})
        if not isinstance(raw_risk_settings, dict):
            raw_risk_settings = {}
        self.session_risk_settings = {
            "enabled": True,
            "notifications_enabled": True,
            "holiday_liquidity_flags": True,
            "opening_window_minutes": 15,
            "closing_window_minutes": 15,
            "pre_open_window_minutes": 15,
            **raw_risk_settings,
        }
        self.risk_alerted_keys: set[str] = set()
        self.alerted_session_keys: set[str] = set()
        self.alerted_event_ids: set[str] = set()
        self.previous_overlap_active: bool | None = None
        self.economic_events: list[dict] = list(self.config.get("economic_events", []))
        self.alert_log_lines: list[str] = []
        self.is_closing = False

        # Phase 11: persistent personal focus timers, goals and milestones.
        self.focus_store = FocusStore(
            APP_DATA_DIR / "focus_goals.sqlite3",
            timezone_name=self.config.get("home_timezone", "Africa/Nairobi"),
        )
        self.focus_mode_var = tk.StringVar(value="Stopwatch")
        self.focus_label_var = tk.StringVar(value="Focused work")
        self.focus_hours_var = tk.StringVar(value="01")
        self.focus_minutes_var = tk.StringVar(value="00")
        self.focus_seconds_var = tk.StringVar(value="00")
        self.focus_daily_target_var = tk.StringVar(
            value=str(self.config.get("focus", {}).get("daily_target_hours", 4))
        )
        self.focus_goal_title_var = tk.StringVar(value="")
        self.focus_goal_category_var = tk.StringVar(value="Personal")
        self.focus_goal_start_var = tk.StringVar(
            value=datetime.now(self.home_zone).date().isoformat()
        )
        self.focus_goal_deadline_var = tk.StringVar(
            value=(datetime.now(self.home_zone).date() + timedelta(days=365)).isoformat()
        )
        self.focus_goal_status_var = tk.StringVar(value="Not started")
        self.focus_goal_progress_var = tk.StringVar(value="0")
        self.focus_selected_goal_id: int | None = None
        self.focus_tick_job: str | None = None
        self.focus_daily_summary_updated_monotonic = 0.0
        self.focus_last_timer_status: str | None = None
        self.focus_last_timer_id: int | None = None
        initial_focus_timer = self.focus_store.get_active_timer()
        if initial_focus_timer:
            self.focus_last_timer_status = str(initial_focus_timer.get("status"))
            self.focus_last_timer_id = int(initial_focus_timer.get("id"))

        self.calendar_settings = {
            "refresh_minutes": 15,
            "lookahead_days": 7,
            "notify_high_impact": True,
            "reminder_minutes": 15,
            **self.config.get("calendar", {}),
        }
        self.calendar_payload = load_calendar_cache(CALENDAR_CACHE_PATH) or {
            "events": [], "attribution": {"text": "Economic calendar by ShowMyTrades",
            "url": "https://showmytrades.com/tools/economic-calendar", "required": False},
            "generated_at": "", "fetched_at": "", "provider": "ShowMyTrades",
        }
        self.calendar_events: list[dict] = list(self.calendar_payload.get("events", []))
        self.calendar_last_updated = str(self.calendar_payload.get("fetched_at", ""))
        self.calendar_last_fetch_monotonic: float | None = None
        self.calendar_retry_count = 0
        self.calendar_retry_after_monotonic: float | None = None
        self.calendar_fetch_in_progress = False
        self.calendar_auto_refresh_job: str | None = None
        self.calendar_startup_fetch_job: str | None = None
        self.calendar_queue_job: str | None = None
        self.calendar_result_queue: queue.Queue[tuple[dict | None, str | None]] = queue.Queue()
        self.calendar_reminder_fired: set[str] = set()

        # Phase 5 market-data and volatility monitor. Cache is displayed as stale
        # until a successful request completes in this application run.
        self.market_settings = {
            "refresh_minutes": 5, "interval": "5m", "intraday_range": "5d",
            "daily_range": "3mo", "atr_period": 14, "expected_move_lookback": 20,
            "baseline_sessions": 3, "regime_alerts_enabled": True,
            "expansion_multiple": 1.5, "contraction_multiple": 0.67,
            **self.config.get("market_data", {}),
        }
        self.market_instruments = list(self.config.get("market_instruments", [
            {"key": "gold_spot", "name": "SPOT GOLD", "symbol": "XAUUSD=X", "unit": "USD/oz",
             "description": "Yahoo Finance spot XAUUSD symbol"},
            {"key": "spx_cash", "name": "S&P 500 CASH", "symbol": "^GSPC", "unit": "pts",
             "description": "Cash index; generally only New York cash-session observations"},
            {"key": "spx_futures", "name": "E-MINI S&P 500", "symbol": "ES=F", "unit": "pts",
             "description": "Continuous futures proxy; session coverage and roll behaviour can vary"},
        ]))
        self.market_snapshot = load_market_cache(MARKET_CACHE_PATH) or {"assets": {}, "fetched_at": ""}
        self.market_is_fresh = False
        self.market_fetch_in_progress = False
        self.market_last_attempt_monotonic: float | None = None
        self.market_auto_refresh_job: str | None = None
        self.market_startup_fetch_job: str | None = None
        self.market_queue_job: str | None = None
        self.market_result_queue: queue.Queue[tuple[dict | None, str | None]] = queue.Queue()
        self.market_regime_alerted: set[str] = set()
        self.market_reports: dict[str, list[dict]] = {}
        self.market_summaries: dict[str, dict] = {}
        self.market_status_message = "WAITING FOR MARKET DATA"

        # Core Edition: standalone local OHLC dataset library for Regime Lab.
        self.regime_datasets: dict[str, dict[str, Any]] = {}
        self.regime_dataset_label_to_key: dict[str, str] = {}
        self.regime_cache_loading = True
        self.regime_cache_load_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.regime_cache_load_job: str | None = None
        self.regime_cache_write_queue: queue.Queue[dict[str, dict[str, Any]] | None] = queue.Queue(maxsize=1)
        self.regime_cache_writer_thread: threading.Thread | None = None
        self.regime_import_result_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.regime_import_queue_job: str | None = None
        self.regime_import_in_progress = False
        self.regime_settings = {
            "lookback": 20, "atr_fast_period": 14, "atr_slow_period": 50,
            "range_er_max": 0.25, "trend_er_min": 0.35,
            "trend_slope_atr_min": 0.20, "shock_atr_ratio": 1.80,
            "shock_true_range_multiple": 2.50, "forward_horizon": 10,
            **self.config.get("regime_lab", {}),
        }
        self.regime_vars = {
            key: tk.StringVar(value=str(self.regime_settings[key]))
            for key in (
                "lookback", "atr_fast_period", "atr_slow_period", "range_er_max",
                "trend_er_min", "trend_slope_atr_min", "shock_atr_ratio",
                "shock_true_range_multiple", "forward_horizon",
            )
        }
        self.regime_asset_var = tk.StringVar(value="")
        self.regime_result: dict[str, Any] | None = None
        self.regime_result_metadata: dict[str, Any] = {}
        self.regime_in_progress = False
        self.regime_result_queue: queue.Queue[tuple[str, dict, dict | None, str | None]] = queue.Queue()
        self.regime_queue_job: str | None = None

        # Historical session-performance research uses the same local OHLC library.
        self.session_performance_result: dict[str, Any] | None = None
        self.session_performance_result_metadata: dict[str, Any] = {}
        self.session_performance_in_progress = False
        self.session_performance_result_queue: queue.Queue[tuple[str, dict, dict | None, str | None]] = queue.Queue()
        self.session_performance_queue_job: str | None = None

        self._initialise_audio()
        self._build_interface()
        self.apply_theme()
        self._render_market_snapshot()
        self.update_clock()
        self.session_animation_job = self.root.after(SESSION_CLOCK_FRAME_MS, self._animate_session_clocks)
        self.check_alarm()
        self.calendar_queue_job = self.root.after(UI_QUEUE_POLL_MS, self._drain_calendar_results)
        self.calendar_startup_fetch_job = self.root.after(700, lambda: self.refresh_live_calendar(silent=True))
        self._schedule_calendar_auto_refresh()
        self.market_queue_job = self.root.after(UI_QUEUE_POLL_MS, self._drain_market_results)
        self.market_startup_fetch_job = self.root.after(1200, lambda: self.refresh_market_data(silent=True))
        self._schedule_market_auto_refresh()
        self.regime_queue_job = self.root.after(UI_QUEUE_POLL_MS, self._drain_regime_results)
        self.regime_cache_load_job = self.root.after(UI_QUEUE_POLL_MS, self._drain_regime_cache_load_results)
        self.regime_import_queue_job = self.root.after(UI_QUEUE_POLL_MS, self._drain_regime_import_results)
        self.session_performance_queue_job = self.root.after(
            UI_QUEUE_POLL_MS, self._drain_session_performance_results
        )
        self.focus_tick_job = self.root.after(1000, self._focus_timer_tick)
        self.regime_cache_writer_thread = threading.Thread(
            target=self._regime_cache_writer_loop, name="VeltrixRegimeCacheWriter", daemon=False
        )
        self.regime_cache_writer_thread.start()
        self._start_regime_cache_load()

    @staticmethod
    def _load_config() -> dict:
        return load_config(CONFIG_PATH)

    def _register_theme(self, widget: tk.Widget, bg_key: str, fg_key: str | None = None) -> tk.Widget:
        self.theme_items.append((widget, bg_key, fg_key))
        return widget

    def _frame(self, parent: tk.Widget, *, bg: str = "bg", **kwargs) -> tk.Frame:
        palette = THEMES[self.theme_name]
        resolved_bg = {"card": "panel", "raised": "dim"}.get(bg, bg)
        frame = tk.Frame(parent, bg=palette[resolved_bg], **kwargs)
        self._register_theme(frame, bg)
        return frame

    def _label(
        self,
        parent: tk.Widget,
        text: str = "",
        *,
        bg: str = "bg",
        fg: str = "text",
        **kwargs,
    ) -> tk.Label:
        palette = THEMES[self.theme_name]
        resolved_bg = {"card": "panel", "raised": "dim"}.get(bg, bg)
        label = tk.Label(parent, text=text, bd=0, bg=palette[resolved_bg], fg=palette[fg], **kwargs)
        self._register_theme(label, bg, fg)
        return label

    def _build_interface(self) -> None:
        self.outer = self._frame(self.root, padx=22, pady=16)
        self.outer.pack(fill="both", expand=True)

        # Header / brand strip.
        header = self._frame(self.outer)
        header.pack(fill="x", pady=(0, 13))
        brand_block = self._frame(header)
        brand_block.pack(side="left", anchor="w")
        self.brand_label = self._label(brand_block, "VELTRIX", fg="bright", font=("Consolas", 23, "bold"))
        self.brand_label.pack(anchor="w")
        self.subtitle_label = self._label(
            brand_block, "CAPITAL  /  GLOBAL TRADING CLOCK", fg="muted", font=("Consolas", 8, "bold")
        )
        self.subtitle_label.pack(anchor="w", pady=(1, 0))

        right_header = self._frame(header)
        right_header.pack(side="right", anchor="e")
        self.live_label = self._label(right_header, "● LIVE MONITOR", fg="success", font=("Consolas", 9, "bold"))
        self.live_label.pack(side="left", padx=(0, 13))
        self.theme_selector = tk.OptionMenu(right_header, self.theme_var, *THEMES.keys(), command=self.set_theme)
        self.theme_selector.configure(font=("Consolas", 9, "bold"), relief="flat", bd=0, padx=7, pady=5, cursor="hand2")
        self.theme_selector.pack(side="left")

        # Main clock display, retaining the original seven-segment visual identity.
        hero = self._frame(self.outer, bg="panel", padx=16, pady=12)
        hero.pack(fill="x", pady=(0, 12))
        hero.grid_columnconfigure(0, weight=3)
        hero.grid_columnconfigure(1, weight=2)
        display_side = self._frame(hero, bg="panel")
        display_side.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.digital_canvas = tk.Canvas(display_side, height=180, highlightthickness=0, bd=0)
        self.digital_canvas.pack(fill="both", expand=True)
        self.digital_canvas.bind("<Configure>", self._on_clock_resize)

        info_side = self._frame(hero, bg="panel")
        info_side.grid(row=0, column=1, sticky="nsew")
        self.local_heading = self._label(info_side, "LOCAL CONTROL CLOCK", bg="panel", fg="muted", font=("Consolas", 9, "bold"))
        self.local_heading.pack(anchor="w", pady=(8, 2))
        self.home_time_label = self._label(info_side, "--:--:--", bg="panel", fg="bright", font=("Consolas", 27, "bold"))
        self.home_time_label.pack(anchor="w")
        self.home_date_label = self._label(info_side, "Loading date...", bg="panel", fg="text", font=("Segoe UI", 9))
        self.home_date_label.pack(anchor="w", pady=(1, 12))
        self.next_alarm_label = self._label(info_side, "◉  NEXT ALARM: NONE", bg="panel", fg="muted", font=("Consolas", 9, "bold"), wraplength=340, justify="left")
        self.next_alarm_label.pack(anchor="w", pady=(3, 0))
        self.audio_label = self._label(info_side, "AUDIO: SYSTEM BELL", bg="panel", fg="muted", font=("Consolas", 8, "bold"))
        self.audio_label.pack(anchor="w", pady=(7, 0))

        # Main workspace navigation. The alarm strip remains visible on both pages.
        nav = self._frame(self.outer)
        nav.pack(fill="x", pady=(0, 9))
        self.sessions_nav_button = tk.Button(
            nav, text="GLOBAL SESSIONS", command=lambda: self.show_page("sessions"),
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=12, pady=7, cursor="hand2",
        )
        self.sessions_nav_button.pack(side="left", padx=(0, 5))
        self.session_performance_nav_button = tk.Button(
            nav, text="SESSION PERFORMANCE", command=lambda: self.show_page("session_performance"),
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=9, pady=7, cursor="hand2",
        )
        self.session_performance_nav_button.pack(side="left", padx=(0, 5))
        self.alerts_nav_button = tk.Button(
            nav, text="ALERTS & EVENTS", command=lambda: self.show_page("alerts"),
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=12, pady=7, cursor="hand2",
        )
        self.alerts_nav_button.pack(side="left", padx=(0, 6))
        self.calendar_nav_button = tk.Button(
            nav, text="ECONOMIC CALENDAR", command=lambda: self.show_page("calendar"),
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=12, pady=7, cursor="hand2",
        )
        self.calendar_nav_button.pack(side="left", padx=(0, 6))
        self.volatility_nav_button = tk.Button(
            nav, text="VOLATILITY LAB", command=lambda: self.show_page("volatility"),
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=12, pady=7, cursor="hand2",
        )
        self.volatility_nav_button.pack(side="left", padx=(0, 6))
        self.regime_nav_button = tk.Button(
            nav, text="REGIME LAB", command=lambda: self.show_page("regime"),
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=10, pady=7, cursor="hand2",
        )
        self.regime_nav_button.pack(side="left", padx=(0, 6))
        self.focus_nav_button = tk.Button(
            nav, text="FOCUS & GOALS", command=lambda: self.show_page("focus"),
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=10, pady=7, cursor="hand2",
        )
        self.focus_nav_button.pack(side="left")

        self.page_host = self._frame(self.outer)
        self.page_host.pack(fill="both", expand=True)
        self.sessions_view = self._frame(self.page_host)
        self.session_performance_view = self._frame(self.page_host)
        self.alerts_view = self._frame(self.page_host)
        self.calendar_view = self._frame(self.page_host)
        self.volatility_view = self._frame(self.page_host)
        self.regime_view = self._frame(self.page_host)
        self.focus_view = self._frame(self.page_host)
        self.sessions_view.pack(fill="both", expand=True)

        # The Global Sessions page is vertically scrollable so the four clocks,
        # 24-hour map and market summary remain usable on shorter displays.
        sessions_scroll_shell = self._frame(self.sessions_view)
        sessions_scroll_shell.pack(fill="both", expand=True)
        self.sessions_canvas = tk.Canvas(
            sessions_scroll_shell, bg=THEMES[self.theme_name]["bg"],
            highlightthickness=0, bd=0,
        )
        self.sessions_scrollbar = ttk.Scrollbar(
            sessions_scroll_shell, orient="vertical", command=self.sessions_canvas.yview,
        )
        self.sessions_canvas.configure(yscrollcommand=self.sessions_scrollbar.set)
        self.sessions_canvas.pack(side="left", fill="both", expand=True)
        self.sessions_scrollbar.pack(side="right", fill="y")
        self.sessions_content = self._frame(self.sessions_canvas)
        self.sessions_content_window = self.sessions_canvas.create_window(
            (0, 0), window=self.sessions_content, anchor="nw",
        )
        self.sessions_content.bind(
            "<Configure>", lambda _event: self.sessions_canvas.configure(
                scrollregion=self.sessions_canvas.bbox("all")
            )
        )
        self.sessions_canvas.bind(
            "<Configure>", lambda event: self.sessions_canvas.itemconfigure(
                self.sessions_content_window, width=event.width
            )
        )
        self.sessions_canvas.bind(
            "<MouseWheel>",
            lambda event: self.sessions_canvas.yview_scroll(int(-event.delta / 120), "units"),
        )
        self.sessions_canvas.bind(
            "<Button-4>", lambda _event: self.sessions_canvas.yview_scroll(-1, "units"),
        )
        self.sessions_canvas.bind(
            "<Button-5>", lambda _event: self.sessions_canvas.yview_scroll(1, "units"),
        )

        # Global session summary.
        summary = self._frame(self.sessions_content)
        summary.pack(fill="x", pady=(0, 10))
        for column in range(3):
            summary.grid_columnconfigure(column, weight=1, uniform="summary")
        self.summary_open = self._summary_tile(summary, 0, "SESSIONS OPEN", "0 / 4")
        self.summary_overlap = self._summary_tile(summary, 1, "ACTIVE OVERLAPS", "NONE")
        self.summary_next = self._summary_tile(summary, 2, "NEXT TRANSITION", "Calculating")

        section = self._frame(self.sessions_content)
        section.pack(fill="x", pady=(4, 8))
        self.section_title = self._label(section, "GLOBAL MARKET SESSIONS", fg="bright", font=("Consolas", 11, "bold"))
        self.section_title.pack(side="left")
        self.section_hint = self._label(section, "SCHEDULED WEEKDAY HOURS · LOCAL CENTRE TIME", fg="muted", font=("Consolas", 8, "bold"))
        self.section_hint.pack(side="right")

        # Four independent session cards.
        self.session_grid = self._frame(self.sessions_content)
        self.session_grid.pack(fill="x")
        for column in range(2):
            self.session_grid.grid_columnconfigure(column, weight=1, uniform="session")
        for row in range(2):
            self.session_grid.grid_rowconfigure(row, weight=1, uniform="session_row")
        for index, session in enumerate(self.sessions):
            row, column = divmod(index, 2)
            self._build_session_card(session, row, column)

        self._build_session_timeline(self.sessions_content)

        self._build_alerts_page()
        self._build_calendar_page()
        self._build_market_page()
        self._build_regime_page()
        build_session_performance_page(self)
        self._build_focus_page()
        self.show_page("sessions")

        # Alarm control strip from the original clock. This stays visible on both pages.
        alarm_panel = self._frame(self.outer, bg="panel", padx=14, pady=10)
        alarm_panel.pack(fill="x", pady=(10, 0))
        alarm_panel.grid_columnconfigure(0, weight=1)
        self.alarm_title = self._label(alarm_panel, "ALARM CONTROL", bg="panel", fg="bright", font=("Consolas", 9, "bold"))
        self.alarm_title.grid(row=0, column=0, sticky="w", pady=(0, 7))
        controls = self._frame(alarm_panel, bg="panel")
        controls.grid(row=1, column=0, sticky="w")
        spin_options = {
            "font": ("Consolas", 11, "bold"), "justify": "center", "relief": "flat", "bd": 0,
            "highlightthickness": 1, "width": 4,
        }
        self.hour_spin = tk.Spinbox(controls, from_=1, to=12, format="%02.0f", textvariable=self.hour_var, **spin_options)
        self.minute_spin = tk.Spinbox(controls, from_=0, to=59, format="%02.0f", textvariable=self.minute_var, **spin_options)
        self.period_spin = tk.Spinbox(controls, values=("AM", "PM"), textvariable=self.period_var,
                                      font=("Consolas", 11, "bold"), justify="center", relief="flat", bd=0,
                                      highlightthickness=1, width=4)
        self.hour_spin.pack(side="left", padx=(0, 5))
        self.minute_spin.pack(side="left", padx=(0, 5))
        self.period_spin.pack(side="left", padx=(0, 12))
        self.set_button = tk.Button(controls, text="SET ALARM", command=self.set_alarm,
                                    font=("Consolas", 9, "bold"), relief="flat", bd=0,
                                    padx=12, pady=7, cursor="hand2")
        self.set_button.pack(side="left", padx=(0, 7))
        self.cancel_button = tk.Button(controls, text="CLEAR", command=self.cancel_alarm,
                                       font=("Consolas", 9, "bold"), relief="flat", bd=0,
                                       padx=12, pady=7, cursor="hand2")
        self.cancel_button.pack(side="left")

        self.status_label = self._label(alarm_panel, self.status_message, bg="panel", fg="muted", font=("Consolas", 8, "bold"))
        self.status_label.grid(row=2, column=0, sticky="w", pady=(9, 0))

        # Market intelligence footer.
        footer = self._frame(self.sessions_content, bg="panel", padx=14, pady=9)
        footer.pack(fill="x", pady=(10, 0))
        self.overlap_label = self._label(footer, "Checking session alignment...", bg="panel", fg="bright", font=("Consolas", 9, "bold"), anchor="w", justify="left")
        self.overlap_label.pack(fill="x")
        self.footer_note = self._label(
            footer,
            "Session hours are configurable conventions. Public holidays, broker hours and instrument-specific hours are not yet modelled.",
            bg="panel", fg="muted", font=("Segoe UI", 8), anchor="w", justify="left", wraplength=1050,
        )
        self.footer_note.pack(fill="x", pady=(4, 0))

    def _build_session_timeline(self, parent: tk.Widget) -> None:
        """Build the UTC 24-hour map and its live overlap/transition summaries."""
        panel = self._frame(parent, bg="panel", padx=14, pady=10)
        panel.pack(fill="x", pady=(2, 10))
        header = self._frame(panel, bg="panel")
        header.pack(fill="x")
        self.timeline_title = self._label(
            header, "24-HOUR GLOBAL SESSION MAP", bg="panel", fg="bright",
            font=("Consolas", 10, "bold"),
        )
        self.timeline_title.pack(side="left")
        self.timeline_utc_label = self._label(
            header, "UTC · MIDNIGHT TO MIDNIGHT", bg="panel", fg="muted",
            font=("Consolas", 8, "bold"),
        )
        self.timeline_utc_label.pack(side="right")

        profile_controls = self._frame(panel, bg="panel")
        profile_controls.pack(fill="x", pady=(8, 2))
        self.session_profile_label = self._label(
            profile_controls, "PROFILE", bg="panel", fg="muted",
            font=("Consolas", 7, "bold"),
        )
        self.session_profile_label.pack(side="left", padx=(0, 6))
        self.session_profile_combo = ttk.Combobox(
            profile_controls, textvariable=self.session_profile_var,
            values=PROFILE_NAMES, state="readonly", width=19, style="TCombobox",
        )
        self.session_profile_combo.pack(side="left", padx=(0, 6))
        self.apply_session_profile_button = tk.Button(
            profile_controls, text="APPLY", command=self._apply_selected_session_profile,
            font=("Consolas", 7, "bold"), relief="flat", bd=0, padx=9, pady=5, cursor="hand2",
        )
        self.apply_session_profile_button.pack(side="left", padx=(0, 5))
        self.edit_custom_session_profile_button = tk.Button(
            profile_controls, text="EDIT CUSTOM", command=self.edit_custom_session_profile,
            font=("Consolas", 7, "bold"), relief="flat", bd=0, padx=9, pady=5, cursor="hand2",
        )
        self.edit_custom_session_profile_button.pack(side="left")

        self.exchange_calendar_toggle = tk.Checkbutton(
            profile_controls,
            text="CASH EXCHANGE HOLIDAYS / EARLY CLOSES",
            variable=self.exchange_calendar_enabled_var,
            command=self._toggle_exchange_calendar,
            font=("Consolas", 7, "bold"),
            relief="flat", bd=0, padx=6, pady=4, cursor="hand2",
            bg=THEMES[self.theme_name]["panel"],
            fg=THEMES[self.theme_name]["text"],
            activebackground=THEMES[self.theme_name]["panel"],
            activeforeground=THEMES[self.theme_name]["bright"],
            selectcolor=THEMES[self.theme_name]["dim"],
        )
        self.exchange_calendar_toggle.pack(side="right")
        self._register_theme(self.exchange_calendar_toggle, "panel", "text")

        visual_row = self._frame(panel, bg="panel")
        visual_row.pack(fill="x", pady=(5, 2))
        world_dial_panel = self._frame(visual_row, bg="panel")
        world_dial_panel.pack(side="left", fill="y", padx=(0, 15))
        self.world_dial_title = self._label(
            world_dial_panel, "WORLD SESSION DIAL", bg="panel", fg="muted",
            font=("Consolas", 7, "bold"),
        )
        self.world_dial_title.pack(anchor="center", pady=(0, 3))
        self.world_dial_canvas = tk.Canvas(
            world_dial_panel, width=260, height=250,
            bg=THEMES[self.theme_name]["panel"], highlightthickness=0, bd=0,
        )
        self.world_dial_canvas.pack()
        timeline_side = self._frame(visual_row, bg="panel")
        timeline_side.pack(side="left", fill="both", expand=True)
        self.timeline_interaction_hint = self._label(
            timeline_side, "CLICK OR DRAG A LANE TO PROBE ANY UTC TIME",
            bg="panel", fg="muted", font=("Consolas", 7, "bold"),
        )
        self.timeline_interaction_hint.pack(anchor="w", pady=(0, 4))
        self.session_timeline_canvas = tk.Canvas(
            timeline_side, height=166, bg=THEMES[self.theme_name]["panel"],
            highlightthickness=0, bd=0, cursor="crosshair",
        )
        self.session_timeline_canvas.pack(fill="x", expand=True, pady=(10, 2))
        self.session_timeline_canvas.bind("<Button-1>", self._probe_session_timeline)
        self.session_timeline_canvas.bind("<B1-Motion>", self._probe_session_timeline)
        self.session_timeline_signature: tuple[int, int, str, str] | None = None
        self.world_dial_signature = None
        self.session_timeline_plot = None

        self.timeline_probe_label = self._label(
            panel, "TIME PROBE · CLICK OR DRAG THE TIMELINE TO INSPECT SESSION ALIGNMENT",
            bg="panel", fg="muted", font=("Consolas", 7, "bold"),
            anchor="w", justify="left", wraplength=1050,
        )
        self.timeline_probe_label.pack(fill="x", pady=(1, 3))

        self.timeline_overlap_label = self._label(
            panel, "OVERLAPS · CALCULATING", bg="panel", fg="success",
            font=("Consolas", 8, "bold"), anchor="w", justify="left", wraplength=1050,
        )
        self.timeline_overlap_label.pack(fill="x", pady=(2, 3))
        self.timeline_upcoming_label = self._label(
            panel, "NEXT TRANSITIONS · CALCULATING", bg="panel", fg="muted",
            font=("Consolas", 8), anchor="w", justify="left", wraplength=1050,
        )
        self.timeline_upcoming_label.pack(fill="x")

        self.exchange_calendar_status_label = self._label(
            panel, "EXCHANGE CALENDAR OFF · GENERIC WEEKDAY SCHEDULES ONLY",
            bg="panel", fg="muted", font=("Consolas", 7, "bold"),
            anchor="w", justify="left", wraplength=1050,
        )
        self.exchange_calendar_status_label.pack(fill="x", pady=(5, 1))
        self.exchange_calendar_events_label = self._label(
            panel, "UPCOMING EXCHANGE EXCEPTIONS · CALENDAR OVERLAY DISABLED",
            bg="panel", fg="warning", font=("Consolas", 7),
            anchor="w", justify="left", wraplength=1050,
        )
        self.exchange_calendar_events_label.pack(fill="x", pady=(1, 2))

        analytics = self._frame(panel, bg="panel")
        analytics.pack(fill="x", pady=(8, 0))
        analytics_header = self._frame(analytics, bg="panel")
        analytics_header.pack(fill="x")
        self.session_analytics_title = self._label(
            analytics_header, "MARKET SESSION INTELLIGENCE", bg="panel", fg="bright",
            font=("Consolas", 9, "bold"),
        )
        self.session_analytics_title.pack(side="left")
        self.session_history_period_combo = ttk.Combobox(
            analytics_header, textvariable=self.session_history_period_var,
            values=("7", "30", "90"), state="readonly", width=5, style="TCombobox",
        )
        self.session_history_period_combo.pack(side="right")
        self.session_history_period_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._refresh_session_intelligence(
                datetime.now(timezone.utc), force=True
            ),
        )
        self.session_history_period_label = self._label(
            analytics_header, "HISTORY DAYS", bg="panel", fg="muted",
            font=("Consolas", 7, "bold"),
        )
        self.session_history_period_label.pack(side="right", padx=(0, 6))
        self.weekly_session_hours_label = self._label(
            analytics, "WEEKLY SCHEDULED HOURS · LOCAL MON–SUN · CALCULATING",
            bg="panel", fg="text", font=("Consolas", 8, "bold"),
            anchor="w", justify="left", wraplength=1050,
        )
        self.weekly_session_hours_label.pack(fill="x", pady=(7, 3))
        self.historical_overlap_label = self._label(
            analytics, "HISTORICAL SCHEDULED OVERLAP · CALCULATING",
            bg="panel", fg="success", font=("Consolas", 8, "bold"),
            anchor="w", justify="left", wraplength=1050,
        )
        self.historical_overlap_label.pack(fill="x", pady=(2, 3))
        self.historical_pair_label = self._label(
            analytics, "OVERLAP BREAKDOWN · CALCULATING",
            bg="panel", fg="muted", font=("Consolas", 8),
            anchor="w", justify="left", wraplength=1050,
        )
        self.historical_pair_label.pack(fill="x")

    def _draw_world_session_dial(self, now_utc: datetime, snapshot) -> None:
        """Render the four UTC session windows as concentric 24-hour tracks."""
        canvas = self.world_dial_canvas
        palette = THEMES[self.theme_name]
        now_utc = now_utc.astimezone(timezone.utc)
        start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        signature = (
            self.theme_name, start_utc.date().isoformat(),
            bool(self.exchange_calendar_enabled_var.get()),
            tuple((s.key, s.opens, s.closes, s.weekdays, s.timezone_name) for s in self.sessions),
        )
        if self.world_dial_signature != signature:
            canvas.delete("all")
            canvas.configure(bg=palette["panel"])
            cx, cy, outer = 130.0, 125.0, 113.0
            canvas.create_oval(
                cx-outer, cy-outer, cx+outer, cy+outer,
                fill=palette["bg"], outline=palette["border"], width=3,
                tags="world-dial-static",
            )
            for hour in range(24):
                angle = math.radians(hour * 15 - 90)
                major = hour % 6 == 0
                inner_tick = 100.0 if major else 103.0
                outer_tick = 107.0
                canvas.create_line(
                    cx+math.cos(angle)*inner_tick, cy+math.sin(angle)*inner_tick,
                    cx+math.cos(angle)*outer_tick, cy+math.sin(angle)*outer_tick,
                    fill=palette["bright"] if major else palette["muted"],
                    width=1.5 if major else 0.7, tags="world-dial-static",
                )
                if major:
                    label_radius = 121.0
                    canvas.create_text(
                        cx+math.cos(angle)*label_radius, cy+math.sin(angle)*label_radius,
                        text=f"{hour:02d}", fill=palette["muted"],
                        font=("Consolas", 7, "bold"), tags="world-dial-static",
                    )
            colours = (palette["success"], palette["bright"], palette["warning"], palette["error"])
            radii = (91.0, 79.0, 67.0, 55.0)
            for index, session in enumerate(self.sessions):
                radius = radii[index % len(radii)]
                colour = colours[index % len(colours)]
                box = (cx-radius, cy-radius, cx+radius, cy+radius)
                canvas.create_oval(*box, outline=palette["dim"], width=4, tags="world-dial-static")
                for window in snapshot.windows:
                    if window.session_key != session.key:
                        continue
                    offset = (window.starts_at - start_utc).total_seconds() / 86400
                    duration = (window.ends_at - window.starts_at).total_seconds() / 86400
                    canvas.create_arc(
                        *box, start=90-offset*360, extent=-duration*360,
                        style=tk.ARC, outline=colour, width=4, tags="world-dial-static",
                    )
            canvas.create_oval(
                cx-39, cy-39, cx+39, cy+39,
                fill=palette["panel"], outline=palette["border"], width=1,
                tags="world-dial-static",
            )
            canvas.create_text(
                cx, cy-15, text="VELTRIX", fill=palette["muted"],
                font=("Consolas", 7, "bold"), tags="world-dial-static",
            )
            canvas.create_text(
                cx, cy+28, text="UTC · 24H", fill=palette["muted"],
                font=("Consolas", 6, "bold"), tags="world-dial-static",
            )
            self.world_dial_signature = signature
        else:
            canvas.delete("world-dial-dynamic")

        cx, cy = 130.0, 125.0
        seconds = now_utc.hour*3600 + now_utc.minute*60 + now_utc.second + now_utc.microsecond/1_000_000
        angle = math.radians(seconds / 86400 * 360 - 90)
        tip_x, tip_y = cx+math.cos(angle)*46, cy+math.sin(angle)*46
        canvas.create_line(
            cx, cy, tip_x, tip_y, fill=palette["bright"], width=2,
            capstyle=tk.ROUND, tags="world-dial-dynamic",
        )
        canvas.create_oval(
            tip_x-3, tip_y-3, tip_x+3, tip_y+3,
            fill=palette["bright"], outline=palette["bright"], tags="world-dial-dynamic",
        )
        canvas.create_text(
            cx, cy+1, text=now_utc.strftime("%H:%M"),
            fill=palette["text"], font=("Consolas", 12, "bold"),
            tags="world-dial-dynamic",
        )
        canvas.create_text(
            cx, cy+16, text=now_utc.strftime("%a %d %b").upper(),
            fill=palette["muted"], font=("Consolas", 5, "bold"),
            tags="world-dial-dynamic",
        )

    def _draw_session_timeline(self, now_utc: datetime, states: list) -> None:
        """Render the UTC session map, world dial and interactive time probe."""
        canvas = self.session_timeline_canvas
        palette = THEMES[self.theme_name]
        start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        end_utc = start_utc + timedelta(hours=24)
        snapshot = build_session_timeline(
            self.sessions, start_utc, hours=24,
            apply_exchange_calendar=self.exchange_calendar_enabled_var.get(),
        )
        self._draw_world_session_dial(now_utc, snapshot)
        if self.session_probe_utc is not None and self.session_probe_utc.date() != start_utc.date():
            self.session_probe_utc = None

        width = max(620, canvas.winfo_width())
        height = 166
        signature = (width, height, self.theme_name, start_utc.date().isoformat())
        left, right = 92.0, float(width - 15)
        self.session_timeline_plot = (left, right, start_utc)
        span = right - left
        top, lane_step, lane_height = 31.0, 23.0, 12.0

        if self.session_timeline_signature != signature:
            canvas.delete("all")
            canvas.configure(bg=palette["panel"])
            for hour in range(0, 25, 3):
                x = left + span * hour / 24
                canvas.create_line(
                    x, top - 7, x, top + lane_step * (len(self.sessions) + 1),
                    fill=palette["dim"], width=1, tags="timeline-static",
                )
                anchor = "center"
                if hour == 0:
                    anchor = "w"
                elif hour == 24:
                    anchor = "e"
                canvas.create_text(
                    x, 10, text=f"{hour:02d}:00", fill=palette["muted"],
                    anchor=anchor, font=("Consolas", 7), tags="timeline-static",
                )
            for index, session in enumerate(self.sessions):
                y = top + index * lane_step
                canvas.create_text(
                    left - 9, y + lane_height / 2, text=session.name,
                    fill=palette["text"], anchor="e", font=("Consolas", 7, "bold"),
                    tags="timeline-static",
                )
                canvas.create_rectangle(
                    left, y, right, y + lane_height,
                    fill=palette["bg"], outline=palette["dim"], width=1,
                    tags="timeline-static",
                )
            overlap_y = top + len(self.sessions) * lane_step + 4
            canvas.create_text(
                left - 9, overlap_y + lane_height / 2, text="OVERLAP",
                fill=palette["bright"], anchor="e", font=("Consolas", 7, "bold"),
                tags="timeline-static",
            )
            canvas.create_rectangle(
                left, overlap_y, right, overlap_y + lane_height,
                fill=palette["bg"], outline=palette["dim"], width=1,
                tags="timeline-static",
            )
            self.session_timeline_signature = signature
        else:
            canvas.delete("timeline-dynamic")

        total_seconds = (end_utc - start_utc).total_seconds()

        def x_at(moment: datetime) -> float:
            seconds = (moment.astimezone(timezone.utc) - start_utc).total_seconds()
            return left + span * seconds / total_seconds

        session_colours = (
            palette["success"], palette["bright"], palette["warning"], palette["error"],
        )
        for index, session in enumerate(self.sessions):
            colour = session_colours[index % len(session_colours)]
            y = top + index * lane_step
            for window in snapshot.windows:
                if window.session_key != session.key:
                    continue
                x1, x2 = x_at(window.starts_at), x_at(window.ends_at)
                canvas.create_rectangle(
                    x1, y + 1, max(x1 + 1, x2), y + lane_height - 1,
                    fill=colour, outline=colour, tags="timeline-dynamic",
                )

        overlap_y = top + len(self.sessions) * lane_step + 4
        for overlap in snapshot.overlaps:
            x1, x2 = x_at(overlap.starts_at), x_at(overlap.ends_at)
            canvas.create_rectangle(
                x1, overlap_y + 1, max(x1 + 1, x2), overlap_y + lane_height - 1,
                fill=palette["error"], outline=palette["error"], tags="timeline-dynamic",
            )

        if start_utc <= now_utc < end_utc:
            marker_x = x_at(now_utc)
            canvas.create_line(
                marker_x, top - 12, marker_x, overlap_y + lane_height + 5,
                fill=palette["bright"], width=2, dash=(4, 2), tags="timeline-dynamic",
            )
            canvas.create_oval(
                marker_x - 3, top - 15, marker_x + 3, top - 9,
                fill=palette["bright"], outline=palette["bright"], tags="timeline-dynamic",
            )

        if self.session_probe_utc is not None and start_utc <= self.session_probe_utc < end_utc:
            probe_x = x_at(self.session_probe_utc)
            canvas.create_line(
                probe_x, top-14, probe_x, overlap_y+lane_height+5,
                fill=palette["warning"], width=2, dash=(2, 2), tags="timeline-dynamic",
            )
            canvas.create_polygon(
                probe_x-4, top-12, probe_x+4, top-12, probe_x, top-6,
                fill=palette["warning"], outline=palette["warning"], tags="timeline-dynamic",
            )

        if snapshot.overlaps:
            overlap_text = "  |  ".join(
                f"{' + '.join(item.session_names)} {item.starts_at.strftime('%H:%M')}–{item.ends_at.strftime('%H:%M')} UTC"
                for item in snapshot.overlaps
            )
            total_overlap = sum(
                (item.ends_at - item.starts_at).total_seconds() for item in snapshot.overlaps
            )
            overlap_hours, remainder = divmod(int(total_overlap), 3600)
            overlap_minutes = remainder // 60
            self.timeline_overlap_label.configure(
                text=f"OVERLAPS TODAY · {overlap_hours}h {overlap_minutes:02d}m TOTAL  |  {overlap_text}",
                fg=palette["success"],
            )
        else:
            self.timeline_overlap_label.configure(
                text="OVERLAPS TODAY · NONE SCHEDULED", fg=palette["muted"],
            )

        upcoming = sorted(states, key=lambda state: state.seconds_to_transition)[:3]
        items = [
            f"{state.definition.name} {state.transition_kind} "
            f"{state.transition_at.strftime('%H:%M')} {state.transition_at.tzname()} "
            f"({format_countdown(state.seconds_to_transition)})"
            for state in upcoming
        ]
        self.timeline_upcoming_label.configure(
            text="NEXT TRANSITIONS · " + ("  |  ".join(items) if items else "NONE"),
            fg=palette["muted"],
        )

    def _probe_session_timeline(self, event) -> None:
        """Inspect configured session state at a clicked UTC minute."""
        if self.session_timeline_plot is None:
            return
        left, right, start_utc = self.session_timeline_plot
        probe = timeline_probe_from_x(event.x, left, right, start_utc)
        self.session_probe_utc = probe
        enabled = bool(self.exchange_calendar_enabled_var.get())
        probe_states = [
            get_exchange_aware_session_state(session, probe, enabled=enabled)
            for session in self.sessions
        ]
        active = [state.definition.name for state in probe_states if state.is_open]
        closed = [state.definition.name for state in probe_states if not state.is_open]
        if len(active) >= 2:
            alignment, colour = "OVERLAP · " + " + ".join(active), THEMES[self.theme_name]["success"]
        elif active:
            alignment, colour = "ACTIVE · " + ", ".join(active), THEMES[self.theme_name]["bright"]
        else:
            alignment, colour = "NO TRACKED SESSION OPEN", THEMES[self.theme_name]["muted"]
        self.timeline_probe_label.configure(
            text=(
                f"TIME PROBE · {probe.strftime('%a %d %b %H:%M')} UTC"
                f"  |  {alignment}  |  CLOSED: {', '.join(closed) if closed else 'NONE'}"
            ),
            fg=colour,
        )
        if self.latest_session_states:
            self._draw_session_timeline(datetime.now(timezone.utc), self.latest_session_states)

    def _toggle_exchange_calendar(self) -> None:
        """Enable or disable official cash-exchange holiday overlays."""
        enabled = bool(self.exchange_calendar_enabled_var.get())
        if enabled and self.active_session_profile not in {"Equities Cash", "Custom"}:
            proceed = messagebox.askyesno(
                "Cash-exchange calendar overlay",
                "You are using a non-equities session profile. Exchange holidays and early closes "
                "will be applied to the currently configured session windows, but this will not "
                "convert those windows into official exchange trading hours. Continue?",
                parent=self.root,
            )
            if not proceed:
                self.exchange_calendar_enabled_var.set(False)
                return
        self.config["exchange_calendar"] = {"enabled": enabled}
        self.session_timeline_signature = None
        self._save_config()
        self._set_alert_banner(
            "OFFICIAL CASH-EXCHANGE HOLIDAY OVERLAY ENABLED"
            if enabled else "EXCHANGE CALENDAR OVERLAY DISABLED",
            "success" if enabled else "muted",
        )
        if self.clock_job is not None:
            try:
                self.root.after_cancel(self.clock_job)
            except tk.TclError:
                pass
            self.clock_job = None
        self.update_clock()

    def _update_exchange_calendar_summary(self, now_utc: datetime, states: list) -> None:
        """Show venue coverage and the next published closure/early-close exceptions."""
        palette = THEMES[self.theme_name]
        if not self.exchange_calendar_enabled_var.get():
            self.exchange_calendar_status_label.configure(
                text="EXCHANGE CALENDAR OFF · GENERIC WEEKDAY SCHEDULES ONLY",
                fg=palette["muted"],
            )
            self.exchange_calendar_events_label.configure(
                text="ENABLE CASH-EXCHANGE OVERLAY TO SHOW PUBLISHED HOLIDAYS AND EARLY CLOSES",
                fg=palette["muted"],
            )
            return

        out_of_range = [
            state.definition.name for state in states
            if state.calendar_status in {"OUT_OF_RANGE", "NO_VENUE_MAPPING"}
        ]
        status = "EXCHANGE CALENDAR ON · ASX / TOKYO STOCK EXCHANGE / LSE / NYSE · BUNDLED DATA THROUGH 2027"
        if out_of_range:
            status += " · OUT OF PUBLISHED RANGE: " + ", ".join(out_of_range)
        self.exchange_calendar_status_label.configure(text=status, fg=palette["success"])

        events = upcoming_exchange_events(now_utc, days_ahead=45)
        parts = []
        for event in events[:5]:
            info = EXCHANGE_CALENDARS[event.exchange_key]
            label = {
                "EARLY_CLOSE": "EARLY CLOSE",
                "CLOSE_PROCESS": "CLOSING PROCESS",
            }.get(event.status, "CLOSED")
            local_date = event.event_date.strftime("%d %b")
            close_note = f" {event.close_time.strftime('%H:%M')} {info.timezone_name}" if event.close_time else ""
            parts.append(f"{info.name} {local_date} {event.title} [{label}{close_note}]")
        self.exchange_calendar_events_label.configure(
            text="UPCOMING EXCHANGE EXCEPTIONS · " + (
                "  |  ".join(parts) if parts else "NONE IN NEXT 45 DAYS"
            ),
            fg=palette["warning"],
        )

    def _apply_selected_session_profile(self) -> None:
        """Apply a preset or saved custom market-hours profile."""
        selected = self.session_profile_var.get().strip()
        try:
            schedules = build_profile_sessions(
                self.session_profile_base_sessions,
                selected,
                self.custom_session_schedules,
            )
            sessions = load_session_definitions(schedules)
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Invalid session profile", str(exc), parent=self.root)
            self.session_profile_var.set(self.active_session_profile)
            return

        self.sessions = sessions
        self.config["sessions"] = schedules
        self.active_session_profile = selected
        refresh_session_performance_dataset_choices(self)
        self.config["session_profiles"] = {
            "selected": selected,
            "base_sessions": [dict(item) for item in self.session_profile_base_sessions],
            "custom": {key: dict(value) for key, value in self.custom_session_schedules.items()},
        }
        self.session_timeline_signature = None
        self.session_intelligence_cache_key = None
        self._refresh_session_intelligence(datetime.now(timezone.utc), force=True)
        self._save_config()
        self._set_alert_banner(
            f"SESSION PROFILE APPLIED · {selected.upper()} · CLOCKS AND TIMELINE UPDATED",
            "success",
        )

    def edit_custom_session_profile(self) -> None:
        """Open a small editor for each session's local open/close times and weekdays."""
        window = tk.Toplevel(self.root)
        window.title("Veltrix · Custom Market Session Profile")
        window.transient(self.root)
        window.geometry("930x455")
        window.minsize(850, 410)
        window.configure(bg=THEMES[self.theme_name]["bg"])

        shell = self._frame(window, padx=16, pady=14)
        shell.pack(fill="both", expand=True)
        self._label(
            shell, "CUSTOM MARKET SESSION PROFILE", fg="bright",
            font=("Consolas", 12, "bold"),
        ).pack(anchor="w")
        self._label(
            shell,
            "Set local open/close times and active weekdays for each market. Times use each market's own timezone.",
            fg="muted", font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(4, 12))

        weekdays = (("Mon", 0), ("Tue", 1), ("Wed", 2), ("Thu", 3),
                    ("Fri", 4), ("Sat", 5), ("Sun", 6))
        grid = self._frame(shell)
        grid.pack(fill="both", expand=True)
        headings = (("MARKET", 0), ("OPEN", 1), ("CLOSE", 2))
        for title, column in headings:
            self._label(
                grid, title, fg="muted", font=("Consolas", 8, "bold"),
            ).grid(row=0, column=column, sticky="w", padx=(0, 8), pady=(0, 8))
        for index, (label, _day) in enumerate(weekdays, start=3):
            self._label(
                grid, label.upper(), fg="muted", font=("Consolas", 7, "bold"),
            ).grid(row=0, column=index, padx=2, pady=(0, 8))

        controls: dict[str, dict[str, Any]] = {}
        for row, session in enumerate(self.sessions, start=1):
            default = {
                "open": session.opens.strftime("%H:%M"),
                "close": session.closes.strftime("%H:%M"),
                "weekdays": list(session.weekdays),
            }
            saved = self.custom_session_schedules.get(session.key, default)
            open_var = tk.StringVar(value=str(saved.get("open", default["open"])))
            close_var = tk.StringVar(value=str(saved.get("close", default["close"])))
            day_vars = {
                day: tk.BooleanVar(value=day in saved.get("weekdays", default["weekdays"]))
                for _label, day in weekdays
            }
            self._label(
                grid, session.name, fg="text", font=("Consolas", 8, "bold"),
            ).grid(row=row, column=0, sticky="w", padx=(0, 9), pady=6)
            ttk.Entry(grid, textvariable=open_var, width=8, justify="center").grid(
                row=row, column=1, padx=(0, 7), pady=6,
            )
            ttk.Entry(grid, textvariable=close_var, width=8, justify="center").grid(
                row=row, column=2, padx=(0, 7), pady=6,
            )
            for column, (_label, day) in enumerate(weekdays, start=3):
                ttk.Checkbutton(grid, variable=day_vars[day]).grid(
                    row=row, column=column, padx=2, pady=6,
                )
            controls[session.key] = {
                "open": open_var, "close": close_var, "weekdays": day_vars,
                "name": session.name,
            }

        footer = self._frame(shell)
        footer.pack(fill="x", pady=(12, 0))

        def save_custom() -> None:
            candidate: dict[str, dict[str, Any]] = {}
            try:
                for key, fields in controls.items():
                    schedule = validate_session_schedule({
                        "open": fields["open"].get(),
                        "close": fields["close"].get(),
                        "weekdays": [
                            day for day, variable in fields["weekdays"].items()
                            if variable.get()
                        ],
                    }, name=fields["name"])
                    candidate[key] = schedule
            except ValueError as exc:
                messagebox.showerror("Invalid custom schedule", str(exc), parent=window)
                return

            self.custom_session_schedules = candidate
            self.session_profile_var.set("Custom")
            window.destroy()
            self._apply_selected_session_profile()

        tk.Button(
            footer, text="SAVE & APPLY CUSTOM PROFILE", command=save_custom,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=13, pady=8,
            bg=THEMES[self.theme_name]["button_active"], fg=THEMES[self.theme_name]["bright"],
            cursor="hand2",
        ).pack(side="right")
        tk.Button(
            footer, text="CANCEL", command=window.destroy,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=13, pady=8,
            bg=THEMES[self.theme_name]["button_bg"], fg=THEMES[self.theme_name]["button_fg"],
            cursor="hand2",
        ).pack(side="right", padx=(0, 7))
        window.grab_set()

    def _refresh_session_intelligence(
        self, now_utc: datetime, *, force: bool = False
    ) -> None:
        """Refresh weekly scheduled hours and reconstructed historical overlap on demand."""
        try:
            period = int(self.session_history_period_var.get())
        except (AttributeError, TypeError, ValueError):
            period = 30
        schedule_signature = tuple(
            (item.key, item.timezone_name, item.opens.isoformat(), item.closes.isoformat(), item.weekdays)
            for item in self.sessions
        )
        exchange_overlay = bool(self.exchange_calendar_enabled_var.get())
        cache_key = (
            now_utc.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            period,
            self.active_session_profile,
            schedule_signature,
            exchange_overlay,
        )
        if not force and cache_key == self.session_intelligence_cache_key:
            return

        weekly = weekly_session_hours(
            self.sessions, now_utc, apply_exchange_calendar=exchange_overlay
        )
        history = historical_overlap_report(
            self.sessions, now_utc, days=period, apply_exchange_calendar=exchange_overlay
        )
        weekly_parts = [
            f"{item.session_name} {item.scheduled_hours:.1f}H/{item.active_days}D"
            for item in weekly
        ]
        weekly_title = "WEEKLY EXCHANGE-ADJUSTED HOURS" if exchange_overlay else "WEEKLY SCHEDULED HOURS"
        self.weekly_session_hours_label.configure(
            text=f"{weekly_title} · LOCAL MON–SUN  |  " + "  ·  ".join(weekly_parts)
        )
        busiest = (
            f"{history.busiest_utc_date} {history.busiest_day_hours:.1f}H"
            if history.busiest_utc_date else "NONE"
        )
        self.historical_overlap_label.configure(
            text=(
                f"PAST {period}D {'EXCHANGE-ADJUSTED' if exchange_overlay else 'SCHEDULED'} OVERLAP · {history.total_overlap_hours:.1f}H TOTAL"
                f"  ·  {history.average_daily_overlap_hours:.2f}H/DAY AVG"
                f"  ·  BUSIEST UTC DAY {busiest}"
            )
        )
        pair_parts = [
            f"{left} + {right} {hours:.1f}H"
            for left, right, hours in history.pair_overlap_hours
        ]
        self.historical_pair_label.configure(
            text="PAIR BREAKDOWN · " + ("  |  ".join(pair_parts) if pair_parts else "NO SCHEDULED OVERLAPS")
        )
        self.session_intelligence_cache_key = cache_key

    def _build_focus_page(self) -> None:
        """Build the personal stopwatch, countdown and long-term goals workspace."""
        palette = THEMES[self.theme_name]
        shell = self._frame(self.focus_view)
        shell.pack(fill="both", expand=True)
        self.focus_canvas = tk.Canvas(shell, bg=palette["bg"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=self.focus_canvas.yview)
        self.focus_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.focus_canvas.pack(side="left", fill="both", expand=True)
        self.focus_content = self._frame(self.focus_canvas)
        self.focus_content_window = self.focus_canvas.create_window((0, 0), window=self.focus_content, anchor="nw")
        self.focus_content.bind(
            "<Configure>", lambda _event: self.focus_canvas.configure(
                scrollregion=self.focus_canvas.bbox("all")
            )
        )
        self.focus_canvas.bind(
            "<Configure>", lambda event: self.focus_canvas.itemconfigure(
                self.focus_content_window, width=event.width
            )
        )

        header = self._frame(self.focus_content, bg="panel", padx=15, pady=12)
        header.pack(fill="x", pady=(0, 10))
        self._label(header, "FOCUS & GOALS CENTER", bg="panel", fg="bright",
                    font=("Consolas", 14, "bold")).pack(anchor="w")
        self._label(
            header,
            "PERSONAL EXECUTION TRACKING  ·  LOCAL-FIRST STORAGE  ·  DEADLINE AWARE",
            bg="panel", fg="muted", font=("Consolas", 8, "bold"),
        ).pack(anchor="w", pady=(3, 0))

        timer_row = self._frame(self.focus_content)
        timer_row.pack(fill="x", pady=(0, 10))
        timer_row.grid_columnconfigure(0, weight=3, uniform="focus_top")
        timer_row.grid_columnconfigure(1, weight=2, uniform="focus_top")

        timer_card = self._frame(timer_row, bg="panel", padx=14, pady=12)
        timer_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._label(timer_card, "FOCUS TIMER", bg="panel", fg="bright",
                    font=("Consolas", 10, "bold")).pack(anchor="w")
        controls = ttk.Frame(timer_card)
        controls.pack(fill="x", pady=(10, 5))
        ttk.Label(controls, text="MODE").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.focus_mode_combo = ttk.Combobox(
            controls, textvariable=self.focus_mode_var, values=("Stopwatch", "Countdown"),
            state="readonly", width=13, style="TCombobox",
        )
        self.focus_mode_combo.grid(row=0, column=1, sticky="w", padx=(0, 12))
        self.focus_mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._focus_mode_changed())
        ttk.Label(controls, text="SESSION LABEL").grid(row=0, column=2, sticky="w", padx=(0, 5))
        self.focus_label_entry = ttk.Entry(controls, textvariable=self.focus_label_var, width=28)
        self.focus_label_entry.grid(row=0, column=3, sticky="ew")
        controls.grid_columnconfigure(3, weight=1)

        duration_row = ttk.Frame(timer_card)
        duration_row.pack(fill="x", pady=(5, 2))
        ttk.Label(duration_row, text="COUNTDOWN DURATION").pack(side="left", padx=(0, 9))
        self.focus_hours_spin = ttk.Spinbox(duration_row, from_=0, to=24, width=3,
                                           textvariable=self.focus_hours_var, format="%02.0f", justify="center")
        self.focus_minutes_spin = ttk.Spinbox(duration_row, from_=0, to=59, width=3,
                                             textvariable=self.focus_minutes_var, format="%02.0f", justify="center")
        self.focus_seconds_spin = ttk.Spinbox(duration_row, from_=0, to=59, width=3,
                                             textvariable=self.focus_seconds_var, format="%02.0f", justify="center")
        self.focus_hours_spin.pack(side="left")
        ttk.Label(duration_row, text=":").pack(side="left", padx=2)
        self.focus_minutes_spin.pack(side="left")
        ttk.Label(duration_row, text=":").pack(side="left", padx=2)
        self.focus_seconds_spin.pack(side="left")
        ttk.Label(duration_row, text="HH : MM : SS", foreground=palette["muted"]).pack(side="left", padx=9)

        self.focus_timer_display = self._label(
            timer_card, "00:00:00", bg="panel", fg="bright",
            font=("Consolas", 39, "bold"), anchor="center",
        )
        self.focus_timer_display.pack(fill="x", pady=(13, 1))
        self.focus_timer_status_label = self._label(
            timer_card, "READY · CHOOSE A MODE AND START", bg="panel", fg="muted",
            font=("Consolas", 8, "bold"), anchor="center",
        )
        self.focus_timer_status_label.pack(fill="x", pady=(0, 11))
        timer_buttons = ttk.Frame(timer_card)
        timer_buttons.pack(fill="x")
        self.focus_start_button = ttk.Button(timer_buttons, text="START", command=self.start_focus_timer)
        self.focus_pause_button = ttk.Button(timer_buttons, text="PAUSE", command=self.pause_focus_timer)
        self.focus_resume_button = ttk.Button(timer_buttons, text="RESUME", command=self.resume_focus_timer)
        self.focus_stop_button = ttk.Button(timer_buttons, text="STOP & SAVE", command=self.stop_focus_timer)
        for button in (self.focus_start_button, self.focus_pause_button,
                       self.focus_resume_button, self.focus_stop_button):
            button.pack(side="left", padx=(0, 6))

        daily_card = self._frame(timer_row, bg="panel", padx=14, pady=12)
        daily_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._label(daily_card, "TODAY'S FOCUS", bg="panel", fg="bright",
                    font=("Consolas", 10, "bold")).pack(anchor="w")
        self.focus_daily_total_label = self._label(
            daily_card, "00:00:00", bg="panel", fg="bright", font=("Consolas", 29, "bold")
        )
        self.focus_daily_total_label.pack(anchor="w", pady=(12, 1))
        target_row = ttk.Frame(daily_card)
        target_row.pack(fill="x", pady=(4, 5))
        ttk.Label(target_row, text="DAILY TARGET (HOURS)").pack(side="left")
        self.focus_daily_target_spin = ttk.Spinbox(
            target_row, from_=0.5, to=24, increment=0.5, width=5,
            textvariable=self.focus_daily_target_var, command=self._refresh_focus_daily_summary,
        )
        self.focus_daily_target_spin.pack(side="right")
        self.focus_daily_progress = ttk.Progressbar(daily_card, mode="determinate", maximum=4, value=0)
        self.focus_daily_progress.pack(fill="x", pady=(5, 4))
        self.focus_daily_progress_label = self._label(
            daily_card, "0% OF DAILY TARGET", bg="panel", fg="muted", font=("Consolas", 8, "bold")
        )
        self.focus_daily_progress_label.pack(anchor="w")
        self._label(
            daily_card, "Timer intervals are recorded locally.\nA running timer continues across app restarts.",
            bg="panel", fg="muted", font=("Segoe UI", 8), justify="left", wraplength=300,
        ).pack(anchor="w", pady=(14, 0))

        history_card = self._frame(self.focus_content, bg="panel", padx=14, pady=11)
        history_card.pack(fill="x", pady=(0, 10))
        history_header = self._frame(history_card, bg="panel")
        history_header.pack(fill="x", pady=(0, 7))
        self._label(history_header, "RECENT FOCUS SESSIONS", bg="panel", fg="bright",
                    font=("Consolas", 9, "bold")).pack(side="left")
        ttk.Button(history_header, text="REFRESH", command=self._refresh_focus_history).pack(side="right")
        self.focus_history_tree = ttk.Treeview(
            history_card, columns=("started", "mode", "label", "duration", "status"),
            show="headings", height=4, style="Veltrix.Treeview",
        )
        for col, heading, width in (
            ("started", "STARTED", 145), ("mode", "MODE", 95), ("label", "SESSION", 260),
            ("duration", "FOCUS TIME", 105), ("status", "STATUS", 100),
        ):
            self.focus_history_tree.heading(col, text=heading)
            self.focus_history_tree.column(col, width=width, anchor="w" if col == "label" else "center")
        self.focus_history_tree.pack(fill="x")

        goals_header = self._frame(self.focus_content, bg="panel", padx=14, pady=10)
        goals_header.pack(fill="x", pady=(0, 9))
        self._label(goals_header, "LONG-TERM GOALS", bg="panel", fg="bright",
                    font=("Consolas", 11, "bold")).pack(anchor="w")
        self._label(
            goals_header,
            "Set a deadline, break the outcome into milestones, and track the days remaining.",
            bg="panel", fg="muted", font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(3, 0))
        self.focus_goal_countdown_label = self._label(
            goals_header, "SELECT A GOAL TO VIEW ITS LIVE DEADLINE COUNTDOWN",
            bg="panel", fg="bright", font=("Consolas", 10, "bold"),
        )
        self.focus_goal_countdown_label.pack(anchor="w", pady=(8, 0))

        goals_card = self._frame(self.focus_content, bg="panel", padx=14, pady=11)
        goals_card.pack(fill="x", pady=(0, 10))
        self.focus_goal_tree = ttk.Treeview(
            goals_card, columns=("title", "category", "deadline", "remaining", "progress", "status"),
            show="headings", height=5, style="Veltrix.Treeview",
        )
        for col, heading, width in (
            ("title", "GOAL", 260), ("category", "CATEGORY", 105), ("deadline", "DEADLINE", 105),
            ("remaining", "TIME LEFT", 105), ("progress", "PROGRESS", 85), ("status", "STATUS", 105),
        ):
            self.focus_goal_tree.heading(col, text=heading)
            self.focus_goal_tree.column(col, width=width, anchor="w" if col == "title" else "center")
        self.focus_goal_tree.pack(fill="x")
        self.focus_goal_tree.bind("<<TreeviewSelect>>", self._focus_goal_selected)

        editor = self._frame(self.focus_content, bg="panel", padx=14, pady=12)
        editor.pack(fill="x", pady=(0, 10))
        self.focus_goal_editor_heading = self._label(
            editor, "CREATE GOAL", bg="panel", fg="bright", font=("Consolas", 9, "bold")
        )
        self.focus_goal_editor_heading.pack(anchor="w", pady=(0, 8))
        form = ttk.Frame(editor)
        form.pack(fill="x")
        ttk.Label(form, text="GOAL TITLE").grid(row=0, column=0, sticky="w", padx=(0, 5), pady=3)
        self.focus_goal_title_entry = ttk.Entry(form, textvariable=self.focus_goal_title_var, width=35)
        self.focus_goal_title_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=3)
        ttk.Label(form, text="CATEGORY").grid(row=0, column=2, sticky="w", padx=(0, 5), pady=3)
        self.focus_goal_category_combo = ttk.Combobox(
            form, textvariable=self.focus_goal_category_var,
            values=("Personal", "Education", "Career", "Finance", "Business", "Health", "Other"),
            state="readonly", width=15, style="TCombobox",
        )
        self.focus_goal_category_combo.grid(row=0, column=3, sticky="w", pady=3)
        ttk.Label(form, text="START DATE (YYYY-MM-DD)").grid(row=1, column=0, sticky="w", padx=(0, 5), pady=3)
        ttk.Entry(form, textvariable=self.focus_goal_start_var, width=18).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(form, text="DEADLINE (YYYY-MM-DD)").grid(row=1, column=2, sticky="w", padx=(0, 5), pady=3)
        ttk.Entry(form, textvariable=self.focus_goal_deadline_var, width=18).grid(row=1, column=3, sticky="w", pady=3)
        ttk.Label(form, text="STATUS").grid(row=2, column=0, sticky="w", padx=(0, 5), pady=3)
        self.focus_goal_status_combo = ttk.Combobox(
            form, textvariable=self.focus_goal_status_var,
            values=("Not started", "In progress", "Completed", "Archived"),
            state="readonly", width=16, style="TCombobox",
        )
        self.focus_goal_status_combo.grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(form, text="MANUAL PROGRESS (%)").grid(row=2, column=2, sticky="w", padx=(0, 5), pady=3)
        ttk.Spinbox(form, from_=0, to=100, increment=5, textvariable=self.focus_goal_progress_var,
                    width=8).grid(row=2, column=3, sticky="w", pady=3)
        form.grid_columnconfigure(1, weight=1)
        ttk.Label(editor, text="DESCRIPTION / SUCCESS CRITERIA").pack(anchor="w", pady=(7, 3))
        self.focus_goal_description = tk.Text(
            editor, height=3, wrap="word", relief="flat", bd=0,
            highlightthickness=1, padx=8, pady=6,
        )
        self.focus_goal_description.pack(fill="x", pady=(0, 8))
        goal_actions = ttk.Frame(editor)
        goal_actions.pack(fill="x")
        ttk.Button(goal_actions, text="NEW GOAL", command=self._new_focus_goal).pack(side="left", padx=(0, 6))
        ttk.Button(goal_actions, text="SAVE GOAL", command=self._save_focus_goal).pack(side="left", padx=(0, 6))
        ttk.Button(goal_actions, text="DELETE GOAL", command=self._delete_focus_goal).pack(side="left")
        self.focus_goal_status_label = self._label(
            editor, "Goals are stored locally on this computer.", bg="panel", fg="muted",
            font=("Consolas", 8),
        )
        self.focus_goal_status_label.pack(anchor="w", pady=(7, 0))

        milestone_card = self._frame(self.focus_content, bg="panel", padx=14, pady=11)
        milestone_card.pack(fill="x", pady=(0, 12))
        milestone_header = self._frame(milestone_card, bg="panel")
        milestone_header.pack(fill="x", pady=(0, 7))
        self._label(milestone_header, "GOAL MILESTONES", bg="panel", fg="bright",
                    font=("Consolas", 9, "bold")).pack(side="left")
        self.focus_milestone_tree = ttk.Treeview(
            milestone_card, columns=("milestone", "status"), show="headings", height=4,
            style="Veltrix.Treeview",
        )
        self.focus_milestone_tree.heading("milestone", text="MILESTONE")
        self.focus_milestone_tree.heading("status", text="STATUS")
        self.focus_milestone_tree.column("milestone", width=500, anchor="w")
        self.focus_milestone_tree.column("status", width=110, anchor="center")
        self.focus_milestone_tree.pack(fill="x")
        milestone_actions = ttk.Frame(milestone_card)
        milestone_actions.pack(fill="x", pady=(7, 0))
        ttk.Button(milestone_actions, text="ADD MILESTONE", command=self._add_focus_milestone).pack(side="left", padx=(0, 6))
        ttk.Button(milestone_actions, text="TOGGLE COMPLETE", command=self._toggle_focus_milestone).pack(side="left", padx=(0, 6))
        ttk.Button(milestone_actions, text="REMOVE", command=self._delete_focus_milestone).pack(side="left")
        self._focus_mode_changed()
        self._refresh_focus_workspace()

    def _focus_mode_changed(self) -> None:
        countdown = self.focus_mode_var.get().strip().lower() == "countdown"
        state = "normal" if countdown else "disabled"
        for widget in (self.focus_hours_spin, self.focus_minutes_spin, self.focus_seconds_spin):
            widget.configure(state=state)

    def _focus_duration_input(self) -> int:
        try:
            hours = int(self.focus_hours_var.get())
            minutes = int(self.focus_minutes_var.get())
            seconds = int(self.focus_seconds_var.get())
        except ValueError as exc:
            raise FocusError("Enter the countdown as hours, minutes and seconds.") from exc
        if not (0 <= hours <= 24 and 0 <= minutes <= 59 and 0 <= seconds <= 59):
            raise FocusError("Countdown fields are outside their valid ranges.")
        duration = hours * 3600 + minutes * 60 + seconds
        if not 1 <= duration <= 24 * 3600:
            raise FocusError("Countdown must be between one second and 24 hours.")
        return duration

    def start_focus_timer(self) -> None:
        try:
            mode = "countdown" if self.focus_mode_var.get().strip().lower() == "countdown" else "stopwatch"
            duration = self._focus_duration_input() if mode == "countdown" else None
            self.focus_store.start_timer(mode, label=self.focus_label_var.get(), duration_seconds=duration)
            self.focus_last_timer_status = "running"
            snapshot = self.focus_store.get_active_timer()
            self.focus_last_timer_id = int(snapshot["id"]) if snapshot else None
            self._refresh_focus_history()
            self._update_focus_timer_display()
        except (FocusError, ValueError) as exc:
            messagebox.showwarning("Veltrix Focus Timer", str(exc), parent=self.root)

    def pause_focus_timer(self) -> None:
        try:
            self.focus_store.pause_timer()
            self._update_focus_timer_display()
            self._refresh_focus_history()
        except FocusError as exc:
            messagebox.showwarning("Veltrix Focus Timer", str(exc), parent=self.root)

    def resume_focus_timer(self) -> None:
        try:
            self.focus_store.resume_timer()
            self._update_focus_timer_display()
            self._refresh_focus_history()
        except FocusError as exc:
            messagebox.showwarning("Veltrix Focus Timer", str(exc), parent=self.root)

    def stop_focus_timer(self) -> None:
        snapshot = self.focus_store.stop_timer()
        if snapshot:
            self.focus_last_timer_status = str(snapshot.get("status"))
            self._update_focus_timer_display()
            self._refresh_focus_history()
            self._refresh_focus_daily_summary()

    def _update_focus_timer_display(self) -> None:
        snapshot = self.focus_store.get_active_timer()
        if not snapshot:
            self.focus_timer_display.configure(text="00:00:00")
            self.focus_timer_status_label.configure(text="READY · CHOOSE A MODE AND START", fg=THEMES[self.theme_name]["muted"])
            self.focus_start_button.configure(state="normal")
            self.focus_pause_button.configure(state="disabled")
            self.focus_resume_button.configure(state="disabled")
            self.focus_stop_button.configure(state="disabled")
            self.focus_last_timer_status = None
            return
        status = str(snapshot["status"])
        session_id = int(snapshot["id"])
        if status == "completed" and self.focus_last_timer_status == "running" and self.focus_last_timer_id == session_id:
            try:
                send_desktop_notification("Focus session complete", snapshot["label"], enabled=True)
            except Exception:
                pass
            try:
                self.root.bell()
            except tk.TclError:
                pass
        if self.focus_last_timer_id != session_id:
            self.focus_last_timer_id = session_id
        self.focus_last_timer_status = status
        display_seconds = int(snapshot.get("display_seconds") or 0)
        self.focus_timer_display.configure(text=format_duration(display_seconds))
        mode_name = "STOPWATCH" if snapshot["mode"] == "stopwatch" else "COUNTDOWN"
        status_text = {
            "running": f"{mode_name} RUNNING · {snapshot['label']}",
            "paused": f"{mode_name} PAUSED · {snapshot['label']}",
            "completed": f"COUNTDOWN COMPLETE · {snapshot['label']}",
            "stopped": f"SESSION STOPPED · {snapshot['label']}",
        }.get(status, status.upper())
        self.focus_timer_status_label.configure(text=status_text)
        live = status in {"running", "paused"}
        self.focus_start_button.configure(state="disabled" if live else "normal")
        self.focus_pause_button.configure(state="normal" if status == "running" else "disabled")
        self.focus_resume_button.configure(state="normal" if status == "paused" else "disabled")
        self.focus_stop_button.configure(state="normal" if live else "disabled")

    def _focus_timer_tick(self) -> None:
        if self.is_closing:
            return
        try:
            self._update_focus_timer_display()
            if self.current_page == "focus":
                if time.monotonic() - self.focus_daily_summary_updated_monotonic >= 60:
                    self._refresh_focus_daily_summary()
                self._update_selected_goal_countdown()
        except (tk.TclError, FocusError):
            pass
        self.focus_tick_job = self.root.after(1000, self._focus_timer_tick)

    def _update_selected_goal_countdown(self) -> None:
        if not hasattr(self, "focus_goal_countdown_label"):
            return
        if self.focus_selected_goal_id is None:
            self.focus_goal_countdown_label.configure(text="SELECT A GOAL TO VIEW ITS LIVE DEADLINE COUNTDOWN")
            return
        goal = self.focus_store.get_goal(self.focus_selected_goal_id)
        if not goal:
            self.focus_goal_countdown_label.configure(text="GOAL NO LONGER EXISTS")
            return
        if goal["status"] == "completed":
            self.focus_goal_countdown_label.configure(text=f"COMPLETED · {goal['title']}")
            return
        if goal["status"] == "archived":
            self.focus_goal_countdown_label.configure(text=f"ARCHIVED · {goal['title']}")
            return
        due_date = date.fromisoformat(goal["deadline_date"])
        deadline_exclusive = datetime.combine(due_date + timedelta(days=1), datetime.min.time(), tzinfo=self.home_zone)
        now_timestamp = time.time()
        deadline_timestamp = deadline_exclusive.timestamp()
        if deadline_timestamp <= now_timestamp:
            elapsed = int(now_timestamp - deadline_timestamp)
            days, remainder = divmod(elapsed, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            countdown_text = f"OVERDUE BY {days}D {hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            remaining = int(deadline_timestamp - now_timestamp)
            days, remainder = divmod(remaining, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            countdown_text = f"{days}D {hours:02d}:{minutes:02d}:{seconds:02d} LEFT"
        self.focus_goal_countdown_label.configure(text=f"DEADLINE · {countdown_text} · {goal['title']}")

    def _refresh_focus_daily_summary(self) -> None:
        seconds = self.focus_store.get_daily_focus_seconds()
        self.focus_daily_summary_updated_monotonic = time.monotonic()
        self.focus_daily_total_label.configure(text=format_duration(seconds))
        try:
            target_hours = max(0.5, min(24.0, float(self.focus_daily_target_var.get())))
        except ValueError:
            target_hours = 4.0
        target_seconds = int(target_hours * 3600)
        self.focus_daily_progress.configure(maximum=target_seconds, value=min(seconds, target_seconds))
        percent = min(100, round(seconds * 100 / target_seconds))
        remaining = max(0, target_seconds - seconds)
        self.focus_daily_progress_label.configure(
            text=f"{percent}% OF DAILY TARGET · {format_duration(remaining)} REMAINING"
        )

    def _refresh_focus_history(self) -> None:
        if not hasattr(self, "focus_history_tree"):
            return
        for item in self.focus_history_tree.get_children(""):
            self.focus_history_tree.delete(item)
        for session in self.focus_store.get_recent_sessions(12):
            started = datetime.fromtimestamp(float(session["created_at"]), timezone.utc).astimezone(self.home_zone)
            mode = "Stopwatch" if session["mode"] == "stopwatch" else "Countdown"
            self.focus_history_tree.insert(
                "", "end", iid=str(session["id"]),
                values=(started.strftime("%Y-%m-%d %H:%M"), mode, session["label"],
                        format_duration(session["duration_seconds"]), str(session["status"]).upper()),
            )

    def _refresh_focus_workspace(self) -> None:
        self._refresh_focus_goals()
        self._refresh_focus_milestones()
        self._refresh_focus_history()
        self._refresh_focus_daily_summary()
        self._update_focus_timer_display()
        self._update_selected_goal_countdown()

    def _refresh_focus_goals(self) -> None:
        if not hasattr(self, "focus_goal_tree"):
            return
        selected = self.focus_selected_goal_id
        for item in self.focus_goal_tree.get_children(""):
            self.focus_goal_tree.delete(item)
        palette = THEMES[self.theme_name]
        self.focus_goal_tree.tag_configure("overdue", foreground=palette["error"])
        self.focus_goal_tree.tag_configure("completed", foreground=palette["success"])
        for goal in self.focus_store.list_goals():
            days = int(goal["days_remaining"])
            if goal["status"] == "completed":
                time_left = "COMPLETED"
                tags = ("completed",)
            elif goal["status"] == "archived":
                time_left = "ARCHIVED"
                tags = ()
            elif goal["overdue"]:
                time_left = f"{abs(days)}D OVERDUE"
                tags = ("overdue",)
            elif days == 0:
                time_left = "DUE TODAY"
                tags = ("overdue",)
            else:
                time_left = f"{days} DAYS"
                tags = ()
            item_id = str(goal["id"])
            self.focus_goal_tree.insert(
                "", "end", iid=item_id,
                values=(goal["title"], goal["category"], goal["deadline_date"],
                        time_left, f"{goal['progress']}%", str(goal["status"]).replace("_", " ").upper()),
                tags=tags,
            )
            if selected == int(goal["id"]):
                self.focus_goal_tree.selection_set(item_id)
                self.focus_goal_tree.focus(item_id)
        if selected is not None and self.focus_goal_tree.exists(str(selected)):
            self._refresh_focus_milestones()

    def _refresh_focus_milestones(self) -> None:
        if not hasattr(self, "focus_milestone_tree"):
            return
        for item in self.focus_milestone_tree.get_children(""):
            self.focus_milestone_tree.delete(item)
        if self.focus_selected_goal_id is None:
            return
        for milestone in self.focus_store.list_milestones(self.focus_selected_goal_id):
            self.focus_milestone_tree.insert(
                "", "end", iid=str(milestone["id"]),
                values=(milestone["title"], "COMPLETED" if milestone["completed"] else "PENDING"),
            )

    def _focus_goal_selected(self, _event=None) -> None:
        selection = self.focus_goal_tree.selection()
        if not selection:
            return
        try:
            goal_id = int(selection[0])
        except ValueError:
            return
        goal = self.focus_store.get_goal(goal_id)
        if not goal:
            return
        self.focus_selected_goal_id = goal_id
        self.focus_goal_title_var.set(goal["title"])
        self.focus_goal_category_var.set(goal["category"])
        self.focus_goal_start_var.set(goal["start_date"])
        self.focus_goal_deadline_var.set(goal["deadline_date"])
        self.focus_goal_status_var.set(str(goal["status"]).replace("_", " ").title())
        self.focus_goal_progress_var.set(str(round(float(goal["manual_progress"]))))
        self.focus_goal_description.delete("1.0", "end")
        self.focus_goal_description.insert("1.0", goal["description"])
        self.focus_goal_editor_heading.configure(text=f"EDIT GOAL · {goal['title'][:48]}")
        self.focus_goal_status_label.configure(text="Milestones determine progress when at least one milestone exists.")
        self._refresh_focus_milestones()

    def _new_focus_goal(self) -> None:
        self.focus_selected_goal_id = None
        self.focus_goal_title_var.set("")
        self.focus_goal_category_var.set("Personal")
        today = datetime.now(self.home_zone).date()
        self.focus_goal_start_var.set(today.isoformat())
        self.focus_goal_deadline_var.set((today + timedelta(days=365)).isoformat())
        self.focus_goal_status_var.set("Not started")
        self.focus_goal_progress_var.set("0")
        self.focus_goal_description.delete("1.0", "end")
        self.focus_goal_editor_heading.configure(text="CREATE GOAL")
        self.focus_goal_status_label.configure(text="Goals are stored locally on this computer.")
        milestone_items = self.focus_milestone_tree.get_children("")
        if milestone_items:
            self.focus_milestone_tree.delete(*milestone_items)
        selected_items = self.focus_goal_tree.selection()
        if selected_items:
            self.focus_goal_tree.selection_remove(*selected_items)
        self._update_selected_goal_countdown()
        self.focus_goal_title_entry.focus_set()

    def _save_focus_goal(self) -> None:
        status = self.focus_goal_status_var.get().strip().lower().replace(" ", "_")
        try:
            progress = float(self.focus_goal_progress_var.get())
            fields = {
                "title": self.focus_goal_title_var.get(),
                "description": self.focus_goal_description.get("1.0", "end-1c"),
                "category": self.focus_goal_category_var.get(),
                "start_date": self.focus_goal_start_var.get().strip(),
                "deadline_date": self.focus_goal_deadline_var.get().strip(),
                "status": status,
                "progress": progress,
            }
            if self.focus_selected_goal_id is None:
                goal_id = self.focus_store.create_goal(
                    fields.pop("title"), description=fields.pop("description"),
                    category=fields.pop("category"), start_date=fields.pop("start_date"),
                    deadline_date=fields.pop("deadline_date"), status=fields.pop("status"),
                    progress=fields.pop("progress"),
                )
                self.focus_selected_goal_id = goal_id
                message = "Goal saved. Add milestones to break it into measurable steps."
            else:
                self.focus_store.update_goal(self.focus_selected_goal_id, **fields)
                message = "Goal changes saved."
            self.focus_goal_status_label.configure(text=message)
            self._refresh_focus_goals()
            self._refresh_focus_milestones()
        except (FocusError, ValueError) as exc:
            messagebox.showwarning("Veltrix Goals", str(exc), parent=self.root)

    def _delete_focus_goal(self) -> None:
        if self.focus_selected_goal_id is None:
            messagebox.showinfo("Veltrix Goals", "Select a goal to delete.", parent=self.root)
            return
        if not messagebox.askyesno(
            "Delete goal", "Delete this goal and all of its milestones? This cannot be undone.", parent=self.root
        ):
            return
        self.focus_store.delete_goal(self.focus_selected_goal_id)
        self._new_focus_goal()
        self._refresh_focus_goals()

    def _selected_focus_milestone_id(self) -> int | None:
        selection = self.focus_milestone_tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _add_focus_milestone(self) -> None:
        if self.focus_selected_goal_id is None:
            messagebox.showinfo("Veltrix Goals", "Select or save a goal before adding milestones.", parent=self.root)
            return
        title = simpledialog.askstring("Add milestone", "Milestone description:", parent=self.root)
        if title is None:
            return
        try:
            self.focus_store.add_milestone(self.focus_selected_goal_id, title)
            self._refresh_focus_milestones()
            self._refresh_focus_goals()
        except FocusError as exc:
            messagebox.showwarning("Veltrix Goals", str(exc), parent=self.root)

    def _toggle_focus_milestone(self) -> None:
        milestone_id = self._selected_focus_milestone_id()
        if milestone_id is None:
            messagebox.showinfo("Veltrix Goals", "Select a milestone first.", parent=self.root)
            return
        self.focus_store.toggle_milestone(milestone_id)
        self._refresh_focus_milestones()
        self._refresh_focus_goals()

    def _delete_focus_milestone(self) -> None:
        milestone_id = self._selected_focus_milestone_id()
        if milestone_id is None:
            messagebox.showinfo("Veltrix Goals", "Select a milestone first.", parent=self.root)
            return
        self.focus_store.delete_milestone(milestone_id)
        self._refresh_focus_milestones()
        self._refresh_focus_goals()

    def _build_alerts_page(self) -> None:
        """Build the Market Watch command centre and retain the rule editor."""
        palette = THEMES[self.theme_name]
        self.alerts_scroll_shell = self._frame(self.alerts_view)
        self.alerts_scroll_shell.pack(fill="both", expand=True)
        self.alerts_canvas = tk.Canvas(
            self.alerts_scroll_shell, bg=palette["bg"], highlightthickness=0, bd=0,
        )
        self.alerts_scrollbar = ttk.Scrollbar(
            self.alerts_scroll_shell, orient="vertical", command=self.alerts_canvas.yview,
            style="Veltrix.Alerts.Vertical.TScrollbar",
        )
        self.alerts_canvas.configure(yscrollcommand=self.alerts_scrollbar.set)
        self.alerts_canvas.pack(side="left", fill="both", expand=True)
        self.alerts_scrollbar.pack(side="right", fill="y")
        self.alerts_content = self._frame(self.alerts_canvas)
        self.alerts_content_window = self.alerts_canvas.create_window(
            (0, 0), window=self.alerts_content, anchor="nw",
        )
        self.alerts_content.bind(
            "<Configure>", lambda _event: self.alerts_canvas.configure(
                scrollregion=self.alerts_canvas.bbox("all")
            )
        )
        self.alerts_canvas.bind(
            "<Configure>", lambda event: self.alerts_canvas.itemconfigure(
                self.alerts_content_window, width=event.width
            )
        )
        self.alerts_canvas.bind(
            "<MouseWheel>",
            lambda event: self.alerts_canvas.yview_scroll(int(-event.delta / 120), "units"),
        )
        self.alerts_canvas.bind(
            "<Button-4>", lambda _event: self.alerts_canvas.yview_scroll(-1, "units"),
        )
        self.alerts_canvas.bind(
            "<Button-5>", lambda _event: self.alerts_canvas.yview_scroll(1, "units"),
        )
        self.alert_settings_container = self._frame(self.alerts_content, bg="panel", padx=4, pady=3)
        self.alert_settings_container.pack_forget()
        build_alerts_dashboard(self, self.alerts_content)
        settings_toggle_row = self._frame(self.alerts_content, bg="panel", padx=7, pady=5)
        settings_toggle_row.pack(fill="x", pady=(0, 6))
        self.alert_config_toggle = tk.Button(
            settings_toggle_row, text="ALERT RULES / PREFERENCES  ▸",
            command=lambda: toggle_alert_settings(self),
            font=("Consolas", 7, "bold"), relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
        )
        self.alert_config_toggle.pack(side="left")

        settings_panel = self._frame(self.alert_settings_container, bg="panel", padx=14, pady=11)
        settings_panel.pack(fill="x", pady=(0, 10))
        self._label(settings_panel, "SESSION ALERT ENGINE", bg="panel", fg="bright",
                    font=("Consolas", 10, "bold")).pack(anchor="w")
        self._label(
            settings_panel,
            "Choose which market transitions should generate an in-app alert.",
            bg="panel", fg="muted", font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(2, 8))

        toggles = self._frame(settings_panel, bg="panel")
        toggles.pack(fill="x")
        toggle_specs = [
            ("notify_pre_open", "PRE-OPEN"),
            ("notify_open", "SESSION OPEN"),
            ("notify_pre_close", "PRE-CLOSE"),
            ("notify_close", "SESSION CLOSE"),
            ("notify_overlap", "OVERLAP START"),
            ("sound_enabled", "SOUND"),
            ("desktop_notifications_enabled", "WINDOWS TOASTS"),
        ]
        self.alert_checkbuttons: list[tk.Checkbutton] = []
        for key, label in toggle_specs:
            variable = tk.BooleanVar(value=bool(self.alert_settings.get(key, True)))
            self.alert_vars[key] = variable
            check = tk.Checkbutton(
                toggles, text=label, variable=variable, command=self.save_alert_settings,
                font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=5, pady=3,
                cursor="hand2", selectcolor=palette["dim"], activebackground=palette["panel"],
            )
            check.pack(side="left", padx=(0, 7))
            self.alert_checkbuttons.append(check)

        lead_row = self._frame(settings_panel, bg="panel")
        lead_row.pack(fill="x", pady=(8, 0))
        self._label(lead_row, "PRE-OPEN MIN", bg="panel", fg="muted",
                    font=("Consolas", 8, "bold")).pack(side="left")
        self.pre_open_var = tk.StringVar(value=str(self.alert_settings.get("pre_open_minutes", 15)))
        self.pre_open_spin = tk.Spinbox(
            lead_row, from_=1, to=180, textvariable=self.pre_open_var,
            width=4, font=("Consolas", 9, "bold"), justify="center", relief="flat", bd=0,
        )
        self.pre_open_spin.pack(side="left", padx=(6, 16))
        self._label(lead_row, "PRE-CLOSE MIN", bg="panel", fg="muted",
                    font=("Consolas", 8, "bold")).pack(side="left")
        self.pre_close_var = tk.StringVar(value=str(self.alert_settings.get("pre_close_minutes", 10)))
        self.pre_close_spin = tk.Spinbox(
            lead_row, from_=1, to=180, textvariable=self.pre_close_var,
            width=4, font=("Consolas", 9, "bold"), justify="center", relief="flat", bd=0,
        )
        self.pre_close_spin.pack(side="left", padx=(6, 12))
        self.save_alert_button = tk.Button(
            lead_row, text="SAVE ALERT SETTINGS", command=self.save_alert_settings,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=10, pady=5, cursor="hand2",
        )
        self.save_alert_button.pack(side="left")
        self.test_alert_button = tk.Button(
            lead_row, text="TEST NOTIFICATION", command=self.test_notification,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=10, pady=5, cursor="hand2",
        )
        self.test_alert_button.pack(side="left", padx=(7, 0))

        overrides_title = self._label(
            settings_panel, "SESSION-SPECIFIC REMINDER OVERRIDES",
            bg="panel", fg="bright", font=("Consolas", 8, "bold"),
        )
        overrides_title.pack(anchor="w", pady=(12, 2))
        self._label(
            settings_panel,
            "Each market has independent lead times, initially set to the global default values.",
            bg="panel", fg="muted", font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(0, 5))
        self.session_lead_vars = {}
        self.session_lead_spins = []
        saved_overrides = self.alert_settings.get("session_lead_overrides", {})
        if not isinstance(saved_overrides, dict):
            saved_overrides = {}
        for session in self.sessions:
            override = saved_overrides.get(session.key, {})
            if not isinstance(override, dict):
                override = {}
            row = self._frame(settings_panel, bg="panel")
            row.pack(fill="x", pady=2)
            self._label(
                row, session.name, bg="panel", fg="text",
                font=("Consolas", 8, "bold"), width=12,
            ).pack(side="left")
            open_var = tk.StringVar(
                value=str(override.get("pre_open_minutes", self.alert_settings.get("pre_open_minutes", 15)))
            )
            close_var = tk.StringVar(
                value=str(override.get("pre_close_minutes", self.alert_settings.get("pre_close_minutes", 10)))
            )
            self._label(row, "PRE-OPEN", bg="panel", fg="muted", font=("Consolas", 7)).pack(side="left", padx=(5, 3))
            open_spin = tk.Spinbox(
                row, from_=1, to=180, textvariable=open_var, width=4,
                font=("Consolas", 8), justify="center", relief="flat", bd=0,
            )
            open_spin.pack(side="left", padx=(0, 12))
            self._label(row, "PRE-CLOSE", bg="panel", fg="muted", font=("Consolas", 7)).pack(side="left", padx=(0, 3))
            close_spin = tk.Spinbox(
                row, from_=1, to=180, textvariable=close_var, width=4,
                font=("Consolas", 8), justify="center", relief="flat", bd=0,
            )
            close_spin.pack(side="left")
            self.session_lead_vars[session.key] = {"pre_open": open_var, "pre_close": close_var}
            self.session_lead_spins.extend((open_spin, close_spin))

        risk_panel = self._frame(self.alert_settings_container, bg="panel", padx=14, pady=11)
        risk_panel.pack(fill="x", pady=(0, 10))
        self._label(
            risk_panel, "SESSION RISK AWARENESS", bg="panel", fg="bright",
            font=("Consolas", 10, "bold"),
        ).pack(anchor="w")
        self._label(
            risk_panel,
            "Schedule-based cautions for opening/closing windows and exchange holiday-adjacent conditions. These are not live liquidity measurements.",
            bg="panel", fg="muted", font=("Segoe UI", 8), wraplength=1050,
            justify="left",
        ).pack(anchor="w", pady=(2, 8))
        risk_toggles = self._frame(risk_panel, bg="panel")
        risk_toggles.pack(fill="x")
        self.risk_enabled_var = tk.BooleanVar(value=bool(self.session_risk_settings.get("enabled", True)))
        self.risk_notifications_var = tk.BooleanVar(
            value=bool(self.session_risk_settings.get("notifications_enabled", True))
        )
        self.holiday_liquidity_var = tk.BooleanVar(
            value=bool(self.session_risk_settings.get("holiday_liquidity_flags", True))
        )
        for variable, label in (
            (self.risk_enabled_var, "SHOW SESSION RISK FLAGS"),
            (self.risk_notifications_var, "RISK NOTIFICATIONS"),
            (self.holiday_liquidity_var, "HOLIDAY LIQUIDITY CAUTIONS"),
        ):
            check = tk.Checkbutton(
                risk_toggles, text=label, variable=variable, command=self.save_alert_settings,
                font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=5, pady=3,
                cursor="hand2", bg=palette["panel"], fg=palette["text"],
                selectcolor=palette["dim"], activebackground=palette["panel"],
                activeforeground=palette["bright"],
            )
            check.pack(side="left", padx=(0, 8))
            self.risk_checkbuttons.append(check)
        risk_windows = self._frame(risk_panel, bg="panel")
        risk_windows.pack(fill="x", pady=(7, 0))
        self._label(risk_windows, "OPENING CAUTION MIN", bg="panel", fg="muted",
                    font=("Consolas", 8, "bold")).pack(side="left")
        self.risk_opening_window_var = tk.StringVar(
            value=str(self.session_risk_settings.get("opening_window_minutes", 15))
        )
        self.risk_opening_window_spin = tk.Spinbox(
            risk_windows, from_=0, to=180, textvariable=self.risk_opening_window_var,
            width=4, font=("Consolas", 8), justify="center", relief="flat", bd=0,
        )
        self.risk_opening_window_spin.pack(side="left", padx=(6, 16))
        self._label(risk_windows, "CLOSING CAUTION MIN", bg="panel", fg="muted",
                    font=("Consolas", 8, "bold")).pack(side="left")
        self.risk_closing_window_var = tk.StringVar(
            value=str(self.session_risk_settings.get("closing_window_minutes", 15))
        )
        self.risk_closing_window_spin = tk.Spinbox(
            risk_windows, from_=0, to=180, textvariable=self.risk_closing_window_var,
            width=4, font=("Consolas", 8), justify="center", relief="flat", bd=0,
        )
        self.risk_closing_window_spin.pack(side="left", padx=(6, 16))
        self.risk_pre_open_window_var = tk.StringVar(
            value=str(self.session_risk_settings.get("pre_open_window_minutes", 15))
        )
        self._label(risk_windows, "PRE-OPEN FLAG MIN", bg="panel", fg="muted",
                    font=("Consolas", 8, "bold")).pack(side="left")
        self.risk_pre_open_window_spin = tk.Spinbox(
            risk_windows, from_=0, to=180, textvariable=self.risk_pre_open_window_var,
            width=4, font=("Consolas", 8), justify="center", relief="flat", bd=0,
        )
        self.risk_pre_open_window_spin.pack(side="left", padx=(6, 0))

        event_panel = self._frame(self.alert_settings_container, bg="panel", padx=14, pady=11)
        event_panel.pack(fill="x", pady=(0, 10))
        self._label(event_panel, "ECONOMIC EVENT REMINDERS", bg="panel", fg="bright",
                    font=("Consolas", 10, "bold")).pack(anchor="w")
        self._label(
            event_panel,
            f"Add events manually. Times are interpreted in {self.home_zone.key} (your control timezone).",
            bg="panel", fg="muted", font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(2, 8))

        event_form = self._frame(event_panel, bg="panel")
        event_form.pack(fill="x")
        self.event_name_var = tk.StringVar()
        self.event_datetime_var = tk.StringVar(value=(datetime.now(self.home_zone) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"))
        self.event_name_entry = tk.Entry(
            event_form, textvariable=self.event_name_var, width=25,
            font=("Consolas", 9), relief="flat", bd=0,
        )
        self.event_name_entry.pack(side="left", padx=(0, 7), ipady=6)
        self.event_datetime_entry = tk.Entry(
            event_form, textvariable=self.event_datetime_var, width=19,
            font=("Consolas", 9), relief="flat", bd=0,
        )
        self.event_datetime_entry.pack(side="left", padx=(0, 7), ipady=6)
        self.add_event_button = tk.Button(
            event_form, text="ADD EVENT", command=self.add_economic_event,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=11, pady=6, cursor="hand2",
        )
        self.add_event_button.pack(side="left")
        self._label(event_form, "REMIND", bg="panel", fg="muted",
                    font=("Consolas", 8, "bold")).pack(side="left", padx=(14, 4))
        self.event_lead_var = tk.StringVar(value=str(self.config.get("event_reminder_minutes", 15)))
        self.event_lead_spin = tk.Spinbox(
            event_form, from_=0, to=1440, textvariable=self.event_lead_var,
            width=5, font=("Consolas", 9, "bold"), justify="center", relief="flat", bd=0,
        )
        self.event_lead_spin.pack(side="left")
        self._label(event_form, "MIN BEFORE", bg="panel", fg="muted",
                    font=("Consolas", 8, "bold")).pack(side="left", padx=(4, 0))

        event_list_row = self._frame(event_panel, bg="panel")
        event_list_row.pack(fill="x", pady=(9, 0))
        self.event_listbox = tk.Listbox(
            event_list_row, height=4, font=("Consolas", 8), relief="flat", bd=0,
            activestyle="none", exportselection=False,
        )
        self.event_listbox.pack(side="left", fill="x", expand=True)
        self.remove_event_button = tk.Button(
            event_list_row, text="REMOVE SELECTED", command=self.remove_economic_event,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
        )
        self.remove_event_button.pack(side="left", padx=(8, 0), anchor="n")

        feed_panel = self._frame(self.alert_settings_container, bg="panel", padx=14, pady=10)
        feed_panel.pack(fill="both", expand=True)
        self._label(feed_panel, "ALERT ACTIVITY", bg="panel", fg="bright",
                    font=("Consolas", 9, "bold")).pack(anchor="w")
        self.alert_banner = self._label(
            feed_panel, "NO ALERTS YET  ·  Session notifications will appear here.",
            bg="panel", fg="muted", font=("Consolas", 8, "bold"), anchor="w", justify="left",
        )
        self.alert_banner.pack(fill="x", pady=(4, 7))
        feed_row = self._frame(feed_panel, bg="panel")
        feed_row.pack(fill="both", expand=True)
        self.alert_listbox = tk.Listbox(
            feed_row, height=5, font=("Consolas", 8), relief="flat", bd=0,
            activestyle="none", exportselection=False,
        )
        self.alert_listbox.pack(fill="both", expand=True)

        self._refresh_economic_event_list()

    def _build_calendar_page(self) -> None:
        """Build the public macro calendar workspace and its refresh controls."""
        palette = THEMES[self.theme_name]

        connection = self._frame(self.calendar_view, bg="panel", padx=14, pady=11)
        connection.pack(fill="x", pady=(0, 9))
        self._label(connection, "LIVE ECONOMIC CALENDAR", bg="panel", fg="bright",
                    font=("Consolas", 10, "bold")).pack(anchor="w")
        self._label(
            connection,
            "ShowMyTrades public calendar · 9 major currencies · No API key · 15-minute refresh floor.",
            bg="panel", fg="muted", font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(2, 8))
        source_row = self._frame(connection, bg="panel")
        source_row.pack(fill="x")
        self.calendar_status_label = self._label(
            source_row, "CONNECTING TO PUBLIC CALENDAR...",
            bg="panel", fg="warning", font=("Consolas", 8, "bold"), anchor="w",
        )
        self.calendar_status_label.pack(side="left", fill="x", expand=True)
        self.refresh_calendar_button = tk.Button(
            source_row, text="REFRESH CALENDAR", command=self.refresh_live_calendar,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
        )
        self.refresh_calendar_button.pack(side="right")
        self.calendar_freshness_label = self._label(
            connection, "Loading cached calendar data...",
            bg="panel", fg="muted", font=("Segoe UI", 8), anchor="w",
        )
        self.calendar_freshness_label.pack(fill="x", pady=(7, 0))
        if self.calendar_last_updated:
            try:
                cached_at = datetime.fromisoformat(self.calendar_last_updated.replace("Z", "+00:00")).astimezone(self.home_zone)
                self.calendar_freshness_label.configure(
                    text=f"Cached snapshot: {cached_at.strftime('%d %b %Y %H:%M:%S %Z')} · Refreshing live feed..."
                )
                self._set_calendar_status("CACHED DATA LOADED · LIVE REFRESH PENDING", "warning")
            except ValueError:
                self.calendar_freshness_label.configure(text="Cached data available · timestamp could not be parsed.")

        preferences = self._frame(self.calendar_view, bg="panel", padx=14, pady=9)
        preferences.pack(fill="x", pady=(0, 9))
        controls = self._frame(preferences, bg="panel")
        controls.pack(fill="x")
        self.calendar_filter_var = tk.StringVar(value="All impact levels")
        self.calendar_filter = ttk.Combobox(
            controls, textvariable=self.calendar_filter_var,
            values=("All impact levels", "High impact", "Medium impact", "Low impact", "Market holidays"),
            state="readonly", width=18, font=("Consolas", 8),
        )
        self.calendar_filter.pack(side="left", padx=(0, 8))
        self.calendar_filter.bind("<<ComboboxSelected>>", lambda _event: self._refresh_calendar_table())
        self.calendar_search_var = tk.StringVar()
        self.calendar_search_entry = tk.Entry(
            controls, textvariable=self.calendar_search_var, width=28,
            font=("Consolas", 8), relief="flat", bd=0,
        )
        self.calendar_search_entry.pack(side="left", padx=(0, 8), ipady=6)
        self.calendar_search_entry.insert(0, "Search currency / event")
        self.calendar_search_entry.bind("<FocusIn>", self._clear_calendar_search_placeholder)
        self.calendar_search_var.trace_add("write", lambda *_args: self._refresh_calendar_table())
        self.calendar_count_label = self._label(
            controls, "0 EVENTS", bg="panel", fg="muted", font=("Consolas", 8, "bold"),
        )
        self.calendar_count_label.pack(side="right")

        reminder_row = self._frame(preferences, bg="panel")
        reminder_row.pack(fill="x", pady=(8, 0))
        self.calendar_reminder_enabled_var = tk.BooleanVar(
            value=bool(self.calendar_settings.get("notify_high_impact", True))
        )
        self.calendar_reminder_check = tk.Checkbutton(
            reminder_row, text="REMIND ME BEFORE HIGH-IMPACT RELEASES",
            variable=self.calendar_reminder_enabled_var, command=self.save_calendar_preferences,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=4, pady=2,
            cursor="hand2", selectcolor=palette["dim"], activebackground=palette["panel"],
        )
        self.calendar_reminder_check.pack(side="left")
        self._label(reminder_row, "LEAD MIN", bg="panel", fg="muted",
                    font=("Consolas", 8, "bold")).pack(side="left", padx=(12, 5))
        self.calendar_reminder_minutes_var = tk.StringVar(
            value=str(self.calendar_settings.get("reminder_minutes", 15))
        )
        self.calendar_reminder_spin = tk.Spinbox(
            reminder_row, from_=0, to=1440, textvariable=self.calendar_reminder_minutes_var,
            width=5, font=("Consolas", 8, "bold"), justify="center", relief="flat", bd=0,
            command=self.save_calendar_preferences,
        )
        self.calendar_reminder_spin.pack(side="left")
        self.save_calendar_preferences_button = tk.Button(
            reminder_row, text="SAVE REMINDER SETTINGS", command=self.save_calendar_preferences,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=9, pady=5, cursor="hand2",
        )
        self.save_calendar_preferences_button.pack(side="left", padx=(10, 0))

        table_panel = self._frame(self.calendar_view, bg="panel", padx=10, pady=9)
        table_panel.pack(fill="both", expand=True)
        self._label(
            table_panel, f"UPCOMING MACRO RELEASES · DISPLAYED IN {datetime.now(self.home_zone).tzname()} ({self.home_zone.key})",
            bg="panel", fg="bright", font=("Consolas", 8, "bold"),
        ).pack(anchor="w", pady=(0, 7))
        table_frame = self._frame(table_panel, bg="panel")
        table_frame.pack(fill="both", expand=True)
        columns = ("time", "currency", "event", "impact", "previous", "forecast", "actual", "status", "confidence")
        self.calendar_tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", height=13,
            style="Veltrix.Treeview", selectmode="browse",
        )
        headings = {
            "time": (f"TIME ({datetime.now(self.home_zone).tzname()})", 105), "currency": ("CCY", 55),
            "event": ("EVENT", 275), "impact": ("IMPACT", 78),
            "previous": ("PREVIOUS", 85), "forecast": ("FORECAST", 85),
            "actual": ("ACTUAL", 85), "status": ("SCHEDULE", 85),
            "confidence": ("SOURCE CONFIDENCE", 125),
        }
        for column, (heading, width) in headings.items():
            self.calendar_tree.heading(column, text=heading)
            self.calendar_tree.column(column, width=width, minwidth=55, anchor="w", stretch=(column == "event"))
        self.calendar_tree.tag_configure("high", foreground=palette["error"])
        self.calendar_tree.tag_configure("medium", foreground=palette["warning"])
        self.calendar_tree.tag_configure("low", foreground=palette["success"])
        self.calendar_tree.tag_configure("holiday", foreground=palette["muted"])
        self.calendar_tree.tag_configure("tentative", font=("Consolas", 8, "italic"))
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.calendar_tree.yview)
        horizontal_scrollbar = ttk.Scrollbar(table_panel, orient="horizontal", command=self.calendar_tree.xview)
        self.calendar_tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal_scrollbar.set)
        self.calendar_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        horizontal_scrollbar.pack(fill="x", pady=(2, 0))
        attribution = self.calendar_payload.get("attribution", {})
        self.calendar_attribution_label = self._label(
            table_panel, str(attribution.get("text", "Economic calendar by ShowMyTrades")) + "  ·  VIEW SOURCE",
            bg="panel", fg="muted", font=("Segoe UI", 7, "underline"), anchor="w", cursor="hand2",
        )
        self.calendar_attribution_label.pack(fill="x", pady=(5, 0))
        self.calendar_attribution_label.bind("<Button-1>", lambda _event: self._open_calendar_source())
        self._refresh_calendar_table()

    def _build_market_page(self) -> None:
        """Build Phase 5 realised-volatility, ATR and expected-move workspace."""
        palette = THEMES[self.theme_name]

        # Keep the bottom alarm strip visible on shorter displays. The volatility
        # workspace scrolls independently inside the page host.
        self.volatility_canvas = tk.Canvas(self.volatility_view, highlightthickness=0, bd=0)
        self.volatility_scrollbar = ttk.Scrollbar(
            self.volatility_view, orient="vertical", command=self.volatility_canvas.yview,
            style="Veltrix.Market.Vertical.TScrollbar",
        )
        self.volatility_canvas.configure(yscrollcommand=self.volatility_scrollbar.set)
        self.volatility_scrollbar.pack(side="right", fill="y")
        self.volatility_canvas.pack(side="left", fill="both", expand=True)
        self.market_content = self._frame(self.volatility_canvas)
        self.market_content_window = self.volatility_canvas.create_window(
            (0, 0), window=self.market_content, anchor="nw"
        )
        self.market_content.bind(
            "<Configure>", lambda _event: self.volatility_canvas.configure(
                scrollregion=self.volatility_canvas.bbox("all")
            )
        )
        self.volatility_canvas.bind(
            "<Configure>", lambda event: self.volatility_canvas.itemconfigure(
                self.market_content_window, width=event.width
            )
        )

        header = self._frame(self.market_content, bg="panel", padx=14, pady=10)
        header.pack(fill="x", pady=(0, 9))
        self._label(header, "MARKET VOLATILITY MONITOR", bg="panel", fg="bright",
                    font=("Consolas", 10, "bold")).pack(anchor="w")
        self.market_description_label = self._label(
            header, "5m realised volatility (√Σr²) · Daily Wilder ATR(14) · 20-session 1σ move",
            bg="panel", fg="muted", font=("Segoe UI", 8),
        )
        self.market_description_label.pack(anchor="w", pady=(2, 7))
        top_row = self._frame(header, bg="panel")
        top_row.pack(fill="x")
        self.market_status_label = self._label(top_row, "WAITING FOR MARKET DATA...", bg="panel", fg="warning",
                                               font=("Consolas", 8, "bold"), anchor="w")
        self.market_status_label.pack(side="left", fill="x", expand=True)
        self.refresh_market_button = tk.Button(
            top_row, text="REFRESH MARKET DATA", command=self.refresh_market_data,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
        )
        self.refresh_market_button.pack(side="right")
        self.market_freshness_label = self._label(
            header, "Yahoo Finance legacy fallback · Unofficial feed · Price timing may vary · Provider validation pending",
            bg="panel", fg="muted", font=("Segoe UI", 7), anchor="w",
        )
        self.market_freshness_label.pack(fill="x", pady=(6, 0))

        cards_frame = self._frame(self.market_content)
        cards_frame.pack(fill="x", pady=(0, 9))
        for column in range(max(1, len(self.market_instruments))):
            cards_frame.grid_columnconfigure(column, weight=1, uniform="market_asset")
        self.market_asset_cards: dict[str, dict[str, tk.Widget]] = {}
        for column, instrument in enumerate(self.market_instruments):
            card = self._frame(cards_frame, bg="panel", padx=11, pady=9, highlightthickness=1, bd=0)
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 5 if column < len(self.market_instruments)-1 else 0))
            name = self._label(card, str(instrument.get("name", instrument["key"])), bg="panel", fg="bright",
                               font=("Consolas", 9, "bold"))
            name.pack(anchor="w")
            symbol = self._label(card, str(instrument.get("symbol", "")), bg="panel", fg="muted",
                                 font=("Consolas", 7))
            symbol.pack(anchor="w", pady=(1, 5))
            price = self._label(card, "--", bg="panel", fg="text", font=("Consolas", 17, "bold"))
            price.pack(anchor="w")
            atr = self._label(card, "ATR(14): N/A", bg="panel", fg="muted", font=("Consolas", 8, "bold"))
            atr.pack(anchor="w", pady=(5, 0))
            expected = self._label(card, "1D EXPECTED MOVE: N/A", bg="panel", fg="muted", font=("Consolas", 8, "bold"))
            expected.pack(anchor="w", pady=(2, 0))
            quote_time = self._label(card, "No quote loaded", bg="panel", fg="muted", font=("Segoe UI", 7))
            quote_time.pack(anchor="w", pady=(4, 0))
            self.market_asset_cards[str(instrument["key"])] = {
                "frame": card, "name": name, "symbol": symbol, "price": price,
                "atr": atr, "expected": expected, "quote_time": quote_time,
            }

        table_panel = self._frame(self.market_content, bg="panel", padx=11, pady=9)
        table_panel.pack(fill="both", expand=True, pady=(0, 9))
        self._label(table_panel, "SESSION-BY-SESSION REALISED VOLATILITY", bg="panel", fg="bright",
                    font=("Consolas", 9, "bold")).pack(anchor="w", pady=(0, 6))
        table_frame = self._frame(table_panel, bg="panel")
        table_frame.pack(fill="both", expand=True)
        columns = ("instrument", "session", "realised", "range", "bars", "regime", "observation")
        self.market_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=6,
                                        style="Veltrix.Market.Treeview", selectmode="browse")
        headings = {
            "instrument": ("INSTRUMENT", 150), "session": ("SESSION", 100),
            "realised": ("REALIZED VOL %", 115), "range": ("SESSION RANGE %", 115),
            "bars": ("BARS / RETURNS", 105), "regime": ("REGIME", 110),
            "observation": ("OBSERVATION", 115),
        }
        for column, (heading, width) in headings.items():
            self.market_tree.heading(column, text=heading)
            self.market_tree.column(column, width=width, minwidth=65, anchor="w", stretch=(column == "instrument"))
        for tag, colour in (("expansion", palette["error"]), ("contraction", palette["success"]),
                            ("normal", palette["text"]), ("nodata", palette["muted"])):
            self.market_tree.tag_configure(tag, foreground=colour)
        market_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.market_tree.yview)
        self.market_tree.configure(yscrollcommand=market_scroll.set)
        self.market_tree.pack(side="left", fill="both", expand=True)
        market_scroll.pack(side="right", fill="y")

        controls = self._frame(self.market_content, bg="panel", padx=12, pady=8)
        controls.pack(fill="x", pady=(0, 8))
        self.market_regime_enabled_var = tk.BooleanVar(value=bool(self.market_settings.get("regime_alerts_enabled", True)))
        self.market_regime_check = tk.Checkbutton(
            controls, text="VOLATILITY REGIME ALERTS", variable=self.market_regime_enabled_var,
            command=self.save_market_preferences, font=("Consolas", 8, "bold"), relief="flat", bd=0,
            padx=4, pady=2, cursor="hand2", selectcolor=palette["dim"], activebackground=palette["panel"],
        )
        self.market_regime_check.pack(side="left")
        self._label(controls, "EXPANSION ≥", bg="panel", fg="muted", font=("Consolas", 7, "bold")).pack(side="left", padx=(10, 4))
        self.market_expansion_var = tk.StringVar(value=str(self.market_settings.get("expansion_multiple", 1.5)))
        self.market_expansion_spin = tk.Spinbox(controls, from_=1.1, to=5.0, increment=0.1,
            textvariable=self.market_expansion_var, width=4, font=("Consolas", 8, "bold"), justify="center", relief="flat", bd=0)
        self.market_expansion_spin.pack(side="left")
        self._label(controls, "CONTRACTION ≤", bg="panel", fg="muted", font=("Consolas", 7, "bold")).pack(side="left", padx=(9, 4))
        self.market_contraction_var = tk.StringVar(value=str(self.market_settings.get("contraction_multiple", 0.67)))
        self.market_contraction_spin = tk.Spinbox(controls, from_=0.1, to=0.99, increment=0.01,
            textvariable=self.market_contraction_var, width=4, font=("Consolas", 8, "bold"), justify="center", relief="flat", bd=0)
        self.market_contraction_spin.pack(side="left")
        self.save_market_settings_button = tk.Button(controls, text="SAVE SETTINGS", command=self.save_market_preferences,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=9, pady=5, cursor="hand2")
        self.save_market_settings_button.pack(side="left", padx=(10, 0))

        alerts_panel = self._frame(self.market_content, bg="panel", padx=12, pady=8)
        alerts_panel.pack(fill="x")
        self._label(alerts_panel, "VOLATILITY REGIME ACTIVITY", bg="panel", fg="bright",
                    font=("Consolas", 8, "bold")).pack(anchor="w")
        self.market_alert_listbox = tk.Listbox(alerts_panel, height=2, font=("Consolas", 7),
            relief="flat", bd=0, activestyle="none", exportselection=False)
        self.market_alert_listbox.pack(fill="x", pady=(4, 0))
        self.market_alert_listbox.insert("end", "No expansion or contraction alerts have been recorded this run.")

    def run_session_performance(self) -> None:
        """Run historical session/overlap performance calculations off the Tk thread."""
        if self.session_performance_in_progress:
            return
        if self.regime_cache_loading:
            self.session_performance_status_label.configure(
                text="LOCAL OHLC DATA LIBRARY IS STILL LOADING · RETRY IN A MOMENT",
                fg=THEMES[self.theme_name]["warning"],
            )
            return
        key = self.session_performance_dataset_label_to_key.get(
            self.session_performance_dataset_var.get(), ""
        )
        dataset = self.regime_datasets.get(key)
        if not isinstance(dataset, dict) or not dataset.get("bars"):
            self.session_performance_status_label.configure(
                text="NO DATASET SELECTED · IMPORT A COMPLETED OHLC CSV IN REGIME LAB FIRST",
                fg=THEMES[self.theme_name]["warning"],
            )
            return
        metadata = dataset.get("metadata", {}) if isinstance(dataset.get("metadata"), dict) else {}
        if (
            dataset.get("variable_interval_bars")
            or metadata.get("variable_interval_bars")
            or metadata.get("bar_construction")
        ):
            self.session_performance_status_label.configure(
                text="UNSUPPORTED DATA · THIS STUDY REQUIRES FIXED-INTERVAL OHLC BARS, NOT TICK / VARIABLE BARS",
                fg=THEMES[self.theme_name]["error"],
            )
            return
        try:
            interval = float(dataset.get("bar_interval_minutes") or 0)
            minimum_bars = int(self.session_performance_min_bars_var.get())
            minimum_coverage = float(self.session_performance_min_coverage_var.get())
            if minimum_bars < 1 or minimum_bars > 500:
                raise ValueError("Minimum bars must be from 1 to 500.")
            if not 0 <= minimum_coverage <= 100:
                raise ValueError("Minimum coverage must be from 0 to 100.")
            if interval <= 0:
                raise ValueError("Dataset does not contain a valid median bar interval.")
        except (ValueError, tk.TclError) as exc:
            self.session_performance_status_label.configure(
                text=f"INVALID STUDY PARAMETERS · {exc}",
                fg=THEMES[self.theme_name]["error"],
            )
            return

        bars = tuple(dict(item) for item in dataset.get("bars", []) if isinstance(item, dict))
        sessions = tuple(self.sessions)
        study_metadata = {
            "key": key,
            "name": str(dataset.get("name") or key),
            "source": str(dataset.get("source") or "Unknown source"),
            "symbol": str(dataset.get("symbol") or ""),
            "bar_interval_minutes": interval,
            "session_profile": str(self.active_session_profile),
        }
        self.session_performance_result = None
        self.session_performance_result_metadata = {}
        self.session_performance_export_button.configure(state="disabled")
        self.session_performance_in_progress = True
        self.session_performance_run_button.configure(state="disabled", text="ANALYSING...")
        self.session_performance_status_label.configure(
            text=f"ANALYSING {len(bars):,} OHLC BARS · {study_metadata['name']} · BACKGROUND TASK",
            fg=THEMES[self.theme_name]["warning"],
        )

        def worker() -> None:
            try:
                result = analyse_session_performance(
                    bars, sessions,
                    bar_interval_minutes=interval,
                    minimum_bars_per_session=minimum_bars,
                    minimum_coverage_pct=minimum_coverage,
                )
                self.session_performance_result_queue.put((key, study_metadata, result, None))
            except Exception as exc:
                self.session_performance_result_queue.put((key, study_metadata, None, str(exc)))

        threading.Thread(
            target=worker, name="VeltrixSessionPerformance", daemon=True
        ).start()

    def _drain_session_performance_results(self) -> None:
        if self.is_closing:
            return
        try:
            while True:
                key, metadata, result, error = self.session_performance_result_queue.get_nowait()
                self.session_performance_in_progress = False
                self.session_performance_run_button.configure(state="normal", text="RUN SESSION STUDY")
                selected_key = self.session_performance_dataset_label_to_key.get(
                    self.session_performance_dataset_var.get(), ""
                )
                if key != selected_key:
                    self.session_performance_status_label.configure(
                        text="STUDY FINISHED FOR A PREVIOUS DATASET SELECTION · SELECT IT AGAIN TO VIEW",
                        fg=THEMES[self.theme_name]["warning"],
                    )
                    continue
                if error:
                    self.session_performance_result = None
                    self.session_performance_export_button.configure(state="disabled")
                    self.session_performance_status_label.configure(
                        text=f"SESSION STUDY FAILED · {error[:220]}",
                        fg=THEMES[self.theme_name]["error"],
                    )
                    continue
                render_session_performance_result(self, metadata, result)
        except queue.Empty:
            pass
        if not self.is_closing:
            self.session_performance_queue_job = self.root.after(
                UI_QUEUE_POLL_MS, self._drain_session_performance_results
            )

    def export_session_performance(self) -> None:
        if not self.session_performance_result:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export daily session-performance and overlap rows",
            defaultextension=".csv",
            initialfile="veltrix_session_performance.csv",
            filetypes=(("CSV files", "*.csv"),),
        )
        if not path:
            return
        try:
            export_session_performance_csv(path, self.session_performance_result)
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("Session performance export failed", str(exc), parent=self.root)
            return
        self.session_performance_status_label.configure(
            text=f"DAILY SESSION / OVERLAP ROWS EXPORTED · {Path(path).name}",
            fg=THEMES[self.theme_name]["success"],
        )

    def _build_regime_page(self) -> None:
        """Build Phase 12 causal market-regime research workspace."""
        self.regime_canvas = tk.Canvas(self.regime_view, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(self.regime_view, orient="vertical", command=self.regime_canvas.yview)
        self.regime_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.regime_canvas.pack(side="left", fill="both", expand=True)
        self.regime_content = self._frame(self.regime_canvas)
        self.regime_content_window = self.regime_canvas.create_window(
            (0, 0), window=self.regime_content, anchor="nw"
        )
        self.regime_content.bind(
            "<Configure>", lambda _event: self.regime_canvas.configure(
                scrollregion=self.regime_canvas.bbox("all")
            )
        )
        self.regime_canvas.bind(
            "<Configure>", lambda event: self.regime_canvas.itemconfigure(
                self.regime_content_window, width=event.width
            )
        )

        header = self._frame(self.regime_content, bg="panel", padx=14, pady=11)
        header.pack(fill="x", pady=(0, 9))
        self._label(header, "CAUSAL MARKET REGIME LAB", bg="panel", fg="bright",
                    font=("Consolas", 10, "bold")).pack(anchor="w")
        self._label(
            header,
            "CAUSAL OHLC CLASSIFICATION · TREND / RANGE / VOLATILITY SHOCK · HISTORICAL OUTCOME STUDY",
            bg="panel", fg="muted", font=("Consolas", 7, "bold"),
        ).pack(anchor="w", pady=(3, 6))
        self.regime_status_label = self._label(
            header,
            "LOCAL OHLC DATA · IMPORT A COMPLETED BAR CSV HERE, THEN RUN CLASSIFICATION",
            bg="panel", fg="warning", font=("Consolas", 8, "bold"), anchor="w", justify="left", wraplength=980,
        )
        self.regime_status_label.pack(fill="x")

        controls = self._frame(self.regime_content, bg="panel", padx=12, pady=10)
        controls.pack(fill="x", pady=(0, 9))
        controls.grid_columnconfigure(0, weight=1)
        self._label(controls, "DATASET / INSTRUMENT", bg="panel", fg="muted",
                    font=("Consolas", 7, "bold")).grid(row=0, column=0, sticky="w")
        self.regime_asset_combo = ttk.Combobox(
            controls, textvariable=self.regime_asset_var,
            values=list(self.regime_dataset_label_to_key.keys()), state="readonly", width=54,
            style="Veltrix.Regime.TCombobox",
        )
        self.regime_asset_combo.grid(row=1, column=0, sticky="ew", pady=(4, 9))
        selected_key = str(self.regime_settings.get("selected_asset") or "")
        selected_label = next((label for label, key in self.regime_dataset_label_to_key.items() if key == selected_key), "")
        if not selected_label and self.regime_dataset_label_to_key:
            selected_label = next(iter(self.regime_dataset_label_to_key))
        self.regime_asset_var.set(selected_label)
        self.regime_asset_combo.bind("<<ComboboxSelected>>", lambda _event: self._regime_asset_changed())

        field_specs = [
            ("EFFICIENCY LOOKBACK", "lookback"),
            ("FAST ATR PERIOD", "atr_fast_period"),
            ("SLOW ATR PERIOD", "atr_slow_period"),
            ("RANGE ER MAX", "range_er_max"),
            ("TREND ER MIN", "trend_er_min"),
            ("TREND SLOPE · ATR", "trend_slope_atr_min"),
            ("SHOCK ATR RATIO", "shock_atr_ratio"),
            ("SHOCK TR / PRIOR ATR", "shock_true_range_multiple"),
            ("FORWARD HORIZON · BARS", "forward_horizon"),
        ]
        fields = self._frame(controls, bg="panel")
        fields.grid(row=2, column=0, sticky="ew")
        for column in range(3):
            fields.grid_columnconfigure(column, weight=1, uniform="regime_fields")
        self.regime_field_widgets: list[tk.Widget] = []
        for index, (label, key) in enumerate(field_specs):
            row, column = divmod(index, 3)
            cell = self._frame(fields, bg="panel")
            cell.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 7, 7 if column < 2 else 0),
                      pady=(0, 7))
            self._label(cell, label, bg="panel", fg="muted", font=("Consolas", 7, "bold")).pack(anchor="w")
            widget = tk.Entry(
                cell, textvariable=self.regime_vars[key], width=17,
                font=("Consolas", 9, "bold"), relief="flat", bd=0, highlightthickness=1,
            )
            self._register_theme(widget, "entry_bg", "entry_fg")
            widget.pack(fill="x", pady=(3, 0), ipady=5)
            self.regime_field_widgets.append(widget)

        actions = self._frame(controls, bg="panel")
        actions.grid(row=3, column=0, sticky="ew", pady=(3, 0))
        self.regime_import_button = tk.Button(
            actions, text="IMPORT OHLC CSV", command=self.import_regime_csv,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=12, pady=7,
            cursor="hand2", state="disabled",
        )
        self.regime_import_button.pack(side="left", padx=(0, 7))
        self.regime_run_button = tk.Button(
            actions, text="RUN REGIME ANALYSIS", command=self.run_regime_analysis,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=12, pady=7, cursor="hand2",
        )
        self.regime_run_button.pack(side="left", padx=(0, 7))
        self.regime_export_button = tk.Button(
            actions, text="EXPORT REGIME CSV", command=self.export_regime_results,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=12, pady=7,
            cursor="hand2", state="disabled",
        )
        self.regime_export_button.pack(side="left", padx=7)
        self.regime_save_button = tk.Button(
            actions, text="SAVE SETTINGS", command=self.save_regime_preferences,
            font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=12, pady=7, cursor="hand2",
        )
        self.regime_save_button.pack(side="left", padx=7)

        metrics_panel = self._frame(self.regime_content, bg="panel", padx=11, pady=9)
        metrics_panel.pack(fill="x", pady=(0, 9))
        self._label(metrics_panel, "CLASSIFICATION SNAPSHOT", bg="panel", fg="bright",
                    font=("Consolas", 9, "bold")).pack(anchor="w", pady=(0, 7))
        metrics_grid = self._frame(metrics_panel, bg="panel")
        metrics_grid.pack(fill="x")
        for column in range(3):
            metrics_grid.grid_columnconfigure(column, weight=1, uniform="regime_metrics")
        self.regime_metric_tiles: dict[str, dict[str, tk.Widget]] = {}
        metric_specs = [
            ("bars", "VALID BARS", "N/A"), ("classified", "CLASSIFIED BARS", "N/A"),
            ("range", "RANGE FREQUENCY", "N/A"), ("trend", "TREND FREQUENCY", "N/A"),
            ("shock", "SHOCK FREQUENCY", "N/A"), ("latest", "LATEST REGIME", "N/A"),
        ]
        for index, (key, title, initial) in enumerate(metric_specs):
            row, column = divmod(index, 3)
            tile = self._frame(metrics_grid, bg="panel", padx=9, pady=7,
                               highlightthickness=1, bd=0)
            tile.grid(row=row, column=column, sticky="nsew",
                      padx=(0 if column == 0 else 5, 5 if column < 2 else 0), pady=(0, 6))
            title_label = self._label(tile, title, bg="panel", fg="muted", font=("Consolas", 7, "bold"))
            title_label.pack(anchor="w")
            value_label = self._label(tile, initial, bg="panel", fg="text", font=("Consolas", 12, "bold"))
            value_label.pack(anchor="w", pady=(3, 0))
            self.regime_metric_tiles[key] = {"frame": tile, "title": title_label, "value": value_label}

        chart_panel = self._frame(self.regime_content, bg="panel", padx=11, pady=9)
        chart_panel.pack(fill="x", pady=(0, 9))
        self._label(chart_panel, "PRICE PATH WITH CAUSAL REGIME LABELS · MOST RECENT 250 BARS",
                    bg="panel", fg="bright", font=("Consolas", 9, "bold")).pack(anchor="w", pady=(0, 6))
        self.regime_chart_canvas = tk.Canvas(
            chart_panel, height=245, highlightthickness=1, highlightbackground=THEMES[self.theme_name]["border"],
            bd=0,
        )
        self._register_theme(self.regime_chart_canvas, "panel")
        self.regime_chart_canvas.pack(fill="x", expand=True)
        self.regime_chart_canvas.bind("<Configure>", lambda _event: self._draw_regime_chart())

        tables = self._frame(self.regime_content, bg="bg")
        tables.pack(fill="both", expand=True, pady=(0, 9))
        tables.grid_columnconfigure(0, weight=3, uniform="regime_tables")
        tables.grid_columnconfigure(1, weight=2, uniform="regime_tables")
        distribution_panel = self._frame(tables, bg="panel", padx=10, pady=9)
        distribution_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._label(distribution_panel, "REGIME FREQUENCY & FORWARD OUTCOMES",
                    bg="panel", fg="bright", font=("Consolas", 8, "bold")).pack(anchor="w", pady=(0, 5))
        distribution_columns = ("regime", "count", "frequency", "samples", "mean", "median", "positive")
        self.regime_distribution_tree = ttk.Treeview(
            distribution_panel, columns=distribution_columns, show="headings", height=6,
            style="Veltrix.Regime.Treeview", selectmode="browse",
        )
        distribution_headings = {
            "regime": ("REGIME", 145), "count": ("BARS", 55), "frequency": ("FREQ %", 70),
            "samples": ("FWD N", 60), "mean": ("MEAN %", 75), "median": ("MEDIAN %", 75),
            "positive": ("POSITIVE %", 80),
        }
        for key, (heading, width) in distribution_headings.items():
            self.regime_distribution_tree.heading(key, text=heading)
            self.regime_distribution_tree.column(key, width=width, minwidth=48, anchor="center",
                                                 stretch=(key == "regime"))
        self.regime_distribution_tree.pack(fill="both", expand=True)

        transition_panel = self._frame(tables, bg="panel", padx=10, pady=9)
        transition_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self._label(transition_panel, "REGIME TRANSITION COUNTS",
                    bg="panel", fg="bright", font=("Consolas", 8, "bold")).pack(anchor="w", pady=(0, 5))
        transition_columns = ("from", "range", "up", "down", "shock", "transition")
        self.regime_transition_tree = ttk.Treeview(
            transition_panel, columns=transition_columns, show="headings", height=6,
            style="Veltrix.Regime.Treeview", selectmode="browse",
        )
        transition_headings = {
            "from": ("FROM", 90), "range": ("RNG", 45), "up": ("UP", 45),
            "down": ("DN", 45), "shock": ("SHK", 45), "transition": ("TRN", 45),
        }
        for key, (heading, width) in transition_headings.items():
            self.regime_transition_tree.heading(key, text=heading)
            self.regime_transition_tree.column(key, width=width, minwidth=38, anchor="center",
                                               stretch=(key == "from"))
        self.regime_transition_tree.pack(fill="both", expand=True)

        recent_panel = self._frame(self.regime_content, bg="panel", padx=11, pady=9)
        recent_panel.pack(fill="both", expand=True, pady=(0, 9))
        self._label(recent_panel, "RECENT CLASSIFICATIONS · LATEST 60",
                    bg="panel", fg="bright", font=("Consolas", 9, "bold")).pack(anchor="w", pady=(0, 6))
        recent_columns = ("timestamp", "close", "regime", "er", "slope", "atr_ratio", "tr_multiple", "forward")
        self.regime_recent_tree = ttk.Treeview(
            recent_panel, columns=recent_columns, show="headings", height=12,
            style="Veltrix.Regime.Treeview", selectmode="browse",
        )
        recent_headings = {
            "timestamp": ("BAR TIME · UTC", 155), "close": ("CLOSE", 85),
            "regime": ("REGIME", 145), "er": ("ER", 65), "slope": ("SLOPE / ATR", 85),
            "atr_ratio": ("ATR RATIO", 80), "tr_multiple": ("TR / PRIOR ATR", 90),
            "forward": ("FWD RETURN %", 95),
        }
        for key, (heading, width) in recent_headings.items():
            self.regime_recent_tree.heading(key, text=heading)
            self.regime_recent_tree.column(key, width=width, minwidth=60, anchor="center",
                                           stretch=(key == "timestamp"))
        recent_scroll = ttk.Scrollbar(recent_panel, orient="vertical", command=self.regime_recent_tree.yview)
        self.regime_recent_tree.configure(yscrollcommand=recent_scroll.set)
        self.regime_recent_tree.pack(side="left", fill="both", expand=True)
        recent_scroll.pack(side="right", fill="y")

        methodology = self._frame(self.regime_content, bg="panel", padx=12, pady=9)
        methodology.pack(fill="x", pady=(0, 8))
        self._label(
            methodology,
            "METHODOLOGY: Each bar is classified using only its own and earlier completed OHLC bars. Efficiency ratio measures net displacement / total path; trend slope is normalised by slow ATR; volatility shocks use fast/slow ATR and current true range versus prior slow ATR. Forward returns are calculated only after labels are fixed and are historical conditional outcomes, not predictions or trade signals. Thresholds are research parameters, not universal gold constants. Results depend on feed, symbol, bar construction, interval, missing data and transaction-cost assumptions.",
            bg="panel", fg="muted", font=("Segoe UI", 8), justify="left", wraplength=980,
        ).pack(fill="x")
        self._apply_regime_tree_theme()

    def _start_regime_cache_load(self) -> None:
        """Load the compact Regime dataset store, migrating compatible old OHLC caches once."""
        def worker() -> None:
            try:
                payload = load_regime_datasets(REGIME_DATA_PATH, LEGACY_RESEARCH_CACHE_PATH)
            except Exception:
                payload = {"datasets": {}, "migrated_from_legacy": False, "skipped_tick_datasets": 0}
            self.regime_cache_load_queue.put(payload)

        threading.Thread(target=worker, name="VeltrixRegimeCacheLoader", daemon=True).start()

    def _drain_regime_cache_load_results(self) -> None:
        if self.is_closing:
            return
        try:
            payload = self.regime_cache_load_queue.get_nowait()
        except queue.Empty:
            self.regime_cache_load_job = self.root.after(UI_QUEUE_POLL_MS, self._drain_regime_cache_load_results)
            return

        self.regime_datasets = dict(payload.get("datasets", {}))
        self.regime_cache_loading = False
        self.regime_import_button.configure(state="normal")
        self._refresh_regime_dataset_choices(
            preferred_key=str(self.regime_settings.get("selected_asset") or "")
        )
        if payload.get("migrated_from_legacy"):
            self._save_regime_cache()
        count = len(self.regime_datasets)
        skipped = int(payload.get("skipped_tick_datasets", 0) or 0)
        if count:
            note = f" · {skipped} LEGACY TICK-BAR DATASET(S) LEFT IN THE OLD CACHE" if skipped else ""
            self.regime_status_label.configure(
                text=f"LOCAL OHLC DATA READY · {count} DATASET(S) · IMPORTS STAY ON THIS DEVICE{note}",
                fg=THEMES[self.theme_name]["success"],
            )
        else:
            self.regime_status_label.configure(
                text="NO LOCAL OHLC DATASET · IMPORT A COMPLETED OHLC CSV TO BEGIN",
                fg=THEMES[self.theme_name]["warning"],
            )

    def _regime_cache_writer_loop(self) -> None:
        """Serialise local Regime datasets away from the Tk event loop."""
        while True:
            payload = self.regime_cache_write_queue.get()
            try:
                if payload is None:
                    return
                save_regime_datasets(REGIME_DATA_PATH, payload)
            except Exception as exc:
                self.regime_import_result_queue.put({"error": f"Dataset save failed: {exc}"})
            finally:
                self.regime_cache_write_queue.task_done()

    def _save_regime_cache(self) -> None:
        snapshot = {key: dict(value) for key, value in self.regime_datasets.items()}
        try:
            self.regime_cache_write_queue.put_nowait(snapshot)
        except queue.Full:
            try:
                self.regime_cache_write_queue.get_nowait()
                self.regime_cache_write_queue.task_done()
            except queue.Empty:
                pass
            self.regime_cache_write_queue.put_nowait(snapshot)

    def _refresh_regime_dataset_choices(self, preferred_key: str | None = None) -> None:
        labels: list[str] = []
        mapping: dict[str, str] = {}
        for key, dataset in self.regime_datasets.items():
            if not isinstance(dataset, dict) or not dataset.get("bars"):
                continue
            name = str(dataset.get("name") or key).strip()
            symbol = str(dataset.get("symbol") or "").strip()
            source = str(dataset.get("source") or "Local CSV").strip()
            label = f"{name} · {symbol} · {source}" if symbol else f"{name} · {source}"
            if label in mapping:
                label = f"{label} · {key}"
            labels.append(label)
            mapping[label] = str(key)
        self.regime_dataset_label_to_key = mapping
        if hasattr(self, "regime_asset_combo"):
            self.regime_asset_combo.configure(values=labels)
        requested = str(preferred_key if preferred_key is not None else self.regime_settings.get("selected_asset") or "")
        target = next((label for label, key in mapping.items() if key == requested), "")
        if not target and labels:
            target = labels[0]
        self.regime_asset_var.set(target)
        self.regime_settings["selected_asset"] = mapping.get(target, "")
        refresh_session_performance_dataset_choices(self)

    def import_regime_csv(self) -> None:
        if self.regime_cache_loading or self.regime_import_in_progress:
            return
        path = filedialog.askopenfilename(
            parent=self.root, title="Import OHLC history for Regime Lab",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if not path:
            return
        default_name = Path(path).stem.replace("_", " ").replace("-", " ").strip().title()
        name = simpledialog.askstring(
            "Name OHLC dataset", "Dataset / instrument name:",
            initialvalue=default_name, parent=self.root,
        )
        if name is None or not name.strip():
            return
        name = name.strip()
        asset_key = f"regime_{uuid4().hex[:12]}"
        timezone_name = self.home_zone.key
        self.regime_import_in_progress = True
        self.regime_import_button.configure(state="disabled")
        self.regime_status_label.configure(
            text=f"IMPORTING {Path(path).name} · NAIVE CSV TIMES ASSUMED {timezone_name}",
            fg=THEMES[self.theme_name]["warning"],
        )

        def worker() -> None:
            try:
                bars, import_meta = import_ohlc_csv(path, naive_timezone=timezone_name)
                record = {
                    "bars": [bar.to_dict() for bar in bars],
                    "source": f"Local CSV · {Path(path).name}",
                    "name": name,
                    "symbol": "",
                    "unit": "source price units",
                    "bar_interval_minutes": infer_bar_interval_minutes(bars),
                    "metadata": {**import_meta, "imported_for": "regime_lab"},
                }
                self.regime_import_result_queue.put({"asset_key": asset_key, "record": record, "error": None})
            except Exception as exc:
                self.regime_import_result_queue.put({"asset_key": asset_key, "record": None, "error": str(exc)})

        threading.Thread(target=worker, name="VeltrixRegimeCSVImport", daemon=True).start()

    def _drain_regime_import_results(self) -> None:
        if self.is_closing:
            return
        try:
            while True:
                result = self.regime_import_result_queue.get_nowait()
                if result.get("error"):
                    self.regime_import_in_progress = False
                    self.regime_import_button.configure(state="normal")
                    self.regime_status_label.configure(
                        text=f"REGIME DATA TASK FAILED · {result['error']}",
                        fg=THEMES[self.theme_name]["error"],
                    )
                    continue
                key = str(result["asset_key"])
                record = result["record"]
                if record is None:
                    continue
                self.regime_import_in_progress = False
                self.regime_import_button.configure(state="normal")
                self.regime_datasets[key] = record
                self._refresh_regime_dataset_choices(preferred_key=key)
                self._clear_regime_results()
                self._save_regime_cache()
                metadata = record.get("metadata", {})
                self.regime_status_label.configure(
                    text=f"OHLC DATASET IMPORTED · {record['name']} · {len(record['bars']):,} BARS · "
                         f"{metadata.get('invalid_rows', 0)} INVALID ROWS SKIPPED · SAVED LOCALLY",
                    fg=THEMES[self.theme_name]["success"],
                )
        except queue.Empty:
            pass
        if not self.is_closing:
            self.regime_import_queue_job = self.root.after(UI_QUEUE_POLL_MS, self._drain_regime_import_results)

    def _selected_regime_asset_key(self) -> str:
        label = self.regime_asset_var.get() if hasattr(self, "regime_asset_var") else ""
        return self.regime_dataset_label_to_key.get(label, str(self.regime_settings.get("selected_asset", "")))

    def _clear_regime_results(self) -> None:
        """Clear prior output so stale results can never be mistaken for a new run."""
        self.regime_result = None
        self.regime_result_metadata = {}
        if hasattr(self, "regime_export_button"):
            self.regime_export_button.configure(state="disabled")
        for key in ("bars", "classified", "range", "trend", "shock", "latest"):
            tile = getattr(self, "regime_metric_tiles", {}).get(key)
            if tile:
                tile["value"].configure(text="N/A")
        for tree_name in (
            "regime_distribution_tree", "regime_transition_tree", "regime_recent_tree"
        ):
            tree = getattr(self, tree_name, None)
            if tree is not None:
                for item in tree.get_children():
                    tree.delete(item)
        if hasattr(self, "regime_chart_canvas"):
            self._draw_regime_chart()

    def _regime_asset_changed(self) -> None:
        self._clear_regime_results()
        self.regime_status_label.configure(
            text="DATASET CHANGED · RUN REGIME ANALYSIS TO REFRESH CLASSIFICATIONS",
            fg=THEMES[self.theme_name]["warning"],
        )
        self.regime_settings["selected_asset"] = self._selected_regime_asset_key()

    def _collect_regime_config(self) -> RegimeConfig:
        integer_keys = {"lookback", "atr_fast_period", "atr_slow_period", "forward_horizon"}
        values: dict[str, Any] = {}
        for key, variable in self.regime_vars.items():
            raw = variable.get().strip()
            if key in integer_keys:
                values[key] = int(raw)
            else:
                values[key] = float(raw)
        return RegimeConfig(**values).validate()

    def save_regime_preferences(self) -> None:
        try:
            config = self._collect_regime_config()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Invalid regime parameters", str(exc), parent=self.root)
            return
        self.regime_settings.update(asdict(config))
        self.regime_settings["selected_asset"] = self._selected_regime_asset_key()
        self.config["regime_lab"] = dict(self.regime_settings)
        self._save_config()
        self.regime_status_label.configure(
            text="REGIME PARAMETERS SAVED · NO TRADING SIGNALS OR ORDERS ARE GENERATED",
            fg=THEMES[self.theme_name]["success"],
        )

    def run_regime_analysis(self) -> None:
        if self.regime_in_progress:
            return
        if self.regime_cache_loading:
            self.regime_status_label.configure(
                text="LOCAL OHLC DATASET LIBRARY IS STILL LOADING · PLEASE RETRY",
                fg=THEMES[self.theme_name]["warning"],
            )
            return
        asset_key = self._selected_regime_asset_key()
        dataset = self.regime_datasets.get(asset_key)
        bars = list(dataset.get("bars", [])) if isinstance(dataset, dict) else []
        if not bars:
            messagebox.showwarning(
                "No historical bars",
                "Import an OHLC CSV in Regime Lab before running regime analysis.",
                parent=self.root,
            )
            return
        try:
            config = self._collect_regime_config()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Invalid regime parameters", str(exc), parent=self.root)
            return

        self.save_regime_preferences()
        metadata = {
            "key": asset_key,
            "name": str(dataset.get("name") or asset_key),
            "symbol": str(dataset.get("symbol") or ""),
            "source": str(dataset.get("source") or "Unknown source"),
            "bar_interval_minutes": dataset.get("bar_interval_minutes"),
            "variable_interval_bars": bool(dataset.get("variable_interval_bars", False)),
        }
        snapshot = tuple(dict(item) if isinstance(item, dict) else item for item in bars)
        self._clear_regime_results()
        self.regime_in_progress = True
        self.regime_run_button.configure(state="disabled")
        self.regime_export_button.configure(state="disabled")
        self.regime_status_label.configure(
            text=f"CLASSIFYING {len(snapshot):,} BARS IN BACKGROUND · {metadata['name']} · UI REMAINS RESPONSIVE",
            fg=THEMES[self.theme_name]["warning"],
        )

        def worker() -> None:
            try:
                result = analyse_market_regimes(snapshot, config)
                self.regime_result_queue.put((asset_key, metadata, result, None))
            except Exception as exc:
                self.regime_result_queue.put((asset_key, metadata, None, str(exc)))

        threading.Thread(target=worker, name="VeltrixRegimeResearch", daemon=True).start()

    def _drain_regime_results(self) -> None:
        if self.is_closing:
            return
        try:
            while True:
                asset_key, metadata, result, error = self.regime_result_queue.get_nowait()
                self.regime_in_progress = False
                self.regime_run_button.configure(state="normal")
                if asset_key != self._selected_regime_asset_key():
                    self.regime_status_label.configure(
                        text="ANALYSIS COMPLETED FOR A PREVIOUS DATASET SELECTION · SELECT IT TO VIEW OR RERUN",
                        fg=THEMES[self.theme_name]["warning"],
                    )
                    continue
                if error or result is None:
                    self.regime_status_label.configure(
                        text=f"REGIME ANALYSIS FAILED · {error or 'Unknown analysis error'}",
                        fg=THEMES[self.theme_name]["error"],
                    )
                    continue
                self.regime_result = result
                self.regime_result_metadata = metadata
                self._display_regime_results()
        except queue.Empty:
            pass
        self.regime_queue_job = self.root.after(UI_QUEUE_POLL_MS, self._drain_regime_results)

    @staticmethod
    def _format_regime_number(value: Any, digits: int = 3, suffix: str = "") -> str:
        if value is None:
            return "N/A"
        try:
            number = float(value)
            if not math.isfinite(number):
                return "N/A"
            return f"{number:.{digits}f}{suffix}"
        except (TypeError, ValueError):
            return "N/A"

    def _display_regime_results(self) -> None:
        if not self.regime_result:
            return
        result = self.regime_result
        metadata = self.regime_result_metadata
        summary = result["metadata"]
        distribution = result["distribution"]
        trend_count = distribution["TREND_UP"]["count"] + distribution["TREND_DOWN"]["count"]
        shock_pct = distribution["VOLATILITY_SHOCK"]["frequency_pct"]
        latest = result["latest"]
        self.regime_metric_tiles["bars"]["value"].configure(text=f"{summary['valid_bars']:,}")
        self.regime_metric_tiles["classified"]["value"].configure(text=f"{summary['classified_bars']:,}")
        self.regime_metric_tiles["range"]["value"].configure(
            text=f"{distribution['RANGE']['frequency_pct']:.1f}%")
        self.regime_metric_tiles["trend"]["value"].configure(
            text=f"{trend_count / max(1, summary['classified_bars']) * 100.0:.1f}%")
        self.regime_metric_tiles["shock"]["value"].configure(text=f"{shock_pct:.1f}%")
        self.regime_metric_tiles["latest"]["value"].configure(text=str(latest["regime"]))

        first = summary.get("first_timestamp_utc", "")
        last = summary.get("last_timestamp_utc", "")
        interval = metadata.get("bar_interval_minutes")
        interval_text = f" · {interval:g}m" if isinstance(interval, (int, float)) and interval > 0 else ""
        variable_text = " · VARIABLE-INTERVAL BARS" if metadata.get("variable_interval_bars") else ""
        self.regime_status_label.configure(
            text=(f"ANALYSIS COMPLETE · {metadata.get('name', metadata.get('key', 'DATASET'))} · "
                  f"{metadata.get('symbol', '')} · {metadata.get('source', '')}{interval_text}{variable_text} · "
                  f"{summary['valid_bars']:,} valid bars · {summary['warmup_bars']:,} warm-up · "
                  f"{first} → {last} · LABELS USE NO FUTURE DATA"),
            fg=THEMES[self.theme_name]["success"],
        )

        for tree in (self.regime_distribution_tree, self.regime_transition_tree, self.regime_recent_tree):
            for item in tree.get_children():
                tree.delete(item)
        for regime in ("RANGE", "TREND_UP", "TREND_DOWN", "VOLATILITY_SHOCK", "TRANSITION"):
            freq = distribution[regime]
            outcome = result["outcomes"][regime]
            self.regime_distribution_tree.insert("", "end", values=(
                regime, freq["count"], f"{freq['frequency_pct']:.1f}", outcome["samples"],
                self._format_regime_number(outcome["mean_return_pct"], 3),
                self._format_regime_number(outcome["median_return_pct"], 3),
                self._format_regime_number(outcome["positive_rate_pct"], 1),
            ), tags=(regime.lower(),))

        transition_keys = {
            "RANGE": "range", "TREND_UP": "up", "TREND_DOWN": "down",
            "VOLATILITY_SHOCK": "shock", "TRANSITION": "transition",
        }
        for regime in ("RANGE", "TREND_UP", "TREND_DOWN", "VOLATILITY_SHOCK", "TRANSITION"):
            row = result["transitions"][regime]
            self.regime_transition_tree.insert("", "end", values=(
                regime, row["RANGE"], row["TREND_UP"], row["TREND_DOWN"],
                row["VOLATILITY_SHOCK"], row["TRANSITION"],
            ), tags=(regime.lower(),))

        for record in reversed(result["records"][-60:]):
            stamp = str(record["timestamp_utc"]).replace("T", " ").replace("+00:00", "")
            self.regime_recent_tree.insert("", "end", values=(
                stamp, f"{record['close']:.3f}", record["regime"],
                self._format_regime_number(record["efficiency_ratio"], 3),
                self._format_regime_number(record["normalised_slope_atr"], 3),
                self._format_regime_number(record["volatility_ratio"], 3),
                self._format_regime_number(record["true_range_vs_prior_atr"], 2),
                self._format_regime_number(record["forward_return_pct"], 3),
            ), tags=(str(record["regime"]).lower(),))
        self.regime_export_button.configure(state="normal")
        self._draw_regime_chart()

    def _draw_regime_chart(self) -> None:
        if not hasattr(self, "regime_chart_canvas"):
            return
        canvas = self.regime_chart_canvas
        canvas.delete("all")
        palette = THEMES[self.theme_name]
        width = max(300, canvas.winfo_width())
        height = max(180, canvas.winfo_height())
        left, right, top, bottom = 66, 16, 18, 28
        plot_width = max(10, width - left - right)
        plot_height = max(10, height - top - bottom)
        canvas.create_rectangle(0, 0, width, height, fill=palette["panel"], outline="")
        if not self.regime_result:
            canvas.create_text(width / 2, height / 2, text="RUN REGIME ANALYSIS TO DISPLAY HISTORICAL CLASSIFICATIONS",
                               fill=palette["muted"], font=("Consolas", 9, "bold"))
            return
        records = self.regime_result["records"][-250:]
        if len(records) < 2:
            canvas.create_text(width / 2, height / 2, text="INSUFFICIENT CLASSIFIED HISTORY",
                               fill=palette["muted"], font=("Consolas", 9, "bold"))
            return
        prices = [float(item["close"]) for item in records]
        low, high = min(prices), max(prices)
        if high <= low:
            padding = max(abs(high) * 0.001, 0.01)
            low -= padding
            high += padding
        colors = {
            "RANGE": palette["bright"], "TREND_UP": palette["success"],
            "TREND_DOWN": palette["error"], "VOLATILITY_SHOCK": palette["warning"],
            "TRANSITION": palette["muted"], "WARMUP": palette["muted"],
        }
        for grid_index in range(5):
            y = top + plot_height * grid_index / 4
            price = high - (high - low) * grid_index / 4
            canvas.create_line(left, y, width - right, y, fill=palette["border"], dash=(2, 4))
            canvas.create_text(left - 8, y, text=f"{price:.2f}", fill=palette["muted"],
                               anchor="e", font=("Consolas", 7))
        points = []
        for index, record in enumerate(records):
            x = left + plot_width * index / (len(records) - 1)
            y = top + plot_height * (high - float(record["close"])) / (high - low)
            points.append((x, y))
        for index in range(1, len(points)):
            regime = records[index]["regime"]
            canvas.create_line(*points[index - 1], *points[index], fill=colors.get(regime, palette["text"]),
                               width=2)
        band_y = height - 13
        band_width = plot_width / len(records)
        for index, record in enumerate(records):
            x0 = left + index * band_width
            canvas.create_rectangle(x0, band_y, x0 + max(1, band_width + 0.4), height - 5,
                                    fill=colors.get(record["regime"], palette["muted"]), outline="")
        canvas.create_text(left, height - 2, text="OLDER", fill=palette["muted"],
                           anchor="sw", font=("Consolas", 7))
        canvas.create_text(width - right, height - 2, text="LATEST", fill=palette["muted"],
                           anchor="se", font=("Consolas", 7))

    def export_regime_results(self) -> None:
        if not self.regime_result:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export causal regime classifications", defaultextension=".csv",
            initialfile="veltrix_regime_analysis.csv", filetypes=(("CSV files", "*.csv"),),
        )
        if path:
            try:
                export_regime_analysis_csv(path, self.regime_result)
                self.regime_status_label.configure(
                    text=f"REGIME CSV EXPORTED · {Path(path).name} · FORWARD OUTCOMES ARE DESCRIPTIVE ONLY",
                    fg=THEMES[self.theme_name]["success"],
                )
            except OSError as exc:
                messagebox.showerror("Export failed", str(exc), parent=self.root)

    def _apply_regime_tree_theme(self) -> None:
        palette = THEMES[self.theme_name]
        style = ttk.Style(self.root)
        style.configure(
            "Veltrix.Regime.Treeview", background=palette["bg"], foreground=palette["text"],
            fieldbackground=palette["bg"], rowheight=25, bordercolor=palette["border"],
            font=("Consolas", 8),
        )
        style.configure(
            "Veltrix.Regime.Treeview.Heading", background=palette["panel"], foreground=palette["bright"],
            relief="flat", font=("Consolas", 8, "bold"),
        )
        style.map("Veltrix.Regime.Treeview", background=[("selected", palette["button_active"])],
                  foreground=[("selected", palette["bright"])])
        style.configure("Veltrix.Regime.TCombobox", fieldbackground=palette["entry_bg"],
                        background=palette["button_bg"], foreground=palette["entry_fg"],
                        arrowcolor=palette["bright"])
        if hasattr(self, "regime_canvas"):
            self.regime_canvas.configure(bg=palette["bg"])
        if hasattr(self, "regime_chart_canvas"):
            self.regime_chart_canvas.configure(bg=palette["panel"], highlightbackground=palette["border"])
        tags = {
            "range": palette["bright"], "trend_up": palette["success"],
            "trend_down": palette["error"], "volatility_shock": palette["warning"],
            "transition": palette["muted"], "warmup": palette["muted"],
        }
        for tree_name in ("regime_distribution_tree", "regime_transition_tree", "regime_recent_tree"):
            tree = getattr(self, tree_name, None)
            if tree is not None:
                for tag, colour in tags.items():
                    tree.tag_configure(tag, foreground=colour)

    def save_market_preferences(self) -> None:
        try:
            expansion = float(self.market_expansion_var.get())
            contraction = float(self.market_contraction_var.get())
            if not 1.1 <= expansion <= 5.0 or not 0.1 <= contraction <= 0.99:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid volatility thresholds",
                "Expansion must be 1.1–5.0x and contraction must be 0.10–0.99x.", parent=self.root)
            return
        if contraction >= expansion:
            messagebox.showerror("Invalid volatility thresholds",
                "The contraction threshold must be lower than the expansion threshold.", parent=self.root)
            return
        self.market_settings.update({
            "regime_alerts_enabled": bool(self.market_regime_enabled_var.get()),
            "expansion_multiple": expansion, "contraction_multiple": contraction,
        })
        self.config["market_data"] = dict(self.market_settings)
        self._save_config()
        self.market_status_label.configure(text="VOLATILITY SETTINGS SAVED", fg=THEMES[self.theme_name]["success"])

    def refresh_market_data(self, silent: bool = False) -> None:
        if self.market_fetch_in_progress:
            return
        now_monotonic = time.monotonic()
        if self.market_last_attempt_monotonic is not None:
            elapsed = now_monotonic - self.market_last_attempt_monotonic
            if elapsed < 60:
                remaining = int(60 - elapsed)
                if not silent:
                    self.market_status_label.configure(
                        text=f"MARKET DATA COOLDOWN · RETRY IN {remaining:02d}s", fg=THEMES[self.theme_name]["warning"]
                    )
                return
        self.market_fetch_in_progress = True
        self.market_last_attempt_monotonic = now_monotonic
        self.refresh_market_button.configure(state="disabled", text="FETCHING...")
        if not silent:
            self.market_status_label.configure(text="FETCHING INTRADAY AND DAILY BARS...", fg=THEMES[self.theme_name]["warning"])
        instruments = [dict(item) for item in self.market_instruments]
        interval = str(self.market_settings.get("interval", "5m"))
        intraday_range = str(self.market_settings.get("intraday_range", "5d"))
        daily_range = str(self.market_settings.get("daily_range", "3mo"))

        def worker() -> None:
            try:
                payload = fetch_market_snapshot(instruments, interval=interval,
                    intraday_range=intraday_range, daily_range=daily_range)
                result = (payload, None)
            except Exception as exc:
                result = (None, str(exc))
            self.market_result_queue.put(result)

        threading.Thread(target=worker, name="VeltrixMarketDataFetch", daemon=True).start()

    def _drain_market_results(self) -> None:
        if self.is_closing:
            return
        while True:
            try:
                payload, error = self.market_result_queue.get_nowait()
            except queue.Empty:
                break
            self._on_market_fetch_complete(payload, error)
        self.market_queue_job = self.root.after(UI_QUEUE_POLL_MS, self._drain_market_results)

    def _schedule_market_auto_refresh(self) -> None:
        if self.is_closing:
            return
        minutes = max(5, min(60, int(self.market_settings.get("refresh_minutes", 5))))
        self.market_auto_refresh_job = self.root.after(minutes * 60_000, self._run_market_auto_refresh)

    def _run_market_auto_refresh(self) -> None:
        self.market_auto_refresh_job = None
        self.refresh_market_data(silent=True)
        self._schedule_market_auto_refresh()

    def _on_market_fetch_complete(self, payload: dict | None, error: str | None) -> None:
        if self.is_closing:
            return
        self.market_fetch_in_progress = False
        self.refresh_market_button.configure(state="normal", text="REFRESH MARKET DATA")
        if error:
            self.market_is_fresh = False
            self.market_status_label.configure(text=f"MARKET DATA UPDATE FAILED · {error[:145]}",
                                               fg=THEMES[self.theme_name]["error"])
            self.market_freshness_label.configure(
                text="OFFLINE / STALE MODE · Cached observations remain visible; regime alerts are paused."
            )
            return
        self.market_snapshot = payload or {"assets": {}, "fetched_at": ""}
        self.market_is_fresh = True
        try:
            save_market_cache(MARKET_CACHE_PATH, self.market_snapshot)
        except OSError as exc:
            self.market_status_label.configure(text=f"DATA RECEIVED · CACHE WRITE FAILED: {exc}",
                                               fg=THEMES[self.theme_name]["warning"])
        assets = self.market_snapshot.get("assets", {})
        partial_errors = sum(bool(asset.get("error")) for asset in assets.values())
        status = "CONNECTED" if not partial_errors else f"PARTIAL DATA · {partial_errors} INSTRUMENT(S) WITH GAPS"
        self.market_status_label.configure(text=f"{status} · YAHOO FINANCE CHART DATA",
                                           fg=THEMES[self.theme_name]["success" if not partial_errors else "warning"])
        fetched = str(self.market_snapshot.get("fetched_at", ""))
        try:
            local_fetched = datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(self.home_zone)
            fetched_text = local_fetched.strftime("%d %b %Y %H:%M:%S %Z")
        except (ValueError, TypeError):
            fetched_text = "timestamp unavailable"
        self.market_freshness_label.configure(
            text=f"Fetch completed: {fetched_text} · 5-minute bars · auto-refresh: 5 min · manual retry: 60 sec · Indicative data only"
        )
        self._render_market_snapshot()
        self._emit_market_regime_alerts()

    def _render_market_snapshot(self) -> None:
        if not hasattr(self, "market_tree"):
            return
        assets = self.market_snapshot.get("assets", {}) if isinstance(self.market_snapshot, dict) else {}
        self.market_tree.delete(*self.market_tree.get_children())
        self.market_reports = {}
        self.market_summaries = {}
        now_utc = datetime.now(timezone.utc)
        for instrument in self.market_instruments:
            key = str(instrument["key"])
            asset = assets.get(key, {**instrument, "intraday_bars": [], "daily_bars": [], "error": ""})
            summary = instrument_summary(
                asset, atr_period=int(self.market_settings.get("atr_period", 14)),
                expected_move_lookback=int(self.market_settings.get("expected_move_lookback", 20)),
            )
            self.market_summaries[key] = summary
            reports = session_volatility_report(
                asset.get("intraday_bars", []), self.sessions, now=now_utc,
                baseline_sessions=int(self.market_settings.get("baseline_sessions", 3)),
                expansion_multiple=float(self.market_settings.get("expansion_multiple", 1.5)),
                contraction_multiple=float(self.market_settings.get("contraction_multiple", 0.67)),
            )
            for report in reports:
                report["asset_name"] = instrument.get("name", key)
            self.market_reports[key] = reports

            card = self.market_asset_cards.get(key)
            if card:
                quote = summary.get("quote")
                unit = str(instrument.get("unit", ""))
                card["price"].configure(text=(f"{quote:,.2f} {unit}" if quote is not None else "NO QUOTE DATA"))
                atr = summary.get("atr")
                card["atr"].configure(text=(f"ATR(14): {atr:,.2f} {unit}" if atr is not None else "ATR(14): N/A · NEED 15+ DAILY BARS"))
                expected = summary.get("expected_move", {})
                move, pct = expected.get("expected_move_abs"), expected.get("expected_move_pct")
                if move is not None and pct is not None:
                    expected_text = f"1D 1σ MOVE: ±{move:,.2f} ({pct:.2f}%)"
                else:
                    expected_text = "1D 1σ MOVE: N/A · NEED MORE HISTORY"
                card["expected"].configure(text=expected_text)
                quote_time = summary.get("quote_time")
                if quote_time:
                    try:
                        quote_dt = datetime.fromisoformat(quote_time).astimezone(self.home_zone)
                        time_text = f"Last bar: {quote_dt.strftime('%d %b %H:%M %Z')}"
                    except ValueError:
                        time_text = "Last bar timestamp unavailable"
                else:
                    time_text = "No quote loaded"
                if summary.get("error"):
                    time_text += " · PARTIAL"
                if not self.market_is_fresh:
                    time_text += " · CACHED"
                card["quote_time"].configure(text=time_text)

            for report in reports:
                rv = report.get("realised_vol_pct")
                range_pct = report.get("range_pct")
                regime = str(report.get("regime", "NO DATA"))
                if regime == "EXPANSION":
                    tag = "expansion"
                elif regime == "CONTRACTION":
                    tag = "contraction"
                elif report.get("state") == "NO DATA":
                    tag = "nodata"
                else:
                    tag = "normal"
                rv_text = f"{rv:.3f}%" if rv is not None else "N/A"
                range_text = f"{range_pct:.3f}%" if range_pct is not None else "N/A"
                bars_text = f"{report.get('bars', 0)} / {report.get('returns', 0)}"
                regime_text = regime
                if report.get("ratio") is not None:
                    regime_text += f" · {report['ratio']:.2f}x"
                date_value = str(report.get("date", ""))
                short_date = date_value[5:] if len(date_value) >= 10 else date_value
                observation = ("LIVE" if report.get("state") == "LIVE SESSION" else
                               "LAST" if report.get("state") == "LAST SESSION" else "NO DATA")
                if short_date and observation != "NO DATA":
                    observation += f" · {short_date}"
                self.market_tree.insert("", "end", values=(
                    instrument.get("name", key), report.get("session_name", ""), rv_text,
                    range_text, bars_text, regime_text, observation,
                ), tags=(tag,))
        if not self.market_snapshot.get("assets"):
            self.market_status_label.configure(text="NO MARKET SNAPSHOT · PRESS REFRESH TO LOAD DATA",
                                               fg=THEMES[self.theme_name]["warning"])
        elif not self.market_is_fresh:
            self.market_status_label.configure(text="CACHED MARKET SNAPSHOT · LIVE DATA NOT VERIFIED THIS RUN",
                                               fg=THEMES[self.theme_name]["warning"])

    def _emit_market_regime_alerts(self) -> None:
        if not self.market_is_fresh or not bool(self.market_settings.get("regime_alerts_enabled", True)):
            return
        for asset_key, reports in self.market_reports.items():
            asset_name = next((item.get("name", asset_key) for item in self.market_instruments
                               if item.get("key") == asset_key), asset_key)
            for report in reports:
                regime = report.get("regime")
                if regime not in {"EXPANSION", "CONTRACTION"}:
                    continue
                key = f"{asset_key}:{report.get('session_key')}:{report.get('date')}:{regime}"
                if key in self.market_regime_alerted:
                    continue
                self.market_regime_alerted.add(key)
                ratio = float(report.get("ratio") or 0.0)
                current = float(report.get("realised_vol_pct") or 0.0)
                baseline = float(report.get("baseline_pct") or 0.0)
                title = f"VOLATILITY {regime} · {asset_name} · {report.get('session_name', '')}"
                message = (f"Session realised volatility is {ratio:.2f}x its same-time historical median "
                           f"({current:.3f}% vs {baseline:.3f}%). Descriptive monitor only; not a trade signal.")
                self._emit_alert(title, message, "warning" if regime == "EXPANSION" else "info")
                try:
                    if self.market_alert_listbox.size() == 1 and "No expansion" in self.market_alert_listbox.get(0):
                        self.market_alert_listbox.delete(0)
                    self.market_alert_listbox.insert("end", f"{datetime.now(self.home_zone).strftime('%H:%M:%S')} · {title} · {ratio:.2f}x")
                    self.market_alert_listbox.see("end")
                except tk.TclError:
                    pass

    def show_page(self, page: str) -> None:
        page_map = {
            "sessions": (self.sessions_view, self.sessions_nav_button),
            "session_performance": (self.session_performance_view, self.session_performance_nav_button),
            "alerts": (self.alerts_view, self.alerts_nav_button),
            "calendar": (self.calendar_view, self.calendar_nav_button),
            "volatility": (self.volatility_view, self.volatility_nav_button),
            "regime": (self.regime_view, self.regime_nav_button),
            "focus": (self.focus_view, self.focus_nav_button),
        }
        if page not in page_map:
            page = "sessions"
        for view in (
            self.sessions_view, self.session_performance_view, self.alerts_view,
            self.calendar_view, self.volatility_view, self.regime_view, self.focus_view,
        ):
            view.pack_forget()
        active_view, active_button = page_map[page]
        active_view.pack(fill="both", expand=True)
        palette = THEMES[self.theme_name]
        for _name, (_view, button) in page_map.items():
            if button is active_button:
                button.configure(bg=palette["button_active"], fg=palette["bright"])
            else:
                button.configure(bg=palette["button_bg"], fg=palette["button_fg"])
        self.current_page = page
        if page == "volatility" and hasattr(self, "volatility_canvas"):
            self.volatility_canvas.yview_moveto(0.0)
        if page == "regime" and hasattr(self, "regime_canvas"):
            self.regime_canvas.yview_moveto(0.0)
            self._draw_regime_chart()
        if page == "session_performance" and hasattr(self, "session_performance_canvas"):
            self.session_performance_canvas.yview_moveto(0.0)
        if page == "focus" and hasattr(self, "focus_canvas"):
            self.focus_canvas.yview_moveto(0.0)
            self._refresh_focus_workspace()

    def _clear_calendar_search_placeholder(self, _event=None) -> None:
        if self.calendar_search_var.get() == "Search currency / event":
            self.calendar_search_var.set("")

    def _set_calendar_status(self, text: str, kind: str = "muted") -> None:
        if not hasattr(self, "calendar_status_label"):
            return
        palette = THEMES[self.theme_name]
        colour = {
            "success": palette["success"],
            "warning": palette["warning"],
            "error": palette["error"],
        }.get(kind, palette["muted"])
        self.calendar_status_label.configure(text=text, fg=colour)

    def save_calendar_preferences(self) -> None:
        try:
            reminder_minutes = max(0, min(1440, int(self.calendar_reminder_minutes_var.get())))
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid reminder lead", "Use a whole number from 0 to 1440 minutes.", parent=self.root)
            return
        self.calendar_settings["notify_high_impact"] = bool(self.calendar_reminder_enabled_var.get())
        self.calendar_settings["reminder_minutes"] = reminder_minutes
        self.config["calendar"] = dict(self.calendar_settings)
        self._save_config()
        self._set_calendar_status("CALENDAR REMINDER SETTINGS SAVED", "success")

    def refresh_live_calendar(self, silent: bool = False) -> None:
        if self.calendar_fetch_in_progress:
            return

        now_monotonic = time.monotonic()

        # A successful response observes the provider's 15-minute cache window.
        # Failed attempts use a separate short backoff and do not lock the user out
        # for 15 minutes.
        retry_after = self.calendar_retry_after_monotonic
        if retry_after is not None and now_monotonic < retry_after:
            remaining = max(1, int(retry_after - now_monotonic))
            if not silent:
                self._set_calendar_status(
                    f"RETRY COOLDOWN · TRY AGAIN IN {remaining:02d}s", "warning"
                )
            if self.calendar_auto_refresh_job is None:
                self._schedule_calendar_auto_refresh(delay_seconds=remaining + 1)
            return

        minimum_refresh = max(15, int(self.calendar_settings.get("refresh_minutes", 15)))
        if not calendar_is_due(
            self.calendar_last_fetch_monotonic,
            refresh_minutes=minimum_refresh,
            now=now_monotonic,
        ):
            remaining = max(
                1,
                int(minimum_refresh * 60 - (now_monotonic - self.calendar_last_fetch_monotonic)),
            )
            if not silent:
                self._set_calendar_status(
                    f"PROVIDER CACHE WINDOW · TRY AGAIN IN {remaining // 60:02d}:{remaining % 60:02d}",
                    "warning",
                )
            if self.calendar_auto_refresh_job is None:
                self._schedule_calendar_auto_refresh(delay_seconds=remaining + 1)
            return

        self.calendar_fetch_in_progress = True
        self.refresh_calendar_button.configure(state="disabled", text="REFRESHING...")
        if not silent:
            self._set_calendar_status("FETCHING PUBLIC ECONOMIC CALENDAR · 25s TIMEOUT · 1 RETRY", "warning")

        lookahead = max(1, min(30, int(self.calendar_settings.get("lookahead_days", 7))))

        def worker() -> None:
            try:
                payload = fetch_calendar(days=lookahead, timeout=25, retries=1)
                result = (payload, None)
            except Exception as exc:  # Network/provider failures never interrupt Tk's event loop.
                result = (None, str(exc))
            self.calendar_result_queue.put(result)

        threading.Thread(target=worker, name="VeltrixCalendarFetch", daemon=True).start()

    def _drain_calendar_results(self) -> None:
        """Transfer worker results to Tk only from the main event-loop thread."""
        if self.is_closing:
            return
        while True:
            try:
                payload, error = self.calendar_result_queue.get_nowait()
            except queue.Empty:
                break
            self._on_calendar_fetch_complete(payload, error)
        self.calendar_queue_job = self.root.after(UI_QUEUE_POLL_MS, self._drain_calendar_results)

    def _open_calendar_source(self) -> None:
        # Use a fixed HTTPS source URL instead of opening arbitrary URLs from feed data.
        webbrowser.open("https://showmytrades.com/tools/economic-calendar")

    def _on_calendar_fetch_complete(self, payload: dict | None, error: str | None) -> None:
        if self.is_closing:
            return
        self.calendar_fetch_in_progress = False
        self.refresh_calendar_button.configure(state="normal", text="REFRESH CALENDAR")
        if self.calendar_auto_refresh_job is not None:
            try:
                self.root.after_cancel(self.calendar_auto_refresh_job)
            except tk.TclError:
                pass
            self.calendar_auto_refresh_job = None

        if error:
            # Exponential backoff: 30s, 60s, 120s ... capped at 15 minutes.
            # This is deliberately independent of the provider's successful-fetch cache floor.
            self.calendar_retry_count = min(self.calendar_retry_count + 1, 6)
            retry_delay = calendar_retry_delay_seconds(self.calendar_retry_count)
            self.calendar_retry_after_monotonic = time.monotonic() + retry_delay
            self._set_calendar_status(
                f"CALENDAR UPDATE FAILED · {error[:105]} · RETRY IN {retry_delay}s", "error"
            )
            if self.calendar_last_updated:
                self.calendar_freshness_label.configure(
                    text="OFFLINE MODE · Showing cached events. Confirm freshness before trading."
                )
            else:
                self.calendar_freshness_label.configure(
                    text="OFFLINE · No cached snapshot is available. Check your connection and retry later."
                )
            self._schedule_calendar_auto_refresh(delay_seconds=retry_delay)
            return

        self.calendar_retry_count = 0
        self.calendar_retry_after_monotonic = None
        self.calendar_payload = payload or {}
        self.calendar_events = list(self.calendar_payload.get("events", []))
        self.calendar_last_updated = str(self.calendar_payload.get("fetched_at", ""))
        self.calendar_last_fetch_monotonic = time.monotonic()
        try:
            save_calendar_cache(CALENDAR_CACHE_PATH, self.calendar_payload)
        except OSError as exc:
            self._set_calendar_status(f"DATA RECEIVED · CACHE WRITE FAILED: {exc}", "warning")
        else:
            self._set_calendar_status(
                f"CONNECTED · SHOWMYTRADES · {len(self.calendar_events)} EVENTS", "success"
            )
        updated = self.calendar_last_updated
        if updated:
            parsed = datetime.fromisoformat(updated.replace("Z", "+00:00")).astimezone(self.home_zone)
            generated = str(self.calendar_payload.get("generated_at", ""))
            self.calendar_freshness_label.configure(
                text=f"Fetched: {parsed.strftime('%d %b %Y %H:%M:%S %Z')} · Provider data timestamp: {generated or 'not supplied'} · Refresh cadence: 15 min."
            )
        attribution = self.calendar_payload.get("attribution", {})
        self.calendar_attribution_label.configure(
            text=str(attribution.get("text", "Economic calendar by ShowMyTrades")) + "  ·  VIEW SOURCE"
        )
        self._refresh_calendar_table()
        self._schedule_calendar_auto_refresh()

    def _schedule_calendar_auto_refresh(self, delay_seconds: int | None = None) -> None:
        if self.is_closing:
            return
        if delay_seconds is None:
            minutes = max(15, min(240, int(self.calendar_settings.get("refresh_minutes", 15))))
            delay_ms = minutes * 60_000
        else:
            delay_ms = max(1_000, int(delay_seconds * 1000))
        self.calendar_auto_refresh_job = self.root.after(delay_ms, self._run_calendar_auto_refresh)

    def _run_calendar_auto_refresh(self) -> None:
        self.calendar_auto_refresh_job = None
        self.refresh_live_calendar(silent=True)

    def _refresh_calendar_table(self) -> None:
        if not hasattr(self, "calendar_tree"):
            return
        self.calendar_tree.delete(*self.calendar_tree.get_children())
        impact_filter = self.calendar_filter_var.get() if hasattr(self, "calendar_filter_var") else "All impact levels"
        search = self.calendar_search_var.get().strip().lower() if hasattr(self, "calendar_search_var") else ""
        if search == "search currency / event":
            search = ""
        impact_map = {
            "High impact": "high", "Medium impact": "medium", "Low impact": "low", "Market holidays": "holiday",
        }
        required_impact = impact_map.get(impact_filter)
        visible = 0
        now_utc = datetime.now(timezone.utc)
        for event in sorted(self.calendar_events, key=lambda item: int(item.get("timestamp_utc", 0) or 0)):
            try:
                event_utc = datetime.fromtimestamp(int(event["timestamp_utc"]), tz=timezone.utc)
                local_time = event_utc.astimezone(self.home_zone)
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                continue
            if event_utc < now_utc - timedelta(hours=6):
                continue
            impact = str(event.get("impact", "unknown")).lower()
            if required_impact is not None and impact != required_impact:
                continue
            search_blob = " ".join((
                str(event.get("currency", "")), str(event.get("title", "")),
                str(event.get("period", "")), str(event.get("status", "")),
            )).lower()
            if search and search not in search_blob:
                continue
            impact_name = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW", "holiday": "HOLIDAY"}.get(impact, "N/A")
            title = str(event.get("title", "Unnamed release"))
            status = str(event.get("status", "scheduled")).upper()
            if status == "TENTATIVE":
                title = f"≈ {title}"
            if status == "MOVED":
                title = f"↪ {title}"
            tags = [impact if impact in {"high", "medium", "low", "holiday"} else "low"]
            if status == "TENTATIVE":
                tags.append("tentative")
            confidence = str(event.get("confidence", "")).replace("_", " ").upper()
            values = (
                local_time.strftime("%d %b %H:%M"), event.get("currency", ""), title,
                impact_name, event.get("previous", ""), event.get("forecast", ""),
                event.get("actual", ""), status, confidence,
            )
            self.calendar_tree.insert("", "end", values=values, tags=tuple(tags))
            visible += 1
        if hasattr(self, "calendar_count_label"):
            self.calendar_count_label.configure(text=f"{visible} / {len(self.calendar_events)} EVENTS")
        if not self.calendar_events and hasattr(self, "calendar_freshness_label"):
            self.calendar_freshness_label.configure(
                text="No cached calendar data yet. Select REFRESH CALENDAR to connect to the public feed."
            )

    def _poll_live_calendar_events(self, now_home: datetime) -> None:
        # Cached events remain visible offline, but live reminders require a successful
        # fetch during this run so an old cache cannot fire a stale release alert.
        if self.calendar_last_fetch_monotonic is None:
            return
        if not self.calendar_settings.get("notify_high_impact", True):
            return
        try:
            lead_minutes = max(0, min(1440, int(self.calendar_settings.get("reminder_minutes", 15))))
        except (ValueError, TypeError):
            lead_minutes = 15
        due_events = due_calendar_reminders(
            self.calendar_events,
            now_home,
            lead_minutes=lead_minutes,
            allowed_impacts={"high"},
            fired_keys=self.calendar_reminder_fired,
        )
        for event in due_events:
            event_time = datetime.fromtimestamp(int(event["timestamp_utc"]), tz=timezone.utc).astimezone(self.home_zone)
            confidence = str(event.get("confidence", "")).replace("_", " ").upper()
            confidence_note = f" · SOURCE CONFIDENCE: {confidence}" if confidence else ""
            self._emit_alert(
                f"HIGH-IMPACT RELEASE APPROACHING · {str(event.get('title', 'EVENT')).upper()}",
                f"{event.get('currency', '')} · {event_time.strftime('%d %b %Y %H:%M %Z')}{confidence_note}.",
                "event",
            )

    def save_alert_settings(self) -> None:
        for key, variable in self.alert_vars.items():
            self.alert_settings[key] = bool(variable.get())
        try:
            self.alert_settings["pre_open_minutes"] = max(1, min(180, int(self.pre_open_var.get())))
            self.alert_settings["pre_close_minutes"] = max(1, min(180, int(self.pre_close_var.get())))
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid alert lead time", "Enter whole minutes between 1 and 180.", parent=self.root)
            return
        session_overrides = {}
        try:
            for key, variables in self.session_lead_vars.items():
                session_overrides[key] = {
                    "pre_open_minutes": max(1, min(180, int(variables["pre_open"].get()))),
                    "pre_close_minutes": max(1, min(180, int(variables["pre_close"].get()))),
                }
            self.alert_settings["session_lead_overrides"] = session_overrides
            self.session_risk_settings.update({
                "enabled": bool(self.risk_enabled_var.get()),
                "notifications_enabled": bool(self.risk_notifications_var.get()),
                "holiday_liquidity_flags": bool(self.holiday_liquidity_var.get()),
                "opening_window_minutes": max(0, min(180, int(self.risk_opening_window_var.get()))),
                "closing_window_minutes": max(0, min(180, int(self.risk_closing_window_var.get()))),
                "pre_open_window_minutes": max(0, min(180, int(self.risk_pre_open_window_var.get()))),
            })
        except (ValueError, tk.TclError):
            messagebox.showerror(
                "Invalid session risk settings",
                "Session reminders must be whole minutes from 1–180. Risk windows must be 0–180.",
                parent=self.root,
            )
            return
        self.config["alerts"] = dict(self.alert_settings)
        self.config["session_risk"] = dict(self.session_risk_settings)
        self._save_config()
        self._set_alert_banner("ALERT AND SESSION RISK SETTINGS SAVED", "success")

    def add_economic_event(self) -> None:
        name = self.event_name_var.get().strip()
        raw_datetime = self.event_datetime_var.get().strip()
        if not name:
            messagebox.showerror("Missing event name", "Enter an event name, such as US CPI or FOMC Rate Decision.", parent=self.root)
            return
        try:
            local_naive = datetime.strptime(raw_datetime, "%Y-%m-%d %H:%M")
            scheduled = local_naive.replace(tzinfo=self.home_zone)
            now = datetime.now(self.home_zone)
            if scheduled <= now:
                raise ValueError("The event must be scheduled in the future.")
            lead_minutes = max(0, min(1440, int(self.event_lead_var.get())))
        except ValueError as exc:
            messagebox.showerror(
                "Invalid event date/time",
                f"Use YYYY-MM-DD HH:MM in {self.home_zone.key}.\n{exc}",
                parent=self.root,
            )
            return
        except tk.TclError:
            messagebox.showerror("Invalid reminder", "Reminder lead time must be a whole number.", parent=self.root)
            return

        event_id = f"event-{uuid4().hex}"
        self.economic_events.append({
            "id": event_id,
            "name": name,
            "datetime": local_naive.isoformat(timespec="minutes"),
            "reminder_minutes": lead_minutes,
        })
        self.event_name_var.set("")
        self.config["economic_events"] = self.economic_events
        self.config["event_reminder_minutes"] = lead_minutes
        self._save_config()
        self._refresh_economic_event_list()
        self._set_alert_banner(f"EVENT ADDED  ·  {name.upper()}", "success")

    def remove_economic_event(self) -> None:
        selection = self.event_listbox.curselection()
        if not selection:
            return
        upcoming = self._sorted_upcoming_events()
        index = selection[0]
        if index < len(upcoming):
            event = upcoming[index]
            self.economic_events = [item for item in self.economic_events if item.get("id") != event.get("id")]
            self.alerted_event_ids.discard(str(event.get("id")))
            self.config["economic_events"] = self.economic_events
            self._save_config()
            self._refresh_economic_event_list()
            self._set_alert_banner("EVENT REMOVED", "warning")

    def _sorted_upcoming_events(self) -> list[dict]:
        now = datetime.now(self.home_zone)
        upcoming = []
        for event in self.economic_events:
            try:
                event_time = datetime.fromisoformat(event["datetime"]).replace(tzinfo=self.home_zone)
            except (KeyError, TypeError, ValueError):
                continue
            if event_time > now:
                upcoming.append((event_time, event))
        return [event for _, event in sorted(upcoming, key=lambda item: item[0])]

    def _refresh_economic_event_list(self) -> None:
        if not hasattr(self, "event_listbox"):
            return
        self.event_listbox.delete(0, tk.END)
        upcoming = self._sorted_upcoming_events()
        if not upcoming:
            self.event_listbox.insert(tk.END, "No upcoming manual economic events.")
            return
        for event in upcoming:
            event_time = datetime.fromisoformat(event["datetime"]).replace(tzinfo=self.home_zone)
            self.event_listbox.insert(
                tk.END, f"{event_time.strftime('%d %b %Y  %H:%M')}  |  {event.get('name', 'Unnamed event')}"
            )

    def _poll_economic_events(self, now: datetime) -> None:
        for event in self.economic_events:
            event_id = str(event.get("id", ""))
            if not event_id or event_id in self.alerted_event_ids:
                continue
            try:
                event_time = datetime.fromisoformat(event["datetime"]).replace(tzinfo=self.home_zone)
                lead_minutes = max(0, int(event.get("reminder_minutes", self.config.get("event_reminder_minutes", 15))))
            except (KeyError, TypeError, ValueError):
                continue
            alert_at = event_time - timedelta(minutes=lead_minutes)
            if lead_minutes == 0:
                due = 0 <= (now - event_time).total_seconds() <= 90
            else:
                due = alert_at <= now < event_time
            if due:
                self.alerted_event_ids.add(event_id)
                self._emit_alert(
                    f"ECONOMIC EVENT APPROACHING  ·  {str(event.get('name', 'EVENT')).upper()}",
                    f"Scheduled for {event_time.strftime('%d %b %Y at %H:%M %Z')}.",
                    "event",
                )

    def _poll_market_alerts(self, now_utc: datetime, open_states: list) -> None:
        alerts = due_session_alerts(
            self.sessions, now_utc, self.alert_settings, self.alerted_session_keys,
            apply_exchange_calendar=self.exchange_calendar_enabled_var.get(),
        )
        for alert in alerts:
            self._emit_alert(alert.title, alert.message, alert.category)

        overlap_active = len(open_states) >= 2
        if (self.alert_settings.get("notify_overlap", True)
                and self.previous_overlap_active is False and overlap_active):
            names = " + ".join(state.definition.name for state in open_states)
            self._emit_alert("TRADING SESSION OVERLAP STARTED", f"Currently scheduled open: {names}.", "overlap")
        self.previous_overlap_active = overlap_active

    def _poll_session_risk_alerts(self, now_utc: datetime, states: list) -> None:
        alerts = due_session_risk_alerts(
            self.sessions, states, now_utc, self.session_risk_settings,
            self.risk_alerted_keys,
            apply_exchange_calendar=self.exchange_calendar_enabled_var.get(),
        )
        for alert in alerts:
            self._emit_alert(alert.title, alert.message, "warning" if alert.severity != "INFO" else "info")

    def _emit_alert(self, title: str, message: str, category: str = "info") -> None:
        timestamp = datetime.now(self.home_zone).strftime("%H:%M:%S")
        line = f"{timestamp}  |  {title}  |  {message}"
        self.alert_log_lines.insert(0, line)
        self.alert_log_lines = self.alert_log_lines[:50]
        if hasattr(self, "alert_listbox"):
            self.alert_listbox.delete(0, tk.END)
            for entry in self.alert_log_lines:
                self.alert_listbox.insert(tk.END, entry)
        update_recent_alerts(self)
        self._set_alert_banner(title, "warning" if category in ("warning", "transition", "overlap", "event") else "success")
        if self.alert_settings.get("sound_enabled", True):
            try:
                self.root.bell()
            except tk.TclError:
                pass
        if self.alert_settings.get("desktop_notifications_enabled", True):
            threading.Thread(
                target=send_desktop_notification,
                args=(title, message),
                kwargs={"enabled": True},
                name="VeltrixWindowsToast",
                daemon=True,
            ).start()

    def _set_alert_banner(self, text: str, kind: str = "muted") -> None:
        if not hasattr(self, "alert_banner"):
            return
        palette = THEMES[self.theme_name]
        colour = {
            "success": palette["success"],
            "warning": palette["warning"],
            "error": palette["error"],
        }.get(kind, palette["muted"])
        self.alert_banner.configure(text=text, fg=colour)

    def test_notification(self) -> None:
        self._emit_alert("TEST NOTIFICATION", "Testing in-app alert and Windows desktop notification channels.", "info")
        if not sys.platform == "win32":
            self._set_alert_banner("IN-APP TEST SENT · WINDOWS TOASTS REQUIRE WINDOWS 10/11", "warning")

    def _save_config(self) -> None:
        try:
            save_config(CONFIG_PATH, self.config)
        except (OSError, TypeError, ValueError) as exc:
            messagebox.showerror("Could not save settings", str(exc), parent=self.root)

    def _summary_tile(self, parent: tk.Widget, column: int, title: str, value: str) -> dict[str, tk.Widget]:
        frame = self._frame(parent, bg="panel", padx=12, pady=8, highlightthickness=1)
        frame.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 5 if column < 2 else 0))
        title_label = self._label(frame, title, bg="panel", fg="muted", font=("Consolas", 7, "bold"))
        title_label.pack(anchor="w")
        value_label = self._label(frame, value, bg="panel", fg="text", font=("Consolas", 11, "bold"))
        value_label.pack(anchor="w", pady=(3, 0))
        return {"frame": frame, "title": title_label, "value": value_label}

    def _build_session_card(self, session, row: int, column: int) -> None:
        card = self._frame(self.session_grid, bg="card", padx=14, pady=10, highlightthickness=1, bd=0)
        card.grid(row=row, column=column, sticky="nsew", padx=(0 if column == 0 else 7, 7 if column == 0 else 0), pady=(0, 10))
        card.grid_columnconfigure(0, weight=1)
        top = self._frame(card, bg="card")
        top.grid(row=0, column=0, sticky="ew")
        name = self._label(top, session.name, bg="card", fg="text", font=("Consolas", 11, "bold"))
        name.pack(side="left")
        country = self._label(top, session.flag, bg="raised", fg="bright", font=("Consolas", 8, "bold"), padx=6, pady=2)
        country.pack(side="left", padx=(8, 0))
        status = self._label(top, "CHECKING", bg="raised", fg="muted", font=("Consolas", 8, "bold"), padx=8, pady=3)
        status.pack(side="right")
        city = self._label(card, session.city, bg="card", fg="muted", font=("Segoe UI", 8))
        city.grid(row=1, column=0, sticky="w", pady=(3, 1))
        analog_canvas = tk.Canvas(
            card, width=240, height=240, bg=THEMES[self.theme_name]["panel"],
            highlightthickness=0, bd=0,
        )
        analog_canvas.grid(row=2, column=0, sticky="n", pady=(4, 0))
        analog_clock = {"canvas": analog_canvas, "signature": None, "hands": {}}
        local_time = self._label(card, "--:--:--", bg="card", fg="bright", font=("Consolas", 15, "bold"))
        local_time.grid(row=3, column=0, sticky="n", pady=(0, 2))
        zone = self._label(card, session.timezone_name, bg="card", fg="muted", font=("Consolas", 8))
        zone.grid(row=4, column=0, sticky="n", pady=(0, 2))
        session_progress_label = self._label(
            card, "DAY CYCLE · SESSION WINDOW", bg="card", fg="muted",
            font=("Consolas", 7, "bold"),
        )
        session_progress_label.grid(row=5, column=0, sticky="n", pady=(0, 6))
        divider = self._frame(card, bg="border", height=1)
        divider.grid(row=6, column=0, sticky="ew", pady=(0, 6))
        transition = self._label(card, "Calculating next transition...", bg="card", fg="text", font=("Consolas", 9, "bold"))
        transition.grid(row=7, column=0, sticky="w")
        transition_at = self._label(card, "", bg="card", fg="muted", font=("Segoe UI", 8))
        transition_at.grid(row=8, column=0, sticky="w", pady=(2, 0))
        risk = self._label(
            card, "SESSION RISK · NORMAL", bg="card", fg="muted",
            font=("Consolas", 7, "bold"), anchor="w", justify="left", wraplength=500,
        )
        risk.grid(row=9, column=0, sticky="ew", pady=(5, 0))
        self.cards[session.key] = {
            "card": card, "top": top, "name": name, "country": country, "status": status,
            "city": city, "time": local_time, "analog": analog_canvas, "analog_clock": analog_clock,
            "zone": zone, "session_progress": session_progress_label, "divider": divider,
            "transition": transition, "transition_at": transition_at, "risk": risk,
        }

    def _draw_session_analog_clock(
        self, clock_state: dict, local_now: datetime, session=None, state=None
    ):
        """Render a detailed instrument dial with a live 24-hour session-window ring."""
        canvas: tk.Canvas = clock_state["canvas"]
        palette = THEMES[self.theme_name]
        width = max(150, canvas.winfo_width())
        height = max(150, canvas.winfo_height())
        schedule_signature = (
            session.key, session.opens, session.closes, session.weekdays
        ) if session is not None else None
        signature = (width, height, self.theme_name, schedule_signature)

        if clock_state.get("signature") != signature:
            canvas.delete("all")
            canvas.configure(bg=palette["panel"])
            size = min(width, height) - 14
            cx, cy = width / 2, height / 2
            radius = size / 2
            face = palette["bg"]
            accent = palette["error"]

            # Layered case and glass rings give the dial depth without raster assets.
            canvas.create_oval(
                cx-radius, cy-radius, cx+radius, cy+radius,
                fill=palette["dim"], outline=palette["border"], width=3, tags="clock-face",
            )
            canvas.create_oval(
                cx-radius+4, cy-radius+4, cx+radius-4, cy+radius-4,
                fill=face, outline=palette["muted"], width=1, tags="clock-face",
            )
            canvas.create_oval(
                cx-radius+9, cy-radius+9, cx+radius-9, cy+radius-9,
                outline=palette["dim"], width=1, tags="clock-face",
            )
            canvas.create_oval(
                cx-radius*0.93, cy-radius*0.93, cx+radius*0.93, cy+radius*0.93,
                outline=palette["border"], width=1, tags="clock-face",
            )
            canvas.create_oval(
                cx-radius*0.55, cy-radius*0.55, cx+radius*0.55, cy+radius*0.55,
                outline=palette["dim"], width=1, tags="clock-face",
            )

            # The 24-hour ring maps the configured local session window onto the dial.
            ring_radius = radius * 0.79
            ring_box = (cx-ring_radius, cy-ring_radius, cx+ring_radius, cy+ring_radius)
            session_ring = {}
            if session is not None:
                session_ring["schedule"] = canvas.create_arc(
                    *ring_box, start=0, extent=0, style=tk.ARC,
                    outline=palette["dim"], width=3, tags="clock-face",
                )
                session_ring["progress"] = canvas.create_arc(
                    *ring_box, start=0, extent=0, style=tk.ARC,
                    outline=palette["success"], width=4, tags="clock-hands",
                )
                for marker_name, colour in (("open", palette["success"]), ("close", palette["warning"])):
                    session_ring[marker_name] = canvas.create_oval(
                        cx-2.7, cy-2.7, cx+2.7, cy+2.7,
                        fill=colour, outline=palette["bg"], width=1, tags="clock-face",
                    )

            # Sixty graduation marks: five-minute marks are longer and brighter.
            for tick in range(60):
                angle = math.radians(tick * 6 - 90)
                cardinal = tick % 15 == 0
                major = tick % 5 == 0
                outer = radius * 0.89
                inner = outer - (radius * 0.105 if cardinal else radius * 0.080 if major else radius * 0.038)
                x1, y1 = cx + math.cos(angle) * inner, cy + math.sin(angle) * inner
                x2, y2 = cx + math.cos(angle) * outer, cy + math.sin(angle) * outer
                colour = palette["bright"] if cardinal else palette["muted"] if major else palette["dim"]
                canvas.create_line(
                    x1, y1, x2, y2, fill=colour,
                    width=2.2 if cardinal else 1.55 if major else 0.8,
                    capstyle=tk.ROUND, tags="clock-face",
                )

            # Readable hour numerals sit inside the minute track.
            number_radius = radius * 0.69
            for hour in range(1, 13):
                angle = math.radians(hour * 30 - 90)
                x = cx + math.cos(angle) * number_radius
                y = cy + math.sin(angle) * number_radius
                cardinal = hour in (12, 3, 6, 9)
                canvas.create_text(
                    x, y, text=str(hour),
                    fill=palette["bright"] if cardinal else palette["text"],
                    font=("Segoe UI", 11 if cardinal else 9, "bold"),
                    tags="clock-face",
                )

            # Small dial signatures add instrument character without competing
            # with the live hands or the local digital readout below the dial.
            canvas.create_text(
                cx, cy - radius * 0.30, text="VELTRIX",
                fill=palette["muted"], font=("Consolas", 7, "bold"),
                tags="clock-face",
            )
            canvas.create_text(
                cx, cy - radius * 0.20, text="WORLD TIME",
                fill=palette["dim"], font=("Consolas", 5, "bold"),
                tags="clock-face",
            )

            # Four recessed bezel fasteners at diagonal positions.
            for degrees in (45, 135, 225, 315):
                angle = math.radians(degrees - 90)
                sx = cx + math.cos(angle) * radius * 0.95
                sy = cy + math.sin(angle) * radius * 0.95
                screw_r = max(2.0, radius * 0.022)
                canvas.create_oval(
                    sx-screw_r, sy-screw_r, sx+screw_r, sy+screw_r,
                    fill=palette["panel"], outline=palette["muted"], width=1,
                    tags="clock-face",
                )
                canvas.create_line(
                    sx-screw_r*0.55, sy, sx+screw_r*0.55, sy,
                    fill=palette["dim"], width=1, tags="clock-face",
                )

            # Shadowed, layered hands: retained Canvas objects avoid redraw flicker.
            hands = {
                "hour_shadow": canvas.create_line(
                    cx, cy, cx, cy, fill=palette["dim"], width=7,
                    capstyle=tk.ROUND, tags="clock-hands",
                ),
                "minute_shadow": canvas.create_line(
                    cx, cy, cx, cy, fill=palette["border"], width=5.2,
                    capstyle=tk.ROUND, tags="clock-hands",
                ),
                "hour": canvas.create_line(
                    cx, cy, cx, cy, fill=palette["bright"], width=4.0,
                    capstyle=tk.ROUND, tags="clock-hands",
                ),
                "minute": canvas.create_line(
                    cx, cy, cx, cy, fill=palette["bright_edge"], width=2.6,
                    capstyle=tk.ROUND, tags="clock-hands",
                ),
                "second": canvas.create_line(
                    cx, cy, cx, cy, fill=accent, width=1.35,
                    capstyle=tk.ROUND, tags="clock-hands",
                ),
                "second_tail": canvas.create_line(
                    cx, cy, cx, cy, fill=accent, width=2.6,
                    capstyle=tk.ROUND, tags="clock-hands",
                ),
                "second_counterweight": canvas.create_oval(
                    cx-2, cy-2, cx+2, cy+2, fill=accent,
                    outline=accent, tags="clock-hands",
                ),
            }
            canvas.create_oval(
                cx-6, cy-6, cx+6, cy+6, fill=palette["panel"],
                outline=accent, width=1.5, tags="clock-hands",
            )
            canvas.create_oval(
                cx-2.6, cy-2.6, cx+2.6, cy+2.6,
                fill=palette["bright"], outline=palette["bright"],
                tags="clock-hands",
            )
            clock_state.update({
                "signature": signature, "hands": hands, "session_ring": session_ring,
                "center_x": cx, "center_y": cy, "radius": radius,
            })

        endpoints = session_clock_hand_endpoints(
            local_now,
            center_x=clock_state["center_x"],
            center_y=clock_state["center_y"],
            radius=clock_state["radius"],
        )
        cx, cy = clock_state["center_x"], clock_state["center_y"]
        for hand_name, (x, y) in endpoints.items():
            canvas.coords(clock_state["hands"][hand_name], cx, cy, x, y)
            if hand_name in ("hour", "minute"):
                canvas.coords(clock_state["hands"][f"{hand_name}_shadow"], cx, cy, x, y)

        # The seconds hand has a short rear counterweight, like a mechanical dial.
        second_x, second_y = endpoints["second"]
        tail_x = cx - (second_x - cx) * 0.18
        tail_y = cy - (second_y - cy) * 0.18
        canvas.coords(clock_state["hands"]["second_tail"], tail_x, tail_y, cx, cy)
        counterweight_radius = max(1.8, clock_state["radius"] * 0.022)
        canvas.coords(
            clock_state["hands"]["second_counterweight"],
            tail_x-counterweight_radius, tail_y-counterweight_radius,
            tail_x+counterweight_radius, tail_y+counterweight_radius,
        )

        progress = None
        if session is not None:
            effective_close = session_calendar_close_override(session, local_now, state)
            progress = session_window_progress(session, local_now, close_at=effective_close)
            arc_close = progress.closes_at or datetime.combine(
                local_now.date(), session.closes, tzinfo=session.tz
            )
            arc_start, arc_extent = session_window_arc_angles(session, close_at=arc_close)
            ring = clock_state.get("session_ring", {})
            if ring:
                canvas.itemconfigure(
                    ring["schedule"], start=arc_start, extent=arc_extent, outline=palette["dim"],
                )
                fraction = progress.fraction
                if state is not None and state.calendar_status == "EXCHANGE_HOLIDAY":
                    fraction = 0.0
                canvas.itemconfigure(
                    ring["progress"], start=arc_start, extent=arc_extent*fraction,
                    outline=palette["success"] if progress.status == "ACTIVE" else palette["bright"],
                )
                open_minutes = session.opens.hour * 60 + session.opens.minute
                close_time = arc_close.astimezone(session.tz).time()
                close_minutes = close_time.hour * 60 + close_time.minute
                open_angle = math.radians(open_minutes * 0.25 - 90)
                close_angle = math.radians(close_minutes * 0.25 - 90)
                marker_radius = clock_state["radius"] * 0.79
                marker_size = max(2.0, clock_state["radius"] * 0.022)
                open_x = cx + math.cos(open_angle) * marker_radius
                open_y = cy + math.sin(open_angle) * marker_radius
                close_x = cx + math.cos(close_angle) * marker_radius
                close_y = cy + math.sin(close_angle) * marker_radius
                canvas.coords(
                    ring["open"], open_x-marker_size, open_y-marker_size,
                    open_x+marker_size, open_y+marker_size,
                )
                canvas.coords(
                    ring["close"], close_x-marker_size, close_y-marker_size,
                    close_x+marker_size, close_y+marker_size,
                )
        return progress

    def _session_progress_text(self, state, progress) -> str:
        phase = local_day_phase(state.local_now)
        if state.calendar_status == "EXCHANGE_HOLIDAY":
            return f"{phase} CYCLE · EXCHANGE HOLIDAY"
        if state.calendar_status == "EARLY_CLOSE_PASSED":
            return f"{phase} CYCLE · EARLY CLOSE PASSED"
        if progress.status == "ACTIVE":
            return f"{phase} CYCLE · {progress.fraction:.0%} SESSION ELAPSED"
        if progress.status == "UPCOMING":
            return f"{phase} CYCLE · OPENS IN {format_countdown(progress.until_open_seconds)}"
        if progress.status == "OFF DAY":
            return f"{phase} CYCLE · NO SESSION TODAY"
        return f"{phase} CYCLE · SESSION COMPLETE"

    def _animate_session_clocks(self) -> None:
        """Sweep all four session dials independently of the slower status poll."""
        if self.is_closing:
            return
        now_utc = datetime.now(timezone.utc)
        states_by_key = {state.definition.key: state for state in self.latest_session_states}
        for session in self.sessions:
            widgets = self.cards.get(session.key)
            if widgets is None:
                continue
            local_now = now_utc.astimezone(ZoneInfo(session.timezone_name))
            self._draw_session_analog_clock(
                widgets["analog_clock"], local_now, session, states_by_key.get(session.key)
            )
        self.session_animation_job = self.root.after(
            SESSION_CLOCK_FRAME_MS, self._animate_session_clocks
        )

    # ------------------------------------------------------------------
    # Theme and visual clock
    # ------------------------------------------------------------------
    def set_theme(self, selected_theme: str) -> None:
        if selected_theme in THEMES:
            self.theme_name = selected_theme
            self.theme_var.set(selected_theme)
            self.apply_theme()
            self.update_clock()

    def apply_theme(self) -> None:
        palette = THEMES[self.theme_name]
        self.root.configure(bg=palette["bg"])
        for widget, bg_key, fg_key in self.theme_items:
            try:
                bg_key = {"card": "panel", "raised": "dim"}.get(bg_key, bg_key)
                options = {"bg": palette[bg_key]}
                if fg_key:
                    options["fg"] = palette[fg_key]
                widget.configure(**options)
            except tk.TclError:
                pass

        # Sweep every existing classic Tk widget, including controls nested in
        # secondary workspaces and dynamically created menu/popup children.
        # Registered frame/label colours have already been updated above;
        # unregistered controls inherit the active parent surface instead.
        apply_veltrix_classic_widget_palette(
            self.root, palette, (widget for widget, _bg, _fg in self.theme_items)
        )

        self.digital_canvas.configure(bg=palette["bg"])
        if hasattr(self, "sessions_canvas"):
            self.sessions_canvas.configure(bg=palette["bg"])
        if hasattr(self, "alerts_canvas"):
            self.alerts_canvas.configure(bg=palette["bg"])
        if hasattr(self, "alerts_session_canvas"):
            self.alerts_session_canvas.configure(bg=palette["bg"])
            self.alerts_session_timeline_signature = None
        if hasattr(self, "session_timeline_canvas"):
            self.session_timeline_canvas.configure(bg=palette["panel"])
            self.session_timeline_signature = None
        if hasattr(self, "world_dial_canvas"):
            self.world_dial_canvas.configure(bg=palette["panel"])
            self.world_dial_signature = None
        if hasattr(self, "session_performance_canvas"):
            self.session_performance_canvas.configure(bg=palette["bg"])
        if hasattr(self, "session_performance_chart_canvas"):
            self.session_performance_chart_canvas.configure(bg=palette["panel"])
        for tile in (self.summary_open, self.summary_overlap, self.summary_next):
            tile["frame"].configure(bg=palette["panel"], highlightbackground=palette["border"])
            tile["title"].configure(bg=palette["panel"], fg=palette["muted"])
            tile["value"].configure(bg=palette["panel"], fg=palette["text"])
        for widgets in self.cards.values():
            widgets["card"].configure(bg=palette["panel"], highlightbackground=palette["border"])
            widgets["top"].configure(bg=palette["panel"])
            widgets["analog"].configure(bg=palette["panel"])
            for key in ("name", "city", "time", "zone", "session_progress", "transition", "transition_at", "risk"):
                widgets[key].configure(bg=palette["panel"])
            widgets["name"].configure(fg=palette["text"])
            widgets["risk"].configure(fg=palette["muted"])
            widgets["city"].configure(fg=palette["muted"])
            widgets["time"].configure(fg=palette["bright"])
            widgets["zone"].configure(fg=palette["muted"])
            widgets["transition"].configure(fg=palette["text"])
            widgets["transition_at"].configure(fg=palette["muted"])
            widgets["country"].configure(bg=palette["dim"], fg=palette["bright"])
            widgets["status"].configure(bg=palette["dim"])
            widgets["divider"].configure(bg=palette["border"])

        for card in self.market_asset_cards.values():
            card["frame"].configure(bg=palette["panel"], highlightbackground=palette["border"])

        for widget in (self.hour_spin, self.minute_spin, self.period_spin):
            widget.configure(
                bg=palette["entry_bg"], fg=palette["entry_fg"], insertbackground=palette["bright"],
                buttonbackground=palette["button_bg"], highlightbackground=palette["border"],
                highlightcolor=palette["bright"], disabledbackground=palette["entry_bg"],
                disabledforeground=palette["muted"],
            )
        for button in (self.set_button, self.cancel_button):
            button.configure(bg=palette["button_bg"], fg=palette["button_fg"],
                             activebackground=palette["button_active"], activeforeground=palette["bright"])
        for button in (
            self.sessions_nav_button, self.session_performance_nav_button,
            self.alerts_nav_button, self.calendar_nav_button,
            self.volatility_nav_button, self.regime_nav_button, self.focus_nav_button,
            self.session_performance_import_button, self.session_performance_run_button,
            self.session_performance_export_button,
            self.alerts_search_button, self.alerts_clear_button, self.alerts_sort_up_button,
            self.alerts_sort_down_button, self.alert_config_toggle,
            self.alerts_news_previous_button, self.alerts_news_today_button,
            self.alerts_news_next_button,
            self.save_alert_button, self.test_alert_button, self.add_event_button,
            self.remove_event_button, self.refresh_calendar_button,
            self.save_calendar_preferences_button, self.refresh_market_button,
            self.save_market_settings_button, self.regime_import_button,
            self.regime_run_button, self.regime_export_button, self.regime_save_button,
            self.apply_session_profile_button, self.edit_custom_session_profile_button,
        ):
            button.configure(bg=palette["button_bg"], fg=palette["button_fg"],
                             activebackground=palette["button_active"], activeforeground=palette["bright"])
        self.exchange_calendar_toggle.configure(
            bg=palette["panel"], fg=palette["text"], selectcolor=palette["dim"],
            activebackground=palette["panel"], activeforeground=palette["bright"],
        )
        for check in (*self.alert_checkbuttons, *self.risk_checkbuttons):
            check.configure(bg=palette["panel"], fg=palette["text"], selectcolor=palette["dim"],
                            activebackground=palette["panel"], activeforeground=palette["bright"])
        for spin in (
            self.pre_open_spin, self.pre_close_spin, self.event_lead_spin,
            self.calendar_reminder_spin, self.market_expansion_spin, self.market_contraction_spin,
            self.risk_opening_window_spin, self.risk_closing_window_spin,
            self.risk_pre_open_window_spin, *self.session_lead_spins,
            self.session_performance_min_bars_spin, self.session_performance_min_coverage_spin,
        ):
            spin.configure(bg=palette["entry_bg"], fg=palette["entry_fg"], insertbackground=palette["bright"],
                           buttonbackground=palette["button_bg"], highlightbackground=palette["border"])
        for entry in (
            self.event_name_entry, self.event_datetime_entry, self.calendar_search_entry,
            self.alerts_market_watch_entry,
        ):
            entry.configure(bg=palette["entry_bg"], fg=palette["entry_fg"], insertbackground=palette["bright"])
        for check in (self.calendar_reminder_check, self.market_regime_check):
            check.configure(
                bg=palette["panel"], fg=palette["text"], selectcolor=palette["dim"],
                activebackground=palette["panel"], activeforeground=palette["bright"],
            )
        self._apply_calendar_tree_theme()
        self._apply_market_tree_theme()
        apply_alerts_tree_theme(self)
        self._apply_regime_tree_theme()
        apply_session_performance_theme(self)
        # Apply shared ttk styles globally: standard controls, all Treeviews,
        # tabs, headers, scrollbars, progress bars and every named selector.
        apply_veltrix_ttk_palette(self.ttk_style, palette, self.root)
        for listbox in (
            self.event_listbox, self.alert_listbox, self.market_alert_listbox,
            self.alerts_recent_listbox,
        ):
            listbox.configure(bg=palette["bg"], fg=palette["text"], selectbackground=palette["button_active"],
                              selectforeground=palette["bright"], highlightthickness=1,
                              highlightbackground=palette["border"])
        self.show_page(getattr(self, "current_page", "sessions"))
        self.theme_selector.configure(bg=palette["button_bg"], fg=palette["button_fg"],
                                       activebackground=palette["button_active"], activeforeground=palette["bright"])
        try:
            menu = self.theme_selector["menu"]
            menu.configure(bg=palette["panel"], fg=palette["button_fg"], activebackground=palette["button_active"],
                           activeforeground=palette["bright"], font=("Consolas", 9, "bold"), bd=1, relief="solid")
        except tk.TclError:
            pass
        if self.alarm_window is not None:
            self._apply_popup_theme()
        self._draw_digital_clock(datetime.now())

    def _apply_calendar_tree_theme(self) -> None:
        palette = THEMES[self.theme_name]
        style = ttk.Style(self.root)
        style.configure(
            "Veltrix.Treeview", background=palette["bg"], foreground=palette["text"],
            fieldbackground=palette["bg"], rowheight=27, bordercolor=palette["border"],
            font=("Consolas", 8),
        )
        style.configure(
            "Veltrix.Treeview.Heading", background=palette["panel"], foreground=palette["bright"],
            relief="flat", font=("Consolas", 8, "bold"),
        )
        style.map(
            "Veltrix.Treeview", background=[("selected", palette["button_active"])],
            foreground=[("selected", palette["bright"])],
        )
        self.calendar_tree.tag_configure("high", foreground=palette["error"])
        self.calendar_tree.tag_configure("medium", foreground=palette["warning"])
        self.calendar_tree.tag_configure("low", foreground=palette["success"])

    def _apply_market_tree_theme(self) -> None:
        palette = THEMES[self.theme_name]
        style = ttk.Style(self.root)
        style.configure(
            "Veltrix.Market.Treeview", background=palette["bg"], foreground=palette["text"],
            fieldbackground=palette["bg"], rowheight=25, bordercolor=palette["border"],
            font=("Consolas", 8),
        )
        style.configure(
            "Veltrix.Market.Treeview.Heading", background=palette["panel"], foreground=palette["bright"],
            relief="flat", font=("Consolas", 8, "bold"),
        )
        style.map("Veltrix.Market.Treeview", background=[("selected", palette["button_active"])],
                  foreground=[("selected", palette["bright"])])
        style.configure("Veltrix.Market.Vertical.TScrollbar", background=palette["button_bg"],
                        troughcolor=palette["bg"], arrowcolor=palette["bright"], bordercolor=palette["border"])
        if hasattr(self, "volatility_canvas"):
            self.volatility_canvas.configure(bg=palette["bg"])
        for tag, colour in (("expansion", palette["error"]), ("contraction", palette["success"]),
                            ("normal", palette["text"]), ("nodata", palette["muted"])):
            self.market_tree.tag_configure(tag, foreground=colour)

    @staticmethod
    def _segment_polygons(width: int, height: int, thickness: int) -> dict[str, list[tuple[int, int]]]:
        w, h, t = width, height, thickness
        mid = h // 2
        return {
            "a": [(t, 0), (w - t, 0), (w - 2 * t, t), (2 * t, t)],
            "b": [(w - t, t // 2), (w, t + t // 2), (w, mid - t // 2), (w - t, mid)],
            "c": [(w - t, mid), (w, mid + t // 2), (w, h - t // 2), (w - t, h)],
            "d": [(2 * t, h - t), (w - 2 * t, h - t), (w - t, h), (t, h)],
            "e": [(t, mid), (0, mid + t // 2), (0, h - t // 2), (t, h)],
            "f": [(0, t // 2), (t, t), (t, mid), (0, mid - t // 2)],
            "g": [(2 * t, mid - t // 2), (w - 2 * t, mid - t // 2),
                  (w - t, mid), (w - 2 * t, mid + t // 2), (2 * t, mid + t // 2), (t, mid)],
        }

    def _on_clock_resize(self, _event=None) -> None:
        self._draw_digital_clock(datetime.now())

    def _draw_digital_clock(self, now: datetime) -> None:
        if not hasattr(self, "digital_canvas"):
            return
        canvas = self.digital_canvas
        width = max(canvas.winfo_width(), 500)
        height = max(canvas.winfo_height(), 150)
        palette = THEMES[self.theme_name]
        signature = (width, height, self.theme_name)
        if signature != self.clock_canvas_signature:
            canvas.delete("all")
            canvas.configure(bg=palette["panel"])
            canvas.create_rectangle(
                3, 3, width - 3, height - 3,
                outline=palette["border"], width=1, tags="clock-static",
            )
            for scanline_y in range(8, height - 5, 5):
                canvas.create_line(
                    7, scanline_y, width - 7, scanline_y,
                    fill=palette["scanline"], width=1, tags="clock-static",
                )
            self.clock_canvas_signature = signature
        else:
            canvas.delete("clock-dynamic")

        digits = now.strftime("%I%M%S")
        digit_w = min(63, (width - 125) / 6.7)
        digit_h = min(116, height - 39)
        thickness = max(7, int(digit_w * 0.15))
        total_digits_width = digit_w * 6 + 4 * digit_w * 0.26 + 2 * digit_w * 0.25
        start_x = max(17, (width - total_digits_width) / 2)
        y = (height - digit_h) / 2
        x = start_x
        for index, value in enumerate(digits):
            if index in (2, 4):
                x += digit_w * 0.26
            active_segments = DIGIT_SEGMENTS.get(value, "")
            for segment, points in self._segment_polygons(int(digit_w), int(digit_h), thickness).items():
                flat = [coord for px, py in points for coord in (x + px, y + py)]
                is_on = segment in active_segments
                canvas.create_polygon(
                    flat,
                    fill=palette["bright"] if is_on else palette["inactive"],
                    outline=palette["bright_edge"] if is_on else palette["dim"],
                    width=1,
                    tags="clock-dynamic",
                )
            x += digit_w + digit_w * 0.12
            if index in (1, 3):
                colon_x = x + digit_w * 0.035
                radius = max(3, int(thickness * 0.38))
                for cy in (y + digit_h * 0.34, y + digit_h * 0.68):
                    canvas.create_oval(colon_x - radius, cy - radius, colon_x + radius, cy + radius,
                                       fill=palette["bright"], outline=palette["bright_edge"],
                                       tags="clock-dynamic")
                x += digit_w * 0.22

        period = now.strftime("%p")
        canvas.create_text(width - 18, 17, text=period, anchor="ne", fill=palette["muted"],
                           font=("Consolas", 10, "bold"), tags="clock-dynamic")
        canvas.create_text(18, height - 15, text="SYSTEM LOCAL TIME", anchor="sw", fill=palette["muted"],
                           font=("Consolas", 7, "bold"), tags="clock-dynamic")

    # ------------------------------------------------------------------
    # Global market session updates
    # ------------------------------------------------------------------
    def update_clock(self) -> None:
        now_utc = datetime.now(timezone.utc)
        home_now = now_utc.astimezone(self.home_zone)
        self.home_time_label.configure(text=home_now.strftime("%H:%M:%S"))
        self.home_date_label.configure(text=home_now.strftime("%A  ·  %d %B %Y  ·  %Z"))
        self._draw_digital_clock(home_now)

        exchange_calendar_enabled = self.exchange_calendar_enabled_var.get()
        states = [
            get_exchange_aware_session_state(
                session, now_utc, enabled=exchange_calendar_enabled
            )
            for session in self.sessions
        ]
        self.latest_session_states = states
        open_states = [state for state in states if state.is_open]
        refresh_alerts_dashboard(self, now_utc, states)
        self._poll_market_alerts(now_utc, open_states)
        self._poll_session_risk_alerts(now_utc, states)
        self._poll_economic_events(home_now)
        self._poll_live_calendar_events(home_now)
        self.summary_open["value"].configure(text=f"{len(open_states)} / {len(states)}")
        transitions = sorted(states, key=lambda item: item.seconds_to_transition)
        if transitions:
            nearest = transitions[0]
            event_name = f"{nearest.definition.name} {nearest.transition_kind.lower()}"
            self.summary_next["value"].configure(text=f"{event_name} · {format_countdown(nearest.seconds_to_transition)}")

        overlaps = self._find_overlaps(open_states)
        self.summary_overlap["value"].configure(text=overlaps if overlaps else "NONE")
        self._draw_session_timeline(now_utc, states)
        self._refresh_session_intelligence(now_utc)
        self._update_exchange_calendar_summary(now_utc, states)
        palette = THEMES[self.theme_name]
        for state in states:
            widgets = self.cards[state.definition.key]
            widgets["time"].configure(text=state.local_now.strftime("%H:%M:%S"))
            progress = self._draw_session_analog_clock(
                widgets["analog_clock"], state.local_now, state.definition, state
            )
            widgets["zone"].configure(
                text=(
                    f"{state.definition.timezone_name}  ·  {state.timezone_label}"
                    f"  ·  {utc_offset_label(state.local_now)}"
                )
            )
            widgets["session_progress"].configure(
                text=self._session_progress_text(state, progress)
            )
            widgets["card"].configure(
                highlightbackground=palette["success"] if state.is_open else palette["border"]
            )
            if state.calendar_status == "EXCHANGE_HOLIDAY":
                widgets["status"].configure(text="● HOLIDAY", fg=palette["error"])
                transition_text = f"EXCHANGE CLOSED · OPENS IN {format_countdown(state.seconds_to_transition)}"
            elif state.calendar_status in {"OUT_OF_RANGE", "NO_VENUE_MAPPING"}:
                widgets["status"].configure(text="● SCHEDULE ONLY", fg=palette["warning"])
                transition_text = (
                    f"BASE SCHEDULE CLOSE IN  {format_countdown(state.seconds_to_transition)}"
                    if state.is_open
                    else f"BASE SCHEDULE OPEN IN  {format_countdown(state.seconds_to_transition)}"
                )
            elif state.calendar_status == "CLOSING_PROCESS" and state.transition_kind == "CLOSE_PROCESS":
                widgets["status"].configure(text="● CLOSING PROCESS", fg=palette["warning"])
                transition_text = f"PROCESS STARTS IN  {format_countdown(state.seconds_to_transition)}"
            elif state.calendar_status == "CLOSING_PROCESS" and not state.is_open:
                widgets["status"].configure(text="● EARLY CLOSE DAY", fg=palette["warning"])
                transition_text = f"OPENS IN  {format_countdown(state.seconds_to_transition)}"
            elif state.calendar_status == "CLOSING_PROCESS_PASSED" and state.is_open:
                widgets["status"].configure(text="● OPEN", fg=palette["success"])
                transition_text = f"CLOSES IN  {format_countdown(state.seconds_to_transition)}"
            elif state.calendar_status in {"EARLY_CLOSE", "EARLY_CLOSE_PASSED"}:
                if state.is_open:
                    widgets["status"].configure(text="● EARLY CLOSE", fg=palette["warning"])
                    transition_text = f"EARLY CLOSE IN  {format_countdown(state.seconds_to_transition)}"
                elif state.calendar_status == "EARLY_CLOSE":
                    widgets["status"].configure(text="● EARLY CLOSE DAY", fg=palette["warning"])
                    transition_text = f"OPENS IN  {format_countdown(state.seconds_to_transition)}"
                else:
                    widgets["status"].configure(text="● CLOSED", fg=palette["error"])
                    transition_text = f"EARLY CLOSE PASSED · OPENS IN {format_countdown(state.seconds_to_transition)}"
            elif state.is_open:
                widgets["status"].configure(text="● OPEN", fg=palette["success"])
                transition_text = f"CLOSES IN  {format_countdown(state.seconds_to_transition)}"
            else:
                widgets["status"].configure(text="● CLOSED", fg=palette["error"])
                transition_text = f"OPENS IN  {format_countdown(state.seconds_to_transition)}"
            widgets["transition"].configure(text=transition_text)
            widgets["transition_at"].configure(
                text=(
                    f"{'CLOSING PROCESS START' if state.transition_kind == 'CLOSE_PROCESS' else state.transition_kind.title()} "
                    f"at {state.transition_at.strftime('%H:%M')} {state.transition_at.tzname()}  ·  "
                    f"{state.transition_at.strftime('%a, %d %b')}"
                    + (f"  ·  {state.calendar_event}" if state.calendar_event else "")
                )
            )
            assessment = assess_session_risk(
                state.definition, state, now_utc, self.session_risk_settings,
                apply_exchange_calendar=exchange_calendar_enabled,
            )
            if assessment.level == "HIGH":
                risk_colour = palette["error"]
            elif assessment.level == "CAUTION":
                risk_colour = palette["warning"]
            else:
                risk_colour = palette["muted"]
            risk_text = f"SESSION RISK · {assessment.level}"
            if assessment.flags and self.session_risk_settings.get("enabled", True):
                risk_text += "  |  " + assessment.summary
            widgets["risk"].configure(text=risk_text, fg=risk_colour)

        if len(open_states) >= 2:
            names = " + ".join(state.definition.name for state in open_states)
            message = f"OVERLAP ACTIVE  ·  {names} are currently scheduled open."
            colour = palette["success"]
        elif len(open_states) == 1:
            message = f"{open_states[0].definition.name} SESSION ACTIVE  ·  The other tracked centres are closed."
            colour = palette["bright"]
        else:
            message = "NO TRACKED SESSION IS OPEN  ·  Monitoring the next scheduled opening."
            colour = palette["warning"]
        self.overlap_label.configure(text=message, fg=colour)

        self.audio_label.configure(
            text="AUDIO // MP3 READY" if self.audio_available and ALARM_SOUND_FILE.is_file() else "AUDIO: SYSTEM BELL"
        )
        self._update_next_alarm_display()
        self.clock_job = self.root.after(self.refresh_ms, self.update_clock)

    @staticmethod
    def _find_overlaps(open_states) -> str:
        if len(open_states) < 2:
            return "NONE"
        active = {state.definition.key for state in open_states}
        if {"sydney", "tokyo"}.issubset(active):
            return "SYDNEY + TOKYO"
        if {"london", "new_york"}.issubset(active):
            return "LONDON + NEW YORK"
        return " + ".join(state.definition.name for state in open_states)

    # ------------------------------------------------------------------
    # Original alarm clock functionality
    # ------------------------------------------------------------------
    def _persist_alarm_state(self) -> None:
        state = self.alarm_state if self.alarm_state in {self.SCHEDULED, self.SNOOZED} else self.IDLE
        deadline = self.alarm_datetime if state != self.IDLE else None
        try:
            save_alarm_state(ALARM_STATE_PATH, state, deadline)
        except (OSError, ValueError) as exc:
            messagebox.showwarning(
                "Alarm was not saved",
                f"The alarm remains active for this session but may not be restored after restart:\n{exc}",
                parent=self.root,
            )

    def _initialise_audio(self) -> None:
        if pygame is None:
            print("pygame is not installed; using the system bell.")
            return
        try:
            pygame.mixer.init()
            self.audio_available = True
        except pygame.error as exc:
            print(f"Audio initialisation failed; using the system bell: {exc}")

    def play_audio(self) -> None:
        if self.audio_available and ALARM_SOUND_FILE.is_file():
            try:
                pygame.mixer.music.load(str(ALARM_SOUND_FILE))
                pygame.mixer.music.play(-1)
                return
            except pygame.error as exc:
                print(f"Could not play alarm audio: {exc}")
        if not ALARM_SOUND_FILE.is_file():
            print(f"{ALARM_SOUND_FILE.name} not found; using the system bell.")
        self._ring_system_bell()

    def _ring_system_bell(self) -> None:
        if self.alarm_state != self.RINGING:
            return
        try:
            self.root.bell()
            self.bell_job = self.root.after(1000, self._ring_system_bell)
        except tk.TclError:
            self.bell_job = None

    def stop_audio(self) -> None:
        if self.bell_job is not None:
            try:
                self.root.after_cancel(self.bell_job)
            except tk.TclError:
                pass
            self.bell_job = None
        if self.audio_available:
            try:
                pygame.mixer.music.stop()
            except pygame.error as exc:
                print(f"Could not stop alarm audio: {exc}")

    def check_alarm(self) -> None:
        if (self.alarm_state in (self.SCHEDULED, self.SNOOZED)
                and self.alarm_datetime is not None and datetime.now(self.home_zone) >= self.alarm_datetime):
            self.trigger_alarm()
        self.alarm_job = self.root.after(1000, self.check_alarm)

    def set_alarm(self) -> None:
        try:
            raw_time = f"{self.hour_var.get().strip()}:{self.minute_var.get().strip()} {self.period_var.get().strip().upper()}"
            parsed = datetime.strptime(raw_time, "%I:%M %p").time()
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid alarm time", "Enter a valid time, such as 07:05 AM or 08:30 PM.", parent=self.root)
            return
        now = datetime.now(self.home_zone)
        scheduled = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
        if scheduled <= now:
            scheduled += timedelta(days=1)
        self.stop_audio()
        self._close_alarm_popup()
        self.alarm_datetime = scheduled
        self.ringing_time = None
        self.alarm_state = self.SCHEDULED
        self._persist_alarm_state()
        self._update_next_alarm_display()
        day_label = "TODAY" if scheduled.date() == now.date() else "TOMORROW"
        self._set_status(f"ALARM SAVED: {day_label} {scheduled.strftime('%I:%M %p')}", "success")

    def cancel_alarm(self) -> None:
        self.stop_audio()
        self._close_alarm_popup()
        self.alarm_datetime = None
        self.ringing_time = None
        self.alarm_state = self.IDLE
        self._persist_alarm_state()
        self._update_next_alarm_display()
        self._set_status("SYSTEM READY: NO ALARM SET", "muted")

    def trigger_alarm(self) -> None:
        if self.alarm_state == self.RINGING:
            return
        self.ringing_time = self.alarm_datetime or datetime.now(self.home_zone)
        self.alarm_datetime = None
        self.alarm_state = self.RINGING
        self._persist_alarm_state()
        self._update_next_alarm_display()
        self._set_status("ALARM SIGNAL: ACTIVE", "warning")
        self.play_audio()
        self._show_alarm_popup()

    def _show_alarm_popup(self) -> None:
        if self.alarm_window is not None:
            try:
                if self.alarm_window.winfo_exists():
                    self.alarm_window.lift()
                    return
            except tk.TclError:
                self.alarm_window = None
        palette = THEMES[self.theme_name]
        self.alarm_window = tk.Toplevel(self.root)
        self.alarm_window.title("ALARM SIGNAL")
        self.alarm_window.geometry("350x205")
        self.alarm_window.resizable(False, False)
        self.alarm_window.transient(self.root)
        self.alarm_window.attributes("-topmost", True)
        self.alarm_window.protocol("WM_DELETE_WINDOW", self.dismiss_alarm)
        self.popup_label = tk.Label(
            self.alarm_window,
            text="ALARM SIGNAL ACTIVE\n" + (self.ringing_time.strftime("%I:%M %p") if self.ringing_time else ""),
            font=("Consolas", 15, "bold"), justify="center", bd=0,
        )
        self.popup_label.pack(pady=(27, 18))
        self.popup_frame = tk.Frame(self.alarm_window, bd=0)
        self.popup_frame.pack()
        self.snooze_button = tk.Button(
            self.popup_frame, text=f"SNOOZE {SNOOZE_MINUTES}M", command=self.snooze_alarm,
            font=("Consolas", 10, "bold"), relief="flat", bd=0, padx=11, pady=8, cursor="hand2",
        )
        self.snooze_button.grid(row=0, column=0, padx=6)
        self.dismiss_button = tk.Button(
            self.popup_frame, text="DISMISS", command=self.dismiss_alarm,
            font=("Consolas", 10, "bold"), relief="flat", bd=0, padx=11, pady=8, cursor="hand2",
        )
        self.dismiss_button.grid(row=0, column=1, padx=6)
        self._apply_popup_theme()

    def _apply_popup_theme(self) -> None:
        if self.alarm_window is None:
            return
        palette = THEMES[self.theme_name]
        try:
            self.alarm_window.configure(bg=palette["bg"])
            self.popup_label.configure(bg=palette["bg"], fg=palette["bright"])
            self.popup_frame.configure(bg=palette["bg"])
            for button in (self.snooze_button, self.dismiss_button):
                button.configure(bg=palette["button_bg"], fg=palette["button_fg"],
                                 activebackground=palette["button_active"], activeforeground=palette["bright"])
        except (tk.TclError, AttributeError):
            pass

    def _close_alarm_popup(self) -> None:
        popup = self.alarm_window
        self.alarm_window = None
        if popup is not None:
            try:
                if popup.winfo_exists():
                    popup.destroy()
            except tk.TclError:
                pass

    def snooze_alarm(self) -> None:
        if self.alarm_state != self.RINGING:
            return
        self.stop_audio()
        self._close_alarm_popup()
        self.alarm_datetime = datetime.now(self.home_zone) + timedelta(minutes=SNOOZE_MINUTES)
        self.ringing_time = None
        self.alarm_state = self.SNOOZED
        self._persist_alarm_state()
        self._update_next_alarm_display()
        self._set_status(f"SNOOZED // {self.alarm_datetime.strftime('%I:%M %p')}", "warning")

    def dismiss_alarm(self) -> None:
        self.stop_audio()
        self._close_alarm_popup()
        self.alarm_datetime = None
        self.ringing_time = None
        self.alarm_state = self.IDLE
        self._persist_alarm_state()
        self._update_next_alarm_display()
        self._set_status("ALARM DISMISSED - SYSTEM READY", "muted")

    def _update_next_alarm_display(self) -> None:
        if self.alarm_datetime is None:
            text = "◉  ALARM: RINGING" if self.alarm_state == self.RINGING else "◉  NEXT ALARM: NONE"
        else:
            now = datetime.now(self.home_zone)
            day = "TODAY" if self.alarm_datetime.date() == now.date() else "TOMORROW"
            state = "SNOOZE" if self.alarm_state == self.SNOOZED else "NEXT ALARM"
            text = f"◉  {state} // {day} {self.alarm_datetime.strftime('%I:%M %p')}"
        self.next_alarm_label.configure(text=text)

    def _set_status(self, message: str, kind: str = "muted") -> None:
        self.status_message = message
        self.status_kind = kind
        palette = THEMES[self.theme_name]
        colour = {
            "success": palette["success"],
            "warning": palette["warning"],
            "error": palette["error"],
        }.get(kind, palette["text"])
        self.status_label.configure(text=message, fg=colour)

    def on_close(self) -> None:
        self.is_closing = True
        for job in (
            self.clock_job, self.session_animation_job, self.alarm_job, self.bell_job,
            self.calendar_auto_refresh_job, self.calendar_startup_fetch_job, self.calendar_queue_job,
            self.market_auto_refresh_job, self.market_startup_fetch_job, self.market_queue_job,
            self.regime_queue_job, self.regime_cache_load_job, self.regime_import_queue_job,
            self.focus_tick_job,
        ):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        self.stop_audio()
        self._close_alarm_popup()
        self.config["theme"] = self.theme_name
        self.config["alerts"] = dict(self.alert_settings)
        self.config["economic_events"] = self.economic_events
        self.config["calendar"] = dict(self.calendar_settings)
        self.config["market_data"] = dict(self.market_settings)
        self.config["market_instruments"] = list(self.market_instruments)
        self.config["session_profiles"] = {
            "selected": self.active_session_profile,
            "base_sessions": [dict(item) for item in self.session_profile_base_sessions],
            "custom": {key: dict(value) for key, value in self.custom_session_schedules.items()},
        }
        self.config["exchange_calendar"] = {
            "enabled": bool(self.exchange_calendar_enabled_var.get())
        }
        self.config["session_risk"] = dict(self.session_risk_settings)
        try:
            self.regime_settings.update(asdict(self._collect_regime_config()))
            self.regime_settings["selected_asset"] = self._selected_regime_asset_key()
        except (AttributeError, ValueError, tk.TclError):
            pass
        self.config["regime_lab"] = dict(self.regime_settings)
        try:
            daily_target = max(0.5, min(24.0, float(self.focus_daily_target_var.get())))
        except (AttributeError, ValueError, tk.TclError):
            daily_target = 4.0
        self.config["focus"] = {"daily_target_hours": daily_target}
        try:
            self.config["event_reminder_minutes"] = max(0, min(1440, int(self.event_lead_var.get())))
        except (AttributeError, ValueError, tk.TclError):
            pass
        self._persist_alarm_state()
        self._save_config()
        if self.regime_cache_writer_thread is not None and self.regime_cache_writer_thread.is_alive():
            if not self.regime_cache_loading:
                self._save_regime_cache()
            self.regime_cache_write_queue.put(None)
        self.focus_store.close()
        if self.audio_available:
            try:
                pygame.mixer.quit()
            except pygame.error:
                pass
        self.root.destroy()


def main() -> None:
    try:
        root = tk.Tk()
        VeltrixTradingClock(root)
        root.mainloop()
    except Exception as exc:
        try:
            messagebox.showerror("Veltrix Trading Clock", str(exc))
        except tk.TclError:
            print(f"Veltrix Trading Clock could not start: {exc}")
        raise


if __name__ == "__main__":
    main()
