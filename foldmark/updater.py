"""GitHub release checking, download, verification, and staging.

Deliberately free of Tk and of any hard-coded network call in its testable
surface: ``check_for_update`` takes an injected ``fetch_json``, mirroring the
``Converter`` protocol used by ``converter.py`` so the whole update path can
be exercised without touching the network.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import posixpath
import shutil
import ssl
import stat
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

GITHUB_REPO = "bjaysingh/foldmark"
PROJECT_URL = f"https://github.com/{GITHUB_REPO}"
MARKITDOWN_URL = "https://github.com/microsoft/markitdown"

_API_TEMPLATE = "https://api.github.com/repos/{repo}/releases/latest"
_API_OVERRIDE_ENV = "MARKITDOWN_RELEASES_API"

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
NETWORK_TIMEOUT = 5.0
DOWNLOAD_TIMEOUT = 60.0
USER_AGENT = "MarkItDown-Desktop-Updater"

ASSET_PREFIX = "foldmark-"
ASSET_SUFFIX = "-source.zip"
CHECKSUMS_NAME = "SHA256SUMS.txt"

REQUIRED_ENTRIES = ("app.py", "requirements.txt", os.path.join("foldmark", "__init__.py"))

ALLOWED_HOSTS = {
    "github.com",
    "api.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


class UpdateError(Exception):
    """Any condition that makes an update unsafe to continue."""


def describe_network_error(exc: BaseException) -> str:
    """Turn a urllib failure into something a person can act on."""
    text = str(exc)
    if "CERTIFICATE_VERIFY_FAILED" in text:
        return (
            "Could not verify the connection to GitHub. On macOS, run "
            "\"Install Certificates.command\" from your Python installation folder, "
            "then try again."
        )
    if "HTTP Error 404" in text:
        return (
            "GitHub returned 404 for this project's releases. The repository may be "
            "private, or it may have no published releases yet."
        )
    if "HTTP Error 403" in text or "rate limit" in text.lower():
        return "GitHub temporarily rate-limited this check. Try again later."
    if "Name or service not known" in text or "nodename nor servname" in text or "getaddrinfo" in text:
        return "No internet connection was available."
    if "timed out" in text.lower():
        return "The connection to GitHub timed out."
    return f"Could not reach GitHub: {text}"


# --------------------------------------------------------------------------- versions


def parse_version(text: str) -> tuple[int, ...]:
    """Return a comparable tuple for a dotted version string.

    A pre-release ("1.2.0-rc1") must sort below its final release, so the
    numeric part is padded to three components and followed by a release flag
    (1 for final, 0 for pre-release) and the pre-release ordinal.
    """
    raw = (text or "").strip()
    if raw[:1] in {"v", "V"}:
        raw = raw[1:]
    core, _, pre = raw.partition("-")
    numbers: list[int] = []
    for part in core.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        numbers.append(int(digits))
    if not numbers:
        return (-1, 0, 0, 0, 0)
    numbers = (numbers + [0, 0, 0])[:3]
    if not pre:
        return (*numbers, 1, 0)
    ordinal = "".join(ch for ch in pre if ch.isdigit())
    return (*numbers, 0, int(ordinal) if ordinal else 0)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


# --------------------------------------------------------------------------- urls


def _api_url(repo: str) -> str:
    override = os.environ.get(_API_OVERRIDE_ENV)
    if override:
        return override.replace("{repo}", repo)
    return _API_TEMPLATE.format(repo=repo)


def check_url(url: str) -> str:
    """Refuse anything that is not HTTPS on a known GitHub host.

    The host allowlist is relaxed only when the API override environment
    variable is set, which exists solely so the offline end-to-end test can
    point the updater at a local http.server.
    """
    if os.environ.get(_API_OVERRIDE_ENV):
        return url
    parsed = urlparse(url or "")
    if parsed.scheme != "https":
        raise UpdateError("Update downloads must use HTTPS.")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise UpdateError(f"Refusing to download from an unexpected host: {parsed.hostname}")
    return url


def ssl_context() -> Any:
    """Verify TLS against certifi's bundle when it is available.

    A stock python.org install on macOS ships no CA certificates for OpenSSL
    until "Install Certificates.command" is run, so urllib raises
    CERTIFICATE_VERIFY_FAILED for every HTTPS call. certifi is already present
    as a MarkItDown dependency, so prefer its bundle and fall back to the
    system default only if it cannot be imported.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def default_fetch_json(url: str, timeout: float = NETWORK_TIMEOUT) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(  # noqa: S310 - scheme checked
        request, timeout=timeout, context=ssl_context()
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str, timeout: float = NETWORK_TIMEOUT) -> str:
    check_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(  # noqa: S310 - scheme checked
        request, timeout=timeout, context=ssl_context()
    ) as response:
        return response.read(1024 * 64).decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- release check


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag: str
    notes: str
    asset_url: str
    checksums_url: str
    asset_name: str
    size: int


def _find_asset(assets: list, predicate: Callable[[str], bool]) -> dict | None:
    for asset in assets:
        if isinstance(asset, dict) and isinstance(asset.get("name"), str) and predicate(asset["name"]):
            return asset
    return None


def check_for_update(
    current_version: str,
    *,
    fetch_json: Callable[..., Any] = default_fetch_json,
    repo: str = GITHUB_REPO,
    skipped_version: str | None = None,
    on_error: Callable[[str], None] | None = None,
) -> UpdateInfo | None:
    """Return the newer release to offer, or None.

    Every failure is a None, never an exception: a launch-time check must not
    be able to stop the app from opening. ``on_error`` receives the reason so a
    check the user asked for can say what went wrong rather than claiming the
    app is up to date.
    """
    try:
        payload = fetch_json(_api_url(repo), timeout=NETWORK_TIMEOUT)
    except Exception as exc:
        if on_error:
            on_error(describe_network_error(exc))
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("draft") or payload.get("prerelease"):
        return None

    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        return None
    version = tag.lstrip("vV").strip()
    if not is_newer(version, current_version):
        return None
    if skipped_version and parse_version(skipped_version) >= parse_version(version):
        return None

    assets = payload.get("assets")
    if not isinstance(assets, list):
        return None
    source = _find_asset(assets, lambda n: n.startswith(ASSET_PREFIX) and n.endswith(ASSET_SUFFIX))
    checksums = _find_asset(assets, lambda n: n == CHECKSUMS_NAME)
    if not source or not checksums:
        return None
    asset_url = source.get("browser_download_url")
    checksums_url = checksums.get("browser_download_url")
    if not isinstance(asset_url, str) or not isinstance(checksums_url, str):
        return None

    notes = payload.get("body")
    return UpdateInfo(
        version=version,
        tag=tag,
        notes=notes if isinstance(notes, str) else "",
        asset_url=asset_url,
        checksums_url=checksums_url,
        asset_name=source["name"],
        size=int(source.get("size") or 0),
    )


# --------------------------------------------------------------------------- download + verify


def download_asset(
    url: str,
    dest: Path,
    *,
    expected_size: int = 0,
    max_bytes: int = MAX_ARCHIVE_BYTES,
    progress: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    check_url(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    downloaded = 0
    try:
        with urllib.request.urlopen(  # noqa: S310 - scheme checked
            request, timeout=DOWNLOAD_TIMEOUT, context=ssl_context()
        ) as response:
            declared = int(response.headers.get("Content-Length") or expected_size or 0)
            if declared > max_bytes:
                raise UpdateError("The update download is larger than expected; refusing it.")
            total = declared or expected_size
            with dest.open("wb") as handle:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise UpdateError("Cancelled")
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise UpdateError("The update download exceeded the size limit.")
                    handle.write(chunk)
                    if progress:
                        progress(downloaded, total)
    except UpdateError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from exc
    return dest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksums(text: str) -> dict[str, str]:
    """Parse ``sha256sum`` output: '<digest>  <name>' or '<digest> *<name>'."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        digest, name = parts
        result[name.lstrip("*")] = digest.lower()
    return result


def verify_sha256(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if not expected or actual.lower() != expected.strip().lower():
        raise UpdateError("The downloaded update failed its checksum check and was discarded.")


# --------------------------------------------------------------------------- staging


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _safe_member_name(name: str) -> str:
    """Return the archive-relative path, or raise if the entry escapes the root."""
    if not name or name in {".", ".."}:
        raise UpdateError("The update archive contains an invalid entry.")
    if ntpath.isabs(name) or posixpath.isabs(name) or ntpath.splitdrive(name)[0]:
        raise UpdateError(f"The update archive contains an absolute path: {name}")
    normalised = name.replace("\\", "/")
    parts = [part for part in normalised.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise UpdateError(f"The update archive contains a path traversal entry: {name}")
    if not parts:
        raise UpdateError("The update archive contains an invalid entry.")
    return "/".join(parts)


def stage_archive(
    zip_path: Path, staging_dir: Path, *, max_bytes: int = MAX_ARCHIVE_BYTES
) -> Path:
    """Extract an update archive into a clean staging directory.

    Extraction is done entry by entry rather than with ``extractall`` so every
    member can be checked first: zip-slip paths, absolute paths, and symlink
    members are all rejected before anything is written to disk.
    """
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"The update archive could not be opened: {exc}") from exc

    with archive:
        members = archive.infolist()
        total = sum(info.file_size for info in members)
        if total > max_bytes:
            raise UpdateError("The update archive expands to more than the allowed size.")
        checked: list[tuple[zipfile.ZipInfo, str]] = []
        for info in members:
            if _is_symlink(info):
                raise UpdateError("The update archive contains a symbolic link; refusing it.")
            checked.append((info, _safe_member_name(info.filename)))

        root = staging_dir.resolve()
        for info, relative in checked:
            target = (staging_dir / relative).resolve()
            if target != root and root not in target.parents:
                raise UpdateError(f"The update archive contains an unsafe entry: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle, 64 * 1024)

    return _locate_tree(staging_dir)


def _locate_tree(staging_dir: Path) -> Path:
    """Unwrap a single top-level folder, which is how GitHub zipballs are shaped."""
    if (staging_dir / "app.py").exists():
        return staging_dir
    children = list(staging_dir.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return staging_dir


def validate_tree(tree: Path) -> None:
    missing = [entry for entry in REQUIRED_ENTRIES if not (tree / entry).exists()]
    if missing:
        raise UpdateError(f"The update is missing required files: {', '.join(missing)}")


# --------------------------------------------------------------------------- requirements


def _file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def requirements_changed(old_root: Path, new_root: Path) -> bool:
    """Compare content, not timestamps: an archive's mtimes carry no meaning."""
    old = _file_digest(old_root / "requirements.txt")
    new = _file_digest(new_root / "requirements.txt")
    if old is None or new is None:
        return True
    return old != new
