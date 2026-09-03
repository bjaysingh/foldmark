# MarkItDown for Obsidian

Converts PDFs, Word, PowerPoint, Excel, e-books, email, and audio into Markdown notes in your
vault, using [Microsoft MarkItDown](https://github.com/microsoft/markitdown).

Desktop only — the plugin runs a local Python process, which Obsidian mobile cannot do.

## Requirements

A checkout of [bjaysingh/microsoftmarkitdown](https://github.com/bjaysingh/microsoftmarkitdown)
with its setup script run (`Setup-macOS.command` or `Setup-Windows.bat`). That provides both
Python and Microsoft MarkItDown.

The plugin looks for it in this order:

1. The **Converter location** set in plugin settings
2. `$MARKITDOWN_DESKTOP_ROOT`
3. `~/microsoftmarkitdown`, `~/Documents/microsoftmarkitdown`, `~/Claude/Projects/MicrosoftMarkItDown`

Use **Settings → MarkItDown → Test setup** to confirm it works. That button reports the
interpreter, the Python version, and the installed MarkItDown version, so a misconfiguration
shows up during setup rather than at conversion time.

## Using it

- **Ribbon icon** or **Convert the current file to Markdown** — converts the active file
- **Convert every supported file in a folder** — converts the active file's folder
- **Right-click a file or folder** in the file explorer → *Convert with MarkItDown*

Converted notes land in the vault folder named in settings (default `MarkItDown`). Existing
notes are never overwritten: a name clash becomes `-2`, `-3`, and so on, matching the desktop
app's behaviour.

## Settings

| Setting | Default | Purpose |
|---|---|---|
| Converter location | auto-detect | Folder containing `foldmark/` |
| Python interpreter | auto-detect | Overrides the converter's own `.venv` |
| Output folder | `MarkItDown` | Vault-relative destination for converted notes |
| Open the note after converting | on | Opens the first result |
| Conversion timeout | 300s | Limit for one batch |

## Development

```bash
npm install
npm run dev     # watch build
npm run build   # type-check, then a minified bundle
```

To test in a vault, copy `main.js`, `manifest.json`, and `styles.css` (if present) into
`<vault>/.obsidian/plugins/markitdown/`.

## How conversion runs

A folder of fifty documents is converted in **one** Python process
(`python -m foldmark.cli convert … --out <temp> --json`) rather than fifty, because
starting Python and importing MarkItDown costs about a second each time. The results are then
imported through Obsidian's vault API so they are indexed and linked immediately.

Conversion happens entirely on your machine. Nothing is uploaded.

## Attribution

This plugin is an independent frontend for Microsoft MarkItDown, an open-source project
released by Microsoft under the MIT License. It is not a Microsoft product and is not endorsed
or sponsored by Microsoft. “Microsoft” and related marks belong to Microsoft Corporation.
