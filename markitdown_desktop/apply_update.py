"""Standalone update applier.

Run as a separate process *after* the app exits, because a running Python
process cannot safely have its own package directory replaced underneath it,
and on Windows the OS refuses to move files the process still holds open.

This module deliberately imports nothing from ``markitdown_desktop``: at the
moment it runs, that package is exactly what is being swapped out. It is
copied to ``<root>/.update/apply_update.py`` and executed from there.

Usage:  python <root>/.update/apply_update.py <root>
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROTECTED = {".venv", ".update", ".git"}
REQUIRED_ENTRIES = ("app.py", "requirements.txt", os.path.join("markitdown_desktop", "__init__.py"))
PARENT_EXIT_TIMEOUT = 30.0
SMOKE_CODE = "import markitdown_desktop, sys; sys.stdout.write(markitdown_desktop.__version__)"


class Runner:
    """Real subprocess execution; tests substitute a recording stand-in."""

    def run(self, command: list[str], cwd: str | None = None) -> tuple[int, str]:
        try:
            completed = subprocess.run(
                command, cwd=cwd, capture_output=True, text=True, timeout=900, check=False
            )
        except Exception as exc:
            return 1, str(exc)
        output = (completed.stderr or completed.stdout or "").strip()
        return completed.returncode, output

    def launch(self, command: list[str]) -> None:
        kwargs: dict = {"close_fds": True}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(command, **kwargs)


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, check=False,
        )
        return str(pid) in (result.stdout or "")
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_for_exit(pid: int, timeout: float = PARENT_EXIT_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process_alive(pid):
        time.sleep(0.25)


def _read_pending(root: Path) -> dict | None:
    try:
        data = json.loads((root / ".update" / "pending.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _validate(tree: Path) -> str | None:
    if not tree.is_dir():
        return "The staged update folder is missing."
    missing = [entry for entry in REQUIRED_ENTRIES if not (tree / entry).exists()]
    if missing:
        return f"The staged update is incomplete: {', '.join(missing)}"
    return None


def _managed_names(staging: Path) -> list[str]:
    """Only replace what the update actually ships, never .venv or .update."""
    return sorted(child.name for child in staging.iterdir() if child.name not in PROTECTED)


def _move(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
    shutil.move(str(source), str(destination))


def _write_error(root: Path, message: str) -> None:
    try:
        path = root / ".update" / "last_error.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(message, encoding="utf-8")
    except OSError:
        pass


def _rollback(root: Path, backup: Path, names: list[str]) -> None:
    for name in names:
        target = root / name
        try:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        except OSError:
            pass
    if not backup.is_dir():
        return
    for child in sorted(backup.iterdir()):
        try:
            _move(child, root / child.name)
        except OSError:
            pass


def apply(root: Path | str, runner: Runner | None = None) -> tuple[bool, str]:
    """Swap the staged tree into place, rolling back on any failure.

    Returns (ok, message). Never raises: the caller's only job afterwards is
    to relaunch something that works.
    """
    root = Path(root).resolve()
    runner = runner or Runner()

    pending = _read_pending(root)
    if pending is None:
        return False, "No pending update was found."

    staging = root / pending.get("staging", "")
    backup = root / pending.get("backup", ".update/backup/previous")
    relaunch = pending.get("relaunch") or []
    python = pending.get("python") or sys.executable

    problem = _validate(staging)
    if problem:
        _write_error(root, problem)
        if relaunch:
            runner.launch(relaunch)
        return False, problem

    names = _managed_names(staging)
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True, exist_ok=True)

    try:
        for name in names:
            current = root / name
            if current.exists():
                _move(current, backup / name)
        for name in names:
            _move(staging / name, root / name)
    except OSError as exc:
        message = f"The update could not be installed: {exc}"
        _rollback(root, backup, names)
        _write_error(root, message)
        if relaunch:
            runner.launch(relaunch)
        return False, message

    if pending.get("requirements_changed"):
        code, output = runner.run(
            [python, "-m", "pip", "install", "--disable-pip-version-check",
             "-r", str(root / "requirements.txt")],
            cwd=str(root),
        )
        if code != 0:
            message = f"Updating dependencies failed, so the previous version was restored.\n{output}"[:2000]
            _rollback(root, backup, names)
            _write_error(root, message)
            if relaunch:
                runner.launch(relaunch)
            return False, message

    # The smoke check must import from the install root, not from whatever
    # directory this helper happens to have been started in.
    code, output = runner.run([python, "-c", SMOKE_CODE], cwd=str(root))
    if code != 0:
        message = f"The new version failed to start, so the previous version was restored.\n{output}"[:2000]
        _rollback(root, backup, names)
        _write_error(root, message)
        if relaunch:
            runner.launch(relaunch)
        return False, message

    shutil.rmtree(staging, ignore_errors=True)
    (root / ".update" / "pending.json").unlink(missing_ok=True)
    (root / ".update" / "last_error.txt").unlink(missing_ok=True)
    if relaunch:
        runner.launch(relaunch)
    return True, f"Updated to {pending.get('version', 'the new version')}."


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return 2
    root = Path(argv[1]).resolve()
    pending = _read_pending(root) or {}
    wait_for_exit(int(pending.get("parent_pid") or 0))
    ok, _message = apply(root)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
