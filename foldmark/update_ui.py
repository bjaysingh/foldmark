"""Tk dialogs for attribution and updates.

Kept separate from ``app.py`` so the main window module stays focused on the
conversion workflow.
"""

from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

from . import theme
from .updater import MARKITDOWN_URL, PROJECT_URL, UpdateInfo


def open_link(url: str) -> None:
    try:
        webbrowser.open_new_tab(url)
    except Exception:
        pass


def link_label(parent, text: str, url: str, *, background: str, foreground: str, font) -> tk.Label:
    """A label that looks and behaves like a hyperlink.

    Tk has no link widget, so the affordances have to be assembled by hand:
    underline, a hand cursor, and a click binding.
    """
    label = tk.Label(
        parent, text=text, bg=background, fg=foreground, cursor="hand2",
        font=(*font, "underline") if len(font) == 2 else (font[0], font[1], f"{font[2]} underline"),
    )
    label.bind("<Button-1>", lambda _event: open_link(url))
    label.bind("<Return>", lambda _event: open_link(url))
    return label


def _centre(window: tk.Toplevel, parent: tk.Misc) -> None:
    window.update_idletasks()
    try:
        x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 3
        window.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    except tk.TclError:
        pass


class UpdateAvailableDialog:
    """Asks what to do about a newer release. Returns 'update', 'later', or 'skip'."""

    def __init__(self, parent: tk.Misc, current_version: str, info: UpdateInfo) -> None:
        self.choice = "later"
        self.window = window = tk.Toplevel(parent)
        window.title("Update available")
        window.configure(bg=theme.CANVAS)
        window.resizable(False, False)
        window.transient(parent)

        header = tk.Frame(window, bg=theme.NAVY)
        header.pack(fill="x")
        tk.Label(
            header, text=f"Version {info.version} is available",
            bg=theme.NAVY, fg="white", font=theme.ui(15, "bold"),
        ).pack(anchor="w", padx=20, pady=(16, 2))
        tk.Label(
            header, text=f"You are running {current_version}",
            bg=theme.NAVY, fg=theme.HEADER_SUBTITLE, font=theme.ui(9),
        ).pack(anchor="w", padx=20, pady=(0, 14))

        body = ttk.Frame(window, padding=(20, 16, 20, 8))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="RELEASE NOTES", style="Muted.TLabel").pack(anchor="w", pady=(0, 6))

        notes_frame = ttk.Frame(body)
        notes_frame.pack(fill="both", expand=True)
        notes = tk.Text(
            notes_frame, wrap="word", width=64, height=12, relief="flat",
            bg=theme.PREVIEW_BG, fg=theme.TEXT, padx=10, pady=10, font=theme.ui(9),
        )
        scroll = ttk.Scrollbar(notes_frame, orient="vertical", command=notes.yview)
        notes.configure(yscrollcommand=scroll.set)
        notes.insert("1.0", (info.notes or "No release notes were provided.").strip())
        notes.configure(state="disabled")
        notes.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        buttons = ttk.Frame(window, padding=(20, 8, 20, 16))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Update now", style="Primary.TButton",
                   command=lambda: self._close("update")).pack(side="right")
        ttk.Button(buttons, text="Later", style="Secondary.TButton",
                   command=lambda: self._close("later")).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="Skip this version", style="Secondary.TButton",
                   command=lambda: self._close("skip")).pack(side="left")

        window.protocol("WM_DELETE_WINDOW", lambda: self._close("later"))
        _centre(window, parent)
        window.grab_set()
        window.wait_window()

    def _close(self, choice: str) -> None:
        self.choice = choice
        try:
            self.window.destroy()
        except tk.TclError:
            pass


class UpdateProgressDialog:
    """Determinate progress with a cancel button wired to a threading.Event."""

    def __init__(self, parent: tk.Misc, cancel_event: threading.Event) -> None:
        self.cancel_event = cancel_event
        self.window = window = tk.Toplevel(parent)
        window.title("Updating")
        window.configure(bg=theme.CANVAS)
        window.resizable(False, False)
        window.transient(parent)

        frame = ttk.Frame(window, padding=(24, 20))
        frame.pack(fill="both", expand=True)
        self.status = tk.StringVar(value="Preparing…")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w")
        self.value = tk.DoubleVar(value=0)
        self.bar = ttk.Progressbar(frame, variable=self.value, maximum=100, length=360)
        self.bar.pack(fill="x", pady=(10, 12))
        self.cancel_button = ttk.Button(
            frame, text="Cancel", style="Secondary.TButton", command=self.cancel
        )
        self.cancel_button.pack(anchor="e")

        window.protocol("WM_DELETE_WINDOW", self.cancel)
        _centre(window, parent)
        window.grab_set()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.status.set("Cancelling…")
        try:
            self.cancel_button.state(["disabled"])
        except tk.TclError:
            pass

    def set_status(self, text: str) -> None:
        self.status.set(text)

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.value.set(min(done / total * 100, 100))
            self.status.set(f"Downloading… {done // 1024} of {total // 1024} KB")
        else:
            self.status.set(f"Downloading… {done // 1024} KB")

    def start_indeterminate(self, text: str) -> None:
        self.status.set(text)
        self.bar.configure(mode="indeterminate")
        self.bar.start(12)

    def close(self) -> None:
        try:
            self.bar.stop()
            self.window.grab_release()
            self.window.destroy()
        except tk.TclError:
            pass


class AboutDialog:
    """States the MarkItDown dependency plainly and links to both sources."""

    def __init__(self, parent: tk.Misc, app_version: str, markitdown_version: str,
                 *, ocr_engine: str | None = None) -> None:
        window = tk.Toplevel(parent)
        window.title("About Foldmark")
        window.configure(bg=theme.CANVAS)
        window.resizable(False, False)
        window.transient(parent)

        header = tk.Frame(window, bg=theme.NAVY)
        header.pack(fill="x")
        tk.Label(header, text="Foldmark", bg=theme.NAVY, fg="white",
                 font=theme.ui(16, "bold")).pack(anchor="w", padx=20, pady=(16, 0))
        tk.Label(header, text=f"Version {app_version}", bg=theme.NAVY,
                 fg=theme.HEADER_SUBTITLE, font=theme.ui(9)).pack(anchor="w", padx=20, pady=(2, 14))

        body = tk.Frame(window, bg=theme.CANVAS, padx=22, pady=18)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, bg=theme.CANVAS, fg=theme.TEXT, justify="left", wraplength=430,
            font=theme.ui(10),
            text="This application converts documents to Markdown using Microsoft MarkItDown, "
                 "an open-source library released by Microsoft under the MIT License.",
        ).pack(anchor="w")

        row = tk.Frame(body, bg=theme.CANVAS)
        row.pack(anchor="w", pady=(10, 0))
        tk.Label(row, text="MarkItDown source:", bg=theme.CANVAS, fg=theme.MUTED,
                 font=theme.ui(9)).pack(side="left")
        link_label(row, MARKITDOWN_URL, MARKITDOWN_URL, background=theme.CANVAS,
                   foreground=theme.LINK, font=theme.ui(9)).pack(side="left", padx=(6, 0))

        tk.Label(body, text=f"Installed MarkItDown version: {markitdown_version}",
                 bg=theme.CANVAS, fg=theme.MUTED, font=theme.ui(9)).pack(anchor="w", pady=(4, 0))

        # MarkItDown itself has no OCR, so scanned pages depend entirely on
        # whichever engine is installed here - worth stating outright.
        from .ocr import about_line

        tk.Label(body, text=about_line(ocr_engine), bg=theme.CANVAS, fg=theme.MUTED, justify="left",
                 wraplength=430, font=theme.ui(9)).pack(anchor="w", pady=(2, 0))

        row2 = tk.Frame(body, bg=theme.CANVAS)
        row2.pack(anchor="w", pady=(10, 0))
        tk.Label(row2, text="This app's source:", bg=theme.CANVAS, fg=theme.MUTED,
                 font=theme.ui(9)).pack(side="left")
        link_label(row2, PROJECT_URL, PROJECT_URL, background=theme.CANVAS,
                   foreground=theme.LINK, font=theme.ui(9)).pack(side="left", padx=(6, 0))

        tk.Label(
            body, bg=theme.CANVAS, fg=theme.MUTED, justify="left", wraplength=430,
            font=theme.ui(9), pady=12,
            text="This is an independent desktop frontend. It is not a Microsoft product and is "
                 "not endorsed or sponsored by Microsoft. “Microsoft” and related marks belong to "
                 "Microsoft Corporation.",
        ).pack(anchor="w")

        ttk.Button(body, text="Close", style="Secondary.TButton",
                   command=window.destroy).pack(anchor="e")

        _centre(window, parent)
        window.grab_set()
        window.wait_window()
