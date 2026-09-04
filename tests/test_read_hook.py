"""Tests for the Claude Code PreToolUse hook.

The hook ships inside claude-plugin/ rather than the package, so it is loaded
by path the same way Claude Code invokes it.
"""

from pathlib import Path
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

HOOK_PATH = Path(__file__).resolve().parents[1] / "claude-plugin" / "hooks" / "foldmark_read_hook.py"

spec = importlib.util.spec_from_file_location("foldmark_read_hook", HOOK_PATH)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class HookHarness(unittest.TestCase):
    def setUp(self) -> None:
        self._env = dict(os.environ)
        self._stdin, self._stdout = sys.stdin, sys.stdout
        self.temp = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_PLUGIN_DATA"] = self.temp.name

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        sys.stdin, sys.stdout = self._stdin, self._stdout
        self.temp.cleanup()

    def invoke(self, event: dict) -> tuple[int, dict | None]:
        sys.stdin = io.StringIO(json.dumps(event))
        sys.stdout = io.StringIO()
        code = hook.main()
        raw = sys.stdout.getvalue().strip()
        sys.stdout = self._stdout
        return code, json.loads(raw) if raw else None

    def read_event(self, path: Path, **extra) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": str(path), **extra},
        }


class InterceptionTests(HookHarness):
    def make(self, name: str, size: int = 16) -> Path:
        path = Path(self.temp.name) / name
        path.write_bytes(b"x" * size)
        return path

    def test_supported_document_is_redirected_to_converted_markdown(self) -> None:
        source = self.make("report.docx")
        hook.convert = lambda src, dest, timeout: (dest.write_text("# report\n", encoding="utf-8"), (True, ""))[1]
        code, payload = self.invoke(self.read_event(source))
        self.assertEqual(0, code)
        self.assertIsNotNone(payload)
        output = payload["hookSpecificOutput"]
        self.assertEqual("allow", output["permissionDecision"])
        self.assertTrue(output["updatedInput"]["file_path"].endswith(".md"))
        self.assertIn("MarkItDown", output["additionalContext"])
        self.assertIn(str(source), output["additionalContext"])

    def test_page_range_is_dropped_because_markdown_has_no_pages(self) -> None:
        source = self.make("report.pdf")
        hook.convert = lambda src, dest, timeout: (dest.write_text("# report\n", encoding="utf-8"), (True, ""))[1]
        _, payload = self.invoke(self.read_event(source, pages="1-5", offset=0))
        updated = payload["hookSpecificOutput"]["updatedInput"]
        self.assertNotIn("pages", updated)
        self.assertEqual(0, updated["offset"], "unrelated Read arguments must survive")

    def test_conversion_result_is_cached_and_reused(self) -> None:
        source = self.make("report.docx")
        calls: list[Path] = []

        def fake(src, dest, timeout):
            calls.append(src)
            dest.write_text("# report\n", encoding="utf-8")
            return True, ""

        hook.convert = fake
        first = self.invoke(self.read_event(source))[1]
        second = self.invoke(self.read_event(source))[1]
        self.assertEqual(1, len(calls), "the second read must come from cache")
        self.assertEqual(
            first["hookSpecificOutput"]["updatedInput"]["file_path"],
            second["hookSpecificOutput"]["updatedInput"]["file_path"],
        )

    def test_edited_source_reconverts(self) -> None:
        source = self.make("report.docx")
        hook.convert = lambda src, dest, timeout: (dest.write_text("# a\n", encoding="utf-8"), (True, ""))[1]
        first = self.invoke(self.read_event(source))[1]
        source.write_bytes(b"y" * 999)
        second = self.invoke(self.read_event(source))[1]
        self.assertNotEqual(
            first["hookSpecificOutput"]["updatedInput"]["file_path"],
            second["hookSpecificOutput"]["updatedInput"]["file_path"],
        )


class PassThroughTests(HookHarness):
    def make(self, name: str, size: int = 16) -> Path:
        path = Path(self.temp.name) / name
        path.write_bytes(b"x" * size)
        return path

    def assertPassThrough(self, event: dict) -> None:
        code, payload = self.invoke(event)
        self.assertEqual(0, code)
        self.assertIsNone(payload, "the hook must stay silent so Read proceeds untouched")

    def test_other_tools_are_ignored(self) -> None:
        self.assertPassThrough({"tool_name": "Bash", "tool_input": {"command": "ls"}})

    def test_plain_text_and_images_are_left_alone(self) -> None:
        for name in ("notes.md", "data.csv", "photo.png", "script.py"):
            self.assertPassThrough(self.read_event(self.make(name)))

    def test_missing_file_is_ignored(self) -> None:
        self.assertPassThrough(self.read_event(Path(self.temp.name) / "absent.docx"))

    def test_oversized_file_is_skipped(self) -> None:
        os.environ["FOLDMARK_HOOK_MAX_MB"] = "0.00001"
        self.assertPassThrough(self.read_event(self.make("big.docx", size=4096)))

    def test_disable_switch_short_circuits(self) -> None:
        os.environ["FOLDMARK_HOOK_DISABLE"] = "1"
        self.assertPassThrough(self.read_event(self.make("report.docx")))

    def test_failed_conversion_fails_open(self) -> None:
        hook.convert = lambda src, dest, timeout: (False, "simulated failure")
        self.assertPassThrough(self.read_event(self.make("report.docx")))

    def test_malformed_event_is_ignored(self) -> None:
        sys.stdin = io.StringIO("not json")
        sys.stdout = io.StringIO()
        self.assertEqual(0, hook.main())

    def test_extension_list_is_configurable(self) -> None:
        os.environ["FOLDMARK_HOOK_EXTENSIONS"] = "rst, adoc"
        self.assertEqual({".rst", ".adoc"}, hook.wanted_extensions())
        self.assertPassThrough(self.read_event(self.make("report.docx")))


class SubprocessTests(unittest.TestCase):
    """Through the real process boundary, the way Claude Code invokes the hook."""

    def run_hook(self, source: Path, temp: str, **env_extra) -> subprocess.CompletedProcess:
        event = json.dumps({"tool_name": "Read", "tool_input": {"file_path": str(source)}})
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=temp, FOLDMARK_HOOK_TIMEOUT="60", **env_extra)
        return subprocess.run(
            [sys.executable, str(HOOK_PATH)], input=event,
            capture_output=True, text=True, env=env, timeout=120,
        )

    def test_conversion_failure_leaves_the_read_untouched(self) -> None:
        """Point the hook at an interpreter without MarkItDown; it must fail open."""
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "report.docx"
            source.write_bytes(b"not really a docx")
            result = self.run_hook(source, temp, FOLDMARK_PYTHON="/usr/bin/false")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stdout.strip(), "a failure must produce no decision")

    def test_real_document_is_converted_and_the_read_retargeted(self) -> None:
        try:
            import markitdown  # noqa: F401
        except ImportError:
            self.skipTest("MarkItDown is not installed in this environment")

        with tempfile.TemporaryDirectory() as temp:
            # A .zip of a .txt exercises a real MarkItDown converter without
            # needing any platform-specific tool to author the fixture.
            source = Path(temp) / "bundle.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("notes.txt", "QUARTERLY REVENUE REPORT\n\nRevenue grew 18 percent.\n")

            result = self.run_hook(source, temp)
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            output = payload["hookSpecificOutput"]
            self.assertEqual("allow", output["permissionDecision"])

            converted = Path(output["updatedInput"]["file_path"])
            self.assertTrue(converted.is_file())
            self.assertIn("QUARTERLY REVENUE REPORT", converted.read_text(encoding="utf-8"))
            self.assertIn("MarkItDown", output["additionalContext"])


if __name__ == "__main__":
    unittest.main()
