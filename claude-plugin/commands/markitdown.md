---
description: Convert PDFs, Office documents, e-books, email, or audio to Markdown with Microsoft MarkItDown.
argument-hint: <file-or-folder> [more paths...]
allowed-tools: Bash, Read
---

Convert the paths given in `$ARGUMENTS` to Markdown using Microsoft MarkItDown, then
summarise what was produced.

Steps:

1. If `$ARGUMENTS` is empty, ask which file or folder to convert and stop.
2. Locate the converter. Try, in order:
   - `$MARKITDOWN_DESKTOP_ROOT`
   - the directory above `${CLAUDE_PLUGIN_ROOT}`
   Run `python3 -m foldmark.cli version --json` from that directory to confirm it
   works. If neither location works, tell the user to set `MARKITDOWN_DESKTOP_ROOT` to their
   checkout of https://github.com/bjaysingh/microsoftmarkitdown and stop.
3. Convert into a folder next to the sources, or into the folder the user named:

   ```
   python3 -m foldmark.cli convert <paths> --out <output-folder> --json
   ```

4. Report each file's outcome from the JSON: what converted, what failed and why, and how
   many unsupported items were skipped. Name the output folder.
5. Offer to read any converted file if the user wants its content in the conversation.

Do not convert files the user did not name, and do not overwrite existing Markdown unless
they ask for `--overwrite`.

Conversion uses [Microsoft MarkItDown](https://github.com/microsoft/markitdown), an
open-source MIT-licensed Microsoft project.
