from __future__ import annotations

import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from markitdown_desktop import __version__, settings, theme, updater
from markitdown_desktop.ocr import (
    OcrFallbackConverter,
    available_engine,
    mode_from_settings,
    usage_summary,
)
from markitdown_desktop.converter import (
    ConversionResult,
    MicrosoftMarkItDownConverter,
    SUPPORTED_EXTENSIONS,
    convert_files,
    discover_files,
)
from markitdown_desktop.update_ui import (
    AboutDialog,
    UpdateAvailableDialog,
    UpdateProgressDialog,
    link_label,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None


APP_NAME = "MarkItDown"
INSTALL_ROOT = Path(__file__).resolve().parent
HEADLINE_FORMATS = "PDF · Word · Excel · PowerPoint · e-books · email · audio · images"


def markitdown_version() -> str:
    try:
        from importlib.metadata import version

        return version("markitdown")
    except Exception:
        return "not detected"


def _venv_python(root: Path, windowed: bool = False) -> str:
    if sys.platform == "win32":
        name = "pythonw.exe" if windowed else "python.exe"
        candidate = root / ".venv" / "Scripts" / name
    else:
        candidate = root / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def _shorten(path: Path, limit: int = 46) -> str:
    text = str(path)
    home = str(Path.home())
    if text.startswith(home):
        text = "~" + text[len(home):]
    if len(text) <= limit:
        return text
    return "…" + text[-(limit - 1):]


class DropZone(tk.Canvas):
    """The empty state: a dashed target that is also a button.

    Drawn on a Canvas because Tk has no dashed border; the rectangle is
    redrawn on resize so it always frames the current size.
    """

    def __init__(self, parent, on_click) -> None:
        super().__init__(parent, bg=theme.CANVAS, highlightthickness=0, bd=0)
        self.on_click = on_click
        self.active = False
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<Button-1>", lambda _e: self.on_click())
        self.configure(cursor="hand2")

    def set_active(self, active: bool) -> None:
        if active != self.active:
            self.active = active
            self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 40 or height < 40:
            return
        pad_x = max(int(width * 0.12), 24)
        pad_y = max(int(height * 0.14), 20)
        edge = theme.DROPZONE_ACTIVE if self.active else theme.DROPZONE_EDGE
        fill = theme.DROPZONE_ACTIVE_FILL if self.active else theme.SUBTLE
        self.create_rectangle(
            pad_x, pad_y, width - pad_x, height - pad_y,
            outline=edge, fill=fill, dash=(6, 5), width=2,
        )
        middle = height // 2
        self.create_text(
            width // 2, middle - 16, text="Drop files or folders here",
            fill=theme.TEXT, font=theme.ui(theme.SIZE_TITLE - 3),
        )
        self.create_text(
            width // 2, middle + 12, text="or click to browse",
            fill=theme.ACCENT, font=theme.ui(theme.SIZE_BODY),
        )
        self.create_text(
            width // 2, height - pad_y + 26, text=HEADLINE_FORMATS,
            fill=theme.FAINT, font=theme.ui(theme.SIZE_SMALL),
        )


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("980x680")
        self.root.minsize(720, 520)
        self.root.configure(bg=theme.CANVAS)

        theme.resolve_fonts(root)

        self.files: dict[str, Path] = {}
        self.path_to_item: dict[str, str] = {}
        self.outputs: dict[str, Path] = {}
        self.events: queue.Queue[tuple] = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False
        self.ocr_note = ""
        self.updating = False
        self.update_progress: UpdateProgressDialog | None = None
        self.preview_open = False

        self.output_dir = Path.home() / "Documents" / "Markdown Output"
        self.output_var = tk.StringVar(value=str(self.output_dir))
        self.output_label_var = tk.StringVar(value=_shorten(self.output_dir))
        self.overwrite_var = tk.BooleanVar(value=False)
        self.summary_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0)

        self._configure_styles()
        self._build_ui()
        self._enable_drag_drop()
        self._bind_shortcuts()
        self.root.after(100, self._poll_events)

    # ------------------------------------------------------------------ chrome

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=theme.CANVAS)
        style.configure("Surface.TFrame", background=theme.SURFACE)
        style.configure("TLabel", background=theme.CANVAS, foreground=theme.TEXT,
                        font=theme.ui(theme.SIZE_BODY))
        style.configure("Muted.TLabel", background=theme.CANVAS, foreground=theme.MUTED,
                        font=theme.ui(theme.SIZE_SMALL))

        style.configure("Primary.TButton", font=theme.ui(theme.SIZE_BODY, "bold"),
                        padding=(26, 11), borderwidth=0, relief="flat",
                        focuscolor=theme.ACCENT)
        style.map("Primary.TButton",
                  background=[("disabled", "#C3D4F5"), ("active", theme.ACCENT_HOVER),
                              ("!disabled", theme.ACCENT)],
                  foreground=[("!disabled", theme.ACCENT_TEXT), ("disabled", "#FFFFFF")])

        style.configure("Quiet.TButton", font=theme.ui(theme.SIZE_SMALL), padding=(10, 6),
                        borderwidth=0, relief="flat", background=theme.CANVAS,
                        foreground=theme.MUTED)
        style.map("Quiet.TButton",
                  background=[("active", theme.SUBTLE), ("!disabled", theme.CANVAS)],
                  foreground=[("active", theme.TEXT), ("!disabled", theme.MUTED)])

        style.configure("Treeview", font=theme.ui(theme.SIZE_BODY), rowheight=32,
                        background=theme.SURFACE, fieldbackground=theme.SURFACE,
                        foreground=theme.TEXT, borderwidth=0)
        style.configure("Treeview.Heading", font=theme.ui(theme.SIZE_SMALL, "bold"),
                        background=theme.CANVAS, foreground=theme.MUTED,
                        borderwidth=0, relief="flat")
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Horizontal.TProgressbar", troughcolor=theme.TROUGH,
                        background=theme.ACCENT, borderwidth=0, thickness=4)

    def _hairline(self, parent) -> tk.Frame:
        line = tk.Frame(parent, bg=theme.HAIRLINE, height=1)
        return line

    def _build_ui(self) -> None:
        # Order matters. The bottom bars are packed before the content area so
        # the packer reserves their space first; the primary action can then
        # never be dropped when the window is short, which is exactly what
        # happened when the action row was the last child of an expanding body.
        self._build_header()
        self._build_footer_bar()
        self._build_action_bar()
        self._build_content()
        self._show_empty_state()

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=theme.CANVAS)
        header.pack(fill="x", side="top")
        inner = tk.Frame(header, bg=theme.CANVAS)
        inner.pack(fill="x", padx=26, pady=(20, 14))

        tk.Label(inner, text=APP_NAME, bg=theme.CANVAS, fg=theme.TEXT,
                 font=theme.ui(theme.SIZE_TITLE, "bold")).pack(side="left")

        credit = tk.Frame(inner, bg=theme.CANVAS)
        credit.pack(side="right")
        tk.Label(credit, text="Powered by", bg=theme.CANVAS, fg=theme.MUTED,
                 font=theme.ui(theme.SIZE_SMALL)).pack(side="left")
        link_label(credit, "Microsoft MarkItDown", updater.MARKITDOWN_URL,
                   background=theme.CANVAS, foreground=theme.ACCENT,
                   font=theme.ui(theme.SIZE_SMALL)).pack(side="left", padx=(4, 0))

        self._hairline(header).pack(fill="x")

    def _build_footer_bar(self) -> None:
        bar = tk.Frame(self.root, bg=theme.CANVAS)
        bar.pack(fill="x", side="bottom")
        self._hairline(bar).pack(fill="x", side="top")
        inner = tk.Frame(bar, bg=theme.CANVAS)
        inner.pack(fill="x", padx=20, pady=(6, 8))

        tk.Label(inner, text="Uses the open-source", bg=theme.CANVAS, fg=theme.FAINT,
                 font=theme.ui(theme.SIZE_SMALL)).pack(side="left")
        link_label(inner, "Microsoft MarkItDown", updater.MARKITDOWN_URL,
                   background=theme.CANVAS, foreground=theme.ACCENT,
                   font=theme.ui(theme.SIZE_SMALL)).pack(side="left", padx=4)
        tk.Label(inner, text="library · not affiliated with Microsoft", bg=theme.CANVAS,
                 fg=theme.FAINT, font=theme.ui(theme.SIZE_SMALL)).pack(side="left")

        ttk.Button(inner, text="About", style="Quiet.TButton",
                   command=self.show_about).pack(side="right")
        ttk.Button(inner, text="Check for updates", style="Quiet.TButton",
                   command=self.check_updates_manually).pack(side="right")
        self.version_label = tk.Label(inner, text=f"v{__version__}", bg=theme.CANVAS,
                                      fg=theme.FAINT, font=theme.ui(theme.SIZE_SMALL))
        self.version_label.pack(side="right", padx=(0, 10))

    def _build_action_bar(self) -> None:
        bar = tk.Frame(self.root, bg=theme.CANVAS)
        bar.pack(fill="x", side="bottom")
        self._hairline(bar).pack(fill="x", side="top")

        inner = tk.Frame(bar, bg=theme.CANVAS)
        inner.pack(fill="x", padx=26, pady=(14, 16))

        destination = tk.Frame(inner, bg=theme.CANVAS)
        destination.pack(fill="x")
        tk.Label(destination, text="Save to", bg=theme.CANVAS, fg=theme.MUTED,
                 font=theme.ui(theme.SIZE_SMALL)).pack(side="left")
        self.output_button = ttk.Button(
            destination, textvariable=self.output_label_var, style="Quiet.TButton",
            command=self.choose_output)
        self.output_button.pack(side="left", padx=(6, 0))
        ttk.Button(destination, text="Open", style="Quiet.TButton",
                   command=self.open_output).pack(side="left")
        self.overwrite_check = tk.Checkbutton(
            destination, text="Replace files of the same name", variable=self.overwrite_var,
            bg=theme.CANVAS, fg=theme.MUTED, font=theme.ui(theme.SIZE_SMALL),
            activebackground=theme.CANVAS, activeforeground=theme.TEXT,
            selectcolor=theme.SURFACE, highlightthickness=0, bd=0)
        self.overwrite_check.pack(side="right")

        row = tk.Frame(inner, bg=theme.CANVAS)
        row.pack(fill="x", pady=(12, 0))

        status = tk.Frame(row, bg=theme.CANVAS)
        status.pack(side="left", fill="x", expand=True, padx=(0, 18))
        tk.Label(status, textvariable=self.summary_var, bg=theme.CANVAS, fg=theme.MUTED,
                 font=theme.ui(theme.SIZE_SMALL), anchor="w").pack(fill="x")
        self.progress = ttk.Progressbar(status, variable=self.progress_var, maximum=100)

        self.convert_button = ttk.Button(row, text="Convert", style="Primary.TButton",
                                         command=self.start_conversion)
        self.convert_button.pack(side="right")
        self.cancel_button = ttk.Button(row, text="Cancel", style="Quiet.TButton",
                                        command=self.cancel)

    def _build_content(self) -> None:
        self.content = tk.Frame(self.root, bg=theme.CANVAS)
        self.content.pack(fill="both", expand=True, side="top")

        self.dropzone = DropZone(self.content, self.add_files)

        self.list_area = tk.Frame(self.content, bg=theme.CANVAS)
        toolbar = tk.Frame(self.list_area, bg=theme.CANVAS)
        toolbar.pack(fill="x", padx=26, pady=(14, 8))
        self.count_label = tk.Label(toolbar, text="", bg=theme.CANVAS, fg=theme.TEXT,
                                    font=theme.ui(theme.SIZE_BODY, "bold"))
        self.count_label.pack(side="left")
        ttk.Button(toolbar, text="Clear", style="Quiet.TButton",
                   command=self.clear_files).pack(side="right")
        self.remove_button = ttk.Button(toolbar, text="Remove", style="Quiet.TButton",
                                        command=self.remove_selected)
        self.remove_button.pack(side="right")
        ttk.Button(toolbar, text="Add more", style="Quiet.TButton",
                   command=self.add_files).pack(side="right")

        self.panes = ttk.Panedwindow(self.list_area, orient="horizontal")
        self.panes.pack(fill="both", expand=True, padx=26, pady=(0, 6))

        list_holder = tk.Frame(self.panes, bg=theme.SURFACE,
                               highlightbackground=theme.HAIRLINE, highlightthickness=1)
        self.panes.add(list_holder, weight=3)
        self.tree = ttk.Treeview(list_holder, columns=("name", "status"), show="headings",
                                 selectmode="extended")
        self.tree.heading("name", text="FILE", anchor="w")
        self.tree.heading("status", text="STATUS", anchor="w")
        self.tree.column("name", width=380, minwidth=180, anchor="w")
        self.tree.column("status", width=150, minwidth=100, stretch=False, anchor="w")
        self.tree.tag_configure("success", foreground=theme.SUCCESS)
        self.tree.tag_configure("error", foreground=theme.ERROR)
        self.tree.tag_configure("waiting", foreground=theme.WAITING)
        scrollbar = ttk.Scrollbar(list_holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._show_selected_preview)
        self.tree.bind("<Delete>", lambda _e: self.remove_selected())
        self.tree.bind("<BackSpace>", lambda _e: self.remove_selected())

        # Built now, added to the panes only when there is something to preview.
        self.preview_holder = tk.Frame(self.panes, bg=theme.SURFACE,
                                       highlightbackground=theme.HAIRLINE, highlightthickness=1)
        preview_head = tk.Frame(self.preview_holder, bg=theme.SURFACE)
        preview_head.pack(fill="x", padx=12, pady=(10, 6))
        self.preview_title = tk.Label(preview_head, text="", bg=theme.SURFACE, fg=theme.MUTED,
                                      font=theme.ui(theme.SIZE_SMALL, "bold"))
        self.preview_title.pack(side="left")
        self.copy_button = ttk.Button(preview_head, text="Copy", style="Quiet.TButton",
                                      command=self.copy_preview)
        self.copy_button.pack(side="right")
        ttk.Button(preview_head, text="Close", style="Quiet.TButton",
                   command=self.close_preview).pack(side="right")
        self.preview = tk.Text(self.preview_holder, wrap="word", relief="flat", bd=0,
                               bg=theme.PREVIEW_BG, fg=theme.TEXT, padx=14, pady=10,
                               font=theme.mono(theme.SIZE_SMALL + 1), state="disabled",
                               highlightthickness=0)
        preview_scroll = ttk.Scrollbar(self.preview_holder, orient="vertical",
                                       command=self.preview.yview)
        self.preview.configure(yscrollcommand=preview_scroll.set)
        self.preview.pack(side="left", fill="both", expand=True)
        preview_scroll.pack(side="right", fill="y")

    # ------------------------------------------------------------------ states

    def _show_empty_state(self) -> None:
        self.list_area.pack_forget()
        self.dropzone.pack(fill="both", expand=True, padx=26, pady=18)
        self.summary_var.set("")
        self.convert_button.state(["disabled"])

    def _show_list_state(self) -> None:
        self.dropzone.pack_forget()
        self.list_area.pack(fill="both", expand=True)
        self.convert_button.state(["!disabled"] if not self.running else ["disabled"])

    def _refresh_count(self) -> None:
        count = len(self.files)
        self.count_label.configure(text=f"{count} file{'' if count == 1 else 's'}")

    def open_preview(self) -> None:
        if not self.preview_open:
            self.panes.add(self.preview_holder, weight=2)
            self.preview_open = True

    def close_preview(self) -> None:
        if self.preview_open:
            self.panes.forget(self.preview_holder)
            self.preview_open = False

    def show_about(self) -> None:
        AboutDialog(self.root, __version__, markitdown_version(),
                    ocr_engine=getattr(available_engine(), "name", None))

    # ------------------------------------------------------------------ input

    def _enable_drag_drop(self) -> None:
        """Register drag and drop, degrading quietly when tkdnd is unavailable.

        Importing tkinterdnd2 patches drop_target_register onto every widget, so
        the attribute exists even when the tkdnd Tcl package never loaded. Only
        calling it reveals the truth, so the call itself is the test.
        """
        if DND_FILES is None:
            return
        for widget in (self.dropzone, self.tree):
            if not hasattr(widget, "drop_target_register"):
                continue
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
                widget.dnd_bind("<<DropEnter>>", lambda _e: self.dropzone.set_active(True))
                widget.dnd_bind("<<DropLeave>>", lambda _e: self.dropzone.set_active(False))
            except tk.TclError:
                return

    def _bind_shortcuts(self) -> None:
        modifier = "Command" if platform.system() == "Darwin" else "Control"
        self.root.bind(f"<{modifier}-o>", lambda _e: self.add_files())
        self.root.bind(f"<{modifier}-Return>", lambda _e: self.start_conversion())
        self.root.bind(f"<{modifier}-a>", self._select_all_if_tree_focused)

    def _select_all_if_tree_focused(self, _event: tk.Event) -> str | None:
        if self.root.focus_get() == self.tree:
            self.tree.selection_set(self.tree.get_children())
            return "break"
        return None

    def _on_drop(self, event: tk.Event) -> None:
        self.dropzone.set_active(False)
        self._add_paths(list(self.root.tk.splitlist(event.data)))

    def add_files(self) -> None:
        patterns = " ".join(f"*{extension}" for extension in sorted(SUPPORTED_EXTENSIONS))
        paths = filedialog.askopenfilenames(
            title="Choose files",
            filetypes=[("Supported documents", patterns), ("All files", "*.*")])
        self._add_paths(paths)

    def add_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose a folder")
        if path:
            self._add_paths([path])

    def _add_paths(self, paths) -> None:
        accepted, rejected = discover_files(paths)
        for path in accepted:
            key = os.path.normcase(str(path))
            if key in self.path_to_item:
                continue
            item = f"file-{len(self.files) + 1}"
            while item in self.files:
                item += "x"
            self.files[item] = path
            self.path_to_item[key] = item
            self.tree.insert("", "end", iid=item, values=(path.name, "Ready"))
        if not self.files:
            if rejected:
                messagebox.showinfo(
                    "Nothing to convert",
                    "None of those files are formats MarkItDown can read.")
            return
        self._show_list_state()
        self._refresh_count()
        if rejected:
            self.summary_var.set(
                f"{len(rejected)} unsupported item{'' if len(rejected) == 1 else 's'} skipped")
        else:
            self.summary_var.set("")
        self.progress_var.set(0)

    def remove_selected(self) -> None:
        if self.running:
            return
        for item in self.tree.selection():
            path = self.files.pop(item, None)
            if path:
                self.path_to_item.pop(os.path.normcase(str(path)), None)
                self.outputs.pop(item, None)
            self.tree.delete(item)
        self.close_preview()
        if self.files:
            self._refresh_count()
        else:
            self._show_empty_state()

    def clear_files(self) -> None:
        if self.running:
            return
        self.tree.delete(*self.tree.get_children())
        self.files.clear()
        self.path_to_item.clear()
        self.outputs.clear()
        self.progress_var.set(0)
        self.close_preview()
        self._show_empty_state()

    def choose_output(self) -> None:
        path = filedialog.askdirectory(title="Choose output folder",
                                       initialdir=self.output_var.get())
        if path:
            self.output_dir = Path(path)
            self.output_var.set(path)
            self.output_label_var.set(_shorten(self.output_dir))

    # ------------------------------------------------------------------ convert

    def start_conversion(self) -> None:
        if self.running or self.updating or not self.files:
            return
        output_dir = Path(self.output_var.get().strip()).expanduser()
        if output_dir.exists() and not output_dir.is_dir():
            messagebox.showerror("Cannot save there",
                                 "That path is a file, not a folder.")
            return

        self.running = True
        self.cancel_event.clear()
        self.outputs.clear()
        self.progress_var.set(0)
        self.close_preview()
        self._set_running(True)
        for item in self.tree.get_children():
            self.tree.item(item, values=(self.files[item].name, "Waiting"), tags=("waiting",))
        sources = list(self.files.values())
        self.summary_var.set(f"Converting {len(sources)} file{'' if len(sources) == 1 else 's'}…")

        threading.Thread(
            target=self._convert_worker,
            args=(sources, output_dir, self.overwrite_var.get()),
            daemon=True,
        ).start()

    def _convert_worker(self, sources: list[Path], output_dir: Path, overwrite: bool) -> None:
        try:
            from markitdown_desktop import settings as settings_module

            data = settings_module.load()
            mode = mode_from_settings(data)
            engine = available_engine() if mode != "never" else None
            converter = OcrFallbackConverter(
                MicrosoftMarkItDownConverter(), engine,
                mode=mode, language=data.get("ocr_language", "eng"),
            )

            # convert_files reports one file at a time, so OCR use is tallied as
            # each result lands rather than inferred from the finished batch.
            tally = {"files": 0, "pages": 0}

            def on_progress(count: int, total: int, result) -> None:
                if converter.last_pages:
                    tally["files"] += 1
                    tally["pages"] += converter.last_pages
                self.events.put(("progress", count, total, result))

            results = convert_files(
                sources, output_dir, converter, overwrite=overwrite,
                cancel_event=self.cancel_event,
                progress=on_progress,
            )
            self.ocr_note = usage_summary(
                files=tally["files"], pages=tally["pages"],
                engine=getattr(engine, "name", "OCR"),
            )
            self.events.put(("done", results, len(sources)))
        except Exception as exc:
            self.events.put(("fatal", str(exc)))

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    self._apply_result(event[1], event[2], event[3])
                elif kind == "done":
                    self._finish(event[1], event[2])
                elif kind == "fatal":
                    self._fatal(event[1])
                elif kind == "update_result":
                    self._on_update_result(event[1], event[2])
                elif kind == "update_progress":
                    if self.update_progress:
                        self.update_progress.set_progress(event[1], event[2])
                elif kind == "update_stage":
                    if self.update_progress:
                        self.update_progress.start_indeterminate(event[1])
                elif kind == "update_ready":
                    self._launch_applier(event[1], event[2])
                elif kind == "update_failed":
                    self._update_failed(event[1])
                elif kind == "update_unavailable":
                    self._update_unavailable(event[1], event[2])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _apply_result(self, current: int, total: int, result: ConversionResult) -> None:
        item = self.path_to_item.get(os.path.normcase(str(result.source)))
        if item:
            self.tree.item(
                item,
                values=(result.source.name, "Converted" if result.ok else "Failed"),
                tags=("success" if result.ok else "error",))
            if result.output:
                self.outputs[item] = result.output
        self.progress_var.set(current / total * 100 if total else 0)
        self.summary_var.set(f"Converting {current} of {total} — {result.source.name}")

    def _finish(self, results: list[ConversionResult], requested: int) -> None:
        self._set_running(False)
        succeeded = sum(r.ok for r in results)
        failed = len(results) - succeeded
        if len(results) < requested:
            summary = f"Cancelled — {succeeded} converted, {failed} failed"
        elif failed:
            summary = f"{succeeded} converted, {failed} failed"
        else:
            summary = (
                f"{succeeded} file{'' if succeeded == 1 else 's'} converted to "
                f"{_shorten(Path(self.output_var.get()), 34)}")
        # Silent OCR would leave the user wondering where the text came from.
        if self.ocr_note:
            summary = f"{summary}  ·  {self.ocr_note}"
        self.summary_var.set(summary)
        first = next((i for i in self.tree.get_children() if i in self.outputs), None)
        if first:
            self.tree.selection_set(first)
            self.tree.focus(first)
            self._show_selected_preview()
        if failed:
            detail = "\n".join(f"• {r.source.name} — {r.message}" for r in results if not r.ok)
            messagebox.showwarning("Some files could not be converted", detail[:1800])

    def _fatal(self, message: str) -> None:
        self._set_running(False)
        self.summary_var.set("Conversion could not start")
        messagebox.showerror(APP_NAME, message)

    def _set_running(self, running: bool) -> None:
        self.running = running
        if running:
            self.convert_button.state(["disabled"])
            self.cancel_button.pack(side="right", padx=(0, 10))
            self.progress.pack(fill="x", pady=(6, 0))
            self.remove_button.state(["disabled"])
        else:
            self.convert_button.state(["!disabled"] if self.files else ["disabled"])
            self.cancel_button.pack_forget()
            self.progress.pack_forget()
            self.remove_button.state(["!disabled"])

    def cancel(self) -> None:
        if self.running:
            self.cancel_event.set()
            self.cancel_button.state(["disabled"])
            self.summary_var.set("Stopping after the current file…")

    # ------------------------------------------------------------------ preview

    def _show_selected_preview(self, _event: tk.Event | None = None) -> None:
        selected = self.tree.selection()
        if len(selected) != 1 or selected[0] not in self.outputs:
            return
        output = self.outputs[selected[0]]
        try:
            text = output.read_text(encoding="utf-8")
        except OSError as exc:
            self._set_preview(f"Unable to read this file: {exc}")
            self.open_preview()
            return
        limit = 250_000
        suffix = "\n\n[Preview truncated — open the file to read the rest.]" if len(text) > limit else ""
        self.preview_title.configure(text=output.name.upper())
        self._set_preview(text[:limit] + suffix)
        self.open_preview()

    def _set_preview(self, text: str) -> None:
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def copy_preview(self) -> None:
        selected = self.tree.selection()
        if len(selected) != 1 or selected[0] not in self.outputs:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.outputs[selected[0]].read_text(encoding="utf-8"))
            self.summary_var.set(f"Copied {self.outputs[selected[0]].name}")
        except OSError as exc:
            messagebox.showerror("Could not copy", str(exc))

    def open_output(self) -> None:
        path = Path(self.output_var.get()).expanduser()
        if not path.exists():
            messagebox.showinfo("Not created yet",
                                "This folder appears after the first conversion.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror("Could not open folder", str(exc))

    # ------------------------------------------------------------------ updates

    def check_updates_on_start(self) -> None:
        self._report_previous_failure()
        if not settings.load().get("auto_check", True):
            return
        self._start_update_check(manual=False)

    def check_updates_manually(self) -> None:
        if self.updating:
            return
        self.summary_var.set("Checking for updates…")
        self._start_update_check(manual=True)

    def _start_update_check(self, *, manual: bool) -> None:
        threading.Thread(target=self._update_check_worker, args=(manual,), daemon=True).start()

    def _update_check_worker(self, manual: bool) -> None:
        data = settings.load()
        skipped = None if manual else data.get("skipped_version")
        problems: list[str] = []
        info = updater.check_for_update(__version__, skipped_version=skipped,
                                        on_error=problems.append)
        settings.update(last_check=settings.utc_now())
        if info is None and problems:
            self.events.put(("update_unavailable", problems[0], manual))
            return
        self.events.put(("update_result", info, manual))

    def _report_previous_failure(self) -> None:
        error_file = INSTALL_ROOT / ".update" / "last_error.txt"
        try:
            message = error_file.read_text(encoding="utf-8").strip()
        except OSError:
            return
        error_file.unlink(missing_ok=True)
        if message:
            messagebox.showwarning("The last update was not installed", message[:1500])

    def _on_update_result(self, info, manual: bool) -> None:
        if info is None:
            if manual:
                self.summary_var.set(f"You are up to date (v{__version__})")
                messagebox.showinfo("Up to date", f"{APP_NAME} {__version__} is the latest version.")
            return
        if self.running:
            self.summary_var.set(f"Version {info.version} is available — finish converting first")
            return
        choice = UpdateAvailableDialog(self.root, __version__, info).choice
        if choice == "skip":
            settings.update(skipped_version=info.version)
            self.summary_var.set(f"Version {info.version} skipped")
        elif choice == "update":
            self._begin_update(info)

    def _update_unavailable(self, reason: str, manual: bool) -> None:
        if not manual:
            return
        self.summary_var.set("Could not check for updates")
        messagebox.showwarning("Could not check for updates", reason)

    def _begin_update(self, info) -> None:
        self.updating = True
        self.convert_button.state(["disabled"])
        cancel_event = threading.Event()
        self.update_progress = UpdateProgressDialog(self.root, cancel_event)
        threading.Thread(target=self._update_download_worker,
                         args=(info, cancel_event), daemon=True).start()

    def _update_download_worker(self, info, cancel_event: threading.Event) -> None:
        work_dir = INSTALL_ROOT / ".update"
        archive = work_dir / info.asset_name
        try:
            updater.download_asset(
                info.asset_url, archive, expected_size=info.size, cancel_event=cancel_event,
                progress=lambda d, t: self.events.put(("update_progress", d, t)))
            self.events.put(("update_stage", "Verifying download…"))
            checksums = updater.parse_checksums(updater.fetch_text(info.checksums_url))
            updater.verify_sha256(archive, checksums.get(info.asset_name, ""))
            self.events.put(("update_stage", "Preparing the new version…"))
            tree = updater.stage_archive(archive, work_dir / "staging" / info.version)
            updater.validate_tree(tree)
            archive.unlink(missing_ok=True)
            self.events.put(("update_ready", tree, info))
        except updater.UpdateError as exc:
            archive.unlink(missing_ok=True)
            self.events.put(("update_failed", str(exc)))
        except Exception as exc:
            archive.unlink(missing_ok=True)
            self.events.put(("update_failed", f"The update could not be prepared: {exc}"))

    def _update_failed(self, message: str) -> None:
        self.updating = False
        if self.update_progress:
            self.update_progress.close()
            self.update_progress = None
        self.convert_button.state(["!disabled"] if self.files else ["disabled"])
        if message == "Cancelled":
            self.summary_var.set("Update cancelled")
            return
        self.summary_var.set("Update could not be installed")
        messagebox.showerror("Update failed", message[:1500])

    def _launch_applier(self, tree: Path, info) -> None:
        if self.update_progress:
            self.update_progress.start_indeterminate("Installing the update…")
        try:
            work_dir = INSTALL_ROOT / ".update"
            applier = work_dir / "apply_update.py"
            shutil.copyfile(INSTALL_ROOT / "markitdown_desktop" / "apply_update.py", applier)
            pending = {
                "version": info.version,
                "previous_version": __version__,
                "staging": str(tree.relative_to(INSTALL_ROOT)),
                "backup": f".update/backup/{__version__}",
                "parent_pid": os.getpid(),
                "requirements_changed": updater.requirements_changed(INSTALL_ROOT, tree),
                "created": settings.utc_now(),
                "python": _venv_python(INSTALL_ROOT),
                "relaunch": [_venv_python(INSTALL_ROOT, windowed=True),
                             str(INSTALL_ROOT / "app.py")],
            }
            (work_dir / "pending.json").write_text(json.dumps(pending, indent=2), encoding="utf-8")
            kwargs: dict = {"close_fds": True}
            if sys.platform == "win32":
                kwargs["creationflags"] = 0x00000008 | 0x00000200
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen([_venv_python(INSTALL_ROOT), str(applier), str(INSTALL_ROOT)], **kwargs)
        except Exception as exc:
            self._update_failed(f"The update could not be started: {exc}")
            return
        self.root.destroy()


def main() -> None:
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    app = App(root)
    root.after(400, app.check_updates_on_start)
    root.mainloop()


if __name__ == "__main__":
    main()
