"""Tkinter presentation for the Veltrix System Health workspace."""
from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import ttk
from typing import Any

from themes import THEMES
from system_health import SystemHealthSample


def build_system_health_page(app: Any) -> None:
    """Build a read-only dashboard; sampling is controlled by the app page lifecycle."""
    palette = THEMES[app.theme_name]
    shell = app._frame(app.system_health_view)
    shell.pack(fill="both", expand=True)
    app.system_health_canvas = tk.Canvas(
        shell, bg=palette["bg"], highlightthickness=0, bd=0,
    )
    app._register_scrollable_canvas(app.system_health_canvas)
    scrollbar = ttk.Scrollbar(shell, orient="vertical", command=app.system_health_canvas.yview)
    app.system_health_canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    app.system_health_canvas.pack(side="left", fill="both", expand=True)
    app.system_health_content = app._frame(app.system_health_canvas)
    app.system_health_content_window = app.system_health_canvas.create_window(
        (0, 0), window=app.system_health_content, anchor="nw",
    )
    app.system_health_content.bind(
        "<Configure>", lambda _event: app.system_health_canvas.configure(
            scrollregion=app.system_health_canvas.bbox("all")
        )
    )
    app.system_health_canvas.bind(
        "<Configure>", lambda event: app.system_health_canvas.itemconfigure(
            app.system_health_content_window, width=event.width
        )
    )

    content = app.system_health_content
    header = app._frame(content, bg="panel", padx=15, pady=12)
    header.pack(fill="x", pady=(0, 10))
    title_row = app._frame(header, bg="panel")
    title_row.pack(fill="x")
    app._label(
        title_row, "SYSTEM HEALTH MONITOR", bg="panel", fg="bright",
        font=("Segoe UI", 14, "bold"),
    ).pack(side="left")
    app.health_status_label = app._label(
        title_row, "STANDBY · OPEN THIS PAGE TO SAMPLE",
        bg="panel", fg="muted", font=("Segoe UI", 9, "bold"),
    )
    app.health_status_label.pack(side="right")
    app._label(
        header,
        "LOCAL DIAGNOSTICS ONLY · NO NETWORK REQUESTS · SAMPLING PAUSES WHEN THIS WORKSPACE IS HIDDEN",
        bg="panel", fg="muted", font=("Segoe UI", 9),
    ).pack(anchor="w", pady=(5, 0))
    app.health_uptime_label = app._label(
        header, "Application uptime: --", bg="panel", fg="muted",
        font=("Segoe UI", 9),
    )
    app.health_uptime_label.pack(anchor="w", pady=(3, 0))

    metric_panel = app._frame(content, bg="bg")
    metric_panel.pack(fill="x", pady=(0, 9))
    for column in range(4):
        metric_panel.grid_columnconfigure(column, weight=1, uniform="health_metrics")
    metric_specs = (
        ("process_cpu", "VELTRIX CPU", "0.0%", "Application process · total machine capacity"),
        ("system_cpu", "SYSTEM CPU", "N/A", "Whole-machine utilisation"),
        ("process_ram", "VELTRIX RAM", "N/A", "Current resident working set"),
        ("system_ram", "SYSTEM RAM", "N/A", "Physical memory in use"),
    )
    app.health_metric_labels = {}
    app.health_metric_detail_labels = {}
    for column, (key, heading, initial, detail) in enumerate(metric_specs):
        card = app._frame(metric_panel, bg="panel", padx=12, pady=10)
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 4, 0 if column == 3 else 4))
        app._label(card, heading, bg="panel", fg="muted", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        value = app._label(card, initial, bg="panel", fg="bright", font=("Segoe UI", 22, "bold"))
        value.pack(anchor="w", pady=(5, 2))
        detail_label = app._label(
            card, detail, bg="panel", fg="muted", font=("Segoe UI", 8),
            wraplength=220, justify="left",
        )
        detail_label.pack(anchor="w")
        app.health_metric_labels[key] = value
        app.health_metric_detail_labels[key] = detail_label

    runtime_panel = app._frame(content, bg="panel", padx=12, pady=10)
    runtime_panel.pack(fill="x", pady=(0, 9))
    app._label(
        runtime_panel, "APPLICATION RESPONSIVENESS", bg="panel", fg="bright",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", pady=(0, 7))
    runtime_grid = app._frame(runtime_panel, bg="panel")
    runtime_grid.pack(fill="x")
    for column in range(4):
        runtime_grid.grid_columnconfigure(column, weight=1, uniform="health_runtime")
    runtime_specs = (
        ("event_loop", "UI EVENT LOOP", "WARMING UP"),
        ("threads", "PYTHON THREADS", "0"),
        ("active_workers", "ACTIVE WORKERS", "0"),
        ("queued_results", "PENDING RESULTS", "0"),
    )
    app.health_runtime_labels = {}
    app.health_runtime_detail_labels = {}
    for column, (key, heading, initial) in enumerate(runtime_specs):
        cell = app._frame(runtime_grid, bg="panel")
        cell.grid(row=0, column=column, sticky="nsew", padx=(0, 10))
        app._label(cell, heading, bg="panel", fg="muted", font=("Segoe UI", 8, "bold")).pack(anchor="w")
        value = app._label(cell, initial, bg="panel", fg="bright", font=("Segoe UI", 15, "bold"))
        value.pack(anchor="w", pady=(3, 1))
        detail = app._label(cell, "", bg="panel", fg="muted", font=("Segoe UI", 8))
        detail.pack(anchor="w")
        app.health_runtime_labels[key] = value
        app.health_runtime_detail_labels[key] = detail

    history_panel = app._frame(content, bg="panel", padx=12, pady=10)
    history_panel.pack(fill="x", pady=(0, 9))
    app._label(
        history_panel, "RECENT PERFORMANCE · LAST 60 SAMPLES",
        bg="panel", fg="bright", font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", pady=(0, 5))
    app.system_health_history_canvas = tk.Canvas(
        history_panel, height=175, bg=palette["panel"], highlightthickness=0, bd=0,
    )
    app.system_health_history_canvas.pack(fill="x", expand=True)

    worker_panel = app._frame(content, bg="panel", padx=12, pady=10)
    worker_panel.pack(fill="x", pady=(0, 9))
    app._label(
        worker_panel, "BACKGROUND WORKERS", bg="panel", fg="bright",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", pady=(0, 6))
    worker_header = app._frame(worker_panel, bg="panel")
    worker_header.pack(fill="x", pady=(0, 4))
    worker_header.grid_columnconfigure(0, weight=2)
    worker_header.grid_columnconfigure(1, weight=1)
    worker_header.grid_columnconfigure(2, weight=4)
    for column, text in enumerate(("TASK", "STATUS", "DETAIL")):
        app._label(
            worker_header, text, bg="panel", fg="muted", font=("Segoe UI", 8, "bold"),
        ).grid(row=0, column=column, sticky="w", padx=(0, 8))
    app.health_worker_rows = {}
    worker_names = (
        "Market data fetch", "Economic calendar fetch", "OHLC library load",
        "OHLC CSV import", "Regime classification", "Session performance study",
        "Local dataset cache writer",
    )
    for index, name in enumerate(worker_names):
        row = app._frame(worker_panel, bg="panel")
        row.pack(fill="x", pady=2)
        row.grid_columnconfigure(0, weight=2)
        row.grid_columnconfigure(1, weight=1)
        row.grid_columnconfigure(2, weight=4)
        if index % 2:
            for child in (row,):
                child.configure(bg=palette["dim"])
        label = app._label(row, name, bg="panel" if index % 2 == 0 else "dim", fg="text", font=("Segoe UI", 9))
        label.grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        status = app._label(row, "IDLE", bg="panel" if index % 2 == 0 else "dim", fg="muted",
                            font=("Segoe UI", 8, "bold"))
        status.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=4)
        detail = app._label(row, "Waiting for a request", bg="panel" if index % 2 == 0 else "dim",
                            fg="muted", font=("Segoe UI", 8))
        detail.grid(row=0, column=2, sticky="w", pady=4)
        app.health_worker_rows[name] = (status, detail)

    errors_panel = app._frame(content, bg="panel", padx=12, pady=10)
    errors_panel.pack(fill="x", pady=(0, 9))
    app._label(
        errors_panel, "RECENT MONITORED ERRORS", bg="panel", fg="bright",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", pady=(0, 5))
    app.health_error_rows = []
    app.health_error_empty_label = app._label(
        errors_panel, "No monitored worker errors recorded during this run.",
        bg="panel", fg="muted", font=("Segoe UI", 9),
    )
    app.health_error_empty_label.pack(anchor="w")
    for _ in range(6):
        label = app._label(
            errors_panel, "", bg="panel", fg="error", font=("Segoe UI", 8),
            wraplength=1050, justify="left",
        )
        label.pack(anchor="w", pady=1)
        app.health_error_rows.append(label)

    app._label(
        content,
        "CPU percentages are normalised against total logical machine capacity. "
        "Platform APIs may report N/A where current process or system metrics are unavailable. "
        "Event-loop delay is a diagnostic sample, not a guaranteed UI latency bound.",
        bg="bg", fg="muted", font=("Segoe UI", 8), wraplength=1100, justify="left",
    ).pack(anchor="w", pady=(0, 8))


def _format_percent(value: float | None) -> str:
    return f"{value:.1f}%" if value is not None else "N/A"


def _format_megabytes(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.0f} MB" if value >= 100 else f"{value:,.1f} MB"


def draw_system_health_history(app: Any) -> None:
    canvas = getattr(app, "system_health_history_canvas", None)
    if canvas is None:
        return
    palette = THEMES[app.theme_name]
    try:
        width = max(1, int(canvas.winfo_width()))
        height = max(1, int(canvas.winfo_height()))
    except (tk.TclError, TypeError, ValueError):
        return
    canvas.delete("all")
    left, right = 44, max(45, width - 12)
    top, middle, bottom = 24, max(65, height // 2), max(66, height - 22)
    for fraction in (0.0, 0.5, 1.0):
        y = top + int((middle - top) * fraction)
        canvas.create_line(left, y, right, y, fill=palette["border"], dash=(2, 3))
        canvas.create_text(5, y, anchor="w", text=f"{int(100 - fraction * 100)}%", fill=palette["muted"],
                           font=("Segoe UI", 7))
        y2 = middle + int((bottom - middle) * fraction)
        canvas.create_line(left, y2, right, y2, fill=palette["border"], dash=(2, 3))
    canvas.create_text(left, 8, anchor="w", text="CPU", fill=palette["bright"], font=("Segoe UI", 8, "bold"))
    canvas.create_text(right, 8, anchor="e", text="RAM · MB", fill=palette["success"], font=("Segoe UI", 8, "bold"))

    samples = list(getattr(app, "system_health_history", ()))
    if not samples:
        canvas.create_text(width / 2, height / 2, text="Waiting for the first resource sample...",
                           fill=palette["muted"], font=("Segoe UI", 9))
        return
    plot_width = max(1, right - left)
    if len(samples) == 1:
        x_values = [right]
    else:
        x_values = [left + plot_width * index / (len(samples) - 1) for index in range(len(samples))]
    cpu_points: list[float] = []
    ram_values = [sample.process_rss_mb for sample in samples if sample.process_rss_mb is not None]
    ram_scale = max(256.0, max(ram_values, default=0.0) * 1.15)
    ram_points: list[float] = []
    for x, sample in zip(x_values, samples):
        cpu = min(100.0, max(0.0, sample.process_cpu_percent))
        cpu_points.extend((x, top + (1.0 - cpu / 100.0) * (middle - top)))
        ram = sample.process_rss_mb
        if ram is not None:
            ram_points.extend((x, bottom - (min(ram_scale, max(0.0, ram)) / ram_scale) * (bottom - middle)))
    if len(cpu_points) >= 4:
        canvas.create_line(*cpu_points, fill=palette["bright"], width=2, smooth=True)
    if len(ram_points) >= 4:
        canvas.create_line(*ram_points, fill=palette["success"], width=2, smooth=True)


def refresh_system_health_page(
    app: Any,
    sample: SystemHealthSample,
    worker_snapshot: dict[str, Any],
    event_loop_delay_ms: float,
    latency_history: list[float],
    recent_errors: tuple[dict[str, str], ...],
) -> None:
    palette = THEMES[app.theme_name]
    values = {
        "process_cpu": _format_percent(sample.process_cpu_percent),
        "system_cpu": _format_percent(sample.system_cpu_percent),
        "process_ram": _format_megabytes(sample.process_rss_mb),
        "system_ram": _format_percent(sample.system_memory_percent),
    }
    for key, value in values.items():
        app.health_metric_labels[key].configure(text=value)
    app.health_metric_detail_labels["process_cpu"].configure(
        text=f"{max(1, os.cpu_count() or 1)} logical processor(s) · process share"
    )
    app.health_metric_detail_labels["process_ram"].configure(text="Resident working set · current sample")
    app.health_metric_detail_labels["system_ram"].configure(text="Physical memory in use · current sample")

    average_delay = sum(latency_history) / len(latency_history) if latency_history else event_loop_delay_ms
    peak_delay = max(latency_history, default=event_loop_delay_ms)
    runtime_values = {
        "event_loop": f"{event_loop_delay_ms:.1f} ms",
        "threads": str(sample.thread_count),
        "active_workers": str(worker_snapshot["active_workers"]),
        "queued_results": str(worker_snapshot["queued_results"]),
    }
    for key, value in runtime_values.items():
        app.health_runtime_labels[key].configure(text=value)
    app.health_runtime_detail_labels["event_loop"].configure(
        text=f"60-sample avg {average_delay:.1f} ms · peak {peak_delay:.1f} ms"
    )
    app.health_runtime_detail_labels["threads"].configure(
        text=f"{worker_snapshot['background_threads']} Veltrix worker thread(s)"
    )
    app.health_runtime_detail_labels["active_workers"].configure(text="Current background tasks")
    app.health_runtime_detail_labels["queued_results"].configure(text="Waiting for UI transfer")

    for name, (status_label, detail_label) in app.health_worker_rows.items():
        worker = next((item for item in worker_snapshot["workers"] if item["label"] == name), None)
        if worker is None:
            continue
        status = worker["status"]
        colour = palette["success"] if status in {"RUNNING", "WRITING"} else palette["muted"]
        if status == "STOPPED":
            colour = palette["warning"]
        status_label.configure(text=status, fg=colour)
        detail_label.configure(text=worker["detail"])

    app.health_status_label.configure(
        text="LIVE SAMPLING · 1 SECOND · PAUSES WHEN HIDDEN",
        fg=palette["success"],
    )
    elapsed = max(0, int(time.monotonic() - app.system_health_monitor.started_monotonic))
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    app.health_uptime_label.configure(
        text=f"Application uptime: {hours:02d}:{minutes:02d}:{seconds:02d} · Last sample: "
             f"{sample.sampled_at.astimezone().strftime('%H:%M:%S %Z')}"
    )

    visible_errors = list(recent_errors)[-6:]
    app.health_error_empty_label.pack_forget()
    if not visible_errors:
        app.health_error_empty_label.configure(text="No monitored worker errors recorded during this run.")
        app.health_error_empty_label.pack(anchor="w")
    for index, label in enumerate(app.health_error_rows):
        if index < len(visible_errors):
            event = visible_errors[-1 - index]
            label.configure(text=f"{event['time']} · {event['source']} · {event['detail']}")
            label.pack(anchor="w", pady=1)
        else:
            label.configure(text="")
            label.pack_forget()
    draw_system_health_history(app)
