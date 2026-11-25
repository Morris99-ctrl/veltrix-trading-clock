"""Tkinter presentation for Veltrix local backup and recovery."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from backup_recovery import DEFAULT_RETENTION, list_backups, read_pending_restore
from themes import THEMES


def set_backup_status(app: Any, message: str, kind: str = "muted") -> None:
    label = getattr(app, "backup_status_label", None)
    if label is None:
        return
    palette = THEMES[app.theme_name]
    colour = {
        "success": palette["success"],
        "warning": palette["warning"],
        "error": palette["error"],
    }.get(kind, palette["muted"])
    label.configure(text=message, fg=colour)


def _format_bytes(value: int) -> str:
    size = max(0, int(value))
    if size >= 1024 ** 3:
        return f"{size / (1024 ** 3):.2f} GB"
    if size >= 1024 ** 2:
        return f"{size / (1024 ** 2):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


def refresh_backup_recovery_page(app: Any) -> None:
    tree = getattr(app, "backup_history_tree", None)
    if tree is None:
        return
    tree.delete(*tree.get_children())
    app.backup_records = {}
    records = list_backups(app.app_data_dir)
    for record in records:
        name = record["name"]
        app.backup_records[name] = record
        created = record.get("created_at", "") or "Unreadable archive"
        status = "INVALID" if record.get("error") else "AVAILABLE · VERIFY TO RESTORE"
        tree.insert(
            "",
            "end",
            iid=name,
            values=(
                created.replace("T", " ").replace("+00:00", " UTC"),
                _format_bytes(record.get("archive_size_bytes", 0)),
                str(record.get("file_count", 0)),
                status,
            ),
        )
    app.backup_count_label.configure(
        text=f"{len(records)} ARCHIVE(S) · RETENTION {DEFAULT_RETENTION} · LOCAL DEVICE ONLY"
    )
    if records:
        newest = records[0]
        app.backup_latest_label.configure(
            text=f"LATEST SNAPSHOT · {newest.get('created_at') or 'INVALID ARCHIVE'}"
        )
    else:
        app.backup_latest_label.configure(text="LATEST SNAPSHOT · NONE CREATED YET")

    pending = read_pending_restore(app.app_data_dir)
    app.backup_pending_restore = pending
    if pending and pending.get("backup_name"):
        app.backup_pending_label.configure(
            text=f"RESTORE QUEUED · {pending['backup_name']} · APPLIES BEFORE THE NEXT START",
            fg=THEMES[app.theme_name]["warning"],
        )
        app.backup_cancel_restore_button.configure(state="normal")
    elif pending and pending.get("error"):
        app.backup_pending_label.configure(
            text=f"RESTORE REQUEST ERROR · {pending['error']}",
            fg=THEMES[app.theme_name]["error"],
        )
        app.backup_cancel_restore_button.configure(state="normal")
    else:
        app.backup_pending_label.configure(
            text="NO RESTORE QUEUED · CURRENT DATA REMAINS ACTIVE",
            fg=THEMES[app.theme_name]["muted"],
        )
        app.backup_cancel_restore_button.configure(state="disabled")

    app.backup_verified_selection = None
    app.backup_verify_button.configure(state="disabled")
    app.backup_restore_button.configure(state="disabled")
    app.backup_preview_label.configure(
        text="Select a snapshot and choose VERIFY & PREVIEW. Veltrix checks the archive and every file checksum before enabling recovery."
    )


def build_backup_recovery_page(app: Any) -> None:
    """Create the local-only backup, verification and next-launch restore workspace."""
    palette = THEMES[app.theme_name]
    shell = app._frame(app.backup_recovery_view)
    shell.pack(fill="both", expand=True)
    app.backup_canvas = tk.Canvas(shell, bg=palette["bg"], highlightthickness=0, bd=0)
    app._register_scrollable_canvas(app.backup_canvas)
    scrollbar = ttk.Scrollbar(shell, orient="vertical", command=app.backup_canvas.yview)
    app.backup_canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    app.backup_canvas.pack(side="left", fill="both", expand=True)
    app.backup_content = app._frame(app.backup_canvas)
    app.backup_content_window = app.backup_canvas.create_window(
        (0, 0), window=app.backup_content, anchor="nw",
    )
    app.backup_content.bind(
        "<Configure>", lambda _event: app.backup_canvas.configure(
            scrollregion=app.backup_canvas.bbox("all")
        )
    )
    app.backup_canvas.bind(
        "<Configure>", lambda event: app.backup_canvas.itemconfigure(
            app.backup_content_window, width=event.width
        )
    )

    content = app.backup_content
    hero = app._frame(content, bg="panel", padx=15, pady=12)
    hero.pack(fill="x", pady=(0, 9))
    title_row = app._frame(hero, bg="panel")
    title_row.pack(fill="x")
    app._label(
        title_row, "BACKUP & RECOVERY", bg="panel", fg="bright",
        font=("Segoe UI", 14, "bold"),
    ).pack(side="left")
    app.backup_status_label = app._label(
        title_row, "AUTOMATIC BACKUPS ENABLE AFTER STARTUP",
        bg="panel", fg="muted", font=("Segoe UI", 9, "bold"),
    )
    app.backup_status_label.pack(side="right")
    app._label(
        hero,
        "LOCAL SNAPSHOTS · SHA-256 VERIFIED · SQLITE ONLINE BACKUP · NO CLOUD UPLOAD",
        bg="panel", fg="muted", font=("Segoe UI", 9, "bold"),
    ).pack(anchor="w", pady=(5, 2))
    app.backup_latest_label = app._label(
        hero, "LATEST SNAPSHOT · CHECKING", bg="panel", fg="text",
        font=("Segoe UI", 9, "bold"),
    )
    app.backup_latest_label.pack(anchor="w", pady=(4, 0))
    app.backup_count_label = app._label(
        hero, f"RETENTION {DEFAULT_RETENTION} · LOCAL DEVICE ONLY",
        bg="panel", fg="muted", font=("Segoe UI", 8),
    )
    app.backup_count_label.pack(anchor="w", pady=(2, 0))

    data_panel = app._frame(content, bg="panel", padx=12, pady=10)
    data_panel.pack(fill="x", pady=(0, 9))
    app._label(
        data_panel, "WHAT VELTRIX PROTECTS", bg="panel", fg="bright",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", pady=(0, 6))
    app._label(
        data_panel,
        "Configuration and alert history · Alarm state and custom alarm sound · "
        "Focus goals, milestones and timer history · Imported OHLC datasets · "
        "Legacy research cache when present · Market snapshot and economic-calendar cache",
        bg="panel", fg="text", font=("Segoe UI", 9), wraplength=1050, justify="left",
    ).pack(fill="x")
    app._label(
        data_panel,
        "Backups are stored in the local Veltrix application-data folder. API keys, credentials, "
        "temporary files and application binaries are deliberately excluded.",
        bg="panel", fg="muted", font=("Segoe UI", 8), wraplength=1050, justify="left",
    ).pack(fill="x", pady=(5, 0))

    controls = app._frame(content, bg="panel", padx=12, pady=10)
    controls.pack(fill="x", pady=(0, 9))
    app.backup_now_button = tk.Button(
        controls, text="CREATE BACKUP NOW", command=app.create_manual_backup,
        font=("Segoe UI", 9, "bold"), relief="flat", bd=0, padx=13, pady=8, cursor="hand2",
    )
    app.backup_now_button.pack(side="left", padx=(0, 7))
    app.backup_verify_button = tk.Button(
        controls, text="VERIFY & PREVIEW", command=app.verify_selected_backup,
        state="disabled", font=("Segoe UI", 9, "bold"), relief="flat", bd=0,
        padx=13, pady=8, cursor="hand2",
    )
    app.backup_verify_button.pack(side="left", padx=(0, 7))
    app.backup_restore_button = tk.Button(
        controls, text="SCHEDULE RESTORE", command=app.schedule_selected_restore,
        state="disabled", font=("Segoe UI", 9, "bold"), relief="flat", bd=0,
        padx=13, pady=8, cursor="hand2",
    )
    app.backup_restore_button.pack(side="left", padx=(0, 7))
    app.backup_refresh_button = tk.Button(
        controls, text="REFRESH LIST", command=lambda: refresh_backup_recovery_page(app),
        font=("Segoe UI", 9, "bold"), relief="flat", bd=0, padx=13, pady=8, cursor="hand2",
    )
    app.backup_refresh_button.pack(side="left")
    app.backup_cancel_restore_button = tk.Button(
        controls, text="CANCEL QUEUED RESTORE", command=app.cancel_scheduled_restore,
        state="disabled", font=("Segoe UI", 9, "bold"), relief="flat", bd=0,
        padx=12, pady=8, cursor="hand2",
    )
    app.backup_cancel_restore_button.pack(side="right")
    app.backup_pending_label = app._label(
        controls, "NO RESTORE QUEUED", bg="panel", fg="muted",
        font=("Segoe UI", 8, "bold"), wraplength=380, justify="right",
    )
    app.backup_pending_label.pack(side="right", padx=(0, 12))

    history = app._frame(content, bg="panel", padx=12, pady=10)
    history.pack(fill="both", expand=True, pady=(0, 9))
    app._label(
        history, "LOCAL BACKUP ARCHIVE", bg="panel", fg="bright",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", pady=(0, 6))
    tree_frame = app._frame(history, bg="panel")
    tree_frame.pack(fill="both", expand=True)
    columns = ("created", "size", "files", "status")
    app.backup_history_tree = ttk.Treeview(
        tree_frame, columns=columns, show="headings", height=8,
        selectmode="browse", style="Veltrix.Market.Treeview",
    )
    headings = (
        ("created", "CREATED (UTC)", 255),
        ("size", "ARCHIVE SIZE", 100),
        ("files", "FILES", 60),
        ("status", "STATUS", 250),
    )
    for key, heading, width in headings:
        app.backup_history_tree.heading(key, text=heading)
        app.backup_history_tree.column(key, width=width, minwidth=55, anchor="w", stretch=(key in {"created", "status"}))
    tree_scroll = ttk.Scrollbar(
        tree_frame, orient="vertical", command=app.backup_history_tree.yview,
    )
    app.backup_history_tree.configure(yscrollcommand=tree_scroll.set)
    app.backup_history_tree.pack(side="left", fill="both", expand=True)
    tree_scroll.pack(side="right", fill="y")
    app.backup_history_tree.bind("<<TreeviewSelect>>", app._on_backup_selection)

    preview = app._frame(content, bg="panel", padx=12, pady=10)
    preview.pack(fill="x", pady=(0, 9))
    app._label(
        preview, "VERIFICATION & RESTORE PREVIEW", bg="panel", fg="bright",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", pady=(0, 5))
    app.backup_preview_label = app._label(
        preview,
        "Select a snapshot and choose VERIFY & PREVIEW. Veltrix checks the archive and every file checksum before enabling recovery.",
        bg="panel", fg="muted", font=("Segoe UI", 9), wraplength=1080, justify="left",
    )
    app.backup_preview_label.pack(fill="x")
    app._label(
        content,
        "RESTORE SAFETY: a full backup of the current data is created before recovery. "
        "The selected snapshot is restored before Veltrix opens on the next launch, not while the database is in use.",
        bg="bg", fg="muted", font=("Segoe UI", 8), wraplength=1080, justify="left",
    ).pack(anchor="w", pady=(0, 8))

    app.backup_records = {}
    app.backup_verified_selection = None
    app.backup_pending_restore = None
    refresh_backup_recovery_page(app)
