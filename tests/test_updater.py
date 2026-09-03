from pathlib import Path
import io
import stat
import tempfile
import unittest
import zipfile

from foldmark import updater


def release(tag: str, assets: list[str] | None = None, body: str = "notes") -> dict:
    names = assets if assets is not None else [
        f"foldmark-{tag.lstrip('v')}-source.zip",
        "SHA256SUMS.txt",
    ]
    return {
        "tag_name": tag,
        "body": body,
        "assets": [
            {
                "name": name,
                "size": 1234,
                "browser_download_url": f"https://github.com/o/r/releases/download/{tag}/{name}",
            }
            for name in names
        ],
    }


def make_zip(path: Path, entries: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


VALID_TREE = {
    "app.py": "print('hi')\n",
    "requirements.txt": "markitdown[all]==0.1.7\n",
    "foldmark/__init__.py": "__version__ = '1.1.0'\n",
}


class VersionTests(unittest.TestCase):
    def test_dotted_versions_compare_numerically(self) -> None:
        self.assertLess(updater.parse_version("1.2.0"), updater.parse_version("1.10.0"))
        self.assertLess(updater.parse_version("1.2"), updater.parse_version("1.2.1"))
        self.assertEqual(updater.parse_version("v1.2.0"), updater.parse_version("1.2.0"))

    def test_prerelease_sorts_below_its_release(self) -> None:
        self.assertLess(updater.parse_version("1.2.0-rc1"), updater.parse_version("1.2.0"))
        self.assertLess(updater.parse_version("1.2.0-rc1"), updater.parse_version("1.2.0-rc2"))

    def test_unparseable_version_is_lowest(self) -> None:
        self.assertLess(updater.parse_version("garbage"), updater.parse_version("0.0.1"))


class CheckForUpdateTests(unittest.TestCase):
    def fetch(self, payload):
        def _fetch(url: str, timeout: float = 5.0):
            self.requested = url
            return payload
        return _fetch

    def test_newer_release_is_offered(self) -> None:
        info = updater.check_for_update("1.0.0", fetch_json=self.fetch(release("v1.1.0")))
        self.assertIsNotNone(info)
        self.assertEqual("1.1.0", info.version)
        self.assertTrue(info.asset_url.endswith("foldmark-1.1.0-source.zip"))
        self.assertTrue(info.checksums_url.endswith("SHA256SUMS.txt"))
        self.assertEqual("notes", info.notes)

    def test_same_or_older_release_is_ignored(self) -> None:
        self.assertIsNone(updater.check_for_update("1.1.0", fetch_json=self.fetch(release("v1.1.0"))))
        self.assertIsNone(updater.check_for_update("1.2.0", fetch_json=self.fetch(release("v1.1.0"))))

    def test_skipped_version_suppresses_the_prompt(self) -> None:
        payload = release("v1.1.0")
        self.assertIsNone(
            updater.check_for_update("1.0.0", fetch_json=self.fetch(payload), skipped_version="1.1.0")
        )
        self.assertIsNotNone(
            updater.check_for_update("1.0.0", fetch_json=self.fetch(payload), skipped_version="1.0.5")
        )

    def test_release_without_source_asset_is_ignored(self) -> None:
        payload = release("v1.1.0", assets=["SHA256SUMS.txt"])
        self.assertIsNone(updater.check_for_update("1.0.0", fetch_json=self.fetch(payload)))

    def test_release_without_checksums_is_ignored(self) -> None:
        payload = release("v1.1.0", assets=["foldmark-1.1.0-source.zip"])
        self.assertIsNone(updater.check_for_update("1.0.0", fetch_json=self.fetch(payload)))

    def test_draft_and_prerelease_are_ignored(self) -> None:
        payload = release("v1.1.0")
        payload["prerelease"] = True
        self.assertIsNone(updater.check_for_update("1.0.0", fetch_json=self.fetch(payload)))

    def test_malformed_payload_returns_none(self) -> None:
        for payload in ({}, {"tag_name": "v1.1.0"}, [], None, {"tag_name": "", "assets": []}):
            self.assertIsNone(updater.check_for_update("1.0.0", fetch_json=self.fetch(payload)))

    def test_repo_slug_is_used_in_the_request(self) -> None:
        updater.check_for_update("1.0.0", fetch_json=self.fetch(release("v1.1.0")))
        self.assertIn("bjaysingh/foldmark", self.requested)


class ChecksumTests(unittest.TestCase):
    def test_checksums_file_is_parsed(self) -> None:
        text = "abc123  foldmark-1.1.0-source.zip\ndef456 *other.zip\n"
        parsed = updater.parse_checksums(text)
        self.assertEqual("abc123", parsed["foldmark-1.1.0-source.zip"])
        self.assertEqual("def456", parsed["other.zip"])

    def test_mismatched_digest_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "payload.zip"
            target.write_bytes(b"hello")
            actual = updater.sha256_file(target)
            updater.verify_sha256(target, actual)
            with self.assertRaises(updater.UpdateError):
                updater.verify_sha256(target, "0" * 64)


class StagingTests(unittest.TestCase):
    def stage(self, entries: dict[str, str], temp: str):
        archive = make_zip(Path(temp) / "payload.zip", entries)
        return updater.stage_archive(archive, Path(temp) / "staging")

    def test_valid_archive_stages_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tree = self.stage(VALID_TREE, temp)
            updater.validate_tree(tree)
            self.assertTrue((tree / "app.py").exists())
            self.assertTrue((tree / "foldmark" / "__init__.py").exists())

    def test_single_wrapper_directory_is_unwrapped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            wrapped = {f"foldmark-1.1.0/{k}": v for k, v in VALID_TREE.items()}
            tree = self.stage(wrapped, temp)
            updater.validate_tree(tree)
            self.assertTrue((tree / "app.py").exists())

    def test_zip_slip_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(updater.UpdateError):
                self.stage({**VALID_TREE, "../evil.py": "pwned"}, temp)
            self.assertFalse((Path(temp).parent / "evil.py").exists())

    def test_absolute_path_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(updater.UpdateError):
                self.stage({**VALID_TREE, "/etc/evil.py": "pwned"}, temp)

    def test_backslash_traversal_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(updater.UpdateError):
                self.stage({**VALID_TREE, "..\\evil.py": "pwned"}, temp)

    def test_symlink_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "payload.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for name, content in VALID_TREE.items():
                    archive.writestr(name, content)
                info = zipfile.ZipInfo("link.py")
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "/etc/passwd")
            with self.assertRaises(updater.UpdateError):
                updater.stage_archive(archive_path, Path(temp) / "staging")

    def test_oversized_archive_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = make_zip(Path(temp) / "payload.zip", VALID_TREE)
            with self.assertRaises(updater.UpdateError):
                updater.stage_archive(archive, Path(temp) / "staging", max_bytes=10)

    def test_tree_missing_required_files_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tree = self.stage({"app.py": "x", "requirements.txt": "y"}, temp)
            with self.assertRaises(updater.UpdateError):
                updater.validate_tree(tree)


class RequirementsTests(unittest.TestCase):
    def test_change_is_detected_by_content_not_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / "old"
            new = Path(temp) / "new"
            old.mkdir()
            new.mkdir()
            (old / "requirements.txt").write_text("a==1\n", encoding="utf-8")
            (new / "requirements.txt").write_text("a==1\n", encoding="utf-8")
            self.assertFalse(updater.requirements_changed(old, new))
            (new / "requirements.txt").write_text("a==2\n", encoding="utf-8")
            self.assertTrue(updater.requirements_changed(old, new))

    def test_missing_file_counts_as_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / "old"
            new = Path(temp) / "new"
            old.mkdir()
            new.mkdir()
            (new / "requirements.txt").write_text("a==1\n", encoding="utf-8")
            self.assertTrue(updater.requirements_changed(old, new))


class NetworkFailureTests(unittest.TestCase):
    def test_check_reports_why_it_failed(self) -> None:
        """A user-initiated check must not answer "up to date" after a failure."""
        def boom(url: str, timeout: float = 5.0):
            raise OSError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

        reasons: list[str] = []
        info = updater.check_for_update("1.0.0", fetch_json=boom, on_error=reasons.append)
        self.assertIsNone(info)
        self.assertEqual(1, len(reasons))
        self.assertIn("Install Certificates", reasons[0])

    def test_check_still_returns_none_without_a_reporter(self) -> None:
        def boom(url: str, timeout: float = 5.0):
            raise OSError("no network")

        self.assertIsNone(updater.check_for_update("1.0.0", fetch_json=boom))

    def test_failures_are_described_in_terms_a_person_can_act_on(self) -> None:
        cases = [
            ("[SSL: CERTIFICATE_VERIFY_FAILED] x", "Install Certificates"),
            ("HTTP Error 404: Not Found", "private"),
            ("HTTP Error 403: rate limit exceeded", "rate-limited"),
            ("<urlopen error [Errno 8] nodename nor servname provided>", "internet"),
            ("The read operation timed out", "timed out"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertIn(expected, updater.describe_network_error(OSError(raw)))

    def test_ssl_context_prefers_certifi_when_available(self) -> None:
        try:
            import certifi  # noqa: F401
        except ImportError:
            self.skipTest("certifi is not installed in this environment")
        self.assertIsNotNone(updater.ssl_context())


class UrlGuardTests(unittest.TestCase):
    def test_non_https_is_refused(self) -> None:
        with self.assertRaises(updater.UpdateError):
            updater.check_url("http://github.com/o/r/x.zip")

    def test_foreign_host_is_refused(self) -> None:
        with self.assertRaises(updater.UpdateError):
            updater.check_url("https://evil.example.com/x.zip")

    def test_github_hosts_are_allowed(self) -> None:
        updater.check_url("https://github.com/o/r/releases/download/v1/x.zip")
        updater.check_url("https://objects.githubusercontent.com/x.zip")


if __name__ == "__main__":
    unittest.main()
