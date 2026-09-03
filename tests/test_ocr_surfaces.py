from pathlib import Path
import io
import json
import tempfile
import unittest

from markitdown_desktop import cli, settings


class BlankConverter:
    """Converts nothing, the way MarkItDown does for a scanned page."""

    def convert(self, source: Path) -> str:
        return ""


class StubEngine:
    name = "stub-engine"

    def text_from_image(self, path: Path, language: str = "eng") -> str:
        return f"RECOVERED[{language}]"


def run(argv: list[str], *, engine=None, converter=BlankConverter) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        argv,
        converter_factory=converter,
        engine_factory=lambda: engine,
        stdout=out,
        stderr=err,
    )
    return code, out.getvalue(), err.getvalue()


class CliOcrTests(unittest.TestCase):
    def test_ocr_rescues_an_image_the_converter_could_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scan.png"
            source.write_bytes(b"not really a png")
            out_dir = Path(temp) / "out"
            code, output, _ = run(
                ["convert", str(source), "--out", str(out_dir), "--json"],
                engine=StubEngine(),
            )
            self.assertEqual(0, code)
            self.assertTrue(json.loads(output)["results"][0]["ok"])
            self.assertEqual(
                "RECOVERED[eng]", (out_dir / "scan.md").read_text(encoding="utf-8")
            )

    def test_ocr_never_leaves_the_old_failure_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scan.png"
            source.write_bytes(b"not really a png")
            code, output, _ = run(
                ["convert", str(source), "--out", str(Path(temp) / "out"),
                 "--ocr", "never", "--json"],
                engine=StubEngine(),
            )
            self.assertEqual(1, code)
            self.assertFalse(json.loads(output)["results"][0]["ok"])

    def test_language_flag_reaches_the_engine(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scan.png"
            source.write_bytes(b"not really a png")
            out_dir = Path(temp) / "out"
            run(
                ["convert", str(source), "--out", str(out_dir),
                 "--ocr-language", "deu"],
                engine=StubEngine(),
            )
            self.assertEqual(
                "RECOVERED[deu]", (out_dir / "scan.md").read_text(encoding="utf-8")
            )

    def test_no_engine_installed_reports_how_to_install_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scan.png"
            source.write_bytes(b"not really a png")
            code, output, _ = run(
                ["convert", str(source), "--out", str(Path(temp) / "out"), "--json"],
                engine=None,
            )
            self.assertEqual(1, code)
            message = json.loads(output)["results"][0]["message"]
            self.assertRegex(message, r"pip install|winget|apt")

    def test_version_reports_the_active_ocr_engine(self) -> None:
        _, output, _ = run(["version", "--json"], engine=StubEngine())
        self.assertEqual("stub-engine", json.loads(output)["ocr_engine"])

    def test_version_says_when_no_engine_is_available(self) -> None:
        _, output, _ = run(["version", "--json"], engine=None)
        self.assertIsNone(json.loads(output)["ocr_engine"])

    def test_an_unknown_ocr_mode_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scan.png"
            source.write_bytes(b"x")
            code, _, err = run(
                ["convert", str(source), "--out", temp, "--ocr", "sometimes"]
            )
            self.assertEqual(cli.EXIT_USAGE, code)
            self.assertIn("sometimes", err)


class SettingsOcrTests(unittest.TestCase):
    def test_ocr_defaults_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data = settings.load(Path(temp) / "settings.json")
            self.assertTrue(data["ocr_enabled"])
            self.assertEqual("eng", data["ocr_language"])

    def test_ocr_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            settings.update(path, ocr_enabled=False, ocr_language="deu")
            data = settings.load(path)
            self.assertFalse(data["ocr_enabled"])
            self.assertEqual("deu", data["ocr_language"])

    def test_a_nonsense_ocr_value_collapses_to_the_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text(
                json.dumps({"ocr_enabled": "yes please", "ocr_language": 7}),
                encoding="utf-8",
            )
            data = settings.load(path)
            self.assertTrue(data["ocr_enabled"])
            self.assertEqual("eng", data["ocr_language"])


if __name__ == "__main__":
    unittest.main()
