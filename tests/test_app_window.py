"""Window construction and layout checks.

Each check runs the window in a **subprocess**. Tk 9.0 on macOS segfaults when
a suite builds and tears down windows repeatedly in one interpreter, which took
the whole run down with exit 139. Isolating each probe means a crash surfaces
as a failed assertion naming the platform problem, rather than killing every
other test in the process.

The probe skips cleanly where Tk cannot open a display, so headless CI stays
green.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

PROBE = r'''
import json, sys, tkinter as tk
sys.path.insert(0, %(repo)r)

try:
    root = tk.Tk()
except Exception as exc:
    print(json.dumps({"skip": str(exc)}))
    raise SystemExit(0)

import app as appmod

# The window must stay mapped: winfo_ismapped() reports False for every
# child of a withdrawn toplevel, which would make these checks meaningless.
window = appmod.App(root)
out = {"skip": None}

sample = %(sample)r
if sample:
    window._add_paths([sample])

root.geometry("%(geometry)s")
root.update_idletasks()

def facts(widget):
    return {"mapped": bool(widget.winfo_ismapped()), "height": widget.winfo_height()}

out["convert"] = facts(window.convert_button)
out["convert_state"] = list(window.convert_button.state())
out["dropzone"] = facts(window.dropzone)
out["list_area"] = facts(window.list_area)
out["file_count"] = len(window.files)
out["count_label"] = window.count_label.cget("text")
out["preview_open"] = window.preview_open
out["window_height"] = root.winfo_height()

links = []
def walk(widget):
    for child in widget.winfo_children():
        try:
            text = child.cget("text")
        except Exception:
            text = ""
        if isinstance(text, str) and "Microsoft MarkItDown" in text:
            links.append({"text": text,
                          "cursor": str(child.cget("cursor")),
                          "clickable": bool(child.bind("<Button-1>"))})
        walk(child)
walk(root)
out["links"] = links

print(json.dumps(out))
'''


def probe(geometry: str = "980x680", sample: str | None = None) -> dict:
    """Build the window in a fresh interpreter and report what is on screen."""
    script = PROBE % {"repo": str(REPO), "geometry": geometry, "sample": sample}
    result = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True, timeout=120)
    line = next((l for l in reversed(result.stdout.splitlines()) if l.startswith("{")), "")
    if not line:
        raise AssertionError(
            f"the window probe produced no result (exit {result.returncode}). "
            f"stderr: {result.stderr[-600:]}")
    return json.loads(line)


class WindowTests(unittest.TestCase):
    def check(self, **kwargs) -> dict:
        data = probe(**kwargs)
        if data.get("skip"):
            self.skipTest(f"Tk unavailable: {data['skip']}")
        return data

    def test_the_primary_action_is_on_screen_at_every_supported_size(self) -> None:
        """Convert must never be dropped by the packer.

        Tk refuses to map children it cannot fit rather than clipping them. When
        the action row was the last child of an expanding body, a short window
        left Convert, Cancel and the progress bar unmapped - the primary action
        simply absent, with only the keyboard shortcut still working. The bars
        now pack from the bottom edge first, reserving space before the content
        area gets any.
        """
        for geometry in ("980x680", "720x520", "720x420", "600x340"):
            with self.subTest(size=geometry):
                data = self.check(geometry=geometry)
                self.assertTrue(data["convert"]["mapped"],
                                f"Convert is not on screen at {geometry}")
                self.assertGreater(data["convert"]["height"], 4,
                                   f"Convert has collapsed at {geometry}")

    def test_the_empty_state_offers_the_drop_zone_and_disables_convert(self) -> None:
        data = self.check()
        self.assertTrue(data["dropzone"]["mapped"])
        self.assertFalse(data["list_area"]["mapped"])
        self.assertIn("disabled", data["convert_state"],
                      "Convert must be inactive with nothing to convert")
        self.assertFalse(data["preview_open"],
                         "the preview pane must stay closed until there is a result")

    def test_adding_a_file_swaps_the_drop_zone_for_the_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "notes.txt"
            source.write_text("hello", encoding="utf-8")
            data = self.check(sample=str(source))
        self.assertFalse(data["dropzone"]["mapped"])
        self.assertTrue(data["list_area"]["mapped"])
        self.assertNotIn("disabled", data["convert_state"])
        self.assertEqual(1, data["file_count"])
        self.assertIn("1 file", data["count_label"])

    def test_the_ui_states_the_markitdown_dependency_with_working_links(self) -> None:
        from markitdown_desktop import updater

        data = self.check()
        self.assertTrue(data["links"], "the UI must name Microsoft MarkItDown on screen")
        for link in data["links"]:
            self.assertEqual("hand2", link["cursor"], link["text"])
            self.assertTrue(link["clickable"],
                            f"{link['text']!r} must open the source link when clicked")
        self.assertEqual("https://github.com/microsoft/markitdown", updater.MARKITDOWN_URL)


if __name__ == "__main__":
    unittest.main()
