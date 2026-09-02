from pathlib import Path
import io
import json
import tempfile
import unittest

from markitdown_desktop import cli


class FakeConverter:
    def convert(self, source: Path) -> str:
        if source.name.startswith("bad"):
            raise ValueError("deliberate failure")
        return f"# {source.stem}\n\nconverted"


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, converter_factory=FakeConverter, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


class ConvertCommandTests(unittest.TestCase):
    def test_writes_markdown_and_reports_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "note.txt"
            source.write_text("hello", encoding="utf-8")
            out_dir = root / "out"
            code, output, _ = run(["convert", str(source), "--out", str(out_dir), "--json"])
            self.assertEqual(0, code)
            payload = json.loads(output)
            self.assertEqual(1, len(payload["results"]))
            self.assertTrue(payload["results"][0]["ok"])
            self.assertEqual((out_dir / "note.md").read_text(encoding="utf-8"), "# note\n\nconverted")

    def test_partial_failure_exits_one_but_still_reports_each_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "good.txt").write_text("x", encoding="utf-8")
            (root / "bad.txt").write_text("x", encoding="utf-8")
            code, output, _ = run(
                ["convert", str(root / "good.txt"), str(root / "bad.txt"),
                 "--out", str(root / "out"), "--json"]
            )
            self.assertEqual(1, code)
            results = json.loads(output)["results"]
            self.assertEqual([True, False], [r["ok"] for r in results])
            self.assertIn("deliberate failure", results[1]["message"])

    def test_stdout_mode_emits_markdown_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "note.txt"
            source.write_text("hello", encoding="utf-8")
            code, output, _ = run(["convert", str(source), "--stdout"])
            self.assertEqual(0, code)
            self.assertEqual("# note\n\nconverted", output.strip())
            self.assertEqual([source], sorted(root.iterdir()))

    def test_stdout_mode_refuses_multiple_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("a.txt", "b.txt"):
                (root / name).write_text("x", encoding="utf-8")
            code, _, err = run(["convert", str(root / "a.txt"), str(root / "b.txt"), "--stdout"])
            self.assertEqual(2, code)
            self.assertIn("one file", err.lower())

    def test_stdout_mode_failure_exits_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "bad.txt"
            source.write_text("x", encoding="utf-8")
            code, _, err = run(["convert", str(source), "--stdout"])
            self.assertEqual(1, code)
            self.assertIn("deliberate failure", err)

    def test_directory_is_expanded_and_unsupported_files_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_text("x", encoding="utf-8")
            (root / "b.bin").write_bytes(b"x")
            code, output, _ = run(["convert", str(root), "--out", str(root / "out"), "--json"])
            self.assertEqual(0, code)
            payload = json.loads(output)
            self.assertEqual(1, len(payload["results"]))
            self.assertEqual(1, len(payload["skipped"]))

    def test_no_supported_files_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "thing.bin"
            source.write_bytes(b"x")
            code, _, err = run(["convert", str(source), "--out", temp])
            self.assertEqual(2, code)
            self.assertIn("no supported files", err.lower())

    def test_missing_out_defaults_beside_nothing_and_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "a.txt"
            source.write_text("x", encoding="utf-8")
            code, _, err = run(["convert", str(source)])
            self.assertEqual(2, code)
            self.assertIn("--out", err)


class MetadataCommandTests(unittest.TestCase):
    def test_extensions_lists_the_shared_set(self) -> None:
        code, output, _ = run(["extensions", "--json"])
        self.assertEqual(0, code)
        payload = json.loads(output)
        self.assertIn(".pdf", payload["extensions"])
        self.assertIn(".docx", payload["extensions"])
        self.assertEqual(sorted(payload["extensions"]), payload["extensions"])

    def test_version_reports_app_version(self) -> None:
        from markitdown_desktop import __version__

        code, output, _ = run(["version", "--json"])
        self.assertEqual(0, code)
        payload = json.loads(output)
        self.assertEqual(__version__, payload["app_version"])
        self.assertIn("markitdown_version", payload)
        self.assertIn("python", payload)

    def test_unknown_command_is_a_usage_error(self) -> None:
        code, _, _ = run(["frobnicate"])
        self.assertEqual(2, code)

    def test_no_command_is_a_usage_error(self) -> None:
        code, _, _ = run([])
        self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
