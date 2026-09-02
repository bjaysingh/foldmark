from pathlib import Path
import json
import tempfile
import unittest

from markitdown_desktop import apply_update


PROTECTED = (".venv", ".update", ".git")


def build_root(root: Path, version: str = "1.0.0") -> Path:
    (root / "markitdown_desktop").mkdir(parents=True)
    (root / "markitdown_desktop" / "__init__.py").write_text(
        f"__version__ = '{version}'\n", encoding="utf-8"
    )
    (root / "app.py").write_text("# old app\n", encoding="utf-8")
    (root / "requirements.txt").write_text("a==1\n", encoding="utf-8")
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / ".venv" / "marker.txt").write_text("keep me", encoding="utf-8")
    return root


def build_staging(staging: Path, version: str = "1.1.0", requirements: str = "a==1\n") -> Path:
    (staging / "markitdown_desktop").mkdir(parents=True)
    (staging / "markitdown_desktop" / "__init__.py").write_text(
        f"__version__ = '{version}'\n", encoding="utf-8"
    )
    (staging / "app.py").write_text("# new app\n", encoding="utf-8")
    (staging / "requirements.txt").write_text(requirements, encoding="utf-8")
    return staging


def write_pending(root: Path, **overrides) -> Path:
    pending = {
        "version": "1.1.0",
        "previous_version": "1.0.0",
        "staging": ".update/staging/1.1.0",
        "backup": ".update/backup/1.0.0",
        "parent_pid": 0,
        "requirements_changed": False,
        "created": "2026-09-02T15:30:00Z",
        "python": "/usr/bin/python3",
        "relaunch": ["/usr/bin/python3", str(root / "app.py")],
    }
    pending.update(overrides)
    path = root / ".update" / "pending.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pending), encoding="utf-8")
    return path


class Runner:
    """Stand-in for subprocess, so tests never install packages or launch apps."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.cwds: list[str | None] = []
        self.fail_on = fail_on
        self.launched: list[list[str]] = []

    def run(self, command: list[str], cwd: str | None = None) -> tuple[int, str]:
        self.calls.append(command)
        self.cwds.append(cwd)
        joined = " ".join(command)
        if self.fail_on and self.fail_on in joined:
            return 1, f"simulated failure: {self.fail_on}"
        return 0, ""

    def launch(self, command: list[str]) -> None:
        self.launched.append(command)


class SwapTests(unittest.TestCase):
    def test_successful_swap_replaces_code_and_keeps_venv(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = build_root(Path(temp))
            staging = build_staging(root / ".update" / "staging" / "1.1.0")
            write_pending(root)
            runner = Runner()
            ok, message = apply_update.apply(root, runner=runner)
            self.assertTrue(ok, message)
            self.assertEqual("# new app\n", (root / "app.py").read_text(encoding="utf-8"))
            self.assertIn("1.1.0", (root / "markitdown_desktop" / "__init__.py").read_text(encoding="utf-8"))
            self.assertEqual("keep me", (root / ".venv" / "marker.txt").read_text(encoding="utf-8"))
            self.assertTrue((root / ".update" / "backup" / "1.0.0" / "app.py").exists())
            self.assertFalse((root / ".update" / "pending.json").exists())
            self.assertTrue(runner.launched)
            self.assertFalse(staging.exists())
            self.assertEqual([str(root.resolve())], runner.cwds,
                             "the smoke check must import from the install root")

    def test_pip_runs_only_when_requirements_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = build_root(Path(temp))
            build_staging(root / ".update" / "staging" / "1.1.0")
            write_pending(root, requirements_changed=False)
            runner = Runner()
            apply_update.apply(root, runner=runner)
            self.assertFalse(any("pip" in " ".join(call) for call in runner.calls))

        with tempfile.TemporaryDirectory() as temp:
            root = build_root(Path(temp))
            build_staging(root / ".update" / "staging" / "1.1.0", requirements="a==2\n")
            write_pending(root, requirements_changed=True)
            runner = Runner()
            apply_update.apply(root, runner=runner)
            self.assertTrue(any("pip" in " ".join(call) for call in runner.calls))

    def test_failed_smoke_check_rolls_back_to_the_old_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = build_root(Path(temp))
            build_staging(root / ".update" / "staging" / "1.1.0")
            write_pending(root)
            runner = Runner(fail_on="import markitdown_desktop")
            ok, message = apply_update.apply(root, runner=runner)
            self.assertFalse(ok)
            self.assertEqual("# old app\n", (root / "app.py").read_text(encoding="utf-8"))
            self.assertIn("1.0.0", (root / "markitdown_desktop" / "__init__.py").read_text(encoding="utf-8"))
            self.assertTrue((root / ".update" / "last_error.txt").exists())
            self.assertTrue(runner.launched, "the old version must still be relaunched")

    def test_failed_pip_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = build_root(Path(temp))
            build_staging(root / ".update" / "staging" / "1.1.0", requirements="a==2\n")
            write_pending(root, requirements_changed=True)
            runner = Runner(fail_on="pip")
            ok, _ = apply_update.apply(root, runner=runner)
            self.assertFalse(ok)
            self.assertEqual("a==1\n", (root / "requirements.txt").read_text(encoding="utf-8"))

    def test_invalid_staging_tree_is_refused_before_any_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = build_root(Path(temp))
            staging = root / ".update" / "staging" / "1.1.0"
            staging.mkdir(parents=True)
            (staging / "app.py").write_text("# incomplete\n", encoding="utf-8")
            write_pending(root)
            ok, _ = apply_update.apply(root, runner=Runner())
            self.assertFalse(ok)
            self.assertEqual("# old app\n", (root / "app.py").read_text(encoding="utf-8"))

    def test_missing_pending_file_is_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = build_root(Path(temp))
            ok, _ = apply_update.apply(root, runner=Runner())
            self.assertFalse(ok)
            self.assertEqual("# old app\n", (root / "app.py").read_text(encoding="utf-8"))

    def test_protected_directories_are_never_moved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = build_root(Path(temp))
            staging = build_staging(root / ".update" / "staging" / "1.1.0")
            (staging / ".venv").mkdir()
            (staging / ".venv" / "hostile.txt").write_text("no", encoding="utf-8")
            write_pending(root)
            apply_update.apply(root, runner=Runner())
            self.assertEqual("keep me", (root / ".venv" / "marker.txt").read_text(encoding="utf-8"))
            self.assertFalse((root / ".venv" / "hostile.txt").exists())
            for name in PROTECTED:
                self.assertFalse((root / ".update" / "backup" / "1.0.0" / name).exists())


if __name__ == "__main__":
    unittest.main()
