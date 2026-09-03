# MarkItDown Desktop

A Windows and macOS desktop app for the open-source
[Microsoft MarkItDown](https://github.com/microsoft/markitdown) conversion library — plus an
Obsidian plugin and a Claude Code plugin that share the same converter.

## What it does

- Converts one file, many files, or an entire folder into Markdown
- Supports PDF, Word (`.docx`), PowerPoint (`.pptx`), Excel (`.xlsx` and legacy `.xls`),
  HTML, CSV, JSON, XML, EPUB, ZIP, images, audio, email, and text
- Drag and drop, an output folder of your choosing, progress, preview, and copy
- Processes local file paths only; the app does not accept URLs
- Keeps going when one file in a batch fails
- Avoids accidental overwrites by adding `-2`, `-3`, and so on; a Markdown input is never overwritten in place
- **Checks GitHub for updates at launch**, shows the release notes, and installs on your say-so

MarkItDown optimizes its output for language models, indexing, and text analysis. It is not
designed to recreate the visual appearance of the source document.

**Formats it does not handle.** MarkItDown 0.1.7 registers no converter for the pre-2007 binary
`.doc` and `.ppt` formats, so the app refuses them rather than producing nothing. Open them in
Word or PowerPoint and save as `.docx` or `.pptx` first. Legacy `.xls` *is* supported.

**Images and scanned PDFs.** MarkItDown itself extracts no text from a photograph or from a
scanned PDF that has no text layer. The app fills that gap with OCR: on macOS it uses Apple's
Vision framework, which is part of the system and needs only the `pyobjc-framework-Vision`
binding; on Windows and Linux it uses Tesseract via `pytesseract`, which also needs the
Tesseract binary installed.

OCR runs only when it is needed. A file is converted normally first, and the engine is called
only if that produced no usable text, so PDFs that already carry a text layer are never
rasterised and their output does not change. If no engine is installed, such a file is still
reported as a failure — now with the install command for your platform. The About dialog names
the engine in use, or says there is none.

## Windows — first use

1. Install [Python 3.10 or newer](https://www.python.org/downloads/windows/). During installation, select **Add Python to PATH**.
2. Double-click `Setup-Windows.bat`. Internet access is needed during setup.
3. Double-click `Start-Windows.bat` whenever you want to use the app.

## macOS — first use

1. Install [Python 3.10 or newer](https://www.python.org/downloads/macos/).
2. Control-click `Setup-macOS.command`, choose **Open**, and confirm. Internet access is needed during setup.
3. Double-click `Start-macOS.command` whenever you want to use the app.

If macOS reports that Tkinter is missing, use the current universal Python installer from
python.org rather than a minimal command-line-only distribution.

**If update checks report a certificate problem**, run `Install Certificates.command` from your
`/Applications/Python 3.x/` folder. A fresh python.org install ships no CA certificates for
OpenSSL until that runs. The app prefers `certifi`'s bundle, which the setup script installs, so
this is rarely needed — but the message will tell you if it is.

## Everyday use

1. Drop files into the file list, or select **Add files** / **Add folder**.
2. Choose where the `.md` files should be saved.
3. Select **Convert to Markdown**.
4. Select any completed file to preview or copy its Markdown.

Shortcuts: `Ctrl/Cmd+O` adds files. `Ctrl/Cmd+Enter` starts conversion. `Delete` removes selected rows.

## Automatic updates

At launch the app asks GitHub for the newest release of
[bjaysingh/microsoftmarkitdown](https://github.com/bjaysingh/microsoftmarkitdown). If a newer
version exists you are shown its release notes and can choose **Update now**, **Later**, or
**Skip this version**. Choosing to update downloads a small source archive (tens of kilobytes,
not the Python environment), verifies it against the release's `SHA256SUMS.txt`, installs it,
and restarts the app on the new version.

**Safety:**

- The archive is rejected unless its SHA-256 matches the published checksum.
- Archive entries with absolute paths, `..` components, or symbolic links are refused.
- Your `.venv` is never touched by the swap. Dependencies are reinstalled only when
  `requirements.txt` actually changed.
- The previous version is kept in `.update/backup/<version>/`. If the new version fails to
  start, or a dependency install fails, the old one is restored automatically and you are told
  what went wrong the next time you open the app.
- Checksums prove the download was not corrupted or tampered with in transit. They do not prove
  who wrote it: anyone who controls the GitHub repository controls what your app installs.

**Turning it off:** set `"auto_check": false` in `~/.foldmark/settings.json`. The
**Check for updates…** button still works on demand.

## Obsidian plugin

`obsidian-plugin/` converts documents into Markdown notes inside a vault. Desktop-only, since
it runs a local Python process. See [`obsidian-plugin/README.md`](obsidian-plugin/README.md).

## Claude Code plugin

`claude-plugin/` converts PDFs, Office documents, e-books, email, and audio to Markdown before
Claude Code reads them, so the model receives text rather than raw bytes. See
[`claude-plugin/README.md`](claude-plugin/README.md).

## Command line

Both plugins — and anything else you want to script — use one entry point:

```bash
python -m foldmark.cli convert report.pdf notes/ --out out/ --json
python -m foldmark.cli convert report.pdf --stdout
python -m foldmark.cli extensions --json
python -m foldmark.cli version --json
```

Exit codes: `0` everything converted, `1` at least one file failed, `2` usage error.

## Optional: create a standalone executable

After setup, run `Build-Windows.bat` on Windows or `Build-macOS.command` on macOS. PyInstaller
creates the native app in `dist/`. Builds must be made on the target operating system.

Code signing is optional and picked up from the environment: `APPLE_DEVELOPER_ID` (plus
`APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` to notarize) on macOS, `WINDOWS_CERT_PATH` and
`WINDOWS_CERT_PASSWORD` on Windows. Unsigned builds still run, with a first-launch warning.

Note that the auto-updater applies to the source install described above, not to PyInstaller
bundles — those are rebuilt and redistributed rather than self-updating.

## Privacy and security

Conversion runs locally. MarkItDown reads files with the permissions of the current user, so
only open files you trust. This frontend deliberately calls MarkItDown's `convert_local()`
method and does not expose remote-URL conversion.

Audio transcription depends on the local libraries available to MarkItDown. OCR accuracy
depends on the engine and on scan quality; it recovers text, not layout, so a scanned table
comes back as lines rather than as a Markdown table. Complex PDFs may not preserve every table,
equation, or layout detail.

## Troubleshooting

- **Setup cannot download packages:** check the internet connection, VPN/proxy, and security software, then run setup again.
- **A file fails:** select another file to confirm the app works, then inspect the short error shown for the failed file. Password-protected, corrupted, or unusually complex documents may not convert.
- **Drag and drop is unavailable:** the Add files and Add folder buttons provide the same functionality.
- **An update did not install:** the app restores the previous version and shows the reason at next launch. `.update/last_error.txt` holds the same message.
- **Need a clean reinstall:** close the app, delete only the `.venv` folder inside this app folder, then rerun the setup script.

## For maintainers — cutting a release

1. Update `__version__` in `foldmark/__init__.py`.
2. Commit, then tag with a matching `v` prefix: `git tag v1.1.0 && git push --tags`.
3. `.github/workflows/release.yml` verifies the tag matches `__version__`, runs the tests,
   builds `markitdown-desktop-<version>-source.zip` plus `SHA256SUMS.txt`, publishes the
   release, and attaches the Obsidian plugin build and any signed desktop bundles.

The tag/version check is deliberate: a release whose version disagrees with the code would make
the updater loop or skip, so the workflow refuses to publish it.

## Tests

```bash
python -m unittest discover -s tests -t .
```

## License

MIT — see [LICENSE](LICENSE). The Obsidian plugin and the Claude Code plugin in this
repository are covered by the same license.

## Versions and attribution

Configured for MarkItDown 0.1.7 and TkinterDnD2 0.6.2. `requirements.txt` names the MarkItDown
extras the app actually uses rather than `[all]`: `[all]` pins `youtube-transcript-api~=1.0.0`,
which has no matching release on PyPI and makes the install fail, and it pulls in Azure SDKs and
YouTube support this app cannot reach — it converts local files only and never fetches a URL. MarkItDown is an open-source Microsoft
project licensed under MIT. This independent desktop frontend is not a Microsoft product and
does not imply Microsoft sponsorship.
