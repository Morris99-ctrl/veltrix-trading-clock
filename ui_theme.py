"""Application-wide, cross-platform theme helpers for Veltrix."""

from __future__ import annotations

from typing import Any, Iterable


UI_FONT_FAMILY = "Segoe UI"
UI_FONT = (UI_FONT_FAMILY, 10)
UI_FONT_BOLD = (UI_FONT_FAMILY, 10, "bold")
TABLE_FONT = (UI_FONT_FAMILY, 9)
TABLE_HEADING_FONT = (UI_FONT_FAMILY, 9, "bold")

FONT_OPTIONS = {
    "*Font": UI_FONT,
    "*Label.font": UI_FONT,
    "*Button.font": UI_FONT_BOLD,
    "*Menubutton.font": UI_FONT_BOLD,
    "*Entry.font": UI_FONT,
    "*Spinbox.font": UI_FONT,
    "*Text.font": UI_FONT,
    "*Listbox.font": UI_FONT,
    "*Checkbutton.font": (UI_FONT_FAMILY, 9),
    "*Radiobutton.font": (UI_FONT_FAMILY, 9),
    "*Menu.font": (UI_FONT_FAMILY, 9),
}


def apply_veltrix_font_defaults(root: Any) -> None:
    """Set readable Segoe UI defaults for classic Tk controls."""
    for option, font in FONT_OPTIONS.items():
        try:
            root.option_add(option, font)
        except Exception:
            # Fonts must never prevent the clock from starting.
            pass


COMBOBOX_STYLES = (
    "TCombobox",
    "Veltrix.Regime.TCombobox",
)

TREEVIEW_STYLES = (
    "Treeview",
    "Veltrix.Treeview",
    "Veltrix.Market.Treeview",
    "Veltrix.Regime.Treeview",
)


def prepare_veltrix_ttk_theme(style: Any) -> str:
    """Select a ttk theme whose colours are consistently customisable.

    Windows' native ``vista`` theme can ignore several Combobox and Treeview
    colour options, leaving bright controls inside Veltrix's dark palettes.
    ``clam`` honours those options and is bundled with supported Tk builds.
    """
    try:
        available = tuple(style.theme_names())
        if "clam" in available:
            style.theme_use("clam")
        return str(style.theme_use())
    except Exception:
        try:
            return str(style.theme_use())
        except Exception:
            return "default"


def _parent_background(widget: Any, fallback: str) -> str:
    """Return the current parent's Tk background without assuming widget type."""
    parent = getattr(widget, "master", None)
    if parent is not None:
        for option in ("background", "bg"):
            try:
                value = parent.cget(option)
                if value:
                    return str(value)
            except Exception:
                continue
    return fallback


def apply_veltrix_classic_widget_palette(
    root: Any,
    palette: dict[str, str],
    registered_widgets: Iterable[Any] = (),
) -> None:
    """Theme classic Tk widgets throughout the widget tree.

    ``registered_widgets`` are controls already assigned a specific semantic
    role by the application's ``_frame``/``_label`` helpers. Those controls
    are intentionally left alone here; this pass catches directly-created
    widgets, dynamically-created children and popup controls that used to be
    missed by hand-maintained widget lists.
    """
    registered_paths = {str(widget) for widget in registered_widgets}

    def visit(parent: Any) -> None:
        try:
            children = parent.winfo_children()
        except Exception:
            return

        for widget in children:
            try:
                widget_path = str(widget)
                widget_class = str(widget.winfo_class())
                parent_bg = _parent_background(widget, palette["bg"])

                if widget_path not in registered_paths:
                    options: dict[str, Any] = {}
                    if widget_class in {"Toplevel", "Frame", "Labelframe", "Canvas"}:
                        options["bg"] = parent_bg if widget_class != "Toplevel" else palette["bg"]
                        if widget_class in {"Frame", "Labelframe", "Canvas"}:
                            options.update(highlightthickness=0, bd=0, relief="flat")
                    elif widget_class == "Label":
                        options.update(bg=parent_bg, fg=palette["text"])
                    elif widget_class in {"Button", "Menubutton"}:
                        options.update(
                            bg=palette["button_bg"], fg=palette["button_fg"],
                            activebackground=palette["button_active"],
                            activeforeground=palette["bright"],
                            disabledforeground=palette["muted"],
                        )
                    elif widget_class in {"Entry", "Spinbox"}:
                        options.update(
                            bg=palette["entry_bg"], fg=palette["entry_fg"],
                            insertbackground=palette["bright"],
                            selectbackground=palette["button_active"],
                            selectforeground=palette["bright"],
                            highlightbackground=palette["border"],
                            highlightcolor=palette["bright"],
                            disabledbackground=palette["panel"],
                            disabledforeground=palette["muted"],
                        )
                        # Tk Entry has no arrow-button option; passing one
                        # would reject the entire configure call and leave the
                        # field white. Only Spinbox supports this setting.
                        if widget_class == "Spinbox":
                            options["buttonbackground"] = palette["button_bg"]
                    elif widget_class in {"Checkbutton", "Radiobutton"}:
                        options.update(
                            bg=parent_bg, fg=palette["text"],
                            selectcolor=palette["dim"],
                            activebackground=parent_bg,
                            activeforeground=palette["bright"],
                            disabledforeground=palette["muted"],
                        )
                    elif widget_class == "Listbox":
                        options.update(
                            bg=parent_bg, fg=palette["text"],
                            selectbackground=palette["button_active"],
                            selectforeground=palette["bright"],
                            highlightbackground=palette["border"],
                            highlightcolor=palette["bright"],
                        )
                    elif widget_class == "Text":
                        options.update(
                            bg=palette["panel"], fg=palette["text"],
                            insertbackground=palette["bright"],
                            selectbackground=palette["button_active"],
                            selectforeground=palette["bright"],
                            highlightbackground=palette["border"],
                            highlightcolor=palette["bright"],
                        )
                    elif widget_class == "Menu":
                        options.update(
                            bg=palette["panel"], fg=palette["button_fg"],
                            activebackground=palette["button_active"],
                            activeforeground=palette["bright"],
                            disabledforeground=palette["muted"],
                            bd=1, relief="solid",
                        )
                    elif widget_class == "Scale":
                        options.update(
                            bg=parent_bg, fg=palette["text"],
                            troughcolor=palette["dim"],
                            activebackground=palette["bright"],
                            highlightbackground=palette["border"],
                        )
                    elif widget_class == "Scrollbar":
                        options.update(
                            bg=palette["button_bg"], troughcolor=palette["bg"],
                            activebackground=palette["button_active"],
                            highlightbackground=palette["border"],
                        )
                    if options:
                        try:
                            widget.configure(**options)
                        except Exception:
                            # A custom/third-party Tk widget may reject an option.
                            pass
            except Exception:
                # One unusual widget must never prevent the rest of the UI
                # from receiving its active palette.
                pass
            visit(widget)

    visit(root)


def apply_veltrix_ttk_palette(style: Any, palette: dict[str, str], root: Any = None) -> None:
    """Apply the active palette to standard and application-specific ttk controls."""
    entry_bg = palette["entry_bg"]
    entry_fg = palette["entry_fg"]
    button_bg = palette["button_bg"]
    button_active = palette["button_active"]
    bright = palette["bright"]
    muted = palette["muted"]
    panel = palette["panel"]
    border = palette["border"]
    bg = palette["bg"]
    text = palette["text"]

    # Base style provides sensible defaults even for future ttk widgets added
    # without a Veltrix-specific style name.
    try:
        style.configure(
            ".", background=bg, foreground=text, font=UI_FONT,
            bordercolor=bg, lightcolor=bg, darkcolor=bg, troughcolor=bg,
            focuscolor=bright,
        )
    except Exception:
        pass

    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=text, font=UI_FONT)
    style.configure("TButton", background=button_bg, foreground=palette["button_fg"],
                    font=UI_FONT_BOLD, bordercolor=bg, lightcolor=bg, darkcolor=bg,
                    padding=(12, 7), relief="flat", focusthickness=0, focuscolor=bright)
    style.map("TButton", background=[("disabled", panel), ("pressed", button_active),
                                      ("active", button_active)],
              foreground=[("disabled", muted), ("pressed", bright), ("active", bright)])

    entry_options = {
        "fieldbackground": entry_bg, "background": button_bg,
        "foreground": entry_fg, "font": UI_FONT, "bordercolor": border,
        "lightcolor": border, "darkcolor": border,
        "focuscolor": bright, "insertcolor": bright,
        "padding": (8, 6), "relief": "flat",
    }
    entry_map = {
        "fieldbackground": [("disabled", panel), ("readonly", entry_bg), ("!disabled", entry_bg)],
        "background": [("disabled", panel), ("pressed", button_active),
                        ("active", button_active), ("readonly", button_bg), ("!disabled", button_bg)],
        "foreground": [("disabled", muted), ("readonly", entry_fg), ("!disabled", entry_fg)],
    }
    style.configure("TEntry", **entry_options)
    style.map("TEntry", **entry_map)
    style.configure("TSpinbox", **entry_options)
    style.map("TSpinbox", **entry_map)

    combo_options = {
        **entry_options, "arrowcolor": bright, "arrowsize": 12,
    }
    combo_map = {
        **entry_map,
        "arrowcolor": [("disabled", muted), ("pressed", bright), ("active", bright), ("!disabled", bright)],
    }
    for style_name in COMBOBOX_STYLES:
        style.configure(style_name, **combo_options)
        style.map(style_name, **combo_map)

    style.configure("TCheckbutton", background=bg, foreground=text, font=UI_FONT,
                    indicatorcolor=palette["dim"], focuscolor=bright, padding=(4, 3))
    style.map("TCheckbutton", background=[("active", panel)], foreground=[("disabled", muted),
                  ("active", bright)], indicatorcolor=[("selected", bright), ("disabled", panel)])
    style.configure("TRadiobutton", background=bg, foreground=text, font=UI_FONT,
                    indicatorcolor=palette["dim"], focuscolor=bright, padding=(4, 3))
    style.map("TRadiobutton", background=[("active", panel)], foreground=[("disabled", muted),
                  ("active", bright)], indicatorcolor=[("selected", bright), ("disabled", panel)])

    style.configure("TLabelframe", background=bg, bordercolor=bg, relief="flat")
    style.configure("TLabelframe.Label", background=bg, foreground=bright)
    style.configure("TNotebook", background=bg, bordercolor=bg, tabmargins=(4, 4, 4, 0))
    style.configure("TNotebook.Tab", background=palette["dim"], foreground=text,
                    padding=(10, 5), bordercolor=border)
    style.map("TNotebook.Tab", background=[("selected", panel), ("active", button_active)],
              foreground=[("selected", bright), ("active", bright)])
    style.configure("TSeparator", background=border)
    style.configure("TProgressbar", background=bright, troughcolor=palette["dim"], bordercolor=border)
    style.configure("TScale", background=bg, troughcolor=palette["dim"],
                    bordercolor=border, lightcolor=border, darkcolor=border)
    style.map("TScale", background=[("active", panel)])
    style.configure("TScrollbar", background=button_bg, troughcolor=bg,
                    arrowcolor=bright, bordercolor=bg, lightcolor=bg,
                    darkcolor=bg, gripcount=0)
    style.map("TScrollbar", background=[("active", button_active), ("pressed", bright)])

    # Every current and future Treeview uses a dark field and a visible header.
    # Named styles retain their own row heights/fonts configured by main.py.
    for style_name in TREEVIEW_STYLES:
        style.configure(style_name, background=bg, foreground=text,
                        fieldbackground=bg, bordercolor=bg, font=TABLE_FONT, rowheight=29)
        style.configure(f"{style_name}.Heading", background=panel, foreground=bright,
                        relief="flat", bordercolor=bg, font=TABLE_HEADING_FONT)
        style.map(style_name, background=[("selected", button_active)],
                  foreground=[("selected", bright)])
        style.map(f"{style_name}.Heading", background=[("active", button_active)],
                  foreground=[("active", bright)])

    style.configure("Veltrix.Market.Vertical.TScrollbar", background=button_bg,
                    troughcolor=bg, arrowcolor=bright, bordercolor=border,
                    lightcolor=border, darkcolor=border)

    # The ttk Combobox popup is a classic Tk Listbox on some Tk versions.
    # Option-database styling also covers native Tk menus and text widgets
    # created after startup, including popup children.
    if root is not None:
        options = {
            "*Frame.background": bg,
            "*Label.background": bg,
            "*Label.foreground": text,
            "*Button.background": button_bg,
            "*Button.foreground": palette["button_fg"],
            "*Button.activeBackground": button_active,
            "*Button.activeForeground": bright,
            "*Menubutton.background": button_bg,
            "*Menubutton.foreground": palette["button_fg"],
            "*Menubutton.activeBackground": button_active,
            "*Menubutton.activeForeground": bright,
            "*Entry.background": entry_bg,
            "*Entry.foreground": entry_fg,
            "*Entry.insertBackground": bright,
            "*Entry.selectBackground": button_active,
            "*Entry.selectForeground": bright,
            "*Entry.highlightBackground": border,
            "*Entry.highlightColor": bright,
            "*Spinbox.background": entry_bg,
            "*Spinbox.foreground": entry_fg,
            "*Spinbox.insertBackground": bright,
            "*Spinbox.buttonBackground": button_bg,
            "*Spinbox.selectBackground": button_active,
            "*Spinbox.selectForeground": bright,
            "*Listbox.background": entry_bg,
            "*Listbox.foreground": entry_fg,
            "*Listbox.selectBackground": button_active,
            "*Listbox.selectForeground": bright,
            "*Listbox.highlightBackground": border,
            "*Listbox.highlightColor": bright,
            "*Menu.background": panel,
            "*Menu.foreground": palette["button_fg"],
            "*Menu.activeBackground": button_active,
            "*Menu.activeForeground": bright,
            "*Menu.disabledForeground": muted,
            "*Text.background": panel,
            "*Text.foreground": text,
            "*Text.insertBackground": bright,
            "*Text.selectBackground": button_active,
            "*Text.selectForeground": bright,
            "*Checkbutton.background": panel,
            "*Checkbutton.foreground": text,
            "*Checkbutton.selectColor": palette["dim"],
            "*Radiobutton.background": panel,
            "*Radiobutton.foreground": text,
            "*Radiobutton.selectColor": palette["dim"],
            "*Canvas.background": bg,
            "*Toplevel.background": bg,
            "*Scrollbar.background": button_bg,
            "*Scrollbar.troughColor": bg,
        }
        for option, value in options.items():
            try:
                root.option_add(option, value)
            except Exception:
                # Styling must never prevent the clock from starting.
                pass
