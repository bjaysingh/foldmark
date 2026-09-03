# Renaming the product to Foldmark

**Date:** 2026-09-03
**Status:** approved, not yet implemented
**Scope:** rename the product from "MarkItDown Desktop" to "Foldmark" across every surface —
UI, code, files, folders, documentation and the repository itself.

## Why this is not a find-and-replace

The repository contains 332 case-insensitive occurrences of "markitdown", and they are three
different things:

1. **The product's own name** — "MarkItDown Desktop", `markitdown_desktop`, `APP_NAME`, the
   plugin identifiers. These become Foldmark.
2. **The dependency** — Microsoft's MarkItDown library. `from markitdown import MarkItDown`,
   the `markitdown[...]==0.1.7` pin, `convert_local()`. These must not change; the product is
   a frontend for that library and stops working without it.
3. **Attribution to the dependency** — 28 occurrences of the exact phrase "Microsoft
   MarkItDown" across the About dialog, README and THIRD-PARTY-NOTICES. MarkItDown is MIT
   licensed, and MIT requires its notice to accompany every copy. Removing this would be a
   licence violation, not a cosmetic error.

A bulk replace would silently destroy categories 2 and 3. The rename must therefore be
targeted, and the acceptance test must prove the attribution survived.

## Decisions

Settled with the user before implementation:

| Question | Decision |
|---|---|
| Existing installs | **Clean break.** v1.0.3 published the same day; no real installed base. No settings migration, no orphan-directory handling, no compatibility shims. |
| Identifier scheme | **Plain `foldmark`.** Not `foldmark_desktop`. The product is called Foldmark and nothing retains the old name. |
| GUI entry point | **`app.py` keeps its name.** The launcher scripts and PyInstaller specs reference it; renaming buys nothing. |
| Working copy and remote | **Both move.** The folder becomes `~/Claude/Projects/Foldmark` and `origin` points at `github.com/bjaysingh/foldmark`. |
| Version | **2.0.0.** Nothing functional changes, but every integration point breaks — module path, plugin identifiers, settings location. That is what a major bump is for. |

## What changes

| Now | Becomes |
|---|---|
| `markitdown_desktop/` package (72 references) | `foldmark/` |
| `python -m markitdown_desktop.cli` | `python -m foldmark.cli` |
| `APP_NAME = "MarkItDown"` in `app.py` | `"Foldmark"` |
| `~/.markitdown_desktop/settings.json` | `~/.foldmark/settings.json` |
| `GITHUB_REPO = "bjaysingh/microsoftmarkitdown"` | `"bjaysingh/foldmark"` |
| Obsidian plugin `id` `markitdown`, `name` `MarkItDown` | `foldmark`, `Foldmark` |
| Obsidian npm package `obsidian-markitdown` | `obsidian-foldmark` |
| Claude plugin `name` `markitdown` | `foldmark` |
| `claude-plugin/commands/markitdown.md` | `claude-plugin/commands/foldmark.md` |
| `claude-plugin/hooks/markitdown_read_hook.py` | `claude-plugin/hooks/foldmark_read_hook.py` |
| `markitdown-desktop-<version>-source.zip` | `foldmark-<version>-source.zip` |
| `~/Claude/Projects/MicrosoftMarkItDown` | `~/Claude/Projects/Foldmark` |

`hooks.json` must be updated in step with the hook filename, or the Claude Code plugin's
`PreToolUse` hook silently stops firing.

## What explicitly does not change

- `from markitdown import MarkItDown` and `convert_local()` in `converter.py`
- The `markitdown[pdf,docx,xlsx,xls,pptx,outlook,audio-transcription]==0.1.7` pin
- `MARKITDOWN_URL = "https://github.com/microsoft/markitdown"`
- `markitdown_version()` and the `markitdown_version` key in `version --json` — both report the
  dependency's version, so the name is correct as it stands
- Every occurrence of the phrase "Microsoft MarkItDown"
- `app.py`, and the `Setup-*` / `Start-*` / `Build-*` launcher filenames

## Release mechanics

`updater.py:40` matches release assets by the suffix `-source.zip`, not by the full filename,
so renaming the archive does not break asset resolution. This was verified by reading the
matcher rather than assumed.

`release.yml` refuses a tag that disagrees with `__version__`, so the version bump and the tag
must agree, as for any release. The five version declarations named in CLAUDE.md all still
apply.

Because the rename is a clean break, no shipped install will update itself across it. The
`_managed_names` orphan problem — a renamed release ships `foldmark/` while the old install
still holds `markitdown_desktop/`, which is not in staging and so is never removed — is
therefore accepted rather than solved. It would need addressing only if the clean-break
decision were reversed.

## Verification

The rename is complete when all of the following pass:

1. Full suite green (122 tests).
2. Suite green in a dependency-free venv, as `release.yml` runs it.
3. `npm run build` succeeds in `obsidian-plugin/`.
4. `claude plugin validate ./claude-plugin` passes.
5. A real conversion through the renamed CLI, including OCR on an image.
6. The GUI launches and the window title reads "Foldmark".
7. **Grep audit.** Zero hits for `markitdown_desktop`, `MarkItDown Desktop` or
   `microsoftmarkitdown`; the count of `Microsoft MarkItDown` is still **exactly 28**.

Item 7 is the acceptance test that distinguishes this from a careless bulk replace. The
attribution count holding steady is the evidence that categories 2 and 3 above survived.

## Order of operations

1. Rename inside the repository; run checks 1 to 7.
2. Commit.
3. Move the working copy and repoint `origin`.
4. Bump to 2.0.0 across the five version files, tag, release.

Steps 1 and 3 are separated deliberately: if the in-repo rename needs fixing, that is far
easier before the working copy moves out from under the session.

## Follow-up the user must do by hand

Neither survives a clean break, and neither can be fixed from inside the repository:

- The demo install at `~/Desktop/MarkItDown-Desktop-v1.0.0-demo/` — delete and reinstall.
- The vault plugin at `~/Claude/Projects/.obsidian/plugins/markitdown/` — delete, reinstall as
  `foldmark`, and re-enable it in Obsidian.
