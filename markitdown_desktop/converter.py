from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol


SUPPORTED_EXTENSIONS = {
    ".bmp", ".csv", ".docx", ".eml", ".epub", ".flac", ".gif", ".htm",
    ".html", ".jpeg", ".jpg", ".json", ".m4a", ".md", ".msg", ".mp3",
    ".pdf", ".png", ".pptx", ".tif", ".tiff", ".txt", ".wav", ".webp",
    ".xls", ".xlsx", ".xml", ".zip",
}


class Converter(Protocol):
    def convert(self, source: Path) -> str: ...


class MicrosoftMarkItDownConverter:
    """Lazy wrapper around MarkItDown's local-file-only API."""

    def __init__(self) -> None:
        try:
            from markitdown import MarkItDown
        except ImportError as exc:
            raise RuntimeError(
                "Microsoft MarkItDown is not installed. Run the setup script first."
            ) from exc
        self._converter = MarkItDown(enable_plugins=False)

    def convert(self, source: Path) -> str:
        # convert_local avoids accepting URLs or other remote resources.
        result = self._converter.convert_local(str(source))
        return result.text_content


@dataclass(frozen=True)
class ConversionResult:
    source: Path
    output: Path | None
    ok: bool
    message: str


def discover_files(paths: Iterable[str | Path]) -> tuple[list[Path], list[Path]]:
    """Return unique supported files and rejected file paths, in stable order."""
    accepted: list[Path] = []
    rejected: list[Path] = []
    seen: set[str] = set()

    def add_file(candidate: Path) -> None:
        key = os.path.normcase(str(candidate.resolve()))
        if key in seen:
            return
        seen.add(key)
        if candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
            accepted.append(candidate.resolve())
        else:
            rejected.append(candidate.resolve())

    for raw in paths:
        candidate = Path(raw).expanduser()
        if candidate.is_dir():
            for child in sorted(candidate.rglob("*"), key=lambda p: str(p).lower()):
                if child.is_file() and not child.name.startswith("."):
                    add_file(child)
        elif candidate.is_file():
            add_file(candidate)
        else:
            rejected.append(candidate.absolute())
    return accepted, rejected


def _available_output_path(
    source: Path, output_dir: Path, overwrite: bool, reserved: set[str]
) -> Path:
    base = source.stem or "converted"
    target = output_dir / f"{base}.md"

    # Never overwrite an input Markdown file in place.
    try:
        same_as_input = target.resolve() == source.resolve()
    except OSError:
        same_as_input = False
    if same_as_input:
        target = output_dir / f"{base}-converted.md"

    if overwrite and os.path.normcase(str(target)) not in reserved:
        reserved.add(os.path.normcase(str(target)))
        return target

    counter = 2
    original = target
    while target.exists() or os.path.normcase(str(target)) in reserved:
        target = original.with_name(f"{original.stem}-{counter}{original.suffix}")
        counter += 1
    reserved.add(os.path.normcase(str(target)))
    return target


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", delete=False, dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp"
        ) as handle:
            temp_name = handle.name
            handle.write(content)
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def convert_files(
    sources: Iterable[Path],
    output_dir: Path,
    converter: Converter,
    *,
    overwrite: bool = False,
    cancel_event: threading.Event | None = None,
    progress: Callable[[int, int, ConversionResult], None] | None = None,
) -> list[ConversionResult]:
    source_list = list(sources)
    results: list[ConversionResult] = []
    reserved: set[str] = set()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for index, source in enumerate(source_list, start=1):
        if cancel_event and cancel_event.is_set():
            break
        output = _available_output_path(source, output_dir, overwrite, reserved)
        try:
            markdown = converter.convert(source)
            if not isinstance(markdown, str):
                raise TypeError("The converter did not return text.")
            if not markdown.strip():
                # MarkItDown returns an empty string rather than raising when a
                # file has no extractable text - a photo with no OCR, a scanned
                # PDF with no text layer. Writing a 0-byte .md and calling it a
                # success hides that from the user.
                raise ValueError(
                    "No text could be extracted. Images need OCR and scanned "
                    "PDFs need a text layer."
                )
            _atomic_write(output, markdown)
            result = ConversionResult(source, output, True, "Converted")
        except Exception as exc:  # Each file should fail independently in a batch.
            message = str(exc).strip().splitlines()[0] or type(exc).__name__
            result = ConversionResult(source, None, False, message)
        results.append(result)
        if progress:
            progress(index, len(source_list), result)
    return results
