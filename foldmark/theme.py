"""Palette, type scale, and platform fonts.

A quiet light palette: near-white ground, hairline separators instead of card
borders, and a single accent reserved for the primary action so the eye lands
on Convert and nothing else competes with it.
"""

from __future__ import annotations

import sys

# Surfaces
CANVAS = "#FBFBFD"          # window ground
SURFACE = "#FFFFFF"         # raised areas: list rows, preview
SUBTLE = "#F4F5F7"          # drop zone fill, hover
HAIRLINE = "#E4E6EB"        # 1px separators, replaces card borders
DROPZONE_EDGE = "#C9CED6"
DROPZONE_ACTIVE = "#0A66FF"
DROPZONE_ACTIVE_FILL = "#EDF3FF"

# Text
TEXT = "#1D1D1F"
MUTED = "#6E7278"
FAINT = "#9AA0A6"

# Accent, used only on the primary action and links
ACCENT = "#0A66FF"
ACCENT_HOVER = "#0552D1"
ACCENT_TEXT = "#FFFFFF"

# Status
SUCCESS = "#1A7F4B"
ERROR = "#C0392B"
WAITING = "#8A8F96"

# Retained for the update and About dialogs
NAVY = "#0B1F33"
HEADER_SUBTITLE = "#BFD4E8"
LINK = ACCENT
LINK_ON_NAVY = "#8FC2FF"
CARD = SURFACE
PREVIEW_BG = "#FCFCFD"
TROUGH = "#E8EAEE"
BLUE = ACCENT
BLUE_HOVER = ACCENT_HOVER

if sys.platform == "win32":
    UI_FONT = "Segoe UI"
    MONO_FONT = "Consolas"
elif sys.platform == "darwin":
    UI_FONT = "SF Pro Text"
    MONO_FONT = "Menlo"
else:
    UI_FONT = "DejaVu Sans"
    MONO_FONT = "DejaVu Sans Mono"

# Type scale. Kept small and few: three sizes carry the whole interface.
SIZE_TITLE = 19
SIZE_BODY = 12
SIZE_SMALL = 10


def ui(size: int, weight: str | None = None) -> tuple:
    return (UI_FONT, size, weight) if weight else (UI_FONT, size)


def mono(size: int) -> tuple:
    return (MONO_FONT, size)


def resolve_fonts(root) -> None:
    """Fall back to a face Tk actually has, if the preferred one is missing.

    Tk substitutes silently for an unknown font name, so the only reliable
    check is asking the live interpreter what it has.
    """
    global UI_FONT, MONO_FONT
    try:
        available = {name.lower() for name in root.tk.splitlist(root.tk.call("font", "families"))}
    except Exception:
        return
    if UI_FONT.lower() not in available:
        for candidate in ("Helvetica Neue", "Helvetica", "Arial", "TkDefaultFont"):
            if candidate.lower() in available or candidate == "TkDefaultFont":
                UI_FONT = candidate
                break
    if MONO_FONT.lower() not in available:
        for candidate in ("Monaco", "Courier New", "TkFixedFont"):
            if candidate.lower() in available or candidate == "TkFixedFont":
                MONO_FONT = candidate
                break
