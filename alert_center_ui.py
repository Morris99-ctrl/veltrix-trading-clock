"""Tkinter Alert Intelligence Center for Veltrix Trading Clock."""
from __future__ import annotations

from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk

from alert_intelligence import AlertCenterStore, build_alert_candidates
from themes import THEMES


def build_alert_center(app, parent: tk.Widget) -> None:
    """Build the live alert terminal above the retained Market Watch workspace."""
    palette = THEMES[app.theme_name]
    shell = app._frame(parent, bg="panel", padx=11, pady=10, highlightthickness=0, bd=0)
    shell.pack(fill="both", expand=False, pady=(0, 8))

    header = app._frame(shell, bg="panel")
    header.pack(fill="x", pady=(0, 8))
    app._label(
        header, "ALERT INTELLIGENCE CENTER", bg="panel", fg="bright",
        font=("Segoe UI", 13, "bold"),
    ).pack(side="left", anchor="w")
    app.alert_center_feed_label = app._label(
        header, "● MONITORING · LIVE SESSION / CALENDAR CONTEXT",
        bg="panel", fg="muted", font=("Segoe UI", 8, "bold"),
    )
    app.alert_center_feed_label.pack(side="right", anchor="e")

    metrics = app._frame(shell, bg="panel")
    metrics.pack(fill="x", pady=(0, 8))
    app.alert_center_metric_labels = {}
    for column, (key, label, colour) in enumerate((
        ("ACTIVE", "ACTIVE NOW", "success"),
        ("UPCOMING", "UPCOMING", "warning"),
        ("TRIGGERED", "TRIGGERED", "error"),
        ("ACKNOWLEDGED", "ACKNOWLEDGED", "muted"),
    )):
        tile = app._frame(metrics, bg="bg", padx=10, pady=7, highlightthickness=0, bd=0)
        tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 5 if column < 3 else 0))
        metrics.grid_columnconfigure(column, weight=1, uniform="alert_metrics")
        app._label(tile, label, bg="bg", fg="muted", font=("Segoe UI", 8, "bold")).pack(anchor="w")
        value = app._label(tile, "0", bg="bg", fg=colour, font=("Segoe UI", 16, "bold"))
        value.pack(anchor="w", pady=(2, 0))
        app.alert_center_metric_labels[key] = value

    controls = app._frame(shell, bg="panel")
    controls.pack(fill="x", pady=(0, 7))
    app.alert_center_status_var = tk.StringVar(value="ALL")
    app.alert_center_market_var = tk.StringVar(value="ALL")
    app.alert_center_impact_var = tk.StringVar(value="ALL")
    app.alert_center_search_var = tk.StringVar(value="")

    def changed(*_args) -> None:
        refresh_alert_center(
            app, datetime.now(timezone.utc), app.latest_session_states,
            app.calendar_events, app.economic_events,
        )

    app._label(controls, "STATUS", bg="panel", fg="muted", font=("Segoe UI", 8, "bold")).pack(side="left", padx=(2, 4))
    app.alert_center_status_combo = ttk.Combobox(
        controls, textvariable=app.alert_center_status_var,
        values=("ALL", "ACTIVE", "UPCOMING", "TRIGGERED", "ACKNOWLEDGED"),
        state="readonly", width=15, style="Veltrix.AlertCenter.TCombobox",
    )
    app.alert_center_status_combo.pack(side="left", padx=(0, 9))
    app.alert_center_status_combo.bind("<<ComboboxSelected>>", changed)

    app._label(controls, "MARKET", bg="panel", fg="muted", font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 4))
    app.alert_center_market_combo = ttk.Combobox(
        controls, textvariable=app.alert_center_market_var,
        values=("ALL", "GLOBAL", "SYDNEY", "TOKYO", "LONDON", "NEW YORK", "USD", "EUR", "GBP", "JPY", "AUD", "CUSTOM"),
        state="readonly", width=12, style="Veltrix.AlertCenter.TCombobox",
    )
    app.alert_center_market_combo.pack(side="left", padx=(0, 9))
    app.alert_center_market_combo.bind("<<ComboboxSelected>>", changed)

    app._label(controls, "IMPACT", bg="panel", fg="muted", font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 4))
    app.alert_center_impact_combo = ttk.Combobox(
        controls, textvariable=app.alert_center_impact_var,
        values=("ALL", "HIGH", "MEDIUM", "LOW", "INFO"),
        state="readonly", width=9, style="Veltrix.AlertCenter.TCombobox",
    )
    app.alert_center_impact_combo.pack(side="left", padx=(0, 9))
    app.alert_center_impact_combo.bind("<<ComboboxSelected>>", changed)

    app.alert_center_search_entry = tk.Entry(
        controls, textvariable=app.alert_center_search_var, width=19,
        font=("Segoe UI", 9), relief="flat", bd=0,
    )
    app.alert_center_search_entry.pack(side="left", padx=(0, 5), ipady=5)
    app.alert_center_search_entry.insert(0, "")
    app.alert_center_search_var.trace_add("write", changed)

    app.alert_center_reset_button = tk.Button(
        controls, text="RESET", command=lambda: reset_alert_center_filters(app),
        font=("Segoe UI", 8, "bold"), relief="flat", bd=0, padx=9, pady=5, cursor="hand2",
    )
    app.alert_center_reset_button.pack(side="left")

    table_frame = app._frame(shell, bg="panel")
    table_frame.pack(fill="both", expand=True)
    columns = ("status", "time", "market", "impact", "alert", "source")
    app.alert_center_tree = ttk.Treeview(
        table_frame, columns=columns, show="headings", height=8,
        style="Veltrix.AlertCenter.Treeview", selectmode="browse",
    )
    specs = {
        "status": ("STATUS", 104, "center"),
        "time": ("LOCAL TIME / ETA", 160, "center"),
        "market": ("MARKET", 100, "center"),
        "impact": ("IMPACT", 76, "center"),
        "alert": ("ALERT / EVENT", 310, "w"),
        "source": ("SOURCE", 142, "w"),
    }
    for key, (heading, width, anchor) in specs.items():
        app.alert_center_tree.heading(key, text=heading)
        app.alert_center_tree.column(
            key, width=width, minwidth=58, anchor=anchor,
            stretch=key in {"alert", "source"},
        )
    scrollbar = ttk.Scrollbar(
        table_frame, orient="vertical", command=app.alert_center_tree.yview,
        style="Veltrix.Alerts.Vertical.TScrollbar",
    )
    app.alert_center_tree.configure(yscrollcommand=scrollbar.set)
    app.alert_center_tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    app.alert_center_tree.bind("<<TreeviewSelect>>", lambda _event: show_selected_alert(app))

    footer = app._frame(shell, bg="panel")
    footer.pack(fill="x", pady=(7, 0))
    app.alert_center_detail_label = app._label(
        footer, "SELECT AN ALERT TO INSPECT ITS SOURCE AND DETAILS.",
        bg="panel", fg="text", font=("Segoe UI", 9, "bold"), anchor="w",
    )
    app.alert_center_detail_label.pack(fill="x")
    app.alert_center_message_label = app._label(
        footer, "Upcoming rows are schedule/calendar context. They do not send a notification until the existing reminder rules are due.",
        bg="panel", fg="muted", font=("Segoe UI", 8), anchor="w", justify="left", wraplength=1040,
    )
    app.alert_center_message_label.pack(fill="x", pady=(3, 0))

    actions = app._frame(footer, bg="panel")
    actions.pack(fill="x", pady=(6, 0))
    app.alert_center_ack_button = tk.Button(
        actions, text="ACKNOWLEDGE SELECTED",
        command=lambda: acknowledge_selected_alert(app),
        font=("Segoe UI", 8, "bold"), relief="flat", bd=0, padx=11, pady=6, cursor="hand2",
    )
    app.alert_center_ack_button.pack(side="left", padx=(0, 6))
    app.alert_center_ack_all_button = tk.Button(
        actions, text="ACKNOWLEDGE VISIBLE TRIGGERED",
        command=lambda: acknowledge_visible_triggered(app),
        font=("Segoe UI", 8, "bold"), relief="flat", bd=0, padx=11, pady=6, cursor="hand2",
    )
    app.alert_center_ack_all_button.pack(side="left")
    app.alert_center_count_label = app._label(
        actions, "0 ITEMS", bg="panel", fg="muted", font=("Segoe UI", 8),
    )
    app.alert_center_count_label.pack(side="right", padx=(6, 2))

    app.alert_center_candidates = []
    app.alert_center_visible_by_id = {}
    app.alert_center_selected_id = None
    apply_alert_center_theme(app)


def _format_local_time(record: dict, home_zone) -> str:
    stamp = record.get("scheduled_at") or record.get("created_at") or ""
    if not stamp:
        return "LIVE"
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return "TIME N/A"
        local_text = parsed.astimezone(home_zone).strftime("%d %b · %H:%M")
    if str(record.get("status", "")).upper() == "UPCOMING":
        remaining = max(0, int((parsed - datetime.now(timezone.utc)).total_seconds()))
        days, remainder = divmod(remaining, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = remainder // 60
        eta = f"{days}d {hours}h" if days else (f"{hours}h {minutes:02d}m" if hours else f"{minutes}m")
        local_text += f" · {eta}"
    return local_text
    except (TypeError, ValueError, OverflowError, OSError):
        return "TIME N/A"


def refresh_alert_center(
    app,
    now_utc: datetime,
    states: list,
    calendar_events: list[dict],
    manual_events: list[dict],
) -> None:
    if not hasattr(app, "alert_center_tree"):
        return
    app.alert_center_candidates = build_alert_candidates(
        now_utc, states, calendar_events, manual_events, app.home_zone,
    )
    counts = app.alert_center.counts(app.alert_center_candidates)
    for key, label in app.alert_center_metric_labels.items():
        label.configure(text=str(counts.get(key, 0)))
    app.alert_center_feed_label.configure(
        text=f"● MONITORING · {now_utc.astimezone(app.home_zone).strftime('%H:%M:%S')} {app.home_zone.key.upper()}"
    )

    market_values = sorted({
        str(item.get("market", "GLOBAL")).upper()
        for item in app.alert_center.snapshot(app.alert_center_candidates)
    })
    app.alert_center_market_combo.configure(values=("ALL", *market_values))
    rows = app.alert_center.snapshot(
        app.alert_center_candidates,
        status=app.alert_center_status_var.get(),
        market=app.alert_center_market_var.get(),
        impact=app.alert_center_impact_var.get(),
        query=app.alert_center_search_var.get(),
    )
    visible = {str(row["id"]): row for row in rows}
    app.alert_center_visible_by_id = visible
    tree = app.alert_center_tree
    existing = set(tree.get_children())
    desired = set(visible)
    for item_id in existing - desired:
        tree.delete(item_id)
    for record_id, record in visible.items():
        status = str(record.get("status", "UPCOMING")).upper()
        values = (
            status,
            _format_local_time(record, app.home_zone),
            str(record.get("market", "GLOBAL")).upper(),
            str(record.get("impact", "INFO")).upper(),
            str(record.get("title", "")),
            str(record.get("source", "")),
        )
        if record_id in existing:
            tree.item(record_id, values=values, tags=(status.lower(),))
        else:
            tree.insert("", "end", iid=record_id, values=values, tags=(status.lower(),))

    selected = app.alert_center_selected_id
    if selected not in visible:
        current_selection = tree.selection()
        selected = current_selection[0] if current_selection and current_selection[0] in visible else None
    if selected is None and visible:
        selected = next(iter(visible))
    app.alert_center_selected_id = selected
    if selected is not None:
        tree.selection_set(selected)
        show_selected_alert(app)
    else:
        app.alert_center_detail_label.configure(text="NO ALERTS MATCH THE CURRENT FILTERS.")
        app.alert_center_message_label.configure(text="Reset the filters or wait for the next scheduled event.")
    app.alert_center_count_label.configure(text=f"{len(rows)} ITEMS · {len(app.alert_center_candidates)} LIVE CANDIDATES")


def show_selected_alert(app) -> None:
    selection = app.alert_center_tree.selection()
    if not selection:
        return
    record_id = selection[0]
    record = app.alert_center_visible_by_id.get(record_id)
    if not record:
        return
    app.alert_center_selected_id = record_id
    status = str(record.get("status", "")).upper()
    source = str(record.get("source", "Veltrix"))
    category = str(record.get("category", "alert")).upper()
    impact = str(record.get("impact", "INFO")).upper()
    market = str(record.get("market", "GLOBAL")).upper()
    app.alert_center_detail_label.configure(
        text=f"{status}  ·  {market}  ·  {impact} IMPACT  ·  {category}  ·  SOURCE: {source}"
    )
    app.alert_center_message_label.configure(
        text=str(record.get("message", "")) or "No additional detail was supplied."
    )


def acknowledge_selected_alert(app) -> None:
    selection = app.alert_center_tree.selection()
    if not selection:
        return
    changed = app.alert_center.acknowledge(
        selection[0], now=datetime.now(timezone.utc),
        candidates=app.alert_center_candidates,
    )
    if changed:
        app.config["alert_center"] = app.alert_center.export_state()
        app._save_config()
        app._set_alert_banner("ALERT ACKNOWLEDGED", "success")
        refresh_alert_center(
            app, datetime.now(timezone.utc), app.latest_session_states,
            app.calendar_events, app.economic_events,
        )


def acknowledge_visible_triggered(app) -> None:
    ids = [
        record_id for record_id, record in app.alert_center_visible_by_id.items()
        if record.get("status") == "TRIGGERED"
    ]
    changed = app.alert_center.acknowledge_many(
        ids, now=datetime.now(timezone.utc),
        candidates=app.alert_center_candidates,
    )
    if changed:
        app.config["alert_center"] = app.alert_center.export_state()
        app._save_config()
        app._set_alert_banner(f"{changed} TRIGGERED ALERT(S) ACKNOWLEDGED", "success")
        refresh_alert_center(
            app, datetime.now(timezone.utc), app.latest_session_states,
            app.calendar_events, app.economic_events,
        )


def reset_alert_center_filters(app) -> None:
    app.alert_center_status_var.set("ALL")
    app.alert_center_market_var.set("ALL")
    app.alert_center_impact_var.set("ALL")
    app.alert_center_search_var.set("")


def apply_alert_center_theme(app) -> None:
    if not hasattr(app, "alert_center_tree"):
        return
    palette = THEMES[app.theme_name]
    style = ttk.Style(app.root)
    style.configure(
        "Veltrix.AlertCenter.Treeview",
        background=palette["bg"], foreground=palette["text"],
        fieldbackground=palette["bg"], rowheight=31,
        bordercolor=palette["bg"], font=("Segoe UI", 9),
    )
    style.configure(
        "Veltrix.AlertCenter.Treeview.Heading",
        background=palette["panel"], foreground=palette["bright"],
        relief="flat", font=("Segoe UI", 8, "bold"),
    )
    style.map(
        "Veltrix.AlertCenter.Treeview",
        background=[("selected", palette["button_active"])],
        foreground=[("selected", palette["bright"])],
    )
    style.configure(
        "Veltrix.AlertCenter.TCombobox",
        fieldbackground=palette["entry_bg"], background=palette["button_bg"],
        foreground=palette["entry_fg"], arrowcolor=palette["bright"],
    )
    for tag, colour in (
        ("active", palette["success"]),
        ("upcoming", palette["warning"]),
        ("triggered", palette["error"]),
        ("acknowledged", palette["muted"]),
    ):
        app.alert_center_tree.tag_configure(tag, foreground=colour)
