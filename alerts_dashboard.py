"""Screenshot-inspired Market Watch workspace for Veltrix Trading Clock."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import tkinter as tk
from tkinter import ttk

from market_watch import (
    FX_REFERENCE_PAIRS,
    fx_reference_week_label,
    fx_reference_week_state,
)
from session_engine import format_countdown
from session_timeline import build_session_timeline
from themes import THEMES


_FLAG_MAP = {"AU": "🇦🇺", "JP": "🇯🇵", "UK": "🇬🇧", "US": "🇺🇸"}
_SESSION_SHORT_NAMES = {"sydney": "SYD", "tokyo": "TOK", "london": "LON", "new_york": "NY"}
_SESSION_COLOURS = ("success", "bright", "warning", "error")


def build_alerts_dashboard(app, parent: tk.Widget) -> None:
    """Create a dense watchlist and calendar dashboard above existing rule settings."""
    palette = THEMES[app.theme_name]
    app.alert_settings_visible = False
    app.alerts_calendar_day = datetime.now(app.home_zone).date()
    app.alerts_watch_sort_descending = False

    shell = app._frame(parent, bg="panel", padx=10, pady=9, highlightthickness=1, bd=0)
    shell.pack(fill="both", expand=True, pady=(0, 8))

    header = app._frame(shell, bg="panel")
    header.pack(fill="x", pady=(0, 7))
    app.alerts_brand_label = app._label(
        header, "VELTRIX", bg="panel", fg="bright", font=("Consolas", 16, "bold")
    )
    app.alerts_brand_label.pack(side="left", padx=(5, 14))
    app._frame(header, bg="border", width=1).pack(
        side="left", fill="y", padx=(0, 12), pady=2
    )
    title_block = app._frame(header, bg="panel")
    title_block.pack(side="left", anchor="w")
    app._label(
        title_block, "MARKET WATCH · TRADING HOURS", bg="panel", fg="text",
        font=("Consolas", 10, "bold"),
    ).pack(anchor="w")
    app._label(
        title_block, "LIVE SESSION COUNTDOWNS  |  FX REFERENCE WEEK  |  ECONOMIC NEWS",
        bg="panel", fg="muted", font=("Consolas", 7),
    ).pack(anchor="w", pady=(2, 0))

    top = app._frame(shell, bg="panel")
    top.pack(fill="x", pady=(0, 8))
    top.grid_columnconfigure(0, minsize=122)
    top.grid_columnconfigure(1, weight=1)
    top.grid_columnconfigure(2, minsize=174)

    system = app._frame(top, bg="bg", padx=9, pady=8, highlightthickness=1, bd=0)
    system.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
    app._label(system, "◉  SYSTEM TIME", bg="bg", fg="muted",
               font=("Consolas", 7, "bold")).pack(anchor="w")
    app.alerts_system_time_label = app._label(
        system, "--:--:--", bg="bg", fg="bright", font=("Consolas", 18, "bold")
    )
    app.alerts_system_time_label.pack(anchor="w", pady=(8, 2))
    app.alerts_system_date_label = app._label(
        system, "-- --- ----", bg="bg", fg="text", font=("Consolas", 7)
    )
    app.alerts_system_date_label.pack(anchor="w")
    app.alerts_system_zone_label = app._label(
        system, app.home_zone.key, bg="bg", fg="muted", font=("Consolas", 6)
    )
    app.alerts_system_zone_label.pack(anchor="w", pady=(5, 0))

    timeline_panel = app._frame(top, bg="bg", padx=8, pady=6, highlightthickness=1, bd=0)
    timeline_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 7))
    app._label(
        timeline_panel, "GLOBAL SESSION MAP · UTC 00:00–24:00",
        bg="bg", fg="text", font=("Consolas", 7, "bold"),
    ).pack(anchor="w")
    app.alerts_session_canvas = tk.Canvas(
        timeline_panel, height=148, bg=palette["bg"], highlightthickness=0, bd=0,
    )
    app.alerts_session_canvas.pack(fill="both", expand=True, pady=(2, 0))
    app.alerts_session_timeline_signature = None

    status = app._frame(top, bg="bg", padx=8, pady=7, highlightthickness=1, bd=0)
    status.grid(row=0, column=2, sticky="nsew")
    app._label(
        status, "✓  CURRENT SESSION", bg="bg", fg="text", font=("Consolas", 7, "bold")
    ).pack(anchor="w", pady=(0, 5))
    app.alerts_session_rows = {}
    for session in app.sessions:
        line = app._frame(status, bg="bg")
        line.pack(fill="x", pady=2)
        app._label(
            line, f"{_FLAG_MAP.get(session.flag, session.flag)}  {session.name.title()}",
            bg="bg", fg="text", font=("Segoe UI", 7),
        ).pack(side="left")
        state_label = app._label(
            line, "CHECK", bg="bg", fg="muted", font=("Consolas", 7, "bold")
        )
        state_label.pack(side="right")
        app.alerts_session_rows[session.key] = state_label
    app.alerts_overlap_summary = app._label(
        status, "SESSION OVERLAP · CALCULATING", bg="bg", fg="muted",
        font=("Consolas", 6, "bold"), anchor="w", justify="left", wraplength=160,
    )
    app.alerts_overlap_summary.pack(fill="x", pady=(5, 0))
    app.alerts_active_summary = app._label(
        status, "ACTIVE CENTRES · 0 / 4", bg="bg", fg="muted", font=("Consolas", 6),
        anchor="w",
    )
    app.alerts_active_summary.pack(fill="x", pady=(2, 0))

    command = app._frame(shell, bg="panel", padx=7, pady=6, highlightthickness=1, bd=0)
    command.pack(fill="x", pady=(0, 7))
    app.alerts_search_var = tk.StringVar(value="")
    app.alerts_market_watch_entry = tk.Entry(
        command, textvariable=app.alerts_search_var, width=21,
        font=("Consolas", 8), relief="flat", bd=0,
    )
    app.alerts_market_watch_entry.pack(side="left", padx=(4, 5), ipady=5)
    app.alerts_market_watch_entry.insert(0, "Search symbol / event")
    app.alerts_market_watch_entry.bind(
        "<FocusIn>", lambda _event: clear_search_placeholder(app)
    )
    app.alerts_search_button = tk.Button(
        command, text="SEARCH",
        command=lambda: refresh_alerts_dashboard(
            app, datetime.now(timezone.utc), app.latest_session_states, force=True
        ),
        font=("Consolas", 7, "bold"), relief="flat", bd=0, padx=9, pady=5, cursor="hand2",
    )
    app.alerts_search_button.pack(side="left", padx=(0, 5))
    app.alerts_clear_button = tk.Button(
        command, text="CLEAR", command=lambda: clear_watch_search(app),
        font=("Consolas", 7, "bold"), relief="flat", bd=0, padx=9, pady=5, cursor="hand2",
    )
    app.alerts_clear_button.pack(side="left")
    app.alerts_feed_state_label = app._label(
        command, "SHOWMYTRADES · WAITING FOR FEED",
        bg="panel", fg="muted", font=("Consolas", 7),
    )
    app.alerts_feed_state_label.pack(side="left", padx=(16, 4))
    app.alerts_sort_up_button = tk.Button(
        command, text="↑ UP", command=lambda: set_watch_sort(app, False),
        font=("Consolas", 7, "bold"), relief="flat", bd=0, padx=9, pady=5, cursor="hand2",
    )
    app.alerts_sort_up_button.pack(side="right", padx=(4, 0))
    app.alerts_sort_down_button = tk.Button(
        command, text="↓ DOWN", command=lambda: set_watch_sort(app, True),
        font=("Consolas", 7, "bold"), relief="flat", bd=0, padx=9, pady=5, cursor="hand2",
    )
    app.alerts_sort_down_button.pack(side="right", padx=(4, 0))
    app.alerts_watch_count_label = app._label(
        command, "SHOWING 0 / 28", bg="panel", fg="text", font=("Consolas", 7, "bold")
    )
    app.alerts_watch_count_label.pack(side="right", padx=(8, 10))
    app.alerts_search_var.trace_add(
        "write", lambda *_args: refresh_alerts_dashboard(
            app, datetime.now(timezone.utc), app.latest_session_states, force=True
        )
    )

    ticker = app._frame(shell, bg="bg", padx=7, pady=5, highlightthickness=1, bd=0)
    ticker.pack(fill="x", pady=(0, 8))
    app.alerts_news_ticker_label = app._label(
        ticker, "●  NEXT NEWS · WAITING FOR THE ECONOMIC CALENDAR FEED",
        bg="bg", fg="warning", font=("Consolas", 7, "bold"), anchor="w", justify="left",
    )
    app.alerts_news_ticker_label.pack(fill="x")

    lower = app._frame(shell, bg="panel")
    lower.pack(fill="both", expand=True)
    lower.grid_columnconfigure(0, weight=7, uniform="watch_columns")
    lower.grid_columnconfigure(1, weight=4, uniform="watch_columns")
    lower.grid_rowconfigure(0, weight=1)

    watch_panel = app._frame(lower, bg="bg", padx=7, pady=7, highlightthickness=1, bd=0)
    watch_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    watch_header = app._frame(watch_panel, bg="bg")
    watch_header.pack(fill="x", pady=(0, 5))
    app._label(
        watch_header, "SYMBOL WATCHLIST · 28 MAJOR / CROSS FX PAIRS",
        bg="bg", fg="text", font=("Consolas", 8, "bold"),
    ).pack(side="left")
    app._label(
        watch_panel,
        "REFERENCE SCHEDULE ONLY · NY 17:00 SUNDAY OPEN / FRIDAY CLOSE · NOT BROKER QUOTES",
        bg="bg", fg="muted", font=("Consolas", 6),
    ).pack(anchor="w", pady=(0, 5))
    watch_frame = app._frame(watch_panel, bg="bg")
    watch_frame.pack(fill="both", expand=True)
    watch_columns = ("symbol", "status", "countdown", "today", "next")
    app.alerts_watch_tree = ttk.Treeview(
        watch_frame, columns=watch_columns, show="headings", height=14,
        style="Veltrix.Watch.Treeview", selectmode="browse",
    )
    watch_headings = {
        "symbol": ("SYMBOL", 76, "center"),
        "status": ("STATUS", 76, "center"),
        "countdown": ("LIVE COUNTDOWN", 112, "center"),
        "today": ("TODAY", 105, "center"),
        "next": ("NEXT", 150, "w"),
    }
    for key, (label, width, anchor) in watch_headings.items():
        app.alerts_watch_tree.heading(key, text=label)
        app.alerts_watch_tree.column(
            key, width=width, minwidth=48, anchor=anchor, stretch=key == "next"
        )
    watch_scroll = ttk.Scrollbar(
        watch_frame, orient="vertical", command=app.alerts_watch_tree.yview,
        style="Veltrix.Alerts.Vertical.TScrollbar",
    )
    app.alerts_watch_tree.configure(yscrollcommand=watch_scroll.set)
    app.alerts_watch_tree.pack(side="left", fill="both", expand=True)
    watch_scroll.pack(side="right", fill="y")

    news_panel = app._frame(lower, bg="bg", padx=7, pady=7, highlightthickness=1, bd=0)
    news_panel.grid(row=0, column=1, sticky="nsew")
    app._label(
        news_panel, "NEWS CALENDAR · HIGH / MEDIUM IMPACT",
        bg="bg", fg="text", font=("Consolas", 8, "bold"),
    ).pack(anchor="w", pady=(0, 6))
    news_controls = app._frame(news_panel, bg="bg")
    news_controls.pack(fill="x", pady=(0, 5))
    app.alerts_news_previous_button = tk.Button(
        news_controls, text="‹", command=lambda: shift_calendar_date(app, -1),
        font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=6, pady=3, cursor="hand2",
    )
    app.alerts_news_previous_button.pack(side="left")
    app.alerts_news_today_button = tk.Button(
        news_controls, text="TODAY", command=lambda: show_calendar_today(app),
        font=("Consolas", 6, "bold"), relief="flat", bd=0, padx=6, pady=3, cursor="hand2",
    )
    app.alerts_news_today_button.pack(side="left", padx=(3, 0))
    app.alerts_news_next_button = tk.Button(
        news_controls, text="›", command=lambda: shift_calendar_date(app, 1),
        font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=6, pady=3, cursor="hand2",
    )
    app.alerts_news_next_button.pack(side="left", padx=(3, 5))
    app.alerts_news_date_label = app._label(
        news_controls, datetime.now(app.home_zone).strftime("%a %d %b").upper(),
        bg="bg", fg="muted", font=("Consolas", 6, "bold"),
    )
    app.alerts_news_date_label.pack(side="left", padx=(0, 5))
    app.alerts_news_impact_var = tk.StringVar(value="High + Medium")
    app.alerts_news_impact_combo = ttk.Combobox(
        news_controls, textvariable=app.alerts_news_impact_var,
        values=("High + Medium", "All impacts", "High only", "Medium only"),
        state="readonly", width=12, style="Veltrix.Alerts.TCombobox",
    )
    app.alerts_news_impact_combo.pack(side="right")
    app.alerts_news_impact_combo.bind(
        "<<ComboboxSelected>>", lambda _event: refresh_alerts_dashboard(
            app, datetime.now(timezone.utc), app.latest_session_states, force=True
        )
    )
    news_frame = app._frame(news_panel, bg="bg")
    news_frame.pack(fill="both", expand=True)
    news_columns = ("time", "currency", "impact", "event", "countdown")
    app.alerts_news_tree = ttk.Treeview(
        news_frame, columns=news_columns, show="headings", height=11,
        style="Veltrix.News.Treeview", selectmode="browse",
    )
    news_headings = {
        "time": ("TIME", 55, "center"),
        "currency": ("CUR", 38, "center"),
        "impact": ("IMPACT", 58, "center"),
        "event": ("EVENT", 145, "w"),
        "countdown": ("STATUS / COUNTDOWN", 92, "center"),
    }
    for key, (label, width, anchor) in news_headings.items():
        app.alerts_news_tree.heading(key, text=label)
        app.alerts_news_tree.column(
            key, width=width, minwidth=36, anchor=anchor, stretch=key == "event"
        )
    news_scroll = ttk.Scrollbar(
        news_frame, orient="vertical", command=app.alerts_news_tree.yview,
        style="Veltrix.Alerts.Vertical.TScrollbar",
    )
    app.alerts_news_tree.configure(yscrollcommand=news_scroll.set)
    app.alerts_news_tree.pack(side="left", fill="both", expand=True)
    news_scroll.pack(side="right", fill="y")
    app.alerts_news_count_label = app._label(
        news_panel, "SHOWING 0 EVENTS", bg="bg", fg="muted", font=("Consolas", 6)
    )
    app.alerts_news_count_label.pack(anchor="w", pady=(4, 0))
    app.alerts_news_source_label = app._label(
        news_panel, "SOURCE · SHOWMYTRADES PUBLIC ECONOMIC CALENDAR",
        bg="bg", fg="muted", font=("Consolas", 6), anchor="w", wraplength=330,
    )
    app.alerts_news_source_label.pack(anchor="w", pady=(2, 0))

    activity = app._frame(parent, bg="panel", padx=10, pady=7, highlightthickness=1, bd=0)
    activity.pack(fill="x", pady=(0, 7))
    app.alerts_recent_banner = app._label(
        activity, "RECENT ALERT ACTIVITY · NO ALERTS YET",
        bg="panel", fg="muted", font=("Consolas", 7, "bold"),
    )
    app.alerts_recent_banner.pack(anchor="w", pady=(0, 4))
    app.alerts_recent_listbox = tk.Listbox(
        activity, height=3, font=("Consolas", 7), relief="flat", bd=0,
        activestyle="none", exportselection=False,
    )
    app.alerts_recent_listbox.pack(fill="x")

    apply_alerts_tree_theme(app)


def draw_alerts_session_timeline(app, now_utc: datetime, states: list) -> None:
    """Draw the same UTC market schedule as the Global Sessions page in compact form."""
    canvas = app.alerts_session_canvas
    palette = THEMES[app.theme_name]
    start_utc = now_utc.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    snapshot = build_session_timeline(
        app.sessions, start_utc, hours=24,
        apply_exchange_calendar=app.exchange_calendar_enabled_var.get(),
    )
    width = max(440, canvas.winfo_width())
    height = 148
    signature = (
        width, height, app.theme_name, start_utc.date().isoformat(),
        bool(app.exchange_calendar_enabled_var.get()),
        tuple((s.key, s.opens, s.closes, s.weekdays, s.timezone_name) for s in app.sessions),
    )
    left, right = 47.0, float(width - 8)
    span = max(10.0, right - left)
    top, lane_step, lane_height = 32.0, 25.0, 14.0
    if signature != app.alerts_session_timeline_signature:
        canvas.delete("all")
        canvas.configure(bg=palette["bg"])
        canvas.create_text(
            left + span / 4, 8, text="AM", fill=palette["muted"],
            font=("Consolas", 6, "bold"), tags="alerts-timeline-static",
        )
        canvas.create_text(
            left + span * 3 / 4, 8, text="PM", fill=palette["muted"],
            font=("Consolas", 6, "bold"), tags="alerts-timeline-static",
        )
        for hour in range(25):
            x = left + span * hour / 24
            major = hour % 3 == 0
            canvas.create_line(
                x, top - 9, x, top + lane_step * len(app.sessions) + 7,
                fill=palette["dim"] if major else palette["border"],
                width=1, tags="alerts-timeline-static",
            )
            if hour < 24:
                canvas.create_text(
                    x, 20, text=str(hour % 12 or 12), fill=palette["muted"],
                    anchor="center", font=("Consolas", 5), tags="alerts-timeline-static",
                )
        colours = (palette["success"], palette["bright"], palette["warning"], palette["error"])
        for index, session in enumerate(app.sessions):
            y = top + index * lane_step
            canvas.create_text(
                left - 6, y + lane_height / 2,
                text=_SESSION_SHORT_NAMES.get(session.key, session.name[:3]),
                fill=palette["text"], anchor="e", font=("Consolas", 6, "bold"),
                tags="alerts-timeline-static",
            )
            canvas.create_rectangle(
                left, y, right, y + lane_height,
                fill=palette["dim"], outline=palette["border"], width=1,
                tags="alerts-timeline-static",
            )
            colour = colours[index % len(colours)]
            for window in snapshot.windows:
                if window.session_key != session.key:
                    continue
                x1 = left + span * (window.starts_at - start_utc).total_seconds() / 86400
                x2 = left + span * (window.ends_at - start_utc).total_seconds() / 86400
                canvas.create_rectangle(
                    x1, y + 1, max(x1 + 1, x2), y + lane_height - 1,
                    fill=colour, outline=colour, tags="alerts-timeline-static",
                )
        app.alerts_session_timeline_signature = signature
    else:
        canvas.delete("alerts-timeline-dynamic")

    marker = now_utc.astimezone(timezone.utc)
    if marker.date() == start_utc.date():
        x = left + span * (marker.hour * 3600 + marker.minute * 60 + marker.second) / 86400
        canvas.create_line(
            x, top - 12, x, top + lane_step * len(app.sessions) + 4,
            fill=palette["warning"], width=2, tags="alerts-timeline-dynamic",
        )
        canvas.create_rectangle(
            x - 11, 3, x + 11, 15, fill=palette["warning"],
            outline=palette["warning"], tags="alerts-timeline-dynamic",
        )
        canvas.create_text(
            x, 9, text=marker.strftime("%H:%M"), fill=palette["bg"],
            font=("Consolas", 5, "bold"), tags="alerts-timeline-dynamic",
        )


def clear_search_placeholder(app) -> None:
    if app.alerts_market_watch_entry.get() == "Search symbol / event":
        app.alerts_market_watch_entry.delete(0, tk.END)
        app.alerts_search_var.set("")


def clear_watch_search(app) -> None:
    app.alerts_market_watch_entry.delete(0, tk.END)
    app.alerts_search_var.set("")
    refresh_alerts_dashboard(app, datetime.now(timezone.utc), app.latest_session_states, force=True)


def set_watch_sort(app, descending: bool) -> None:
    app.alerts_watch_sort_descending = bool(descending)
    refresh_alerts_dashboard(app, datetime.now(timezone.utc), app.latest_session_states, force=True)


def shift_calendar_date(app, days: int) -> None:
    app.alerts_calendar_day += timedelta(days=int(days))
    refresh_alerts_dashboard(app, datetime.now(timezone.utc), app.latest_session_states, force=True)


def show_calendar_today(app) -> None:
    app.alerts_calendar_day = datetime.now(app.home_zone).date()
    refresh_alerts_dashboard(app, datetime.now(timezone.utc), app.latest_session_states, force=True)


def toggle_alert_settings(app) -> None:
    if app.alert_settings_visible:
        app.alert_settings_container.pack_forget()
        app.alert_settings_visible = False
        app.alert_config_toggle.configure(text="ALERT RULES / PREFERENCES  ▸")
    else:
        app.alert_settings_container.pack(fill="x", pady=(0, 8))
        app.alert_settings_visible = True
        app.alert_config_toggle.configure(text="ALERT RULES / PREFERENCES  ▾")
    app.alerts_canvas.configure(scrollregion=app.alerts_canvas.bbox("all"))


def refresh_alerts_dashboard(
    app, now_utc: datetime, states: list, *, force: bool = False
) -> None:
    """Update session status, reference FX watchlist and provider-sourced macro events."""
    if not hasattr(app, "alerts_watch_tree"):
        return
    palette = THEMES[app.theme_name]
    home_now = now_utc.astimezone(app.home_zone)
    app.alerts_system_time_label.configure(text=home_now.strftime("%H:%M:%S"))
    app.alerts_system_date_label.configure(text=home_now.strftime("%d %B %Y").upper())
    app.alerts_system_zone_label.configure(text=app.home_zone.key.upper())
    draw_alerts_session_timeline(app, now_utc, states)

    active_names = []
    for state in states:
        if state.is_open:
            active_names.append(state.definition.name.title())
        row = app.alerts_session_rows.get(state.definition.key)
        if row is None:
            continue
        if state.calendar_status == "EXCHANGE_HOLIDAY":
            text_value, colour = "HOLIDAY", palette["error"]
        elif state.calendar_status in {"OUT_OF_RANGE", "NO_VENUE_MAPPING"}:
            text_value, colour = "SCHED", palette["warning"]
        elif state.calendar_status in {"EARLY_CLOSE", "CLOSING_PROCESS"}:
            text_value, colour = (
                "EARLY" if state.calendar_status == "EARLY_CLOSE" else "PROCESS",
                palette["warning"],
            )
        elif state.is_open:
            text_value, colour = "OPEN", palette["success"]
        else:
            text_value, colour = "CLOSED", palette["muted"]
        row.configure(text=text_value, fg=colour)

    if len(active_names) >= 2:
        overlap_text, overlap_colour = "OVERLAP · " + " + ".join(active_names), palette["success"]
    elif active_names:
        overlap_text, overlap_colour = "NO MAJOR OVERLAP", palette["muted"]
    else:
        overlap_text, overlap_colour = "NO SESSION OPEN", palette["muted"]
    app.alerts_overlap_summary.configure(text=overlap_text, fg=overlap_colour)
    app.alerts_active_summary.configure(
        text=f"ACTIVE CENTRES · {len(active_names)} / {len(app.sessions)}"
    )

    fx_state = fx_reference_week_state(now_utc)
    fx_status = "OPEN" if fx_state.is_open else "CLOSED"
    fx_countdown = format_countdown(fx_state.seconds_to_transition)
    next_label = fx_reference_week_label(fx_state)
    today_label = "24/5 REF" if fx_state.is_open else "WEEKEND"
    search = app.alerts_search_var.get().strip().lower()
    if search == "search symbol / event":
        search = ""
    symbols = sorted(FX_REFERENCE_PAIRS, reverse=app.alerts_watch_sort_descending)
    visible_symbols = [symbol for symbol in symbols if not search or search in symbol.lower()]
    target_ids = set(visible_symbols)
    current_ids = set(app.alerts_watch_tree.get_children())
    if target_ids != current_ids:
        app.alerts_watch_tree.delete(*app.alerts_watch_tree.get_children())
        for symbol in visible_symbols:
            app.alerts_watch_tree.insert(
                "", "end", iid=symbol,
                values=(symbol, fx_status, fx_countdown, today_label, next_label),
                tags=("open" if fx_state.is_open else "closed",),
            )
    else:
        for symbol in visible_symbols:
            app.alerts_watch_tree.item(
                symbol,
                values=(symbol, fx_status, fx_countdown, today_label, next_label),
                tags=("open" if fx_state.is_open else "closed",),
            )
    app.alerts_watch_count_label.configure(
        text=(
            f"SHOWING 1–{len(visible_symbols)} OF {len(FX_REFERENCE_PAIRS)}"
            if visible_symbols else f"SHOWING 0 OF {len(FX_REFERENCE_PAIRS)}"
        )
    )

    selected_date = app.alerts_calendar_day
    app.alerts_news_date_label.configure(text=selected_date.strftime("%a %d %b").upper())
    allowed_impacts = {
        "High + Medium": {"high", "medium"},
        "High only": {"high"},
        "Medium only": {"medium"},
        "All impacts": {"high", "medium", "low", "holiday"},
    }.get(app.alerts_news_impact_var.get(), {"high", "medium"})
    event_rows = []
    for event in app.calendar_events:
        try:
            event_utc = datetime.fromtimestamp(int(event["timestamp_utc"]), tz=timezone.utc)
            event_local = event_utc.astimezone(app.home_zone)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if event_local.date() != selected_date:
            continue
        impact = str(event.get("impact", "unknown")).lower()
        if impact not in allowed_impacts:
            continue
        if search and search not in (
            str(event.get("currency", "")) + " " + str(event.get("title", ""))
        ).lower():
            continue
        event_rows.append((event_utc, event_local, event))
    event_rows.sort(key=lambda row: row[0])

    news_rows = []
    for index, (event_utc, event_local, event) in enumerate(event_rows):
        impact = str(event.get("impact", "unknown")).lower()
        status = str(event.get("status", "scheduled")).upper()
        title = str(event.get("title", "Unnamed event"))
        if status == "TENTATIVE":
            title = "≈ " + title
        elif status == "MOVED":
            title = "↪ " + title
        seconds = int((event_utc - now_utc).total_seconds())
        countdown = "TENTATIVE" if status == "TENTATIVE" else (
            "DONE" if seconds < 0 else format_countdown(seconds)
        )
        event_id = str(event.get("event_id", f"event-{index}"))
        iid = f"{event_id}-{int(event.get('timestamp_utc', 0))}"
        time_label = "TBD" if status == "TENTATIVE" else event_local.strftime("%H:%M")
        values = (
            time_label, str(event.get("currency", "")),
            impact.upper(), title, countdown,
        )
        tag = impact if impact in {"high", "medium", "low", "holiday"} else "low"
        news_rows.append((iid, values, (tag,)))

    target_news_ids = {row[0] for row in news_rows}
    current_news_ids = set(app.alerts_news_tree.get_children())
    if target_news_ids != current_news_ids:
        app.alerts_news_tree.delete(*app.alerts_news_tree.get_children())
        for iid, values, tags in news_rows:
            app.alerts_news_tree.insert("", "end", iid=iid, values=values, tags=tags)
    else:
        for iid, values, tags in news_rows:
            app.alerts_news_tree.item(iid, values=values, tags=tags)
    app.alerts_news_count_label.configure(text=f"SHOWING {len(news_rows)} EVENTS")

    upcoming = []
    for event in app.calendar_events:
        try:
            timestamp = int(event["timestamp_utc"])
            impact = str(event.get("impact", "unknown")).lower()
        except (KeyError, TypeError, ValueError):
            continue
        if impact in {"high", "medium"} and timestamp >= int(now_utc.timestamp()):
            upcoming.append((timestamp, event))
    upcoming.sort(key=lambda item: item[0])
    if upcoming:
        timestamp, event = upcoming[0]
        event_time = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(app.home_zone)
        impact = str(event.get("impact", "unknown")).upper()
        title = str(event.get("title", "UPCOMING EVENT"))
        event_status = str(event.get("status", "scheduled")).upper()
        if event_status == "TENTATIVE":
            ticker_text = (
                f"●  NEXT NEWS · {event_time.strftime('%a %d %b')} · "
                f"{event.get('currency', '')} {impact} · {title} · TENTATIVE / TIME UNCONFIRMED"
            )
        else:
            countdown = format_countdown(max(0, timestamp - int(now_utc.timestamp())))
            ticker_text = (
                f"●  NEXT NEWS ({event_time.strftime('%a %d %b %H:%M')}) · "
                f"{event.get('currency', '')} {impact} · {title} · {countdown}"
            )
        ticker_colour = palette["warning"] if impact == "HIGH" else palette["bright"]
    else:
        ticker_text = "●  NEXT NEWS · NO UPCOMING HIGH / MEDIUM EVENTS IN THE LOADED CALENDAR"
        ticker_colour = palette["muted"]
    app.alerts_news_ticker_label.configure(text=ticker_text, fg=ticker_colour)

    if app.calendar_last_fetch_monotonic is not None:
        app.alerts_feed_state_label.configure(
            text=f"SHOWMYTRADES · LIVE THIS RUN · {len(app.calendar_events)} EVENTS",
            fg=palette["success"],
        )
        app.alerts_news_source_label.configure(
            text="SOURCE · SHOWMYTRADES PUBLIC CALENDAR · LIVE FETCH IN THIS RUN",
            fg=palette["success"],
        )
    elif app.calendar_events:
        app.alerts_feed_state_label.configure(
            text="SHOWMYTRADES · CACHED SNAPSHOT", fg=palette["warning"],
        )
        app.alerts_news_source_label.configure(
            text="SOURCE · SHOWMYTRADES PUBLIC CALENDAR · CACHED / VERIFY FRESHNESS",
            fg=palette["warning"],
        )
    else:
        app.alerts_feed_state_label.configure(
            text="SHOWMYTRADES · WAITING FOR FEED", fg=palette["muted"],
        )
        app.alerts_news_source_label.configure(
            text="SOURCE · NO CALENDAR SNAPSHOT AVAILABLE", fg=palette["muted"],
        )


def apply_alerts_tree_theme(app) -> None:
    palette = THEMES[app.theme_name]
    style = ttk.Style(app.root)
    for prefix in ("Veltrix.Watch", "Veltrix.News"):
        style.configure(
            f"{prefix}.Treeview", background=palette["bg"], foreground=palette["text"],
            fieldbackground=palette["bg"], rowheight=23, bordercolor=palette["border"],
            font=("Consolas", 7),
        )
        style.configure(
            f"{prefix}.Treeview.Heading", background=palette["panel"],
            foreground=palette["bright"], relief="flat",
            font=("Consolas", 7, "bold"),
        )
        style.map(
            f"{prefix}.Treeview",
            background=[("selected", palette["button_active"])],
            foreground=[("selected", palette["bright"])],
        )
    style.configure(
        "Veltrix.Alerts.Vertical.TScrollbar",
        background=palette["button_bg"], troughcolor=palette["bg"],
        arrowcolor=palette["bright"], bordercolor=palette["border"],
    )
    style.configure(
        "Veltrix.Alerts.TCombobox", fieldbackground=palette["entry_bg"],
        background=palette["button_bg"], foreground=palette["entry_fg"],
        arrowcolor=palette["bright"],
    )
    if hasattr(app, "alerts_watch_tree"):
        app.alerts_watch_tree.tag_configure("open", foreground=palette["success"])
        app.alerts_watch_tree.tag_configure("closed", foreground=palette["muted"])
        app.alerts_news_tree.tag_configure("high", foreground=palette["error"])
        app.alerts_news_tree.tag_configure("medium", foreground=palette["warning"])
        app.alerts_news_tree.tag_configure("low", foreground=palette["success"])
        app.alerts_news_tree.tag_configure("holiday", foreground=palette["warning"])


def update_recent_alerts(app) -> None:
    if not hasattr(app, "alerts_recent_listbox"):
        return
    app.alerts_recent_listbox.delete(0, tk.END)
    for entry in app.alert_log_lines[:3]:
        app.alerts_recent_listbox.insert(tk.END, entry)
    app.alerts_recent_banner.configure(
        text=f"RECENT ALERT ACTIVITY · {len(app.alert_log_lines)} STORED EVENTS"
    )
