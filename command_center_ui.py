"""Tkinter presentation for the Veltrix Trading Command Center."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk

from command_center_engine import build_command_center_snapshot
from session_engine import format_countdown
from themes import THEMES


CHECKLIST_ITEMS = (
    ("calendar", "Review today's economic calendar"),
    ("sessions", "Check session schedule and holidays"),
    ("volatility", "Review volatility and expected moves"),
    ("risk", "Confirm instruments and risk limits"),
)


def _panel(app, parent, *, padding: int = 12):
    return app._frame(parent, bg="panel", padx=padding, pady=padding)


def _button(app, parent, text: str, command):
    palette = THEMES[app.theme_name]
    button = tk.Button(
        parent, text=text, command=command, font=("Segoe UI", 9, "bold"),
        relief="flat", bd=0, padx=10, pady=7, cursor="hand2",
        bg=palette["button_bg"], fg=palette["button_fg"],
        activebackground=palette["button_active"], activeforeground=palette["bright"],
    )
    app.command_center_buttons.append(button)
    return button


def _section_title(app, parent, title: str, hint: str = ""):
    row = app._frame(parent, bg="panel")
    row.pack(fill="x", pady=(0, 8))
    app._label(row, title, bg="panel", fg="bright", font=("Segoe UI", 10, "bold")).pack(side="left")
    if hint:
        app._label(row, hint, bg="panel", fg="muted", font=("Segoe UI", 8, "bold")).pack(side="right")
    return row


def _metric_card(app, parent, title: str, value: str, detail: str):
    frame = _panel(app, parent, padding=11)
    app._label(frame, title, bg="panel", fg="muted", font=("Segoe UI", 8, "bold")).pack(anchor="w")
    value_label = app._label(frame, value, bg="panel", fg="bright", font=("Segoe UI", 19, "bold"))
    value_label.pack(anchor="w", pady=(3, 0))
    detail_label = app._label(frame, detail, bg="panel", fg="muted", font=("Segoe UI", 8))
    detail_label.pack(anchor="w", pady=(2, 0))
    return {"frame": frame, "value": value_label, "detail": detail_label}


def _make_scrollable(app):
    shell = app._frame(app.command_center_view)
    shell.pack(fill="both", expand=True)
    app.command_center_canvas = tk.Canvas(
        shell, bg=THEMES[app.theme_name]["bg"], highlightthickness=0, bd=0,
    )
    scrollbar = ttk.Scrollbar(shell, orient="vertical", command=app.command_center_canvas.yview)
    app.command_center_canvas.configure(yscrollcommand=scrollbar.set)
    app.command_center_canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    content = app._frame(app.command_center_canvas)
    window = app.command_center_canvas.create_window((0, 0), window=content, anchor="nw")
    content.bind("<Configure>", lambda _event: app.command_center_canvas.configure(
        scrollregion=app.command_center_canvas.bbox("all")
    ))
    app.command_center_canvas.bind("<Configure>", lambda event: app.command_center_canvas.itemconfigure(
        window, width=event.width
    ))
    app.command_center_canvas.bind(
        "<MouseWheel>",
        lambda event: app.command_center_canvas.yview_scroll(int(-event.delta / 120), "units"),
    )
    app.command_center_canvas.bind("<Button-4>", lambda _event: app.command_center_canvas.yview_scroll(-1, "units"))
    app.command_center_canvas.bind("<Button-5>", lambda _event: app.command_center_canvas.yview_scroll(1, "units"))
    return content


def build_command_center_page(app) -> None:
    """Build the overview without replacing or hiding any existing workspace."""
    app.command_center_buttons = []
    app.command_center_checks = []
    app.command_center_check_vars = {}
    app.command_center_check_date = ""
    app.command_center_session_rows = {}
    app.command_center_event_rows = []
    app.command_center_market_rows = {}
    app.command_center_risk_rows = []

    content = _make_scrollable(app)
    heading = app._frame(content)
    heading.pack(fill="x", pady=(0, 10))
    heading_left = app._frame(heading)
    heading_left.pack(side="left", fill="x", expand=True)
    app._label(heading_left, "TRADING COMMAND CENTER", fg="bright",
               font=("Segoe UI", 17, "bold")).pack(anchor="w")
    app.command_center_subtitle = app._label(
        heading_left, "Live session context, scheduled events and indicative market data in one place.",
        fg="muted", font=("Segoe UI", 9),
    )
    app.command_center_subtitle.pack(anchor="w", pady=(2, 0))
    heading_right = app._frame(heading)
    heading_right.pack(side="right", anchor="e")
    app.command_center_updated_label = app._label(
        heading_right, "WAITING FOR FIRST UPDATE", fg="muted", font=("Segoe UI", 8, "bold")
    )
    app.command_center_updated_label.pack(anchor="e", pady=(0, 5))
    app.command_center_refresh_button = _button(
        app, heading_right, "REFRESH MARKET + CALENDAR", lambda: refresh_command_center_sources(app)
    )
    app.command_center_refresh_button.pack(anchor="e")

    actions = app._frame(content)
    actions.pack(fill="x", pady=(0, 10))
    for label, page in (
        ("GLOBAL SESSIONS", "sessions"),
        ("ALERTS & EVENTS", "alerts"),
        ("ECONOMIC CALENDAR", "calendar"),
        ("VOLATILITY LAB", "volatility"),
    ):
        _button(app, actions, label, lambda target=page: app.show_page(target)).pack(side="left", padx=(0, 6))

    metrics = app._frame(content)
    metrics.pack(fill="x", pady=(0, 10))
    for column in range(4):
        metrics.grid_columnconfigure(column, weight=1, uniform="command_metrics")
    app.command_center_metrics = {
        "open": _metric_card(app, metrics, "SESSIONS OPEN", "0 / 4", "Tracked market centres"),
        "overlap": _metric_card(app, metrics, "ACTIVE OVERLAP", "NONE", "Configured session windows"),
        "events": _metric_card(app, metrics, "EVENTS NEXT 24H", "0", "Scheduled calendar releases"),
        "feeds": _metric_card(app, metrics, "DATA FEEDS", "CACHED", "Market prices and calendar"),
    }
    for column, key in enumerate(app.command_center_metrics):
        app.command_center_metrics[key]["frame"].grid(
            row=0, column=column, sticky="nsew",
            padx=(0 if column == 0 else 5, 5 if column < 3 else 0),
        )

    sessions_panel = _panel(app, content, padding=12)
    sessions_panel.pack(fill="x", pady=(0, 10))
    _section_title(app, sessions_panel, "GLOBAL SESSION STATUS", "LIVE LOCAL TIME · NEXT TRANSITION")
    session_grid = app._frame(sessions_panel, bg="panel")
    session_grid.pack(fill="x")
    for column in range(4):
        session_grid.grid_columnconfigure(column, weight=1, uniform="command_sessions")
    for index, key in enumerate(("sydney", "tokyo", "london", "new_york")):
        card = app._frame(session_grid, bg="dim", padx=9, pady=9)
        card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 5, 5 if index < 3 else 0))
        name = app._label(card, key.replace("_", " ").upper(), bg="dim", fg="muted",
                          font=("Segoe UI", 8, "bold"))
        name.pack(anchor="w")
        time_label = app._label(card, "--:--:--", bg="dim", fg="bright", font=("Segoe UI", 17, "bold"))
        time_label.pack(anchor="w", pady=(3, 1))
        status = app._label(card, "WAITING", bg="dim", fg="muted", font=("Segoe UI", 8, "bold"))
        status.pack(anchor="w")
        transition = app._label(card, "NEXT TRANSITION · CALCULATING", bg="dim", fg="text",
                                font=("Segoe UI", 8), wraplength=235, justify="left")
        transition.pack(anchor="w", pady=(4, 0))
        app.command_center_session_rows[key] = {
            "name": name, "time": time_label, "status": status, "transition": transition,
        }

    lower = app._frame(content)
    lower.pack(fill="x", pady=(0, 10))
    lower.grid_columnconfigure(0, weight=3, uniform="command_lower")
    lower.grid_columnconfigure(1, weight=2, uniform="command_lower")

    events_panel = _panel(app, lower, padding=12)
    events_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    _section_title(app, events_panel, "UPCOMING ECONOMIC EVENTS", "NEXT 7 DAYS · HOME TIME")
    for _ in range(6):
        row = app._frame(events_panel, bg="panel")
        row.pack(fill="x", pady=4)
        title = app._label(row, "No upcoming events loaded", bg="panel", fg="text",
                           font=("Segoe UI", 9, "bold"), wraplength=500, justify="left")
        title.pack(anchor="w")
        meta = app._label(row, "Calendar feed is waiting for an update.", bg="panel", fg="muted",
                          font=("Segoe UI", 8))
        meta.pack(anchor="w", pady=(1, 0))
        app.command_center_event_rows.append({"title": title, "meta": meta})
    app.command_center_event_source_label = app._label(
        events_panel, "ECONOMIC DATA IS PROVIDER-SUPPLIED · VERIFY CRITICAL RELEASE TIMES",
        bg="panel", fg="muted", font=("Segoe UI", 7, "bold"), wraplength=600, justify="left",
    )
    app.command_center_event_source_label.pack(anchor="w", pady=(5, 0))

    market_panel = _panel(app, lower, padding=12)
    market_panel.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
    _section_title(app, market_panel, "VOLATILITY & MARKET SNAPSHOT", "INDICATIVE DATA")
    for index in range(3):
        row = app._frame(market_panel, bg="panel")
        row.pack(fill="x", pady=(3, 9))
        name = app._label(row, "INSTRUMENT", bg="panel", fg="muted", font=("Segoe UI", 8, "bold"))
        name.pack(anchor="w")
        price = app._label(row, "NO QUOTE DATA", bg="panel", fg="text", font=("Segoe UI", 13, "bold"))
        price.pack(anchor="w", pady=(2, 0))
        detail = app._label(row, "ATR(14): N/A  ·  HISTORICAL 1D 1σ: N/A", bg="panel", fg="muted",
                            font=("Segoe UI", 8), wraplength=360, justify="left")
        detail.pack(anchor="w", pady=(1, 0))
        app.command_center_market_rows[str(index)] = {"name": name, "price": price, "detail": detail}
    app.command_center_market_source_label = app._label(
        market_panel, "YAHOO FINANCE CHART DATA IS UNOFFICIAL AND MAY BE DELAYED OR CACHED.",
        bg="panel", fg="muted", font=("Segoe UI", 7, "bold"), wraplength=420, justify="left",
    )
    app.command_center_market_source_label.pack(anchor="w", pady=(2, 0))

    risk_panel = _panel(app, content, padding=12)
    risk_panel.pack(fill="x", pady=(0, 10))
    _section_title(app, risk_panel, "RISK & ATTENTION", "SCHEDULE FLAGS · LIVE VOLATILITY CONTEXT")
    app.command_center_risk_summary = app._label(
        risk_panel, "No active warnings have been evaluated yet.", bg="panel", fg="muted",
        font=("Segoe UI", 9), wraplength=1050, justify="left",
    )
    app.command_center_risk_summary.pack(anchor="w", pady=(0, 5))
    for _ in range(5):
        row = app._frame(risk_panel, bg="panel")
        row.pack(fill="x", pady=3)
        title = app._label(row, "NO ACTIVE WARNING", bg="panel", fg="muted",
                           font=("Segoe UI", 8, "bold"), wraplength=250, justify="left")
        title.pack(anchor="w")
        detail = app._label(row, "", bg="panel", fg="muted", font=("Segoe UI", 8),
                            wraplength=1050, justify="left")
        detail.pack(anchor="w", pady=(1, 0))
        app.command_center_risk_rows.append({"title": title, "detail": detail})

    checklist_panel = _panel(app, content, padding=12)
    checklist_panel.pack(fill="x", pady=(0, 10))
    _section_title(app, checklist_panel, "PRE-MARKET PREPARATION", "OPTIONAL DAILY CHECKLIST")
    app.command_center_check_progress = app._label(
        checklist_panel, "0 / 4 COMPLETE", bg="panel", fg="bright", font=("Segoe UI", 9, "bold")
    )
    app.command_center_check_progress.pack(anchor="w", pady=(0, 6))
    checks_row = app._frame(checklist_panel, bg="panel")
    checks_row.pack(fill="x")
    for key, label in CHECKLIST_ITEMS:
        variable = tk.BooleanVar(value=False)
        app.command_center_check_vars[key] = variable
        check = tk.Checkbutton(
            checks_row, text=label, variable=variable,
            command=lambda: save_command_center_checklist(app),
            font=("Segoe UI", 8, "bold"), relief="flat", bd=0, padx=5, pady=3,
            cursor="hand2", selectcolor=THEMES[app.theme_name]["dim"],
            activebackground=THEMES[app.theme_name]["panel"],
        )
        check.pack(side="left", padx=(0, 7))
        app.command_center_checks.append(check)
    _load_checklist_for_today(app)
    app.command_center_last_snapshot = {}


def _today_key(app) -> str:
    return datetime.now(timezone.utc).astimezone(app.home_zone).date().isoformat()


def _load_checklist_for_today(app) -> None:
    date_key = _today_key(app)
    if date_key == app.command_center_check_date:
        return
    settings = app.config.get("command_center", {})
    checklists = settings.get("daily_checklists", {}) if isinstance(settings, dict) else {}
    saved = checklists.get(date_key, {}) if isinstance(checklists, dict) else {}
    if not isinstance(saved, dict):
        saved = {}
    for key, variable in app.command_center_check_vars.items():
        variable.set(bool(saved.get(key, False)))
    app.command_center_check_date = date_key
    _update_checklist_progress(app)


def _update_checklist_progress(app) -> None:
    completed = sum(bool(variable.get()) for variable in app.command_center_check_vars.values())
    total = len(CHECKLIST_ITEMS)
    app.command_center_check_progress.configure(text=f"{completed} / {total} COMPLETE · DAILY PREPARATION")
    app.command_center_check_progress.configure(
        fg=THEMES[app.theme_name]["success"] if completed == total else THEMES[app.theme_name]["bright"]
    )


def save_command_center_checklist(app) -> None:
    _load_checklist_for_today(app)
    settings = app.config.setdefault("command_center", {})
    if not isinstance(settings, dict):
        settings = {}
        app.config["command_center"] = settings
    checklists = settings.setdefault("daily_checklists", {})
    if not isinstance(checklists, dict):
        checklists = {}
        settings["daily_checklists"] = checklists
    checklists[app.command_center_check_date] = {
        key: bool(variable.get()) for key, variable in app.command_center_check_vars.items()
    }
    for old_date in sorted(checklists)[:-14]:
        checklists.pop(old_date, None)
    app._save_config()
    _update_checklist_progress(app)


def refresh_command_center_sources(app) -> None:
    """Start existing non-blocking refresh workers; never fetch on the Tk event thread."""
    app.refresh_live_calendar(silent=False)
    app.refresh_market_data(silent=False)




def _format_source_timestamp(value: Any, home_zone) -> str:
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return "TIME UNKNOWN"
        return timestamp.astimezone(home_zone).strftime("%d %b %H:%M %Z")
    except (TypeError, ValueError, OverflowError):
        return "TIME UNKNOWN"

def refresh_command_center(app, now_utc: datetime | None = None) -> None:
    """Refresh dashboard labels from the app's latest in-memory state."""
    if not hasattr(app, "command_center_metrics"):
        return
    now = now_utc or datetime.now(timezone.utc)
    _load_checklist_for_today(app)
    home_zone = getattr(app, "home_zone", timezone.utc)
    home_timezone = getattr(home_zone, "key", "UTC")
    exchange_variable = getattr(app, "exchange_calendar_enabled_var", None)
    snapshot = build_command_center_snapshot(
        getattr(app, "latest_session_states", []),
        getattr(app, "calendar_events", []),
        getattr(app, "market_instruments", []),
        getattr(app, "market_summaries", {}),
        getattr(app, "market_reports", {}),
        getattr(app, "session_risk_settings", {}),
        now,
        home_timezone=home_timezone,
        exchange_calendar_enabled=bool(exchange_variable.get()) if exchange_variable is not None else False,
        market_is_fresh=bool(getattr(app, "market_is_fresh", False)),
        market_fetched_at=str(getattr(app, "market_snapshot", {}).get("fetched_at", "")),
        calendar_is_fresh=getattr(app, "calendar_last_fetch_monotonic", None) is not None,
        calendar_fetched_at=str(getattr(app, "calendar_last_updated", "")),
    )
    app.command_center_last_snapshot = snapshot
    palette = THEMES[app.theme_name]

    metrics = app.command_center_metrics
    metrics["open"]["value"].configure(text=f"{snapshot['open_count']} / {snapshot['session_count']}")
    metrics["open"]["detail"].configure(text="Tracked market centres currently scheduled open")
    overlap = " + ".join(snapshot["overlap_names"]) if snapshot["overlap_names"] else "NONE"
    metrics["overlap"]["value"].configure(text=overlap, font=("Segoe UI", 11, "bold"))
    metrics["overlap"]["detail"].configure(text="At least two configured session windows overlap")
    metrics["events"]["value"].configure(text=str(snapshot["event_count_next_24h"]))
    metrics["events"]["detail"].configure(text="Upcoming provider events within 24 hours")
    if snapshot["market_is_fresh"] and snapshot["calendar_is_fresh"]:
        feed_status, feed_colour = "UPDATED", palette["success"]
    elif snapshot["market_is_fresh"] or snapshot["calendar_is_fresh"]:
        feed_status, feed_colour = "PARTIAL", palette["warning"]
    else:
        feed_status, feed_colour = "CACHED", palette["warning"]
    metrics["feeds"]["value"].configure(text=feed_status, fg=feed_colour)
    metrics["feeds"]["detail"].configure(
        text=("Both providers refreshed successfully this run" if feed_status == "UPDATED"
              else "Cached/offline feeds are labelled, not treated as live")
    )

    app.command_center_updated_label.configure(
        text=f"UPDATED {now.astimezone(app.home_zone).strftime('%H:%M:%S %Z')}"
    )
    app.command_center_subtitle.configure(
        text=f"{now.astimezone(app.home_zone).strftime('%A · %d %B %Y')}  ·  "
             "Schedule context and indicative market data; not trading advice."
    )

    for item in snapshot["sessions"]:
        widgets = app.command_center_session_rows.get(item["key"])
        if not widgets:
            continue
        widgets["time"].configure(text=item["local_time"].strftime("%H:%M:%S"))
        if item["calendar_status"] == "EXCHANGE_HOLIDAY":
            status_text, colour = "EXCHANGE HOLIDAY", palette["error"]
        elif item["calendar_status"] in {"OUT_OF_RANGE", "NO_VENUE_MAPPING"}:
            status_text, colour = "SCHEDULE ONLY · VENUE UNVERIFIED", palette["warning"]
        elif item["calendar_status"] == "CLOSING_PROCESS" and item["transition_kind"] == "CLOSE_PROCESS":
            status_text, colour = "CLOSING PROCESS", palette["warning"]
        elif item["calendar_status"] == "EARLY_CLOSE" and item["is_open"]:
            status_text, colour = "EARLY CLOSE DAY", palette["warning"]
        elif item["is_open"]:
            status_text, colour = "OPEN", palette["success"]
        else:
            status_text, colour = "CLOSED", palette["muted"]
        widgets["status"].configure(text=status_text, fg=colour)
        action = "CLOSE" if item["transition_kind"] == "CLOSE" else (
            "CLOSING PROCESS" if item["transition_kind"] == "CLOSE_PROCESS" else "OPEN"
        )
        widgets["transition"].configure(
            text=f"NEXT {action} IN {format_countdown(item['seconds_to_transition'])}  ·  "
                 f"{item['transition_at'].strftime('%a %d %b %H:%M %Z')}"
        )

    for index, widgets in enumerate(app.command_center_event_rows):
        if index < len(snapshot["events"]):
            event = snapshot["events"][index]
            impact = event["impact"].upper()
            impact_colour = palette["error"] if impact == "HIGH" else (
                palette["warning"] if impact == "MEDIUM" else palette["muted"]
            )
            countdown = format_countdown(event["seconds_until"])
            status_note = f" · {event['status'].upper()}" if event["status"] != "scheduled" else ""
            widgets["title"].configure(
                text=f"{event['currency']}  ·  {event['title']}  ·  {impact}{status_note}",
                fg=impact_colour,
            )
            widgets["meta"].configure(
                text=f"{event['local_time'].strftime('%a %d %b · %H:%M %Z')}  ·  IN {countdown}"
            )
        else:
            widgets["title"].configure(
                text=("No upcoming events in the current calendar window" if index == 0
                      else ""),
                fg=palette["muted"],
            )
            widgets["meta"].configure(text="")
    calendar_time = _format_source_timestamp(snapshot["calendar_fetched_at"], app.home_zone)
    app.command_center_event_source_label.configure(
        text=(f"CALENDAR PROVIDER UPDATED THIS RUN · {calendar_time} · VERIFY HIGH-IMPORTANCE RELEASES WITH THE OFFICIAL SOURCE"
              if snapshot["calendar_is_fresh"]
              else "CACHED / UNVERIFIED CALENDAR · REFRESH OR VERIFY IMPORTANT RELEASE TIMES")
    )

    for index, widgets in enumerate(app.command_center_market_rows.values()):
        if index < len(snapshot["markets"]):
            item = snapshot["markets"][index]
            summary = item["summary"]
            quote = summary.get("quote")
            widgets["name"].configure(text=f"{item['name']}  ·  {item['symbol']}")
            widgets["price"].configure(
                text=(f"{float(quote):,.2f} {item['unit']}" if quote is not None else "NO QUOTE DATA"),
                fg=palette["text"] if quote is not None else palette["muted"],
            )
            atr = summary.get("atr")
            expected = summary.get("expected_move", {})
            move = expected.get("expected_move_abs") if isinstance(expected, dict) else None
            pct = expected.get("expected_move_pct") if isinstance(expected, dict) else None
            atr_text = f"ATR(14): {float(atr):,.2f}" if atr is not None else "ATR(14): N/A"
            move_text = (f"HISTORICAL 1D 1σ: ±{float(move):,.2f} ({float(pct):.2f}%)"
                         if move is not None and pct is not None else "HISTORICAL 1D 1σ: N/A")
            bar_time = _format_source_timestamp(summary.get("quote_time", ""), app.home_zone)
            widgets["detail"].configure(text=f"{atr_text} {item['unit']}  ·  {move_text}  ·  BAR {bar_time}")
        else:
            widgets["name"].configure(text="")
            widgets["price"].configure(text="")
            widgets["detail"].configure(text="")
    market_time = _format_source_timestamp(snapshot["market_fetched_at"], app.home_zone)
    app.command_center_market_source_label.configure(
        text=(f"YAHOO FINANCE CHART DATA · FETCHED {market_time} · INDICATIVE ONLY"
              if snapshot["market_is_fresh"]
              else "YAHOO FINANCE CHART DATA · CACHED / UNVERIFIED THIS RUN · INDICATIVE ONLY")
    )

    risks = snapshot["risks"]
    app.command_center_risk_summary.configure(
        text=(f"{len(risks)} active attention item(s). Review the underlying session or volatility workspace."
              if risks else "NO ACTIVE HIGH / CAUTION FLAGS FROM THE CURRENT SCHEDULE AND LIVE VOLATILITY OBSERVATIONS."),
        fg=palette["warning"] if risks else palette["muted"],
    )
    for index, widgets in enumerate(app.command_center_risk_rows):
        if index < len(risks):
            item = risks[index]
            colour = palette["error"] if item["severity"] == "HIGH" else palette["warning"]
            widgets["title"].configure(text=f"{item['severity']}  ·  {item['source']}  ·  {item['label']}", fg=colour)
            widgets["detail"].configure(text=item["detail"], fg=palette["muted"])
        else:
            widgets["title"].configure(
                text="NO ADDITIONAL ACTIVE WARNING" if index == 0 and not risks else "",
                fg=palette["muted"],
            )
            widgets["detail"].configure(text="")


def apply_command_center_theme(app) -> None:
    """Apply theme-specific styling to classic Tk controls in the new workspace."""
    if not hasattr(app, "command_center_buttons"):
        return
    palette = THEMES[app.theme_name]
    for button in app.command_center_buttons:
        button.configure(
            bg=palette["button_bg"], fg=palette["button_fg"],
            activebackground=palette["button_active"], activeforeground=palette["bright"],
        )
    for check in app.command_center_checks:
        check.configure(
            bg=palette["panel"], fg=palette["text"], selectcolor=palette["dim"],
            activebackground=palette["panel"], activeforeground=palette["bright"],
        )
    if hasattr(app, "command_center_canvas"):
        app.command_center_canvas.configure(bg=palette["bg"])
    if hasattr(app, "command_center_check_progress"):
        completed = sum(bool(variable.get()) for variable in app.command_center_check_vars.values())
        app.command_center_check_progress.configure(
            fg=palette["success"] if completed == len(CHECKLIST_ITEMS) else palette["bright"]
        )
