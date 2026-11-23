"""Tkinter workspace for historical session-performance analytics."""
from __future__ import annotations

from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk

from themes import THEMES


def _pct(value, digits: int = 3) -> str:
    return "N/A" if value is None else f"{float(value):+.{digits}f}%"


def _plain_pct(value, digits: int = 2) -> str:
    return "N/A" if value is None else f"{float(value):.{digits}f}%"


def build_session_performance_page(app) -> None:
    palette = THEMES[app.theme_name]
    shell = app._frame(app.session_performance_view)
    shell.pack(fill="both", expand=True)
    app.session_performance_canvas = tk.Canvas(
        shell, bg=palette["bg"], highlightthickness=0, bd=0,
    )
    scrollbar = ttk.Scrollbar(
        shell, orient="vertical", command=app.session_performance_canvas.yview,
        style="Veltrix.Performance.Vertical.TScrollbar",
    )
    app.session_performance_canvas.configure(yscrollcommand=scrollbar.set)
    app.session_performance_canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    app.session_performance_content = app._frame(app.session_performance_canvas)
    app.session_performance_window = app.session_performance_canvas.create_window(
        (0, 0), window=app.session_performance_content, anchor="nw",
    )
    app.session_performance_content.bind(
        "<Configure>", lambda _event: app.session_performance_canvas.configure(
            scrollregion=app.session_performance_canvas.bbox("all")
        )
    )
    app.session_performance_canvas.bind(
        "<Configure>", lambda event: app.session_performance_canvas.itemconfigure(
            app.session_performance_window, width=event.width
        )
    )
    app.session_performance_canvas.bind(
        "<MouseWheel>",
        lambda event: app.session_performance_canvas.yview_scroll(int(-event.delta / 120), "units"),
    )
    app.session_performance_canvas.bind(
        "<Button-4>", lambda _event: app.session_performance_canvas.yview_scroll(-1, "units"),
    )
    app.session_performance_canvas.bind(
        "<Button-5>", lambda _event: app.session_performance_canvas.yview_scroll(1, "units"),
    )

    header = app._frame(app.session_performance_content, bg="panel", padx=14, pady=11)
    header.pack(fill="x", pady=(0, 9))
    app._label(
        header, "SESSION PERFORMANCE INTELLIGENCE", bg="panel", fg="bright",
        font=("Consolas", 12, "bold"),
    ).pack(anchor="w")
    app._label(
        header,
        "HISTORICAL OHLC STUDY · SESSION RETURNS · REALISED VOLATILITY · PAIRWISE OVERLAPS",
        bg="panel", fg="muted", font=("Consolas", 7, "bold"),
    ).pack(anchor="w", pady=(3, 7))
    app.session_performance_status_label = app._label(
        header, "IMPORT A TIME-STAMPED OHLC CSV IN REGIME LAB, THEN SELECT IT HERE.",
        bg="panel", fg="warning", font=("Consolas", 8, "bold"),
        anchor="w", justify="left", wraplength=1040,
    )
    app.session_performance_status_label.pack(fill="x")

    controls = app._frame(app.session_performance_content, bg="panel", padx=12, pady=10)
    controls.pack(fill="x", pady=(0, 9))
    controls.grid_columnconfigure(0, weight=1)
    app._label(
        controls, "LOCAL OHLC DATASET (SHARED WITH REGIME LAB)",
        bg="panel", fg="muted", font=("Consolas", 7, "bold"),
    ).grid(row=0, column=0, sticky="w")
    app.session_performance_dataset_var = tk.StringVar(value="")
    app.session_performance_dataset_combo = ttk.Combobox(
        controls, textvariable=app.session_performance_dataset_var,
        values=(), state="readonly", width=58, style="Veltrix.Performance.TCombobox",
    )
    app.session_performance_dataset_combo.grid(
        row=1, column=0, sticky="ew", pady=(4, 8)
    )
    app.session_performance_dataset_combo.bind(
        "<<ComboboxSelected>>", lambda _event: update_dataset_info(app)
    )
    app.session_performance_dataset_info = app._label(
        controls, "No dataset selected.", bg="panel", fg="muted",
        font=("Consolas", 7), anchor="w",
    )
    app.session_performance_dataset_info.grid(row=2, column=0, sticky="ew", pady=(0, 8))

    filters = app._frame(controls, bg="panel")
    filters.grid(row=3, column=0, sticky="ew")
    app._label(
        filters, "MIN BARS / SESSION DAY", bg="panel", fg="muted",
        font=("Consolas", 7, "bold"),
    ).pack(side="left")
    app.session_performance_min_bars_var = tk.StringVar(value="3")
    app.session_performance_min_bars_spin = tk.Spinbox(
        filters, from_=1, to=500, textvariable=app.session_performance_min_bars_var,
        width=5, font=("Consolas", 8, "bold"), justify="center",
        relief="flat", bd=0,
    )
    app.session_performance_min_bars_spin.pack(side="left", padx=(5, 16))
    app._label(
        filters, "MIN COVERAGE", bg="panel", fg="muted",
        font=("Consolas", 7, "bold"),
    ).pack(side="left")
    app.session_performance_min_coverage_var = tk.StringVar(value="50")
    app.session_performance_min_coverage_spin = tk.Spinbox(
        filters, from_=0, to=100, increment=5,
        textvariable=app.session_performance_min_coverage_var,
        width=5, font=("Consolas", 8, "bold"), justify="center",
        relief="flat", bd=0,
    )
    app.session_performance_min_coverage_spin.pack(side="left", padx=(5, 15))
    app._label(
        filters, "PROFILE", bg="panel", fg="muted",
        font=("Consolas", 7, "bold"),
    ).pack(side="left", padx=(0, 5))
    app.session_performance_profile_label = app._label(
        filters, str(app.active_session_profile).upper(), bg="panel", fg="bright",
        font=("Consolas", 7, "bold"),
    )
    app.session_performance_profile_label.pack(side="left")

    actions = app._frame(controls, bg="panel")
    actions.grid(row=4, column=0, sticky="ew", pady=(10, 0))
    app.session_performance_import_button = tk.Button(
        actions, text="IMPORT / MANAGE CSV IN REGIME LAB",
        command=lambda: app.show_page("regime"),
        font=("Consolas", 7, "bold"), relief="flat", bd=0, padx=10, pady=7,
        cursor="hand2",
    )
    app.session_performance_import_button.pack(side="left", padx=(0, 7))
    app.session_performance_run_button = tk.Button(
        actions, text="RUN SESSION STUDY", command=app.run_session_performance,
        font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=12, pady=7,
        cursor="hand2",
    )
    app.session_performance_run_button.pack(side="left", padx=(0, 7))
    app.session_performance_export_button = tk.Button(
        actions, text="EXPORT DAILY CSV", command=app.export_session_performance,
        font=("Consolas", 8, "bold"), relief="flat", bd=0, padx=12, pady=7,
        cursor="hand2", state="disabled",
    )
    app.session_performance_export_button.pack(side="left")

    summary_panel = app._frame(app.session_performance_content, bg="panel", padx=11, pady=9)
    summary_panel.pack(fill="x", pady=(0, 9))
    app._label(
        summary_panel, "STUDY SNAPSHOT", bg="panel", fg="bright",
        font=("Consolas", 9, "bold"),
    ).pack(anchor="w", pady=(0, 7))
    grid = app._frame(summary_panel, bg="panel")
    grid.pack(fill="x")
    for column in range(3):
        grid.grid_columnconfigure(column, weight=1, uniform="session_performance_metrics")
    app.session_performance_metric_tiles = {}
    metric_specs = (
        ("bars", "VALID OHLC BARS", "N/A"),
        ("samples", "INCLUDED SESSION DAYS", "N/A"),
        ("overlaps", "OVERLAP SAMPLE DAYS", "N/A"),
        ("interval", "BAR INTERVAL", "N/A"),
        ("excluded", "EXCLUDED SESSION DAYS", "N/A"),
        ("period", "DATA PERIOD (UTC)", "N/A"),
    )
    for index, (key, title, initial) in enumerate(metric_specs):
        row, column = divmod(index, 3)
        tile = app._frame(
            grid, bg="panel", padx=9, pady=7, highlightthickness=1, bd=0,
        )
        tile.grid(
            row=row, column=column, sticky="nsew",
            padx=(0 if column == 0 else 5, 5 if column < 2 else 0), pady=(0, 6),
        )
        title_label = app._label(
            tile, title, bg="panel", fg="muted", font=("Consolas", 7, "bold")
        )
        title_label.pack(anchor="w")
        value_label = app._label(
            tile, initial, bg="panel", fg="text", font=("Consolas", 11, "bold")
        )
        value_label.pack(anchor="w", pady=(3, 0))
        app.session_performance_metric_tiles[key] = {
            "frame": tile, "title": title_label, "value": value_label,
        }

    chart_panel = app._frame(app.session_performance_content, bg="panel", padx=11, pady=9)
    chart_panel.pack(fill="x", pady=(0, 9))
    app._label(
        chart_panel, "MEAN HISTORICAL SESSION RETURN · PER INCLUDED LOCAL SESSION DAY",
        bg="panel", fg="bright", font=("Consolas", 8, "bold"),
    ).pack(anchor="w", pady=(0, 6))
    app.session_performance_chart_canvas = tk.Canvas(
        chart_panel, height=190, bg=palette["panel"],
        highlightthickness=1, highlightbackground=palette["border"], bd=0,
    )
    app.session_performance_chart_canvas.pack(fill="x", expand=True)
    app.session_performance_chart_canvas.bind(
        "<Configure>", lambda _event: draw_session_performance_chart(app)
    )

    tables = app._frame(app.session_performance_content, bg="bg")
    tables.pack(fill="both", expand=True, pady=(0, 9))
    tables.grid_columnconfigure(0, weight=1)
    session_panel = app._frame(tables, bg="panel", padx=10, pady=9)
    session_panel.grid(row=0, column=0, sticky="nsew", pady=(0, 7))
    app._label(
        session_panel, "SESSION-BY-SESSION PERFORMANCE",
        bg="panel", fg="bright", font=("Consolas", 8, "bold"),
    ).pack(anchor="w", pady=(0, 5))
    columns = ("session", "samples", "bars", "mean", "median", "positive", "range", "volatility", "coverage")
    app.session_performance_tree = ttk.Treeview(
        session_panel, columns=columns, show="headings", height=4,
        style="Veltrix.Performance.Treeview", selectmode="browse",
    )
    headings = {
        "session": ("SESSION", 100, "w"),
        "samples": ("DAYS", 55, "center"),
        "bars": ("BARS", 60, "center"),
        "mean": ("MEAN RET %", 80, "center"),
        "median": ("MED RET %", 80, "center"),
        "positive": ("POSITIVE %", 75, "center"),
        "range": ("MEAN RNG %", 80, "center"),
        "volatility": ("REAL VOL %", 80, "center"),
        "coverage": ("COVERAGE %", 82, "center"),
    }
    for key, (heading, width, anchor) in headings.items():
        app.session_performance_tree.heading(key, text=heading)
        app.session_performance_tree.column(
            key, width=width, minwidth=44, anchor=anchor, stretch=key == "session"
        )
    app.session_performance_tree.pack(fill="x")

    overlap_panel = app._frame(tables, bg="panel", padx=10, pady=9)
    overlap_panel.grid(row=1, column=0, sticky="nsew")
    app._label(
        overlap_panel, "PAIRWISE SESSION OVERLAP PERFORMANCE",
        bg="panel", fg="bright", font=("Consolas", 8, "bold"),
    ).pack(anchor="w", pady=(0, 5))
    overlap_columns = ("pair", "days", "bars", "mean", "positive", "range", "volatility")
    app.session_performance_overlap_tree = ttk.Treeview(
        overlap_panel, columns=overlap_columns, show="headings", height=4,
        style="Veltrix.Performance.Treeview", selectmode="browse",
    )
    overlap_headings = {
        "pair": ("SESSION PAIR", 175, "w"),
        "days": ("DAYS", 60, "center"),
        "bars": ("OVERLAP BARS", 90, "center"),
        "mean": ("MEAN RET %", 85, "center"),
        "positive": ("POSITIVE %", 85, "center"),
        "range": ("MEAN RNG %", 85, "center"),
        "volatility": ("REAL VOL %", 85, "center"),
    }
    for key, (heading, width, anchor) in overlap_headings.items():
        app.session_performance_overlap_tree.heading(key, text=heading)
        app.session_performance_overlap_tree.column(
            key, width=width, minwidth=48, anchor=anchor, stretch=key == "pair"
        )
    app.session_performance_overlap_tree.pack(fill="x")

    note = app._frame(app.session_performance_content, bg="panel", padx=11, pady=9)
    note.pack(fill="x", pady=(0, 9))
    app._label(
        note, "METHODOLOGY / DATA QUALITY",
        bg="panel", fg="bright", font=("Consolas", 8, "bold"),
    ).pack(anchor="w", pady=(0, 4))
    methodology = (
        "Bars are allocated by BAR-OPEN timestamp in each session's own IANA timezone and configured weekday/open/close schedule. "
        "Returns are first observed session-bar open to last observed close. Range is observed high-to-low divided by first open. "
        "Realised volatility is the root-sum-square of observed bar log returns, expressed in percent (not annualised). "
        "Coverage is an estimate: observed bars / expected bars from the imported median interval. "
        "Incomplete days below your minimum bars or coverage are shown as excluded and do not enter the averages. "
        "Exchange holidays, broker-specific schedules, spreads, liquidity and execution are not inferred."
    )
    app.session_performance_methodology_label = app._label(
        note, methodology, bg="panel", fg="muted",
        font=("Segoe UI", 8), anchor="w", justify="left", wraplength=1050,
    )
    app.session_performance_methodology_label.pack(fill="x")

    apply_session_performance_theme(app)
    refresh_session_performance_dataset_choices(app)


def refresh_session_performance_dataset_choices(app) -> None:
    if not hasattr(app, "session_performance_dataset_combo"):
        return
    labels = []
    mapping = {}
    for label, key in app.regime_dataset_label_to_key.items():
        record = app.regime_datasets.get(key, {})
        if isinstance(record, dict) and record.get("bars"):
            labels.append(label)
            mapping[label] = key
    app.session_performance_dataset_label_to_key = mapping
    app.session_performance_dataset_combo.configure(values=labels)
    requested = str(app.regime_settings.get("selected_asset") or "")
    target = next((label for label, key in mapping.items() if key == requested), "")
    current = app.session_performance_dataset_var.get()
    if not target and current in mapping:
        target = current
    if not target and labels:
        target = labels[0]
    app.session_performance_dataset_var.set(target)
    update_dataset_info(app)


def selected_dataset_key(app) -> str:
    label = app.session_performance_dataset_var.get()
    return app.session_performance_dataset_label_to_key.get(label, "")


def update_dataset_info(app) -> None:
    key = selected_dataset_key(app)
    record = app.regime_datasets.get(key, {})
    if not isinstance(record, dict) or not record.get("bars"):
        app.session_performance_dataset_info.configure(
            text="NO IMPORTED OHLC DATASET · USE REGIME LAB TO IMPORT A CSV",
            fg=THEMES[app.theme_name]["warning"],
        )
        return
    metadata = record.get("metadata", {})
    interval = record.get("bar_interval_minutes", "N/A")
    app.session_performance_dataset_info.configure(
        text=(
            f"{record.get('name', key)} · {record.get('source', 'Local CSV')} · "
            f"{len(record.get('bars', [])):,} BARS · {interval} MIN MEDIAN INTERVAL · "
            f"NAIVE TIMEZONE {metadata.get('timezone_for_naive_timestamps', 'EXPLICIT UTC OFFSETS')}"
        ),
        fg=THEMES[app.theme_name]["muted"],
    )


def _draw_value(canvas, x, y, value, label, palette, width, scale):
    half = width / 2
    if value is None:
        canvas.create_text(8, y, text=label, anchor="w", fill=palette["text"], font=("Consolas", 8))
        canvas.create_text(half, y, text="NO QUALIFYING SAMPLES", anchor="w", fill=palette["muted"], font=("Consolas", 7))
        return
    canvas.create_text(8, y, text=label, anchor="w", fill=palette["text"], font=("Consolas", 8, "bold"))
    zero_x = half + 25
    value_width = min(140.0, abs(value) / scale * 140.0)
    positive = value >= 0
    bar_start = zero_x if positive else zero_x - value_width
    bar_end = zero_x + value_width if positive else zero_x
    colour = palette["success"] if positive else palette["error"]
    canvas.create_rectangle(
        bar_start, y - 7, bar_end, y + 7,
        fill=colour, outline=colour,
    )
    canvas.create_text(
        min(width - 12, zero_x + 155), y,
        text=f"{value:+.3f}%", anchor="e", fill=palette["text"],
        font=("Consolas", 7, "bold"),
    )


def draw_session_performance_chart(app) -> None:
    canvas = getattr(app, "session_performance_chart_canvas", None)
    if canvas is None:
        return
    palette = THEMES[app.theme_name]
    width = max(500, canvas.winfo_width())
    height = max(150, canvas.winfo_height())
    canvas.delete("all")
    canvas.configure(bg=palette["panel"])
    result = getattr(app, "session_performance_result", None)
    if not result:
        canvas.create_text(
            12, 18, text="RUN A SESSION STUDY TO PLOT HISTORICAL MEAN RETURNS",
            anchor="nw", fill=palette["muted"], font=("Consolas", 8, "bold"),
        )
        return
    values = [item["mean_return_pct"] for item in result.get("sessions", []) if item.get("sample_sessions", 0)]
    max_abs = max((abs(value) for value in values if value is not None), default=0.1)
    scale = max(max_abs, 0.1)
    rows = result.get("sessions", [])
    row_height = max(25.0, (height - 12) / max(1, len(rows)))
    for index, row in enumerate(rows):
        y = 18 + index * row_height
        label = str(row.get("session", ""))
        value = row.get("mean_return_pct") if row.get("sample_sessions", 0) else None
        _draw_value(canvas, 8, y, value, label, palette, width, scale)
    canvas.create_text(
        width - 10, height - 5, text="MEAN RETURN · % · NOT AN EXPECTED RETURN FORECAST",
        anchor="se", fill=palette["muted"], font=("Consolas", 6),
    )


def _format(value, digits: int = 3, suffix: str = "%") -> str:
    if value is None:
        return "N/A"
    return f"{float(value):+.{digits}f}{suffix}"


def render_session_performance_result(app, metadata: dict, result: dict) -> None:
    palette = THEMES[app.theme_name]
    app.session_performance_result = result
    app.session_performance_result_metadata = dict(metadata)
    sessions = result.get("sessions", [])
    overlaps = result.get("overlaps", [])
    total_samples = sum(int(row.get("sample_sessions", 0)) for row in sessions)
    overlap_samples = sum(int(row.get("sample_days", 0)) for row in overlaps)
    excluded = sum(
        int(row.get("excluded_low_bars", 0)) + int(row.get("excluded_low_coverage", 0))
        for row in sessions
    )
    meta = result.get("metadata", {})
    first = str(meta.get("first_timestamp_utc", ""))[:10]
    last = str(meta.get("last_timestamp_utc", ""))[:10]
    period = f"{first} → {last}" if first and last else "N/A"
    tiles = app.session_performance_metric_tiles
    values = {
        "bars": f"{int(meta.get('valid_bars', 0)):,}",
        "samples": f"{total_samples:,}",
        "overlaps": f"{overlap_samples:,}",
        "interval": f"{float(meta.get('bar_interval_minutes', 0)):g} MIN",
        "excluded": f"{excluded:,}",
        "period": period,
    }
    for key, value in values.items():
        tiles[key]["value"].configure(text=value)

    app.session_performance_tree.delete(*app.session_performance_tree.get_children())
    for row in sessions:
        values = (
            row["session"],
            str(row["sample_sessions"]),
            f"{row['bars_used']:,}",
            _format(row["mean_return_pct"]),
            _format(row["median_return_pct"]),
            _plain_pct(row["positive_rate_pct"]),
            _plain_pct(row["mean_range_pct"]),
            _plain_pct(row["mean_realised_volatility_pct"]),
            _plain_pct(row["mean_coverage_pct"]),
        )
        tag = "positive" if (row.get("mean_return_pct") or 0) > 0 else "negative" if (row.get("mean_return_pct") or 0) < 0 else "neutral"
        app.session_performance_tree.insert("", "end", values=values, tags=(tag,))

    app.session_performance_overlap_tree.delete(*app.session_performance_overlap_tree.get_children())
    for row in overlaps:
        values = (
            row["pair"], str(row["sample_days"]), f"{row['bars_used']:,}",
            _format(row["mean_return_pct"]), _plain_pct(row["positive_rate_pct"]),
            _plain_pct(row["mean_range_pct"]), _plain_pct(row["mean_realised_volatility_pct"]),
        )
        tag = "positive" if (row.get("mean_return_pct") or 0) > 0 else "negative" if (row.get("mean_return_pct") or 0) < 0 else "neutral"
        app.session_performance_overlap_tree.insert("", "end", values=values, tags=(tag,))

    app.session_performance_export_button.configure(state="normal")
    app.session_performance_status_label.configure(
        text=(
            f"STUDY COMPLETE · {metadata.get('name', 'DATASET')} · "
            f"{meta.get('valid_bars', 0):,} VALID BARS · {total_samples:,} INCLUDED SESSION DAYS · "
            f"{excluded:,} EXCLUDED DAYS · {metadata.get('session_profile', 'CURRENT PROFILE')}"
        ),
        fg=palette["success"],
    )
    draw_session_performance_chart(app)


def apply_session_performance_theme(app) -> None:
    palette = THEMES[app.theme_name]
    style = ttk.Style(app.root)
    style.configure(
        "Veltrix.Performance.Treeview",
        background=palette["bg"], foreground=palette["text"], fieldbackground=palette["bg"],
        rowheight=25, bordercolor=palette["border"], font=("Consolas", 8),
    )
    style.configure(
        "Veltrix.Performance.Treeview.Heading",
        background=palette["panel"], foreground=palette["bright"], relief="flat",
        font=("Consolas", 8, "bold"),
    )
    style.map(
        "Veltrix.Performance.Treeview",
        background=[("selected", palette["button_active"])],
        foreground=[("selected", palette["bright"])],
    )
    style.configure(
        "Veltrix.Performance.Vertical.TScrollbar",
        background=palette["button_bg"], troughcolor=palette["bg"],
        arrowcolor=palette["bright"], bordercolor=palette["border"],
    )
    style.configure(
        "Veltrix.Performance.TCombobox",
        fieldbackground=palette["entry_bg"], background=palette["button_bg"],
        foreground=palette["entry_fg"], arrowcolor=palette["bright"],
    )
    if hasattr(app, "session_performance_canvas"):
        app.session_performance_canvas.configure(bg=palette["bg"])
    if hasattr(app, "session_performance_chart_canvas"):
        app.session_performance_chart_canvas.configure(bg=palette["panel"])
    if hasattr(app, "session_performance_tree"):
        for tree_name in ("session_performance_tree", "session_performance_overlap_tree"):
            tree = getattr(app, tree_name)
            for tag, colour in (
                ("positive", palette["success"]),
                ("negative", palette["error"]),
                ("neutral", palette["muted"]),
            ):
                tree.tag_configure(tag, foreground=colour)
