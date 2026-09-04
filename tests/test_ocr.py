from pathlib import Path
import tempfile
import unittest

from foldmark.ocr import (
    OcrFallbackConverter,
    OcrUnavailable,
    about_line,
    available_engine,
    install_hint,
    mode_from_settings,
    _platform_candidates,
    ocr_pdf,
    reset_engine_cache,
    usage_summary,
    vision_language,
)


class FakeBase:
    """Stands in for MicrosoftMarkItDownConverter."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[Path] = []

    def convert(self, source: Path) -> str:
        self.calls.append(source)
        return self.text


class FakeEngine:
    name = "fake"

    def __init__(self, text: str = "RECOVERED TEXT") -> None:
        self.text = text
        self.calls: list[Path] = []
        self.languages: list[str] = []

    def text_from_image(self, path: Path, language: str = "eng") -> str:
        self.calls.append(Path(path))
        self.languages.append(language)
        return self.text


try:
    import pypdfium2 as _pypdfium2
except ImportError:  # pragma: no cover - depends on what is installed
    _pypdfium2 = None

# pypdfium2 arrives with MarkItDown, via pdfplumber. CI deliberately runs this
# suite against a bare interpreter with MarkItDown absent, so anything needing a
# real PDF has to stand aside there rather than error.
needs_pypdfium2 = unittest.skipIf(_pypdfium2 is None, "pypdfium2 is not installed")


def _file(root: Path, name: str) -> Path:
    path = root / name
    path.write_bytes(b"not a real document")
    return path


class FallbackDecisionTests(unittest.TestCase):
    def test_empty_image_conversion_falls_back_to_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "scan.png")
            engine = FakeEngine()
            wrapper = OcrFallbackConverter(FakeBase(""), engine)
            self.assertEqual("RECOVERED TEXT", wrapper.convert(source))
            self.assertEqual([source], engine.calls)

    def test_healthy_output_never_reaches_the_engine(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "chart.png")
            engine = FakeEngine()
            base = FakeBase("# Chart\n\nA paragraph with plenty of real text in it.")
            wrapper = OcrFallbackConverter(base, engine)
            self.assertEqual(base.text, wrapper.convert(source))
            self.assertEqual([], engine.calls)

    def test_non_image_non_pdf_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "notes.docx")
            engine = FakeEngine()
            wrapper = OcrFallbackConverter(FakeBase(""), engine)
            self.assertEqual("", wrapper.convert(source))
            self.assertEqual([], engine.calls)

    def test_missing_engine_says_how_to_install_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "scan.png")
            wrapper = OcrFallbackConverter(FakeBase(""), None)
            with self.assertRaises(ValueError) as caught:
                wrapper.convert(source)
            self.assertRegex(str(caught.exception), r"pip install|winget|apt")

    def test_missing_engine_leaves_ineligible_files_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "notes.docx")
            wrapper = OcrFallbackConverter(FakeBase(""), None)
            self.assertEqual("", wrapper.convert(source))

    def test_ocr_switched_off_does_not_advertise_an_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "scan.png")
            wrapper = OcrFallbackConverter(FakeBase(""), None, mode="never")
            self.assertEqual("", wrapper.convert(source))


if __name__ == "__main__":
    unittest.main()


class ModeTests(unittest.TestCase):
    def test_never_skips_ocr_even_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "scan.png")
            engine = FakeEngine()
            wrapper = OcrFallbackConverter(FakeBase(""), engine, mode="never")
            self.assertEqual("", wrapper.convert(source))
            self.assertEqual([], engine.calls)

    def test_always_replaces_healthy_output_for_eligible_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "chart.png")
            engine = FakeEngine()
            base = FakeBase("# Chart\n\nPlenty of perfectly good text already.")
            wrapper = OcrFallbackConverter(base, engine, mode="always")
            self.assertEqual("RECOVERED TEXT", wrapper.convert(source))

    def test_always_still_leaves_ineligible_files_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "notes.docx")
            engine = FakeEngine()
            base = FakeBase("# Notes\n\nA document with a real text layer.")
            wrapper = OcrFallbackConverter(base, engine, mode="always")
            self.assertEqual(base.text, wrapper.convert(source))
            self.assertEqual([], engine.calls)

    def test_language_is_passed_through_to_the_engine(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "scan.png")
            engine = FakeEngine()
            wrapper = OcrFallbackConverter(FakeBase(""), engine, language="deu")
            wrapper.convert(source)
            self.assertEqual(["deu"], engine.languages)


class PdfRoutingTests(unittest.TestCase):
    def test_sparse_pdf_is_routed_through_the_pdf_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "scanned.pdf")
            engine = FakeEngine()
            seen: list[tuple[Path, int]] = []

            def fake_pdf_ocr(path, engine_, *, max_pages, language):
                seen.append((Path(path), max_pages))
                return "## Page 1\n\nRECOVERED PAGE"

            wrapper = OcrFallbackConverter(
                FakeBase(""), engine, max_pages=7, pdf_ocr=fake_pdf_ocr
            )
            self.assertEqual("## Page 1\n\nRECOVERED PAGE", wrapper.convert(source))
            self.assertEqual([(source, 7)], seen)

    def test_pdf_with_a_text_layer_is_returned_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "report.pdf")
            base = FakeBase("# Report\n\nQUARTERLY REVENUE REPORT and a great deal more.")

            def fail_pdf_ocr(*args, **kwargs):
                raise AssertionError("a PDF with a text layer must not be rasterised")

            wrapper = OcrFallbackConverter(
                base, FakeEngine(), pdf_ocr=fail_pdf_ocr
            )
            self.assertEqual(base.text, wrapper.convert(source))

    def test_ocr_that_finds_nothing_keeps_the_original_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "blank.png")
            wrapper = OcrFallbackConverter(FakeBase(""), FakeEngine(""))
            self.assertEqual("", wrapper.convert(source))


def _real_pdf(path: Path, pages: int) -> Path:
    """A genuine blank PDF of ``pages`` pages, built with the library already installed."""
    document = _pypdfium2.PdfDocument.new()
    for _ in range(pages):
        document.new_page(200, 200)
    document.save(str(path))
    document.close()
    return path


class PageEngine:
    """Returns different text per call so page ordering is observable."""

    name = "page-fake"

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls = 0

    def text_from_image(self, path: Path, language: str = "eng") -> str:
        text = self.texts[self.calls] if self.calls < len(self.texts) else ""
        self.calls += 1
        return text


class OcrPdfTests(unittest.TestCase):
    @needs_pypdfium2
    def test_each_page_is_ocred_and_marked_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _real_pdf(Path(temp) / "scan.pdf", 3)
            engine = PageEngine(["FIRST", "SECOND", "THIRD"])
            markdown = ocr_pdf(source, engine, max_pages=10, language="eng")
            self.assertEqual(3, engine.calls)
            self.assertIn("<!-- Page number: 1 -->", markdown)
            self.assertIn("<!-- Page number: 3 -->", markdown)
            self.assertLess(markdown.index("FIRST"), markdown.index("SECOND"))
            self.assertLess(markdown.index("SECOND"), markdown.index("THIRD"))

    @needs_pypdfium2
    def test_max_pages_caps_the_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _real_pdf(Path(temp) / "long.pdf", 5)
            engine = PageEngine(["A", "B", "C", "D", "E"])
            markdown = ocr_pdf(source, engine, max_pages=2, language="eng")
            self.assertEqual(2, engine.calls)
            self.assertIn("C", "ABCDE")
            self.assertNotIn("<!-- Page number: 3 -->", markdown)

    @needs_pypdfium2
    def test_pages_with_no_recognised_text_are_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _real_pdf(Path(temp) / "mixed.pdf", 3)
            engine = PageEngine(["FIRST", "   ", "THIRD"])
            markdown = ocr_pdf(source, engine, max_pages=10, language="eng")
            self.assertIn("<!-- Page number: 1 -->", markdown)
            self.assertNotIn("<!-- Page number: 2 -->", markdown)
            self.assertIn("<!-- Page number: 3 -->", markdown)

    def test_an_unreadable_pdf_yields_no_text_rather_than_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "broken.pdf")
            self.assertEqual("", ocr_pdf(source, FakeEngine(), max_pages=10, language="eng"))


class EngineSelectionTests(unittest.TestCase):
    def test_no_installed_engine_is_not_an_error(self) -> None:
        def missing():
            raise OcrUnavailable("nothing here")

        self.assertIsNone(available_engine(candidates=[missing]))

    def test_the_first_working_candidate_wins(self) -> None:
        def missing():
            raise OcrUnavailable("nothing here")

        def present():
            return FakeEngine()

        def never_reached():
            raise AssertionError("selection must stop at the first working engine")

        engine = available_engine(candidates=[missing, present, never_reached])
        self.assertEqual("fake", engine.name)

    def test_a_candidate_that_fails_oddly_does_not_crash_selection(self) -> None:
        def exploding():
            raise RuntimeError("some unrelated import blew up")

        self.assertIsNone(available_engine(candidates=[exploding]))

    def test_install_hint_is_actionable_on_every_platform(self) -> None:
        for platform in ("darwin", "win32", "linux"):
            with self.subTest(platform=platform):
                hint = install_hint(platform)
                self.assertTrue(hint.strip())
                self.assertRegex(hint, r"pip install|winget|apt|brew")


class EngineLanguageTests(unittest.TestCase):
    def test_tesseract_codes_map_to_vision_locales(self) -> None:
        self.assertEqual("en-US", vision_language("eng"))
        self.assertEqual("de-DE", vision_language("deu"))

    def test_an_unknown_code_falls_back_to_english(self) -> None:
        self.assertEqual("en-US", vision_language("zzz"))


class RealEngineTests(unittest.TestCase):
    """The only tests that touch a real OCR engine. Skipped when none is installed."""

    def test_platform_candidates_are_all_callable(self) -> None:
        candidates = _platform_candidates()
        self.assertTrue(candidates)
        for factory in candidates:
            self.assertTrue(callable(factory))

    def test_an_installed_engine_reads_text_out_of_an_image(self) -> None:
        engine = available_engine()
        if engine is None:
            self.skipTest("no OCR engine installed on this machine")
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            self.skipTest("Pillow is not installed")

        with tempfile.TemporaryDirectory() as temp:
            image_path = Path(temp) / "known.png"
            image = Image.new("RGB", (900, 160), "white")
            draw = ImageDraw.Draw(image)
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
            except OSError:
                font = ImageFont.load_default()
            draw.text((40, 50), "QUARTERLY REVENUE REPORT", fill="black", font=font)
            image.save(image_path)

            text = engine.text_from_image(image_path, "eng")
            self.assertIn("QUARTERLY", text.upper())
            self.assertIn("REVENUE", text.upper())


class UsageReportingTests(unittest.TestCase):
    def test_an_ocred_image_counts_as_one_page(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "scan.png")
            wrapper = OcrFallbackConverter(FakeBase(""), FakeEngine())
            wrapper.convert(source)
            self.assertEqual(1, wrapper.last_pages)
            self.assertEqual("fake", wrapper.last_engine_used)

    def test_a_file_that_did_not_need_ocr_counts_as_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _file(Path(temp), "chart.png")
            base = FakeBase("# Chart\n\nA real conversion with real words in it.")
            wrapper = OcrFallbackConverter(base, FakeEngine())
            wrapper.convert(source)
            self.assertEqual(0, wrapper.last_pages)
            self.assertIsNone(wrapper.last_engine_used)

    @needs_pypdfium2
    def test_a_scanned_pdf_counts_every_page_it_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = _real_pdf(Path(temp) / "scan.pdf", 3)
            wrapper = OcrFallbackConverter(
                FakeBase(""), PageEngine(["FIRST", "SECOND", "THIRD"])
            )
            wrapper.convert(source)
            self.assertEqual(3, wrapper.last_pages)

    def test_counts_reset_between_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            scanned = _file(Path(temp), "scan.png")
            clean = _file(Path(temp), "notes.docx")
            wrapper = OcrFallbackConverter(FakeBase(""), FakeEngine())
            wrapper.convert(scanned)
            wrapper.convert(clean)
            self.assertEqual(0, wrapper.last_pages)


class SettingsBridgeTests(unittest.TestCase):
    def test_the_setting_switches_the_mode(self) -> None:
        self.assertEqual("auto", mode_from_settings({"ocr_enabled": True}))
        self.assertEqual("never", mode_from_settings({"ocr_enabled": False}))

    def test_a_missing_setting_leaves_ocr_on(self) -> None:
        self.assertEqual("auto", mode_from_settings({}))


class UsageSummaryTests(unittest.TestCase):
    def test_summary_names_the_engine_and_the_page_count(self) -> None:
        line = usage_summary(files=2, pages=5, engine="Apple Vision")
        self.assertIn("Apple Vision", line)
        self.assertIn("5", line)
        self.assertIn("2", line)

    def test_a_single_page_reads_as_singular(self) -> None:
        line = usage_summary(files=1, pages=1, engine="Apple Vision")
        self.assertIn("1 page", line)
        self.assertNotIn("1 pages", line)

    def test_no_ocr_means_no_line_at_all(self) -> None:
        self.assertEqual("", usage_summary(files=0, pages=0, engine="Apple Vision"))


class AboutLineTests(unittest.TestCase):
    def test_an_installed_engine_is_named(self) -> None:
        self.assertIn("Apple Vision", about_line("Apple Vision"))

    def test_no_engine_gets_an_install_instruction(self) -> None:
        line = about_line(None)
        self.assertIn("not available", line)
        self.assertRegex(line, r"pip install|winget|apt")


class EngineCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_engine_cache()

    def tearDown(self) -> None:
        reset_engine_cache()

    def test_the_platform_probe_runs_only_once(self) -> None:
        calls = []

        def counted():
            calls.append(1)
            return FakeEngine()

        first = available_engine(candidates=[counted], cache=True)
        second = available_engine(candidates=[counted], cache=True)
        self.assertIs(first, second)
        self.assertEqual(1, len(calls))

    def test_absence_is_cached_too(self) -> None:
        calls = []

        def counted():
            calls.append(1)
            raise OcrUnavailable("nothing here")

        self.assertIsNone(available_engine(candidates=[counted], cache=True))
        self.assertIsNone(available_engine(candidates=[counted], cache=True))
        self.assertEqual(1, len(calls))

    def test_uncached_lookups_stay_independent(self) -> None:
        calls = []

        def counted():
            calls.append(1)
            return FakeEngine()

        available_engine(candidates=[counted])
        available_engine(candidates=[counted])
        self.assertEqual(2, len(calls))
