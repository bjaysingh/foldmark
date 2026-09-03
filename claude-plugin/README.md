# MarkItDown plugin for Claude Code

Converts documents Claude cannot read as text — PDFs, Word, PowerPoint, Excel, e-books,
email, and audio — into Markdown with [Microsoft MarkItDown](https://github.com/microsoft/markitdown),
so their content reaches the model instead of raw bytes.

## What it does

- **Automatic.** A `PreToolUse` hook on `Read` spots an unreadable document, converts it,
  caches the Markdown, and points the `Read` at the conversion. The agent is told plainly
  that it is reading a conversion and which file it came from.
- **On demand.** `/foldmark <path>` converts files or a whole folder and reports results.

## Requirements

A checkout of [bjaysingh/foldmark](https://github.com/bjaysingh/foldmark)
with its dependencies installed (`Setup-macOS.command` or `Setup-Windows.bat`). The plugin
finds it automatically when installed from inside that repository; otherwise set
`FOLDMARK_ROOT` to the checkout path.

## Settings

All optional, set as environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `FOLDMARK_ROOT` | auto-detected | Path to the checkout providing the converter |
| `MARKITDOWN_PYTHON` | the checkout's `.venv` | Interpreter used for conversion |
| `MARKITDOWN_HOOK_EXTENSIONS` | see below | Comma-separated list to convert, replacing the default set |
| `MARKITDOWN_HOOK_MAX_MB` | `40` | Files larger than this are left alone |
| `MARKITDOWN_HOOK_TIMEOUT` | `120` | Seconds before a conversion is abandoned |
| `MARKITDOWN_HOOK_DISABLE` | unset | Set to `1` to turn the automatic hook off |

Default extensions: `.pdf .docx .pptx .xlsx .xls .epub .msg .eml .zip .mp3 .wav .m4a .flac`

Images are deliberately excluded — Claude Code displays them natively, which is more useful
than OCR text for most questions.

## Behaviour guarantees

- **Fails open.** Any failure — missing MarkItDown, a timeout, a corrupt file — leaves the
  original `Read` to proceed untouched. The hook can never block work.
- **Cached by content.** The cache key includes the file's modification time and size, so an
  edited source reconverts and an unchanged one costs nothing on repeat reads.
- **Local only.** Conversion runs on your machine. Nothing is uploaded.

## Attribution

This plugin is an independent frontend for Microsoft MarkItDown, an open-source project
released by Microsoft under the MIT License. It is not a Microsoft product and is not
endorsed or sponsored by Microsoft.
