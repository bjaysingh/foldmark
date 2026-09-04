#!/usr/bin/env python3
"""PreToolUse hook: convert unreadable documents to Markdown before Read runs.

When Claude reads a .docx, .pdf, .pptx and similar, the raw bytes are useless.
This hook converts the file with Microsoft MarkItDown, caches the Markdown, and
rewrites the Read call's file_path to point at the cached .md, so the agent sees
text instead of binary.

Design rule: this hook must never be able to block work. Every failure path
exits 0 with no decision, which lets the original Read proceed untouched.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Formats Read cannot render usefully on its own. Images are deliberately absent:
# Read displays them natively, which beats OCR text for most questions.
DEFAULT_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".epub",
    ".msg", ".eml", ".zip", ".mp3", ".wav", ".m4a", ".flac",
}

DEFAULT_MAX_MB = 40.0
DEFAULT_TIMEOUT = 120.0


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def wanted_extensions() -> set[str]:
    raw = os.environ.get("FOLDMARK_HOOK_EXTENSIONS", "").strip()
    if not raw:
        return DEFAULT_EXTENSIONS
    return {
        item if item.startswith(".") else f".{item}"
        for item in (part.strip().lower() for part in raw.split(",")) if item
    }


def env_float(name: str, fallback: float) -> float:
    try:
        return float(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return fallback


def find_project_root() -> Path | None:
    """Locate the checkout that provides foldmark.cli."""
    candidates: list[Path] = []
    override = os.environ.get("FOLDMARK_ROOT", "").strip()
    if override:
        candidates.append(Path(override).expanduser())
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if plugin_root:
        candidates.append(Path(plugin_root).parent)
    candidates.extend(Path(__file__).resolve().parents[:4])
    for candidate in candidates:
        if (candidate / "foldmark" / "cli.py").is_file():
            return candidate
    return None


def find_python(root: Path | None) -> str:
    override = os.environ.get("FOLDMARK_PYTHON", "").strip()
    if override:
        return override
    if root is not None:
        venv = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if venv.exists():
            return str(venv)
    return shutil.which("python3") or shutil.which("python") or sys.executable


def cache_dir() -> Path:
    base = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    root = Path(base) if base else Path.home() / ".foldmark"
    path = root / "foldmark-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_key(source: Path) -> str:
    """Key on identity *and* content stamp, so an edited source reconverts."""
    stat = source.stat()
    material = f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def convert(source: Path, destination: Path, timeout: float) -> tuple[bool, str]:
    root = find_project_root()
    python = find_python(root)
    if root is not None:
        command = [python, "-m", "foldmark.cli", "convert", str(source), "--stdout"]
        cwd: str | None = str(root)
    else:
        # No checkout nearby: fall back to MarkItDown's own CLI if it is on PATH.
        markitdown = shutil.which("markitdown")
        if not markitdown:
            return False, "MarkItDown is not available."
        command = [markitdown, str(source)]
        cwd = None
    try:
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return False, f"Conversion timed out after {int(timeout)}s."
    except OSError as exc:
        return False, str(exc)
    if result.returncode != 0 or not result.stdout.strip():
        return False, (result.stderr or "Conversion produced no output.").strip().splitlines()[0]
    destination.write_text(result.stdout, encoding="utf-8")
    return True, ""


def allow(updated_input: dict, note: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": updated_input,
                "additionalContext": note,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


def main() -> int:
    if env_flag("FOLDMARK_HOOK_DISABLE"):
        return 0
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if event.get("tool_name") != "Read":
        return 0

    tool_input = event.get("tool_input") or {}
    raw_path = tool_input.get("file_path")
    if not isinstance(raw_path, str) or not raw_path:
        return 0

    source = Path(raw_path).expanduser()
    if source.suffix.lower() not in wanted_extensions() or not source.is_file():
        return 0

    max_bytes = env_float("FOLDMARK_HOOK_MAX_MB", DEFAULT_MAX_MB) * 1024 * 1024
    if source.stat().st_size > max_bytes:
        return 0

    target = cache_dir() / f"{source.stem}-{cache_key(source)}.md"
    if not target.exists():
        ok, message = convert(source, target, env_float("FOLDMARK_HOOK_TIMEOUT", DEFAULT_TIMEOUT))
        if not ok:
            # Fail open: say nothing and let the original Read happen.
            print(f"markitdown hook: {message}", file=sys.stderr)
            return 0

    updated = dict(tool_input)
    updated["file_path"] = str(target)
    # Page ranges belong to the PDF, not to the Markdown that replaced it.
    updated.pop("pages", None)
    allow(
        updated,
        f"{source.name} is not readable as text, so Microsoft MarkItDown converted it to "
        f"Markdown at {target}. You are reading that conversion, not the original bytes. "
        f"Original file: {source}",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # A hook crash must never stop a tool call.
        print(f"markitdown hook: {exc}", file=sys.stderr)
        raise SystemExit(0)
