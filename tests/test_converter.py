from pathlib import Path
import tempfile
import threading
import unittest

from markitdown_desktop.converter import convert_files, discover_files


class FakeConverter:
    def convert(self, source: Path) -> str:
        if source.name.startswith("bad"):
            raise ValueError("deliberate failure")
        if source.name.startswith("empty"):
            return "   \n\n"
        return f"# {source.stem}\n\n{source.read_text(encoding='utf-8')}"


class ConverterTests(unittest.TestCase):
    def test_discovery_is_recursive_unique_and_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            nested = root / "nested"
            nested.mkdir()
            one = root / "one.txt"
            two = nested / "two.csv"
            unsupported = root / "raw.bin"
            one.write_text("one", encoding="utf-8")
            two.write_text("two", encoding="utf-8")
            unsupported.write_bytes(b"raw")
            accepted, rejected = discover_files([root, one])
            self.assertEqual({one.resolve(), two.resolve()}, set(accepted))
            self.assertEqual([unsupported.resolve()], rejected)

    def test_batch_conversion_survives_individual_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "out"
            good = root / "good.txt"
            bad = root / "bad.txt"
            good.write_text("hello", encoding="utf-8")
            bad.write_text("no", encoding="utf-8")
            results = convert_files([good, bad], output, FakeConverter())
            self.assertTrue(results[0].ok)
            self.assertEqual("# good\n\nhello", (output / "good.md").read_text(encoding="utf-8"))
            self.assertFalse(results[1].ok)
            self.assertFalse((output / "bad.md").exists())

    def test_name_collisions_get_safe_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first_dir = root / "a"
            second_dir = root / "b"
            output = root / "out"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "report.txt"
            second = second_dir / "report.csv"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            results = convert_files([first, second], output, FakeConverter())
            self.assertEqual(["report.md", "report-2.md"], [r.output.name for r in results if r.output])

    def test_markdown_input_is_never_overwritten_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "notes.md"
            source.write_text("original", encoding="utf-8")
            results = convert_files([source], root, FakeConverter(), overwrite=True)
            self.assertEqual("original", source.read_text(encoding="utf-8"))
            self.assertEqual("notes-converted.md", results[0].output.name)

    def test_empty_conversion_is_reported_as_a_failure(self) -> None:
        """MarkItDown returns "" for a photo with no OCR rather than raising.

        Writing a 0-byte .md and calling it a success hides that from the user.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "empty-image.txt"
            source.write_text("ignored", encoding="utf-8")
            output = root / "out"
            results = convert_files([source], output, FakeConverter())
            self.assertFalse(results[0].ok)
            self.assertIn("No text could be extracted", results[0].message)
            self.assertIsNone(results[0].output)
            self.assertFalse((output / "empty-image.md").exists())

    def test_cancel_stops_before_first_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "one.txt"
            source.write_text("one", encoding="utf-8")
            cancel = threading.Event()
            cancel.set()
            results = convert_files([source], root / "out", FakeConverter(), cancel_event=cancel)
            self.assertEqual([], results)


if __name__ == "__main__":
    unittest.main()
