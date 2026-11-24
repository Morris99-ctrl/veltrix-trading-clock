"""Tkinter presentation for the Veltrix Market Intelligence workspace."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import tkinter as tk
from tkinter import ttk

from market_intelligence_engine import build_market_intelligence_snapshot
from themes import THEMES


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if not (number == number and abs(number) != float("inf")):
        return "N/A"
    return f"{number:.{digits}f}{suffix}"


def _state_colour(state: str, palette: dict[str, str]) -> str:
    value = str(state).upper()
    if value in {"TREND_UP", "AVAILABLE", "UPDATED", "QUIET", "CONTRACTING"}:
        return palette["success"]
    if value in {"TREND_DOWN", "VOLATILITY_SHOCK", "EXPANDING", "ELEVATED", "PARTIAL"}:
        return palette["warning"]
    if value in {"CACHED", "WARMUP", "TRANSITION", "BALANCED"}:
        return palette["bright"]
    return palette["muted"]


def build_market_intelligence_page(app: Any) -> None:
    """Build the scrollable Market Intelligence workspace."""
    shell = app._frame(app.market_intelligence_view)
    shell.pack(fill="both", expand=True)
    app.market_intelligence_canvas = tk.Canvas(shell, highlightthickness=0, bd=0)
    scrollbar = ttk.Scrollbar(shell, orient="vertical", command=app.market_intelligence_canvas.yview)
    app.market_intelligence_canvas.configure(yscrollcommand=scrollbar.set)
    app.market_intelligence_canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    app.market_intelligence_content = app._frame(app.market_intelligence_canvas)
    app.market_intelligence_content_window = app.market_intelligence_canvas.create_window(
        (0, 0), window=app.market_intelligence_content, anchor="nw",
    )
    app.market_intelligence_content.bind(
        "<Configure>",
        lambda _event: app.market_intelligence_canvas.configure(
            scrollregion=app.market_intelligence_canvas.bbox("all")
        ),
    )
    app.market_intelligence_canvas.bind(
        "<Configure>",
        lambda event: app.market_intelligence_canvas.itemconfigure(
            app.market_intelligence_content_window, width=event.width
        ),
    )
    app.market_intelligence_canvas.bind(
        "<MouseWheel>",
        lambda event: app.market_intelligence_canvas.yview_scroll(int(-event.delta / 120), "units"),
    )
    app.market_intelligence_canvas.bind(
        "<Button-4>", lambda _event: app.market_intelligence_canvas.yview_scroll(-1, "units"),
    )
    app.market_intelligence_canvas.bind(
        "<Button-5>", lambda _event: app.market_intelligence_canvas.yview_scroll(1, "units"),
    )

    header = app._frame(app.market_intelligence_content, bg="panel", padx=15, pady=13)
    header.pack(fill="x", pady=(0, 9))
    app._label(
        header, "MARKET INTELLIGENCE ENGINE", bg="panel", fg="bright",
        font=("Segoe UI", 12, "bold"),
    ).pack(anchor="w")
    app._label(
        header,
        "CAUSAL REGIMES  /  VOLATILITY PROFILE  /  CROSS-ASSET CORRELATION",
        bg="panel", fg="muted", font=("Segoe UI", 9, "bold"),
    ).pack(anchor="w", pady=(3, 8))
    action_row = app._frame(header, bg="panel")
    action_row.pack(fill="x")
    app.market_intelligence_status_label = app._label(
        action_row, "WAITING FOR MARKET DATA", bg="panel", fg="warning",
        font=("Segoe UI", 9, "bold"), anchor="w", justify="left", wraplength=800,
    )
    app.market_intelligence_status_label.pack(side="left", fill="x", expand=True)
    app.market_intelligence_refresh_button = tk.Button(
        action_row, text="REFRESH MARKET DATA",
        command=lambda: app.refresh_market_data(silent=False),
        font=("Segoe UI", 9, "bold"), relief="flat", bd=0,
        padx=12, pady=8, cursor="hand2",
    )
    app.market_intelligence_refresh_button.pack(side="right", padx=(10, 0))

    source_panel = app._frame(app.market_intelligence_content, bg="panel", padx=13, pady=9)
    source_panel.pack(fill="x", pady=(0, 9))
    app.market_intelligence_source_label = app._label(
        source_panel, "SOURCE · EXISTING MARKET DATA FEED", bg="panel", fg="muted",
        font=("Segoe UI", 9, "bold"),
    )
    app.market_intelligence_source_label.pack(anchor="w")
    app.market_intelligence_generated_label = app._label(
        source_panel, "GENERATED · N/A", bg="panel", fg="muted",
        font=("Segoe UI", 9),
    )
    app.market_intelligence_generated_label.pack(anchor="w", pady=(3, 0))

    app.market_intelligence_asset_cards: dict[str, dict[str, tk.Label]] = {}
    instruments = list(getattr(app, "market_instruments", []))
    asset_panel = app._frame(app.market_intelligence_content, bg="panel", padx=13, pady=11)
    asset_panel.pack(fill="x", pady=(0, 9))
    app._label(
        asset_panel, "INSTRUMENT REGIME & VOLATILITY", bg="panel", fg="bright",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", pady=(0, 8))
    asset_grid = app._frame(asset_panel, bg="panel")
    asset_grid.pack(fill="x")
    for column in range(max(1, min(3, len(instruments)))):
        asset_grid.grid_columnconfigure(column, weight=1, uniform="mi_asset")
    for index, instrument in enumerate(instruments):
        key = str(instrument.get("key") or f"asset_{index}")
        row, column = divmod(index, 3)
        card = app._frame(asset_grid, bg="dim", padx=11, pady=10)
        card.grid(row=row, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 6 if column < 2 else 0),
                  pady=(0, 7))
        name = app._label(card, str(instrument.get("name") or key), bg="dim", fg="text",
                          font=("Segoe UI", 9, "bold"))
        name.pack(anchor="w")
        regime = app._label(card, "REGIME · N/A", bg="dim", fg="muted",
                            font=("Segoe UI", 12, "bold"))
        regime.pack(anchor="w", pady=(7, 2))
        volatility = app._label(card, "VOLATILITY · N/A", bg="dim", fg="muted",
                                font=("Segoe UI", 10, "bold"))
        volatility.pack(anchor="w", pady=(0, 5))
        quote = app._label(card, "PRICE · N/A", bg="dim", fg="text", font=("Segoe UI", 10, "bold"))
        quote.pack(anchor="w")
        metrics = app._label(card, "RV 10D / 20D / 60D · N/A", bg="dim", fg="muted",
                             font=("Segoe UI", 8))
        metrics.pack(anchor="w", pady=(4, 0))
        atr = app._label(card, "ATR(14) · N/A", bg="dim", fg="muted", font=("Segoe UI", 8))
        atr.pack(anchor="w", pady=(2, 0))
        evidence = app._label(card, "EVIDENCE · awaiting completed bars", bg="dim", fg="muted",
                              font=("Segoe UI", 8), justify="left", anchor="w", wraplength=330)
        evidence.pack(fill="x", anchor="w", pady=(7, 4))
        freshness = app._label(card, "DATA · NO DATA", bg="dim", fg="muted",
                               font=("Segoe UI", 8, "bold"))
        freshness.pack(anchor="w")
        app.market_intelligence_asset_cards[key] = {
            "regime": regime, "volatility": volatility, "quote": quote,
            "metrics": metrics, "atr": atr, "evidence": evidence, "freshness": freshness,
        }

    lower = app._frame(app.market_intelligence_content)
    lower.pack(fill="x")
    lower.grid_columnconfigure(0, weight=3)
    lower.grid_columnconfigure(1, weight=2)

    correlation_panel = app._frame(lower, bg="panel", padx=13, pady=11)
    correlation_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
    app._label(
        correlation_panel, "CROSS-ASSET CORRELATION", bg="panel", fg="bright",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w")
    app._label(
        correlation_panel, "PEARSON CORRELATION · ALIGNED DAILY LOG RETURNS",
        bg="panel", fg="muted", font=("Segoe UI", 8, "bold"),
    ).pack(anchor="w", pady=(2, 9))
    headings = app._frame(correlation_panel, bg="panel")
    headings.pack(fill="x")
    for text, width in (("PAIR", 1), ("20D", 0), ("60D", 0), ("SAMPLES", 0)):
        app._label(headings, text, bg="panel", fg="muted", font=("Segoe UI", 8, "bold"),
                   width=width, anchor="w").pack(side="left", expand=(width == 1), fill="x",
                                                 padx=(0, 7))
    app.market_intelligence_correlation_rows: list[dict[str, tk.Label]] = []
    for _index in range(max(1, len(instruments) * (len(instruments) - 1) // 2)):
        line = app._frame(correlation_panel, bg="panel")
        line.pack(fill="x", pady=(6, 0))
        pair = app._label(line, "PAIR · N/A", bg="panel", fg="text",
                          font=("Segoe UI", 9, "bold"), anchor="w")
        pair.pack(side="left", expand=True, fill="x", padx=(0, 7))
        c20 = app._label(line, "N/A", bg="panel", fg="muted", font=("Segoe UI", 9, "bold"), width=8)
        c20.pack(side="left", padx=(0, 7))
        c60 = app._label(line, "N/A", bg="panel", fg="muted", font=("Segoe UI", 9, "bold"), width=8)
        c60.pack(side="left", padx=(0, 7))
        samples = app._label(line, "0 / 0", bg="panel", fg="muted", font=("Segoe UI", 8), width=11)
        samples.pack(side="left")
        app.market_intelligence_correlation_rows.append(
            {"pair": pair, "20d": c20, "60d": c60, "samples": samples}
        )

    breadth_panel = app._frame(lower, bg="panel", padx=13, pady=11)
    breadth_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
    app._label(
        breadth_panel, "MARKET BREADTH", bg="panel", fg="bright",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w")
    app.market_intelligence_breadth_state = app._label(
        breadth_panel, "UNAVAILABLE", bg="panel", fg="warning",
        font=("Segoe UI", 12, "bold"),
    )
    app.market_intelligence_breadth_state.pack(anchor="w", pady=(8, 4))
    app.market_intelligence_breadth_detail = app._label(
        breadth_panel, "No constituent-level breadth universe is configured.",
        bg="panel", fg="muted", font=("Segoe UI", 9), wraplength=330,
        justify="left", anchor="w",
    )
    app.market_intelligence_breadth_detail.pack(fill="x")

    method_panel = app._frame(app.market_intelligence_content, bg="panel", padx=13, pady=11)
    method_panel.pack(fill="x", pady=(9, 0))
    app._label(
        method_panel, "EVIDENCE & DATA BOUNDARIES", bg="panel", fg="bright",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w")
    app._label(
        method_panel,
        "Regime labels use completed current/past OHLC bars only. Forward returns are historical outcomes "
        "and never feed the current classification. Realised volatility is annualised using sqrt(252); "
        "correlations use aligned daily log returns. Missing history remains N/A. Market breadth requires "
        "a real constituent universe and is not inferred from index/futures proxies. Existing Yahoo chart "
        "data is unofficial and indicative, not execution-grade. No buy/sell signals or order execution.",
        bg="panel", fg="muted", font=("Segoe UI", 9), wraplength=1050,
        justify="left", anchor="w",
    ).pack(fill="x", pady=(6, 0))

    refresh_market_intelligence_page(app)


def _display_time(value: Any, zone: Any) -> str:
    if not value:
        return "N/A"
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return "N/A"
        return stamp.astimezone(zone).strftime("%d %b %Y · %H:%M %Z")
    except (TypeError, ValueError):
        return "N/A"


def refresh_market_intelligence_page(app: Any) -> None:
    """Recalculate presentation from the existing cached/current market snapshot."""
    if not hasattr(app, "market_intelligence_asset_cards"):
        return
    try:
        snapshot = build_market_intelligence_snapshot(
            getattr(app, "market_snapshot", {}),
            getattr(app, "market_instruments", []),
            market_is_fresh=bool(getattr(app, "market_is_fresh", False)),
            regime_config=getattr(app, "regime_settings", {}),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        app.market_intelligence_status_label.configure(
            text=f"INTELLIGENCE UPDATE FAILED · {str(exc)[:180]}",
            fg=THEMES[app.theme_name]["error"],
        )
        return

    palette = THEMES[app.theme_name]
    asset_results = snapshot["assets"]
    for key, widgets in app.market_intelligence_asset_cards.items():
        item = asset_results.get(key, {})
        regime = item.get("regime", {})
        volatility = item.get("volatility", {})
        label = str(regime.get("label") or "N/A")
        vol_state = str(volatility.get("state") or "N/A")
        widgets["regime"].configure(text=f"REGIME · {label}", fg=_state_colour(label, palette))
        widgets["volatility"].configure(
            text=f"VOLATILITY · {vol_state}", fg=_state_colour(vol_state, palette)
        )
        quote = item.get("quote")
        unit = item.get("unit", "")
        widgets["quote"].configure(
            text=(f"PRICE · {float(quote):,.2f} {unit}".rstrip() if quote is not None
                  else "PRICE · N/A")
        )
        widgets["metrics"].configure(
            text=(
                f"RV 10D / 20D / 60D · "
                f"{_fmt(volatility.get('realised_vol_10d_ann_pct'), 1, '%')} / "
                f"{_fmt(volatility.get('realised_vol_20d_ann_pct'), 1, '%')} / "
                f"{_fmt(volatility.get('realised_vol_60d_ann_pct'), 1, '%')}"
            )
        )
        widgets["atr"].configure(
            text=f"ATR(14) · {_fmt(volatility.get('atr14'), 3)} {unit}  |  "
                 f"{_fmt(volatility.get('atr14_pct'), 2, '%')} of price"
        )
        evidence = regime.get("evidence", {})
        widgets["evidence"].configure(
            text=(
                f"ER {_fmt(evidence.get('efficiency_ratio'), 2)}  ·  "
                f"SLOPE/ATR {_fmt(evidence.get('normalised_slope_atr'), 2)}  ·  "
                f"FAST/SLOW ATR {_fmt(evidence.get('fast_slow_atr_ratio'), 2)}\n"
                f"TR / PRIOR ATR {_fmt(evidence.get('true_range_vs_prior_atr'), 2)}  ·  "
                f"RV20 PCTL {_fmt(volatility.get('rv20_percentile_lookback'), 0, '%')}"
            )
        )
        freshness = str(item.get("freshness") or "NO DATA")
        widgets["freshness"].configure(
            text=f"DATA · {freshness}  |  DAILY BARS {int(item.get('daily_bars') or 0)}",
            fg=_state_colour(freshness, palette),
        )

    correlations = snapshot.get("correlations", [])
    for index, widgets in enumerate(app.market_intelligence_correlation_rows):
        if index >= len(correlations):
            widgets["pair"].configure(text="PAIR · N/A")
            widgets["20d"].configure(text="N/A")
            widgets["60d"].configure(text="N/A")
            widgets["samples"].configure(text="0 / 0")
            continue
        row = correlations[index]
        widgets["pair"].configure(text=f"{row['left_name']} / {row['right_name']}")
        widgets["20d"].configure(text=_fmt(row.get("correlation_20d"), 2))
        widgets["60d"].configure(text=_fmt(row.get("correlation_60d"), 2))
        widgets["samples"].configure(
            text=f"{row.get('samples_20d', 0)} / {row.get('samples_60d', 0)}"
        )

    breadth = snapshot["breadth"]
    breadth_state = str(breadth.get("state") or "UNAVAILABLE")
    app.market_intelligence_breadth_state.configure(
        text=breadth_state, fg=_state_colour(breadth_state, palette)
    )
    if breadth_state == "AVAILABLE":
        detail = (
            f"{breadth.get('advancers')} ADVANCERS  ·  {breadth.get('decliners')} DECLINERS  ·  "
            f"{breadth.get('unchanged')} UNCHANGED\n"
            f"ADVANCE SHARE {_fmt(breadth.get('advance_share_pct'), 1, '%')}  ·  "
            f"{breadth.get('constituents')} CONSTITUENTS  ·  AS OF {breadth.get('as_of_utc')}"
        )
    else:
        detail = str(breadth.get("reason") or "Constituent-level data is not available.")
    app.market_intelligence_breadth_detail.configure(text=detail)

    feed = snapshot.get("feed_state", "NO DATA")
    fetched = _display_time(snapshot.get("fetched_at"), app.home_zone)
    generated = _display_time(snapshot.get("generated_at_utc"), app.home_zone)
    status_colour = _state_colour(feed, palette)
    message = {
        "UPDATED": "CURRENT-RUN MARKET SNAPSHOT · VALUES ARE INDICATIVE",
        "PARTIAL": "PARTIAL MARKET SNAPSHOT · ONE OR MORE INSTRUMENTS ARE MISSING DATA",
        "CACHED": "CACHED OBSERVATIONS · LIVE MARKET FETCH NOT VERIFIED THIS RUN",
        "NO DATA": "NO MARKET OBSERVATIONS AVAILABLE · REFRESH THE EXISTING MARKET FEED",
    }.get(feed, "MARKET DATA STATUS UNAVAILABLE")
    app.market_intelligence_status_label.configure(text=message, fg=status_colour)
    app.market_intelligence_source_label.configure(
        text=f"SOURCE · {snapshot.get('provider', 'N/A')}  |  FEED · {feed}",
        fg=status_colour,
    )
    app.market_intelligence_generated_label.configure(
        text=f"LAST FETCH · {fetched}  |  SNAPSHOT GENERATED · {generated}"
    )


def apply_market_intelligence_theme(app: Any) -> None:
    """Apply the active Veltrix palette to the Market Intelligence workspace."""
    palette = THEMES[app.theme_name]
    if hasattr(app, "market_intelligence_canvas"):
        app.market_intelligence_canvas.configure(bg=palette["bg"])
    if hasattr(app, "market_intelligence_refresh_button"):
        app.market_intelligence_refresh_button.configure(
            bg=palette["button_bg"], fg=palette["button_fg"],
            activebackground=palette["button_active"], activeforeground=palette["bright"],
        )
    if hasattr(app, "market_intelligence_asset_cards"):
        refresh_market_intelligence_page(app)
