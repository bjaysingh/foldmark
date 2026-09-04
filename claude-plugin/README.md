# Foldmark plugin for Claude Code

Converts documents Claude cannot read as text — PDFs, Word, PowerPoint, Excel, e-books,
email, and audio — into Markdown with [Microsoft MarkItDown](https://github.com/microsoft/markitdown),
so their content reaches the model instead of raw bytes.

## What it does

- **Automatic.** A `PreToolUse` hook on `Read` spots an unreadable document, converts it,
  caches the Markdown, and points the `Read` at the conversion. The agent is told plainly
  that it is reading a conversion and which file it came from.
- **On demand.** `/foldmark <path>` converts files or a whole folder and reports results.

## Installing it in Claude Code

Two routes. Both need the converter itself available — see Requirements below.

### From the marketplace (normal use)

The repository publishes itself as a Claude Code marketplace, so it installs by name:

```bash
claude plugin marketplace add bjaysingh/foldmark
claude plugin install foldmark@foldmark
```

Restart Claude Code, then confirm it is loaded:

```bash
claude plugin list
```

To update later, and to remove it:

```bash
claude plugin update foldmark      # restart to apply
claude plugin uninstall foldmark
```

### From a local checkout (development)

Loads the plugin for one session without installing it, which is the fastest way to try a
change:

```bash
claude --plugin-dir ./claude-plugin
```

### Checking it actually works

Registration is silent when it succeeds, so verify against a real document rather than
assuming. In a session with the plugin loaded, ask Claude to read a PDF:

```
Read ~/Desktop/report.pdf and quote its first line.
```

If the plugin is active, Claude reports that it read a MarkItDown conversion and names the
cache file it came from. If it is not, Claude sees the raw PDF bytes instead.

You can also drive that check non-interactively, which is useful in scripts and CI:

```bash
claude -p "Use the Read tool on /path/to/report.pdf and quote the first line verbatim." \
  --plugin-dir ./claude-plugin --allowed-tools Read
```

### Where the cache goes

Inside Claude Code the conversions are written under `$CLAUDE_PLUGIN_DATA/foldmark-cache/`.
Outside a plugin context — running the hook directly, or in tests — the same code falls back to
`~/.foldmark/foldmark-cache/`. Both are correct; seeing two different paths is not a bug.

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
| `FOLDMARK_PYTHON` | the checkout's `.venv` | Interpreter used for conversion |
| `FOLDMARK_HOOK_EXTENSIONS` | see below | Comma-separated list to convert, replacing the default set |
| `FOLDMARK_HOOK_MAX_MB` | `40` | Files larger than this are left alone |
| `FOLDMARK_HOOK_TIMEOUT` | `120` | Seconds before a conversion is abandoned |
| `FOLDMARK_HOOK_DISABLE` | unset | Set to `1` to turn the automatic hook off |

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
