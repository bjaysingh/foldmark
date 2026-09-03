# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# First-time setup (creates .venv, installs dependencies)
./Setup-macOS.command          # macOS
Setup-Windows.bat              # Windows

# Run the desktop app
.venv/bin/python app.py

# Tests
.venv/bin/python -m unittest discover -s tests -t .        # all
.venv/bin/python -m unittest tests.test_updater            # one module
.venv/bin/python -m unittest tests.test_updater.VersionTests.test_prerelease_sorts_below_its_release

# The shared CLI both plugins call
.venv/bin/python -m markitdown_desktop.cli convert <paths> --out <dir> --json
.venv/bin/python -m markitdown_desktop.cli convert <file> --stdout
.venv/bin/python -m markitdown_desktop.cli version --json

# Obsidian plugin
cd obsidian-plugin && npm install && npm run build     # tsc --noEmit, then esbuild
cd obsidian-plugin && npm run dev                      # watch build

# Claude Code plugin
claude plugin validate ./claude-plugin
claude --plugin-dir ./claude-plugin                    # load it in a session
```

The `-t .` on `unittest discover` is required — without it the tests directory becomes the
import root and `markitdown_desktop` cannot be imported.

## Architecture

### One conversion path, three consumers

`markitdown_desktop/converter.py` is the only code that converts anything. The desktop GUI,
the Obsidian plugin and the Claude Code plugin all reach it, the last two by shelling out to
`markitdown_desktop/cli.py`. Obsidian plugins are TypeScript in Electron and Claude Code
plugins are Node; neither can call a Python library in-process, so the CLI is the seam. A
change to supported extensions, output naming or failure handling propagates to all three
automatically — and must not be reimplemented in either plugin.

### Dependency injection is what makes the suite offline

Two protocols carry this. `converter.py` takes a `Converter`, so tests inject `FakeConverter`
and never invoke MarkItDown. `updater.check_for_update` takes a `fetch_json` callable, so the
entire update path is exercised with no network. Follow this pattern for anything new that
touches the outside world; the suite must stay runnable with no network and no MarkItDown
installed.

### Updates run as two processes

A running interpreter cannot safely have its own package directory replaced, and Windows
locks files held open by a running process. So `app.py` stages a verified update, then spawns
`markitdown_desktop/apply_update.py` **detached** and exits; the helper waits for the parent
PID, swaps the trees, and relaunches.

Consequences that are easy to break:

- `apply_update.py` **must not import anything from `markitdown_desktop`** — that package is
  precisely what is being replaced while it runs. It is copied to `.update/apply_update.py`
  and executed as a standalone script.
- The swap only replaces what the update ships (`_managed_names`). `.venv`, `.update` and
  `.git` are never touched, and unrelated files in the install folder survive.
- Any failure — bad checksum, failed `pip install`, a tree that will not import — restores
  the backup and relaunches the old version. Never leave the user without a working app.

### Tk layout invariant

In `app.py:_build_ui`, the header, footer bar and action bar are packed **before** the content
area. Tk's packer refuses to *map* children it cannot fit rather than clipping them, so when
the action row was the last child of an expanding body, a short window left the Convert
button, Cancel and the progress bar entirely absent from the UI. Do not reorder those calls.
`tests/test_app_window.py` guards this down to 600x340.

### Window tests run in subprocesses

Tk 9.0 on macOS segfaults (exit 139) when one interpreter builds and destroys windows
repeatedly, taking the whole run down. Each probe in `tests/test_app_window.py` therefore
runs in a fresh interpreter. Do not "simplify" it back to in-process Tk roots. A probe must
also never call `root.withdraw()` before checking `winfo_ismapped()` — a withdrawn toplevel
reports every child as unmapped, which makes layout assertions silently vacuous.

## Releasing

`markitdown_desktop/__init__.py::__version__` is the single source of truth.
`.github/workflows/release.yml` refuses a tag that disagrees with it.

1. Bump `__version__`, plus `obsidian-plugin/manifest.json`, `obsidian-plugin/package.json`,
   `obsidian-plugin/versions.json` and `claude-plugin/.claude-plugin/plugin.json`.
2. Commit, then `git tag vX.Y.Z && git push origin main --tags`.

The workflow runs the tests, builds `markitdown-desktop-<version>-source.zip` plus
`SHA256SUMS.txt` (the exact format `updater.parse_checksums` consumes), publishes the release
and attaches the Obsidian plugin build. `LICENSE` must stay in the archive: MIT requires the
notice to accompany every copy, and that archive is what the updater installs.

PyInstaller bundles build but are only attached when signing secrets exist. Unsigned releases
are the intended default, not a misconfiguration.

## Constraints worth knowing

- **`requirements.txt` deliberately does not use `markitdown[all]`.** That extra pins
  `youtube-transcript-api~=1.0.0`, which has no matching release on PyPI, so the install fails
  outright. It also pulls Azure SDKs and YouTube support this app cannot reach — it converts
  local files only, via `convert_local()`, and never accepts a URL.
- **MarkItDown 0.1.7 supports neither legacy `.doc` nor `.ppt`** — it registers no converter
  for either binary format. Legacy `.xls` *is* supported. Both are absent from
  `SUPPORTED_EXTENSIONS` and are refused with a clear message.
- **Images and scanned PDFs produce no text** without OCR, which MarkItDown does not include.
  An empty conversion is reported as a failure rather than written as a 0-byte file.
- **Update integrity is checksum-based, not authenticated.** SHA-256 proves the download was
  not corrupted in transit; it does not prove authorship. Whoever controls the repository
  controls what users install.
