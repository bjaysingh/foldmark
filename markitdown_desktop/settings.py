"""User settings persisted outside the install root.

Settings live in the home directory, not the app folder, so an update that
replaces the app tree cannot discard them.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SETTINGS_DIR = Path.home() / ".markitdown_desktop"
SETTINGS_PATH = SETTINGS_DIR / "settings.json"

DEFAULTS: dict[str, Any] = {
    "skipped_version": None,
    "last_check": None,
    "auto_check": True,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    """Return settings, falling back to defaults for anything unreadable.

    A corrupt or unreadable settings file must never stop the app from
    starting, so every failure mode collapses to the defaults.
    """
    data = dict(DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    if not isinstance(raw, dict):
        return data
    for key in DEFAULTS:
        if key in raw:
            data[key] = raw[key]
    if not isinstance(data["auto_check"], bool):
        data["auto_check"] = DEFAULTS["auto_check"]
    if data["skipped_version"] is not None and not isinstance(data["skipped_version"], str):
        data["skipped_version"] = None
    return data


def save(data: dict[str, Any], path: Path = SETTINGS_PATH) -> bool:
    """Write settings atomically. Returns False instead of raising."""
    payload = {key: data.get(key, DEFAULTS[key]) for key in DEFAULTS}
    temp_name: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp"
        ) as handle:
            temp_name = handle.name
            json.dump(payload, handle, indent=2)
        os.replace(temp_name, path)
        temp_name = None
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if temp_name and os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def update(path: Path = SETTINGS_PATH, **changes: Any) -> dict[str, Any]:
    data = load(path)
    data.update(changes)
    save(data, path)
    return data
