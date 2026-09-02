"""Colour and font constants, resolved per platform.

Tk silently substitutes a default face when a named font is missing, so the
Windows-only "Segoe UI"/"Consolas" pair used previously rendered as an
unstyled fallback on macOS. Resolving names per platform keeps the intended
look on every supported OS.
"""

from __future__ import annotations

import sys

NAVY = "#0B1F33"
BLUE = "#1677FF"
BLUE_HOVER = "#0D62D6"
CANVAS = "#F4F7FA"
CARD = "#FFFFFF"
TEXT = "#17212B"
MUTED = "#5F6B76"
SUCCESS = "#138A5B"
ERROR = "#C73737"
LINK = "#1677FF"
LINK_ON_NAVY = "#8FC2FF"
HEADER_SUBTITLE = "#BFD4E8"
PREVIEW_BG = "#F8FAFC"
TROUGH = "#DFE7EF"

if sys.platform == "win32":
    UI_FONT = "Segoe UI"
    MONO_FONT = "Consolas"
elif sys.platform == "darwin":
    UI_FONT = "SF Pro Text"
    MONO_FONT = "Menlo"
else:
    UI_FONT = "DejaVu Sans"
    MONO_FONT = "DejaVu Sans Mono"


def ui(size: int, weight: str | None = None) -> tuple:
    """Return a Tk font tuple for the platform UI face."""
    return (UI_FONT, size, weight) if weight else (UI_FONT, size)


def mono(size: int) -> tuple:
    return (MONO_FONT, size)


def resolve_fonts(root) -> None:
    """Fall back to a face Tk actually has, if the preferred one is missing.

    ``SF Pro Text`` ships with recent macOS but not with every Python/Tk
    build, so verify against the live font list rather than assuming.
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
