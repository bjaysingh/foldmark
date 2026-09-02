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
    open_link,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None


APP_NAME = "MarkItDown Desktop"
INSTALL_ROOT = Path(__file__).resolve().parent


def markitdown_version() -> str:
    try:
        from importlib.metadata import version

        return version("markitdown")
    except Exception:
        return "not detected"


def _venv_python(root: Path, windowed: bool = False) -> str:
    """Prefer the app's own virtualenv interpreter over whatever launched us."""
    if sys.platform == "win32":
        name = "pythonw.exe" if windowed else "python.exe"
        candidate = root / ".venv" / "Scripts" / name
    else:
        candidate = root / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1080x760")
        self.root.minsize(860, 620)
        self.root.configure(bg=theme.CANVAS)

        theme.resolve_fonts(root)

        self.files: dict[str, Path] = {}
        self.path_to_item: dict[str, str] = {}
        self.outputs: dict[str, Path] = {}
        self.events: queue.Queue[tuple] = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False
        self.updating = False
        self.update_progress: UpdateProgressDialog | None = None
        self.output_var = tk.StringVar(value=str(Path.home() / "Documents" / "Markdown Output"))
        self.overwrite_var = tk.BooleanVar(value=False)
        self.summary_var = tk.StringVar(value="Add files or a folder to begin")
        self.progress_var = tk.DoubleVar(value=0)

        self._configure_styles()
        self._build_ui()
        self._enable_drag_drop()
        self._bind_shortcuts()
        self.root.after(100, self._poll_events)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=theme.CANVAS)
        style.configure("Card.TFrame", background=theme.CARD)
        style.configure("TLabel", background=theme.CANVAS, foreground=theme.TEXT, font=theme.ui(10))
        style.configure("Muted.TLabel", background=theme.CANVAS, foreground=theme.MUTED, font=theme.ui(9))
        style.configure("Card.TLabel", background=theme.CARD, foreground=theme.TEXT, font=theme.ui(10))
        style.configure("CardMuted.TLabel", background=theme.CARD, foreground=theme.MUTED, font=theme.ui(9))
        style.configure("Primary.TButton", font=theme.ui(10, "bold"), padding=(16, 9))
        style.map(
            "Primary.TButton",
            background=[("active", theme.BLUE_HOVER), ("!disabled", theme.BLUE)],
            foreground=[("!disabled", "white")],
        )
        style.configure("Secondary.TButton", font=theme.ui(9), padding=(11, 7))
        style.configure("Link.TButton", font=theme.ui(9), padding=(6, 4))
        style.configure("Treeview", font=theme.ui(9), rowheight=30, background=theme.CARD, fieldbackground=theme.CARD)
        style.configure("Treeview.Heading", font=theme.ui(9, "bold"))
        style.configure("Horizontal.TProgressbar", troughcolor=theme.TROUGH, background=theme.BLUE)

    def _build_ui(self) -> None:
        self._build_header()
        self._build_attribution_bar()

        body = ttk.Frame(self.root, padding=(22, 18, 22, 12))
        body.pack(fill="both", expand=True)

        toolbar = ttk.Frame(body)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="＋ Add files", style="Secondary.TButton", command=self.add_files).pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="＋ Add folder", style="Secondary.TButton", command=self.add_folder).pack(side="left", padx=(0, 8))
        self.remove_button = ttk.Button(toolbar, text="Remove", style="Secondary.TButton", command=self.remove_selected)
        self.remove_button.pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="Clear", style="Secondary.TButton", command=self.clear_files).pack(side="left")
        ttk.Label(toolbar, text="Drag and drop also works", style="Muted.TLabel").pack(side="right")

        panes = ttk.Panedwindow(body, orient="horizontal")
        panes.pack(fill="both", expand=True)

        left = ttk.Frame(panes, style="Card.TFrame", padding=12)
        right = ttk.Frame(panes, style="Card.TFrame", padding=12)
        panes.add(left, weight=3)
        panes.add(right, weight=2)

        ttk.Label(left, text="FILES", style="CardMuted.TLabel").pack(anchor="w", pady=(0, 8))
        tree_frame = ttk.Frame(left, style="Card.TFrame")
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("status", "name", "folder"), show="headings", selectmode="extended")
        self.tree.heading("status", text="Status")
        self.tree.heading("name", text="File")
        self.tree.heading("folder", text="Location")
        self.tree.column("status", width=90, minwidth=80, stretch=False)
        self.tree.column("name", width=210, minwidth=140)
        self.tree.column("folder", width=280, minwidth=140)
        self.tree.tag_configure("success", foreground=theme.SUCCESS)
        self.tree.tag_configure("error", foreground=theme.ERROR)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._show_selected_preview)
        self.tree.bind("<Delete>", lambda _event: self.remove_selected())

        preview_header = ttk.Frame(right, style="Card.TFrame")
        preview_header.pack(fill="x", pady=(0, 8))
        ttk.Label(preview_header, text="MARKDOWN PREVIEW", style="CardMuted.TLabel").pack(side="left")
        self.copy_button = ttk.Button(preview_header, text="Copy", style="Secondary.TButton", command=self.copy_preview, state="disabled")
        self.copy_button.pack(side="right")
        preview_frame = ttk.Frame(right, style="Card.TFrame")
        preview_frame.pack(fill="both", expand=True)
        self.preview = tk.Text(preview_frame, wrap="word", relief="flat", bg=theme.PREVIEW_BG, fg=theme.TEXT, padx=12, pady=12, font=theme.mono(9), state="disabled", undo=False)
        preview_scroll = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=preview_scroll.set)
        self.preview.pack(side="left", fill="both", expand=True)
        preview_scroll.pack(side="right", fill="y")
        self._set_preview("Converted Markdown will appear here.\n\nSelect a completed file to preview or copy it.")

        options = ttk.Frame(body, style="Card.TFrame", padding=12)
        options.pack(fill="x", pady=(12, 0))
        ttk.Label(options, text="Save to", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        output_entry = ttk.Entry(options, textvariable=self.output_var)
        output_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 0))
        ttk.Button(options, text="Browse…", style="Secondary.TButton", command=self.choose_output).grid(row=1, column=1, pady=(4, 0), padx=(0, 8))
        self.open_button = ttk.Button(options, text="Open folder", style="Secondary.TButton", command=self.open_output)
        self.open_button.grid(row=1, column=2, pady=(4, 0))
        ttk.Checkbutton(options, text="Replace existing files with the same name", variable=self.overwrite_var).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        options.columnconfigure(0, weight=1)

        footer = ttk.Frame(body)
        footer.pack(fill="x", pady=(12, 0))
        progress_area = ttk.Frame(footer)
        progress_area.pack(side="left", fill="x", expand=True, padx=(0, 18))
        ttk.Label(progress_area, textvariable=self.summary_var, style="Muted.TLabel").pack(anchor="w")
        self.progress = ttk.Progressbar(progress_area, variable=self.progress_var, maximum=100)
        self.progress.pack(fill="x", pady=(5, 0))
        self.cancel_button = ttk.Button(footer, text="Cancel", style="Secondary.TButton", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="right", padx=(0, 8))
        self.convert_button = ttk.Button(footer, text="Convert to Markdown", style="Primary.TButton", command=self.start_conversion)
        self.convert_button.pack(side="right")

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=theme.NAVY, height=96)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text=APP_NAME, bg=theme.NAVY, fg="white", font=theme.ui(22, "bold")).pack(anchor="w", padx=28, pady=(16, 0))

        # Attribution sits in the header so the MarkItDown dependency is stated
        # on screen from the first frame, not buried in a menu.
        credit = tk.Frame(header, bg=theme.NAVY)
        credit.pack(anchor="w", padx=29, pady=(2, 0))
        tk.Label(credit, text="Powered by", bg=theme.NAVY, fg=theme.HEADER_SUBTITLE, font=theme.ui(10)).pack(side="left")
        link_label(
            credit, "Microsoft MarkItDown", updater.MARKITDOWN_URL,
            background=theme.NAVY, foreground=theme.LINK_ON_NAVY, font=theme.ui(10, "bold"),
        ).pack(side="left", padx=(5, 5))
        tk.Label(
            credit, text="— documents converted to Markdown locally on your computer",
            bg=theme.NAVY, fg=theme.HEADER_SUBTITLE, font=theme.ui(10),
        ).pack(side="left")

    def _build_attribution_bar(self) -> None:
        bar = tk.Frame(self.root, bg=theme.CANVAS, height=34)
        bar.pack(side="bottom", fill="x")
        inner = tk.Frame(bar, bg=theme.CANVAS)
        inner.pack(fill="x", padx=22, pady=(0, 10))

        tk.Label(inner, text="Uses the open-source", bg=theme.CANVAS, fg=theme.MUTED, font=theme.ui(9)).pack(side="left")
        link_label(inner, "Microsoft MarkItDown", updater.MARKITDOWN_URL,
                   background=theme.CANVAS, foreground=theme.LINK, font=theme.ui(9)).pack(side="left", padx=4)
        tk.Label(inner, text="library · Not affiliated with Microsoft", bg=theme.CANVAS,
                 fg=theme.MUTED, font=theme.ui(9)).pack(side="left")

        ttk.Button(inner, text="About", style="Link.TButton", command=self.show_about).pack(side="right")
        ttk.Button(inner, text="Check for updates…", style="Link.TButton",
                   command=self.check_updates_manually).pack(side="right", padx=(0, 6))
        self.version_label = tk.Label(inner, text=f"v{__version__}", bg=theme.CANVAS,
                                      fg=theme.MUTED, font=theme.ui(9))
        self.version_label.pack(side="right", padx=(0, 12))

    def show_about(self) -> None:
        AboutDialog(self.root, __version__, markitdown_version())

    def _enable_drag_drop(self) -> None:
        """Register drag and drop, degrading quietly when tkdnd is unavailable.

        Importing tkinterdnd2 patches drop_target_register onto every widget, so
        the attribute exists even when the underlying tkdnd Tcl package failed
        to load - which happens when the root window was not created by
        TkinterDnD.Tk(), or when the platform binary is missing. Only calling it
        reveals the truth, so the call itself is the test. Drag and drop is a
        convenience; the Add files buttons do the same job.
        """
        if DND_FILES is None or not hasattr(self.tree, "drop_target_register"):
            return
        try:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind("<<Drop>>", self._on_drop)
        except tk.TclError:
            pass

    def _bind_shortcuts(self) -> None:
        modifier = "Command" if platform.system() == "Darwin" else "Control"
        self.root.bind(f"<{modifier}-o>", lambda _event: self.add_files())
        self.root.bind(f"<{modifier}-Return>", lambda _event: self.start_conversion())
        self.root.bind(f"<{modifier}-a>", self._select_all_if_tree_focused)

    def _select_all_if_tree_focused(self, _event: tk.Event) -> str | None:
        if self.root.focus_get() == self.tree:
            self.tree.selection_set(self.tree.get_children())
            return "break"
        return None

    def _on_drop(self, event: tk.Event) -> None:
        paths = list(self.root.tk.splitlist(event.data))
        self._add_paths(paths)

    def add_files(self) -> None:
        patterns = " ".join(f"*{extension}" for extension in sorted(SUPPORTED_EXTENSIONS))
        paths = filedialog.askopenfilenames(title="Choose files", filetypes=[("Supported files", patterns), ("All files", "*.*")])
        self._add_paths(paths)

    def add_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose a folder")
        if path:
            self._add_paths([path])

    def _add_paths(self, paths: list[str] | tuple[str, ...]) -> None:
        accepted, rejected = discover_files(paths)
        added = 0
        for path in accepted:
            key = os.path.normcase(str(path))
            if key in self.path_to_item:
                continue
            item = f"file-{len(self.files) + 1}"
            while item in self.files:
                item += "x"
            self.files[item] = path
            self.path_to_item[key] = item
            self.tree.insert("", "end", iid=item, values=("Ready", path.name, str(path.parent)))
            added += 1
        count = len(self.files)
        self.summary_var.set(f"{count} file{'s' if count != 1 else ''} ready")
        if rejected and not accepted:
            messagebox.showinfo("No supported files", "The selected item does not contain a supported file.")
        elif rejected:
            self.summary_var.set(f"{count} ready · {len(rejected)} unsupported item{'s' if len(rejected) != 1 else ''} skipped")
        if added:
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
        self.summary_var.set(f"{len(self.files)} file{'s' if len(self.files) != 1 else ''} ready" if self.files else "Add files or a folder to begin")

    def clear_files(self) -> None:
        if self.running:
            return
        self.tree.delete(*self.tree.get_children())
        self.files.clear()
        self.path_to_item.clear()
        self.outputs.clear()
        self.progress_var.set(0)
        self.summary_var.set("Add files or a folder to begin")
        self._set_preview("Converted Markdown will appear here.\n\nSelect a completed file to preview or copy it.")

    def choose_output(self) -> None:
        path = filedialog.askdirectory(title="Choose output folder", initialdir=self.output_var.get())
        if path:
            self.output_var.set(path)

    def start_conversion(self) -> None:
        if self.running or self.updating:
            return
        if not self.files:
            messagebox.showinfo("Add files", "Choose at least one file or folder first.")
            return
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showinfo("Choose an output folder", "Select where the Markdown files should be saved.")
            return
        output_dir = Path(output_text).expanduser()
        if output_dir.exists() and not output_dir.is_dir():
            messagebox.showerror("Invalid output folder", "The output path points to a file, not a folder.")
            return

        self.running = True
        self.cancel_event.clear()
        self.outputs.clear()
        self.progress_var.set(0)
        self.convert_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.remove_button.configure(state="disabled")
        for item in self.tree.get_children():
            self.tree.item(item, values=("Waiting", self.files[item].name, str(self.files[item].parent)), tags=())
        sources = list(self.files.values())
        self.summary_var.set(f"Preparing {len(sources)} file{'s' if len(sources) != 1 else ''}…")

        worker = threading.Thread(
            target=self._convert_worker,
            args=(sources, output_dir, self.overwrite_var.get()),
            daemon=True,
        )
        worker.start()

    def _convert_worker(self, sources: list[Path], output_dir: Path, overwrite: bool) -> None:
        try:
            converter = MicrosoftMarkItDownConverter()
            results = convert_files(
                sources,
                output_dir,
                converter,
                overwrite=overwrite,
                cancel_event=self.cancel_event,
                progress=lambda current, total, result: self.events.put(("progress", current, total, result)),
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
                    _, current, total, result = event
                    self._apply_result(current, total, result)
                elif kind == "done":
                    _, results, requested = event
                    self._finish(results, requested)
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
            status = "Done" if result.ok else "Failed"
            tag = "success" if result.ok else "error"
            self.tree.item(item, values=(status, result.source.name, str(result.source.parent)), tags=(tag,))
            if result.output:
                self.outputs[item] = result.output
        self.progress_var.set(current / total * 100 if total else 0)
        self.summary_var.set(f"Converting {current} of {total}: {result.source.name}")

    def _finish(self, results: list[ConversionResult], requested: int) -> None:
        self._set_running(False)
        succeeded = sum(result.ok for result in results)
        failed = len(results) - succeeded
        cancelled = len(results) < requested
        if cancelled:
            self.summary_var.set(f"Cancelled · {succeeded} converted · {failed} failed")
        elif failed:
            self.summary_var.set(f"Finished · {succeeded} converted · {failed} failed")
        else:
            self.summary_var.set(f"Finished · {succeeded} file{'s' if succeeded != 1 else ''} converted")
        first_output = next((item for item in self.tree.get_children() if item in self.outputs), None)
        if first_output:
            self.tree.selection_set(first_output)
            self.tree.focus(first_output)
            self._show_selected_preview()
        if failed:
            details = "\n".join(f"• {r.source.name}: {r.message}" for r in results if not r.ok)
            messagebox.showwarning("Some files could not be converted", details[:1800])

    def _fatal(self, message: str) -> None:
        self._set_running(False)
        self.summary_var.set("Conversion could not start")
        messagebox.showerror(APP_NAME, message)

    def _set_running(self, running: bool) -> None:
        self.running = running
        self.convert_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        self.remove_button.configure(state="disabled" if running else "normal")

    def cancel(self) -> None:
        if self.running:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.summary_var.set("Stopping after the current file…")

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
        # A manual check ignores a previously skipped version: asking explicitly
        # is a clear signal the user wants to know either way.
        skipped = None if manual else data.get("skipped_version")
        problems: list[str] = []
        info = updater.check_for_update(
            __version__, skipped_version=skipped, on_error=problems.append
        )
        settings.update(last_check=settings.utc_now())
        if info is None and problems:
            # Silence is fine for the launch check, but a check the user asked
            # for must never answer "up to date" when it never reached GitHub.
            self.events.put(("update_unavailable", problems[0], manual))
            return
        self.events.put(("update_result", info, manual))

    def _report_previous_failure(self) -> None:
        """A rolled-back update leaves a note behind; show it once, then clear it."""
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
                messagebox.showinfo("Up to date", f"MarkItDown Desktop {__version__} is the latest version.")
            return
        if self.running:
            self.summary_var.set(f"Version {info.version} is available — finish converting, then check again")
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
        self.convert_button.configure(state="disabled")
        cancel_event = threading.Event()
        self.update_progress = UpdateProgressDialog(self.root, cancel_event)
        threading.Thread(
            target=self._update_download_worker, args=(info, cancel_event), daemon=True
        ).start()

    def _update_download_worker(self, info, cancel_event: threading.Event) -> None:
        work_dir = INSTALL_ROOT / ".update"
        archive = work_dir / info.asset_name
        try:
            updater.download_asset(
                info.asset_url, archive, expected_size=info.size, cancel_event=cancel_event,
                progress=lambda done, total: self.events.put(("update_progress", done, total)),
            )
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
        self.convert_button.configure(state="normal")
        if message == "Cancelled":
            self.summary_var.set("Update cancelled")
            return
        self.summary_var.set("Update could not be installed")
        messagebox.showerror("Update failed", message[:1500])

    def _launch_applier(self, tree: Path, info) -> None:
        """Hand off to a detached helper, then quit so the swap can proceed."""
        if self.update_progress:
            self.update_progress.start_indeterminate("Installing the update…")
        try:
            work_dir = INSTALL_ROOT / ".update"
            applier = work_dir / "apply_update.py"
            shutil.copyfile(Path(__file__).resolve().parent / "markitdown_desktop" / "apply_update.py", applier)

            pending = {
                "version": info.version,
                "previous_version": __version__,
                "staging": str(tree.relative_to(INSTALL_ROOT)),
                "backup": f".update/backup/{__version__}",
                "parent_pid": os.getpid(),
                "requirements_changed": updater.requirements_changed(INSTALL_ROOT, tree),
                "created": settings.utc_now(),
                "python": _venv_python(INSTALL_ROOT),
                "relaunch": [_venv_python(INSTALL_ROOT, windowed=True), str(INSTALL_ROOT / "app.py")],
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

    # ------------------------------------------------------------------ preview

    def _show_selected_preview(self, _event: tk.Event | None = None) -> None:
        selected = self.tree.selection()
        if len(selected) != 1 or selected[0] not in self.outputs:
            self.copy_button.configure(state="disabled")
            return
        try:
            text = self.outputs[selected[0]].read_text(encoding="utf-8")
        except OSError as exc:
            self._set_preview(f"Unable to read preview: {exc}")
            self.copy_button.configure(state="disabled")
            return
        limit = 250_000
        suffix = "\n\n[Preview truncated — open the Markdown file to see the rest.]" if len(text) > limit else ""
        self._set_preview(text[:limit] + suffix)
        self.copy_button.configure(state="normal")

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
            text = self.outputs[selected[0]].read_text(encoding="utf-8")
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.summary_var.set(f"Copied {self.outputs[selected[0]].name} to clipboard")
        except OSError as exc:
            messagebox.showerror("Could not copy", str(exc))

    def open_output(self) -> None:
        path = Path(self.output_var.get()).expanduser()
        if not path.exists():
            messagebox.showinfo("Output folder", "The output folder will be created after the first conversion.")
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


def main() -> None:
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    app = App(root)
    root.after(400, app.check_updates_on_start)
    root.mainloop()


if __name__ == "__main__":
    main()
