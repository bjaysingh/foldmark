"""Optical character recognition fallback for images and scanned PDFs.

MarkItDown 0.1.7 has no OCR: a photograph of text converts to an empty string.
This module supplies the missing text without touching the existing conversion
path. ``OcrFallbackConverter`` wraps any ``Converter``, calls it first, and
reaches for an engine only when the result comes back empty or near-empty and
the file is one OCR can actually help with.

Engines are injected rather than imported at the call site, so the test suite
exercises every branch on a machine with no OCR installed at all.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Protocol

IMAGE_EXTENSIONS = {
    ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp",
}

# Fewer than this many non-whitespace characters on a page means the page holds
# at most a header or a stray page number - not text a reader could use.
SPARSE_CHARS_PER_PAGE = 20

# A bound, not a judgement about real documents: it stops a mistakenly dropped
# 900-page scan from locking the GUI up for an hour.
DEFAULT_MAX_PAGES = 50

OCR_MODES = ("auto", "never", "always")

# Tesseract speaks ISO 639-2; Vision speaks BCP 47. The app stores the Tesseract
# code because it is the one a user is likely to have seen documented.
VISION_LANGUAGES = {
    "eng": "en-US",
    "fra": "fr-FR",
    "deu": "de-DE",
    "ita": "it-IT",
    "spa": "es-ES",
    "por": "pt-BR",
    "chi_sim": "zh-Hans",
    "chi_tra": "zh-Hant",
    "jpn": "ja-JP",
    "kor": "ko-KR",
}


class OcrUnavailable(RuntimeError):
    """Raised when an engine cannot run here - never fatal, always a fallback."""


def vision_language(code: str) -> str:
    return VISION_LANGUAGES.get(code, VISION_LANGUAGES["eng"])


def mode_from_settings(data: dict) -> str:
    """Translate the stored on/off switch into an OCR mode."""
    return "auto" if data.get("ocr_enabled", True) else "never"


def usage_summary(*, files: int, pages: int, engine: str) -> str:
    """One line for the status bar, or "" when OCR did nothing worth saying."""
    if files <= 0 or pages <= 0:
        return ""
    page_word = "page" if pages == 1 else "pages"
    file_word = "file" if files == 1 else "files"
    return f"{engine} read {pages} {page_word} in {files} {file_word}."


def about_line(engine: str | None) -> str:
    """What the About dialog says about OCR.

    MarkItDown has no OCR of its own, so whether scanned pages work at all
    depends on what is installed here. Said plainly, with the fix attached.
    """
    if engine:
        return f"OCR for images and scanned PDFs: {engine}"
    return f"OCR is not available. {install_hint()}"


def install_hint(platform: str = sys.platform) -> str:
    if platform == "darwin":
        return (
            "Install Apple's OCR binding with: "
            "pip install pyobjc-framework-Vision"
        )
    if platform.startswith("win"):
        return (
            "Install Tesseract with: winget install UB-Mannheim.TesseractOCR "
            "and then: pip install pytesseract"
        )
    return (
        "Install Tesseract with: apt install tesseract-ocr "
        "and then: pip install pytesseract"
    )


class OcrEngine(Protocol):
    name: str

    def text_from_image(self, path: Path, language: str = "eng") -> str: ...


def is_sparse(text: str, pages: int = 1) -> bool:
    """True when ``text`` is too thin to be a real conversion of ``pages`` pages."""
    dense = "".join(text.split())
    return len(dense) < SPARSE_CHARS_PER_PAGE * max(pages, 1)


def pdf_page_count(path: Path) -> int:
    """Page count, or 1 when the file cannot be opened.

    The count only scales the sparseness threshold, so guessing low is safe: it
    makes the fallback fire less eagerly rather than more.
    """
    try:
        import pypdfium2

        document = pypdfium2.PdfDocument(str(path))
        try:
            return max(len(document), 1)
        finally:
            document.close()
    except Exception:
        return 1


class VisionEngine:
    """Apple's Vision framework: offline, accurate, and already on every Mac.

    Only the PyObjC binding needs installing - the recogniser itself ships with
    macOS, which is why it is preferred over Tesseract here.
    """

    name = "Apple Vision"

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise OcrUnavailable("Apple Vision is only available on macOS.")
        try:
            import Quartz
            import Vision
            from Foundation import NSURL
        except ImportError as exc:
            raise OcrUnavailable(install_hint("darwin")) from exc
        self._Quartz = Quartz
        self._Vision = Vision
        self._NSURL = NSURL

    def text_from_image(self, path: Path, language: str = "eng") -> str:
        url = self._NSURL.fileURLWithPath_(str(Path(path).resolve()))
        source = self._Quartz.CGImageSourceCreateWithURL(url, None)
        if source is None:
            raise OcrUnavailable(f"Vision could not read {Path(path).name}.")
        image = self._Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
        if image is None:
            raise OcrUnavailable(f"Vision could not decode {Path(path).name}.")

        request = self._Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(self._Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)
        try:
            request.setRecognitionLanguages_([vision_language(language)])
        except Exception:
            # An unsupported locale must not lose the whole page; Vision's own
            # default is a better outcome than no text at all.
            pass

        handler = self._Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            image, None
        )
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise OcrUnavailable(f"Vision failed on {Path(path).name}: {error}")

        lines: list[str] = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates:
                lines.append(str(candidates[0].string()))
        return "\n".join(lines)


class TesseractEngine:
    """Tesseract via pytesseract, for Windows and Linux.

    Needs both the Python wrapper and the Tesseract binary, so the constructor
    checks for the binary rather than letting a call fail obscurely later.
    """

    name = "Tesseract"

    def __init__(self) -> None:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise OcrUnavailable(install_hint()) from exc
        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:
            raise OcrUnavailable(install_hint()) from exc
        self._pytesseract = pytesseract
        self._Image = Image

    def text_from_image(self, path: Path, language: str = "eng") -> str:
        with self._Image.open(path) as image:
            try:
                return self._pytesseract.image_to_string(image, lang=language)
            except Exception:
                # A missing language pack should still yield the default language
                # rather than failing the whole conversion.
                return self._pytesseract.image_to_string(image)


_ENGINE_CACHE: list = []


def reset_engine_cache() -> None:
    """Forget the probed engine. Exists so tests do not leak state into each other."""
    _ENGINE_CACHE.clear()


def available_engine(
    candidates: Iterable[Callable[[], OcrEngine]] | None = None,
    *,
    cache: bool | None = None,
) -> OcrEngine | None:
    """The best engine installed here, or None.

    None is a normal outcome, not a failure: without an engine the app behaves
    exactly as it did before OCR existed. The result is cached because probing
    means importing PyObjC, which costs about a tenth of a second - once is
    fine, once per converted file is not.
    """
    # Only the real platform probe is worth caching. Injected candidates are a
    # dependency-injection seam; letting them fill the cache would leak one
    # caller's fake engine into every later lookup.
    if cache is None:
        cache = candidates is None
    if cache and _ENGINE_CACHE:
        return _ENGINE_CACHE[0]
    if candidates is None:
        candidates = _platform_candidates()
    engine = _probe(candidates)
    if cache:
        _ENGINE_CACHE.append(engine)
    return engine


def _probe(candidates: Iterable[Callable[[], OcrEngine]]) -> OcrEngine | None:
    for factory in candidates:
        try:
            return factory()
        except Exception:
            # A candidate that cannot load - missing binding, missing binary, or
            # an unrelated import error inside it - must not stop the next one.
            continue
    return None


def _platform_candidates() -> list[Callable[[], OcrEngine]]:
    if sys.platform == "darwin":
        return [VisionEngine, TesseractEngine]
    return [TesseractEngine]


# 200 DPI against PDF's 72-point unit. Enough resolution for body text without
# turning a long scan into hundreds of megabytes of bitmaps.
RASTER_SCALE = 200 / 72


def ocr_pdf(
    path: Path,
    engine: OcrEngine,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    language: str = "eng",
) -> str:
    """Rasterise ``path`` and OCR each page, returning Markdown.

    Rasterising uses pypdfium2, which pdfplumber already installs, so scanned
    PDFs cost no new dependency. A page the engine finds nothing on is left out
    entirely rather than contributing an empty heading.
    """
    try:
        import pypdfium2
    except ImportError:
        return ""

    sections: list[str] = []
    try:
        document = pypdfium2.PdfDocument(str(path))
    except Exception:
        return ""

    try:
        # PdfDocument indexes by integer only - it does not accept a slice.
        for number in range(1, min(len(document), max(max_pages, 0)) + 1):
            page = document[number - 1]
            with tempfile.TemporaryDirectory() as scratch:
                image_path = Path(scratch) / f"page-{number}.png"
                try:
                    page.render(scale=RASTER_SCALE).to_pil().save(image_path)
                    text = engine.text_from_image(image_path, language)
                except Exception:
                    continue
            if text.strip():
                sections.append(f"<!-- Page number: {number} -->\n\n{text.strip()}")
    finally:
        document.close()
    return "\n\n".join(sections)


class OcrFallbackConverter:
    """Wraps a ``Converter``, adding OCR only where the wrapped one comes up empty."""

    def __init__(
        self,
        base,
        engine: OcrEngine | None,
        *,
        mode: str = "auto",
        language: str = "eng",
        max_pages: int = DEFAULT_MAX_PAGES,
        pdf_ocr: Callable[..., str] | None = None,
    ) -> None:
        self._base = base
        self._engine = engine
        self._mode = mode if mode in OCR_MODES else "auto"
        self._language = language
        self._max_pages = max_pages
        self._pdf_ocr = pdf_ocr or ocr_pdf
        self.last_engine_used: str | None = None
        self.last_pages = 0

    def convert(self, source: Path) -> str:
        text = self._base.convert(source)
        self.last_engine_used = None
        self.last_pages = 0
        suffix = source.suffix.lower()
        eligible = suffix in IMAGE_EXTENSIONS or suffix == ".pdf"

        if self._mode == "never":
            return text
        if self._engine is None:
            # Only worth mentioning for a file OCR could actually have rescued,
            # and only when the conversion came back empty anyway.
            if eligible and is_sparse(text, pdf_page_count(source) if suffix == ".pdf" else 1):
                raise ValueError(
                    f"No text could be extracted and no OCR engine is installed. "
                    f"{install_hint()}"
                )
            return text

        if suffix in IMAGE_EXTENSIONS:
            if self._mode != "always" and not is_sparse(text):
                return text
            recovered = self._engine.text_from_image(source, self._language)
            pages = 1
        elif suffix == ".pdf":
            if self._mode != "always" and not is_sparse(text, pdf_page_count(source)):
                return text
            recovered = self._pdf_ocr(
                source, self._engine, max_pages=self._max_pages, language=self._language
            )
            pages = recovered.count("<!-- Page number:")
        else:
            return text

        if not recovered.strip():
            return text
        self.last_engine_used = self._engine.name
        self.last_pages = pages
        return recovered
