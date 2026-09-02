"""Window construction and layout tests.

Skipped wherever Tk cannot open a display, so a headless CI run stays green.

One Tk root is created for the whole class and each test builds the window on a
fresh Toplevel. Creating and destroying multiple Tk *roots* inside a single
process is unstable on macOS - it segfaulted the suite - while Toplevels under
one root are fine.
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
    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        cls.tk = tk
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:
            pass

    def build(self):
        import app as appmod

        window = self.tk.Toplevel(self.root)
        self.addCleanup(lambda: window.destroy())
        return appmod.App(window), window

    def widgets_with_text(self, root, needle: str) -> list:
        found = []

        def walk(widget):
            for child in widget.winfo_children():
                try:
                    text = child.cget("text")
                except (self.tk.TclError, AttributeError):
                    text = ""
                if isinstance(text, str) and needle in text:
                    found.append(child)
                walk(child)

        walk(root)
        return found

    def test_window_builds_on_a_plain_root_without_tkdnd(self) -> None:
        """Importing tkinterdnd2 patches drop_target_register onto every widget,
        so the attribute exists even when the tkdnd Tcl package never loaded.
        Building without it used to raise TclError and abort startup.
        """
        window, _ = self.build()
        self.assertIsNotNone(window.tree)
        self.assertIsNotNone(window.dropzone)

    def test_the_primary_action_is_on_screen_at_every_supported_size(self) -> None:
        """The Convert button must never be dropped by the packer.

        Tk refuses to map children it cannot fit rather than clipping them. When
        the action row was the last child of an expanding body, a short window
        left Convert, Cancel and the progress bar unmapped - the primary action
        simply absent. The bars now pack from the bottom edge first, reserving
        their space ahead of the content area.
        """
        window, toplevel = self.build()
        for width, height in ((980, 680), (720, 520), (720, 420), (600, 340)):
            with self.subTest(size=f"{width}x{height}"):
                toplevel.geometry(f"{width}x{height}")
                toplevel.update_idletasks()
                button = window.convert_button
                self.assertTrue(button.winfo_ismapped(),
                                f"Convert is not mapped at {width}x{height}")
                self.assertGreater(button.winfo_height(), 4,
                                   f"Convert collapsed at {width}x{height}")

    def test_the_empty_state_shows_the_drop_zone_and_no_file_list(self) -> None:
        window, toplevel = self.build()
        toplevel.update_idletasks()
        self.assertTrue(window.dropzone.winfo_ismapped())
        self.assertFalse(window.list_area.winfo_ismapped())
        self.assertIn("disabled", window.convert_button.state(),
                      "Convert must be inactive with nothing to convert")

    def test_adding_files_swaps_the_drop_zone_for_the_list(self) -> None:
        import tempfile

        window, toplevel = self.build()
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "notes.txt"
            source.write_text("hello", encoding="utf-8")
            window._add_paths([str(source)])
            toplevel.update_idletasks()

            self.assertFalse(window.dropzone.winfo_ismapped())
            self.assertTrue(window.list_area.winfo_ismapped())
            self.assertNotIn("disabled", window.convert_button.state())
            self.assertEqual(1, len(window.files))
            self.assertIn("1 file", window.count_label.cget("text"))

            window.clear_files()
            toplevel.update_idletasks()
            self.assertTrue(window.dropzone.winfo_ismapped(),
                            "clearing must return to the empty state")

    def test_the_preview_pane_is_absent_until_there_is_something_to_show(self) -> None:
        window, _ = self.build()
        self.assertFalse(window.preview_open)
        window.open_preview()
        self.assertTrue(window.preview_open)
        window.close_preview()
        self.assertFalse(window.preview_open)

    def test_the_ui_states_the_markitdown_dependency_with_a_working_link(self) -> None:
        from markitdown_desktop import updater

        _, toplevel = self.build()
        links = self.widgets_with_text(toplevel, "Microsoft MarkItDown")
        self.assertTrue(links, "the UI must name Microsoft MarkItDown on screen")
        for label in links:
            self.assertEqual("hand2", label.cget("cursor"))
            self.assertTrue(label.bind("<Button-1>"),
                            "the credit must open the source link when clicked")
        self.assertEqual("https://github.com/microsoft/markitdown", updater.MARKITDOWN_URL)


if __name__ == "__main__":
    unittest.main()
