"""Window construction tests.

Skipped wherever Tk cannot open a display, so a headless CI run stays green.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def tk_available() -> bool:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.destroy()
        return True
    except Exception:
        return False


@unittest.skipUnless(tk_available(), "no display available for Tk")
class WindowTests(unittest.TestCase):
    def setUp(self) -> None:
        import tkinter as tk

        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_window_builds_on_a_plain_root_without_tkdnd(self) -> None:
        """Importing tkinterdnd2 patches drop_target_register onto every widget,
        so the attribute exists even when the tkdnd Tcl package never loaded.
        Building on a plain Tk root used to raise TclError and abort startup.
        """
        import app as appmod

        window = appmod.App(self.root)
        self.assertIsNotNone(window.tree)

    def test_the_ui_states_the_markitdown_dependency_with_a_working_link(self) -> None:
        import app as appmod
        from markitdown_desktop import updater

        appmod.App(self.root)

        links = []
        def walk(widget):
            for child in widget.winfo_children():
                try:
                    text = child.cget("text")
                    cursor = child.cget("cursor")
                except self.tk.TclError:
                    text, cursor = "", ""
                if isinstance(text, str) and "Microsoft MarkItDown" in text:
                    links.append((text, cursor, bool(child.bind("<Button-1>"))))
                walk(child)
        walk(self.root)

        self.assertTrue(links, "the UI must name Microsoft MarkItDown on screen")
        for text, cursor, clickable in links:
            self.assertEqual("hand2", cursor)
            self.assertTrue(clickable, f"{text!r} must open the source link when clicked")
        self.assertEqual("https://github.com/microsoft/markitdown", updater.MARKITDOWN_URL)


if __name__ == "__main__":
    unittest.main()
