"""Command-line entry point shared by the GUI's siblings.

The Obsidian plugin (TypeScript in Electron) and the Claude Code plugin (Node)
cannot call a Python library in-process, so both shell out to this module. It
is a thin shell over ``converter.py`` — the same discovery rules, the same
collision-safe naming, the same per-file failure isolation as the desktop app.

    python -m markitdown_desktop.cli convert <path>... --out <dir> [--json]
    python -m markitdown_desktop.cli convert <path> --ocr always --ocr-language deu
    python -m markitdown_desktop.cli convert <path> --stdout
    python -m markitdown_desktop.cli extensions --json
    python -m markitdown_desktop.cli version --json

Exit codes: 0 success, 1 at least one file failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, TextIO

from . import __version__
from .converter import (
    SUPPORTED_EXTENSIONS,
    MicrosoftMarkItDownConverter,
    convert_files,
    discover_files,
)
from .ocr import OcrFallbackConverter, available_engine

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def markitdown_version() -> str:
    try:
        from importlib.metadata import version

        return version("markitdown")
    except Exception:
        return "not detected"


class _Parser(argparse.ArgumentParser):
    """Report usage errors through the injected stream, not the real stderr.

    The CLI is called as a subprocess by both plugins, so its diagnostics must
    be capturable rather than written straight to the process's stderr.
    """

    def __init__(self, *args, stderr: TextIO | None = None, **kwargs) -> None:
        self._stderr = stderr
        super().__init__(*args, **kwargs)

    def error(self, message: str):
        (self._stderr or sys.stderr).write(f"{self.prog}: error: {message}\n")
        raise SystemExit(EXIT_USAGE)


def _bound_parser_class(stderr: TextIO | None):
    """A _Parser that already knows where to report errors.

    Subparsers are built by argparse itself, so without this the ``convert``
    parser would fall back to the process's real stderr and both plugins would
    see an exit code with no message attached.
    """

    class BoundParser(_Parser):
        def __init__(self, *args, **kwargs) -> None:
            kwargs.setdefault("stderr", stderr)
            super().__init__(*args, **kwargs)

    return BoundParser


def _build_parser(stderr: TextIO | None = None) -> argparse.ArgumentParser:
    parser = _Parser(
        stderr=stderr,
        prog="markitdown_desktop.cli",
        description="Convert documents to Markdown using Microsoft MarkItDown.",
        add_help=True,
    )
    sub = parser.add_subparsers(dest="command", parser_class=_bound_parser_class(stderr))

    convert = sub.add_parser("convert", help="Convert files or folders to Markdown.")
    convert.add_argument("paths", nargs="+", help="Files or folders to convert.")
    convert.add_argument("--out", help="Folder to write .md files into.")
    convert.add_argument("--stdout", action="store_true",
                         help="Write one file's Markdown to standard output instead of to disk.")
    convert.add_argument("--overwrite", action="store_true",
                         help="Replace an existing .md of the same name instead of adding -2, -3.")
    convert.add_argument("--json", action="store_true", help="Emit a machine-readable result.")
    convert.add_argument(
        "--ocr", choices=("auto", "never", "always"), default="auto",
        help="OCR images and scanned PDFs: auto (only when no text was found), never, or always.")
    convert.add_argument(
        "--ocr-language", default=None,
        help="OCR language as a Tesseract code, e.g. eng or deu. Defaults to the app setting.")

    extensions = sub.add_parser("extensions", help="List the supported file extensions.")
    extensions.add_argument("--json", action="store_true")

    version = sub.add_parser("version", help="Report app, MarkItDown, and Python versions.")
    version.add_argument("--json", action="store_true")

    return parser


def _emit(stream: TextIO, payload: dict, as_json: bool, plain: str) -> None:
    if as_json:
        stream.write(json.dumps(payload, indent=2) + "\n")
    else:
        stream.write(plain + "\n")


def _ocr_language(explicit: str | None) -> str:
    if explicit:
        return explicit
    try:
        from .settings import load

        return load()["ocr_language"]
    except Exception:
        return "eng"


def _with_ocr(converter, args, engine_factory):
    """Layer OCR over any converter. A missing engine is not an error here."""
    engine = None if args.ocr == "never" else engine_factory()
    return OcrFallbackConverter(
        converter, engine, mode=args.ocr, language=_ocr_language(args.ocr_language)
    )


def _convert(args, converter_factory, engine_factory, stdout: TextIO, stderr: TextIO) -> int:
    if not args.stdout and not args.out:
        stderr.write("Specify where to write the Markdown with --out, or use --stdout.\n")
        return EXIT_USAGE

    accepted, skipped = discover_files(args.paths)
    if not accepted:
        stderr.write("No supported files were found in the given paths.\n")
        return EXIT_USAGE
    if args.stdout and len(accepted) > 1:
        stderr.write("--stdout converts one file at a time; you gave more than one file.\n")
        return EXIT_USAGE

    try:
        converter = converter_factory()
    except Exception as exc:
        stderr.write(f"{exc}\n")
        return EXIT_FAILED

    converter = _with_ocr(converter, args, engine_factory)

    if args.stdout:
        source = accepted[0]
        try:
            stdout.write(converter.convert(source))
        except Exception as exc:
            stderr.write(f"{source.name}: {exc}\n")
            return EXIT_FAILED
        return EXIT_OK

    results = convert_files(
        accepted, Path(args.out).expanduser(), converter, overwrite=args.overwrite
    )
    payload = {
        "results": [
            {
                "source": str(result.source),
                "output": str(result.output) if result.output else None,
                "ok": result.ok,
                "message": result.message,
            }
            for result in results
        ],
        "skipped": [str(path) for path in skipped],
    }
    failed = [r for r in results if not r.ok]
    plain_lines = [
        f"{'ok  ' if r.ok else 'FAIL'} {r.source.name} -> {r.output.name if r.output else r.message}"
        for r in results
    ]
    if skipped:
        plain_lines.append(f"skipped {len(skipped)} unsupported item(s)")
    _emit(stdout, payload, args.json, "\n".join(plain_lines))
    return EXIT_FAILED if failed else EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    converter_factory: Callable[[], object] = MicrosoftMarkItDownConverter,
    engine_factory: Callable[[], object] = available_engine,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    parser = _build_parser(stderr)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse exits on bad input; the callers here want a return code.
        return EXIT_USAGE

    if args.command == "convert":
        return _convert(args, converter_factory, engine_factory, stdout, stderr)

    if args.command == "extensions":
        extensions = sorted(SUPPORTED_EXTENSIONS)
        _emit(stdout, {"extensions": extensions}, args.json, "\n".join(extensions))
        return EXIT_OK

    if args.command == "version":
        engine = engine_factory()
        payload = {
            "app_version": __version__,
            "markitdown_version": markitdown_version(),
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "ocr_engine": getattr(engine, "name", None),
        }
        plain = (
            f"MarkItDown Desktop {payload['app_version']}\n"
            f"Microsoft MarkItDown {payload['markitdown_version']}\n"
            f"Python {payload['python']}\n"
            f"OCR {payload['ocr_engine'] or 'not available'}"
        )
        _emit(stdout, payload, args.json, plain)
        return EXIT_OK

    parser.print_help(stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
