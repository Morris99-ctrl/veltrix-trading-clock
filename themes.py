"""Colour themes retained from the original retro-futuristic alarm clock."""

CYAN_PALETTE = {
    "bg": "#020809", "panel": "#061214", "border": "#103438", "scanline": "#071214",
    "text": "#55dadd", "bright": "#20f4f2", "bright_edge": "#a2ffff", "muted": "#17666a",
    "dim": "#0b292c", "inactive": "#092326", "button_bg": "#092326", "button_fg": "#69e8e8",
    "button_active": "#124247", "entry_bg": "#061719", "entry_fg": "#a4ffff",
    "success": "#39e6bd", "warning": "#ffd166", "error": "#ff7777",
}

THEMES = {
    "CYAN": CYAN_PALETTE,
    "AMBER": {
        **CYAN_PALETTE, "bg": "#090602", "panel": "#151006", "border": "#4b3210",
        "scanline": "#110c04", "text": "#d79b3f", "bright": "#ffb52e", "bright_edge": "#ffe1a1",
        "muted": "#80551c", "dim": "#2b1d08", "inactive": "#241704", "button_bg": "#281a07",
        "button_fg": "#f3bd55", "button_active": "#49300c", "entry_bg": "#170f04", "entry_fg": "#ffdc8a",
        "success": "#a4d66d", "warning": "#ffd166", "error": "#ff7777",
    },
    "MATRIX": {
        **CYAN_PALETTE, "bg": "#020903", "panel": "#06140a", "border": "#164326",
        "scanline": "#071309", "text": "#55d878", "bright": "#39ff72", "bright_edge": "#b1ffc5",
        "muted": "#267440", "dim": "#0c2c16", "inactive": "#0b2512", "button_bg": "#0b2a14",
        "button_fg": "#75f994", "button_active": "#164c25", "entry_bg": "#07190c", "entry_fg": "#b8ffc8",
        "success": "#39e6bd", "warning": "#ffd166", "error": "#ff7777",
    },
    "VIOLET": {
        **CYAN_PALETTE, "bg": "#080510", "panel": "#110b1d", "border": "#382052",
        "scanline": "#0d0817", "text": "#bb8be8", "bright": "#c77dff", "bright_edge": "#edcaff",
        "muted": "#77519a", "dim": "#241536", "inactive": "#211331", "button_bg": "#28183b",
        "button_fg": "#d5a7ff", "button_active": "#43265f", "entry_bg": "#130c20", "entry_fg": "#edcaff",
        "success": "#72dfbc", "warning": "#ffd166", "error": "#ff8585",
    },
    "ICE": {
        **CYAN_PALETTE, "bg": "#030914", "panel": "#081627", "border": "#1c4366",
        "scanline": "#07111e", "text": "#83bde8", "bright": "#70c8ff", "bright_edge": "#d1efff",
        "muted": "#47799d", "dim": "#102b43", "inactive": "#10263a", "button_bg": "#102c43",
        "button_fg": "#9bd9ff", "button_active": "#1b4565", "entry_bg": "#091a2b", "entry_fg": "#d1efff",
        "success": "#72dfbc", "warning": "#ffd166", "error": "#ff8585",
    },
    "LIGHT": {
        "bg": "#eaf3f2", "panel": "#dcebea", "border": "#9bbfbd", "scanline": "#e4efee",
        "text": "#356c6d", "bright": "#087d82", "bright_edge": "#075e64", "muted": "#739b9c",
        "dim": "#c7dcda", "inactive": "#c6dcd9", "button_bg": "#d1e5e2", "button_fg": "#175f63",
        "button_active": "#b8d6d2", "entry_bg": "#e7f0ef", "entry_fg": "#164f52",
        "success": "#087d68", "warning": "#986300", "error": "#a12d38",
    },
}
