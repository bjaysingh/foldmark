# Foldmark Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the product from "MarkItDown Desktop" to "Foldmark" across every surface, without disturbing the Microsoft MarkItDown dependency or its MIT-required attribution.

**Architecture:** A targeted rename, not a bulk replace. Three categories of the string "markitdown" coexist in this repository: the product's own name (renamed), the dependency's import and pin (untouched), and attribution to the dependency (untouched). Each task renames one surface and ends green; the final task proves by grep audit that categories two and three survived.

**Tech Stack:** Python 3.14 + Tk, TypeScript/esbuild (Obsidian plugin), Node (Claude Code plugin), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-03-foldmark-rename-design.md`

## Global Constraints

- **Never rename** `from markitdown import MarkItDown`, `convert_local()`, or the pin `markitdown[pdf,docx,xlsx,xls,pptx,outlook,audio-transcription]==0.1.7`.
- **Never rename** the phrase `Microsoft MarkItDown`. It must appear exactly **28** times when
  the work is done. (That figure is a snapshot of the rename's completion. The count may
  legitimately rise later when a new file credits the dependency — `.claude-plugin/marketplace.json`
  took it to 29 on the same day. What must never happen is the count *falling*, which would
  mean an existing attribution was renamed away.)
- **Never rename** `MARKITDOWN_URL = "https://github.com/microsoft/markitdown"`.
- **Never rename** `markitdown_version()` or the `markitdown_version` key in `version --json` — both report the dependency's version.
- **Never rename** `shutil.which("markitdown")` in the Claude plugin hook — that resolves Microsoft's own CLI binary.
- Package name is `foldmark`, not `foldmark_desktop`. CLI is `python -m foldmark.cli`.
- `app.py` keeps its filename. So do all `Setup-*`, `Start-*` and `Build-*` scripts.
- Settings move to `~/.foldmark/settings.json`. No migration from the old path — this is a clean break.
- Use `git mv` for every file and directory move so history is preserved.
- Run tests with `.venv/bin/python -m unittest discover -s tests -t .` — the `-t .` is required.

---

### Task 1: Rename the Python package

**Files:**
- Move: `markitdown_desktop/` → `foldmark/`
- Modify: `app.py` (6 refs, plus `APP_NAME`), `foldmark/cli.py` (6), `foldmark/apply_update.py` (3), `foldmark/settings.py` (1), `foldmark/updater.py` (1)
- Test: `tests/test_app_window.py`, `tests/test_apply_update.py`, `tests/test_cli.py`, `tests/test_converter.py`, `tests/test_ocr.py`, `tests/test_ocr_surfaces.py`, `tests/test_updater.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the module path `foldmark.cli` with unchanged CLI surface (`convert`, `extensions`, `version`; flags `--out --stdout --overwrite --json --ocr --ocr-language`), `foldmark.ocr.available_engine()`, `foldmark.settings.SETTINGS_DIR == Path.home() / ".foldmark"`. Tasks 2 and 3 invoke `python -m foldmark.cli`.

- [ ] **Step 1: Move the package and confirm the suite breaks**

```bash
git mv markitdown_desktop foldmark
.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3
```

Expected: FAIL with `ModuleNotFoundError: No module named 'markitdown_desktop'`. This is the failing state that the rest of the task fixes.

- [ ] **Step 2: Rewrite the package references**

Only the product identifier is touched. `markitdown_version` survives because it is not `markitdown_desktop`.

```bash
grep -rl "markitdown_desktop" --exclude-dir=.git --exclude-dir=.venv \
  --exclude-dir=node_modules --exclude-dir=build --exclude-dir=specs --exclude-dir=plans . \
  | xargs sed -i '' 's/markitdown_desktop/foldmark/g'
```

- [ ] **Step 3: Rename the settings directory and the product constants**

```bash
sed -i '' 's/^APP_NAME = "MarkItDown"$/APP_NAME = "Foldmark"/' app.py
sed -i '' 's|GITHUB_REPO = "bjaysingh/microsoftmarkitdown"|GITHUB_REPO = "bjaysingh/foldmark"|' foldmark/updater.py
```

Verify each landed:

```bash
grep -n 'SETTINGS_DIR' foldmark/settings.py    # expect Path.home() / ".foldmark"
grep -n '^APP_NAME' app.py                      # expect "Foldmark"
grep -n '^GITHUB_REPO' foldmark/updater.py      # expect "bjaysingh/foldmark"
```

`SETTINGS_DIR` needs no `sed` of its own: step 2 already rewrote `.markitdown_desktop` to `.foldmark` inside it. The `grep` above is the assertion that it did. If it shows anything else, fix it by hand before continuing.

- [ ] **Step 4: Rename the remaining product-name strings in this surface**

```bash
sed -i '' 's/MarkItDown Desktop/Foldmark/g' foldmark/cli.py foldmark/update_ui.py
```

Check the attribution in `update_ui.py` was not caught in the crossfire:

```bash
grep -c "Microsoft MarkItDown" foldmark/update_ui.py   # expect 1
```

- [ ] **Step 5: Run the suite**

```bash
.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3
```

Expected: `Ran 122 tests` / `OK`.

- [ ] **Step 6: Confirm the CLI works under its new name, OCR included**

```bash
.venv/bin/python -m foldmark.cli version
.venv/bin/python -m foldmark.cli convert ~/Desktop/MarkItDown-test-documents/chart.png --stdout
```

Expected: version reports `Foldmark 1.0.3` with `OCR Apple Vision`; the image converts to `QUARTERLY REVENUE REPORT`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: rename the markitdown_desktop package to foldmark"
```

---

### Task 2: Rename the Claude Code plugin

**Files:**
- Move: `claude-plugin/commands/markitdown.md` → `claude-plugin/commands/foldmark.md`
- Move: `claude-plugin/hooks/markitdown_read_hook.py` → `claude-plugin/hooks/foldmark_read_hook.py`
- Modify: `claude-plugin/hooks/hooks.json`, `claude-plugin/.claude-plugin/plugin.json`, `claude-plugin/README.md`
- Test: `tests/test_read_hook.py:18`

**Interfaces:**
- Consumes: `python -m foldmark.cli convert <file> --stdout` from Task 1.
- Produces: plugin named `foldmark`, slash command `/foldmark`, hook script `foldmark_read_hook.py`, cache at `~/.foldmark/foldmark-cache`.

- [ ] **Step 1: Point the test at the new filename and watch it fail**

```bash
sed -i '' 's/markitdown_read_hook/foldmark_read_hook/g' tests/test_read_hook.py
.venv/bin/python -m unittest tests.test_read_hook 2>&1 | tail -3
```

Expected: FAIL — the hook file does not exist at the new path yet.

- [ ] **Step 2: Move the files**

```bash
git mv claude-plugin/hooks/markitdown_read_hook.py claude-plugin/hooks/foldmark_read_hook.py
git mv claude-plugin/commands/markitdown.md claude-plugin/commands/foldmark.md
```

- [ ] **Step 3: Update the hook registration**

`hooks.json` names the script by path. If it is not updated in step with the move, the `PreToolUse` hook silently stops firing — no error, the feature just disappears.

```bash
sed -i '' 's/markitdown_read_hook/foldmark_read_hook/g' claude-plugin/hooks/hooks.json
grep -n "foldmark_read_hook" claude-plugin/hooks/hooks.json   # expect one hit
```

- [ ] **Step 4: Rename the environment-variable override**

`MARKITDOWN_DESKTOP_ROOT` lets a user point the plugin at a checkout. It becomes
`FOLDMARK_ROOT`. Clean break: no fallback to the old name.

```bash
sed -i '' 's/MARKITDOWN_DESKTOP_ROOT/FOLDMARK_ROOT/g' \
  claude-plugin/hooks/foldmark_read_hook.py claude-plugin/README.md claude-plugin/commands/foldmark.md
grep -rn "MARKITDOWN_DESKTOP_ROOT" claude-plugin/ || echo "none left in claude-plugin"
```

- [ ] **Step 5: Rename the plugin identity and the cache directory**

```bash
sed -i '' 's/"name": "markitdown"/"name": "foldmark"/' claude-plugin/.claude-plugin/plugin.json
sed -i '' 's|"markitdown-cache"|"foldmark-cache"|; s|/ "markitdown-cache"|/ "foldmark-cache"|' \
  claude-plugin/hooks/foldmark_read_hook.py
sed -i '' 's|markitdown-cache|foldmark-cache|g' claude-plugin/hooks/foldmark_read_hook.py
```

- [ ] **Step 6: Verify the Microsoft binary lookup survived**

This is the trap in this task. Line ~105 resolves Microsoft's own `markitdown` executable as a fallback and must be untouched.

```bash
grep -n 'shutil.which("markitdown")' claude-plugin/hooks/foldmark_read_hook.py
```

Expected: exactly one hit, unchanged. If this is now `which("foldmark")`, revert that line.

- [ ] **Step 7: Run the tests and validate the plugin**

```bash
.venv/bin/python -m unittest tests.test_read_hook 2>&1 | tail -3
claude plugin validate ./claude-plugin
```

Expected: tests OK; `✔ Validation passed`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: rename the Claude Code plugin to foldmark"
```

---

### Task 3: Rename the Obsidian plugin

**Files:**
- Modify: `obsidian-plugin/manifest.json`, `obsidian-plugin/package.json`, `obsidian-plugin/package-lock.json`, `obsidian-plugin/src/python.ts`, `obsidian-plugin/src/settings.ts`, `obsidian-plugin/README.md`

**Interfaces:**
- Consumes: `python -m foldmark.cli` from Task 1; detects a checkout by the presence of `foldmark/cli.py`.
- Produces: plugin `id` `foldmark`, `name` `Foldmark`, npm package `obsidian-foldmark`.

- [ ] **Step 1: Rename the plugin identity**

```bash
sed -i '' 's/"id": "markitdown"/"id": "foldmark"/; s/"name": "MarkItDown"/"name": "Foldmark"/' \
  obsidian-plugin/manifest.json
sed -i '' 's/"obsidian-markitdown"/"obsidian-foldmark"/' \
  obsidian-plugin/package.json obsidian-plugin/package-lock.json
```

- [ ] **Step 2: Update the checkout-detection paths**

`python.ts:43-44` searches for a checkout by folder name and `python.ts:53` by the package directory. Both change; `markitdownVersion` on line 25 does **not**, because it carries the dependency's version.

```bash
sed -i '' 's|"microsoftmarkitdown"|"foldmark"|g; s|/path/to/microsoftmarkitdown|/path/to/foldmark|g' \
  obsidian-plugin/src/python.ts obsidian-plugin/src/settings.ts
sed -i '' 's|bjaysingh/microsoftmarkitdown|bjaysingh/foldmark|g' \
  obsidian-plugin/src/python.ts obsidian-plugin/src/settings.ts obsidian-plugin/README.md
sed -i '' 's|Could not find a checkout of microsoftmarkitdown|Could not find a checkout of Foldmark|' \
  obsidian-plugin/src/python.ts
```

- [ ] **Step 2b: Rename the environment-variable override**

Same variable as Task 2, on the TypeScript side. `python.ts:39` reads it; the README documents it.

```bash
sed -i '' 's/MARKITDOWN_DESKTOP_ROOT/FOLDMARK_ROOT/g' \
  obsidian-plugin/src/python.ts obsidian-plugin/README.md
grep -rn "MARKITDOWN_DESKTOP_ROOT" obsidian-plugin/ || echo "none left in obsidian-plugin"
```

- [ ] **Step 3: Confirm the dependency reference survived**

```bash
grep -n "markitdownVersion" obsidian-plugin/src/python.ts obsidian-plugin/src/settings.ts
grep -n "github.com/microsoft/markitdown" obsidian-plugin/src/settings.ts
```

Expected: `markitdownVersion` still present in both; the Microsoft URL still present. Both refer to the dependency.

- [ ] **Step 4: Build**

```bash
cd obsidian-plugin && npm run build && cd ..
```

Expected: `tsc --noEmit` clean, esbuild succeeds. A TypeScript error here almost certainly means a `sed` renamed an identifier it should not have.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: rename the Obsidian plugin to foldmark"
```

---

### Task 4: Rename the remaining surfaces — docs, workflow, launchers

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `THIRD-PARTY-NOTICES.md`, `.github/workflows/release.yml`, `Setup-macOS.command`, `Setup-Windows.bat`, `Build-macOS.command`, `Build-Windows.bat`

**Interfaces:**
- Consumes: the `foldmark` package name from Task 1.
- Produces: release archive named `foldmark-<version>-source.zip`.

- [ ] **Step 1: Rename the product name and repo URL in text**

```bash
FILES="README.md CLAUDE.md THIRD-PARTY-NOTICES.md .github/workflows/release.yml \
Setup-macOS.command Setup-Windows.bat Build-macOS.command Build-Windows.bat"
sed -i '' 's/MarkItDown Desktop/Foldmark/g; s|bjaysingh/microsoftmarkitdown|bjaysingh/foldmark|g' $FILES
sed -i '' 's/markitdown-desktop-/foldmark-/g' .github/workflows/release.yml
```

- [ ] **Step 2: Rename ASSET_PREFIX to match the new archive name**

This is load-bearing. `updater.py:236` resolves the source asset with **both** a prefix and a
suffix test:

```python
source = _find_asset(assets, lambda n: n.startswith(ASSET_PREFIX) and n.endswith(ASSET_SUFFIX))
```

If the workflow emits `foldmark-2.0.0-source.zip` while `ASSET_PREFIX` still reads
`"markitdown-desktop-"`, the updater finds no asset and every future update fails to start —
silently, because a missing asset is not an exception.

```bash
sed -i '' 's/^ASSET_PREFIX = "markitdown-desktop-"$/ASSET_PREFIX = "foldmark-"/' foldmark/updater.py
grep -n 'ASSET_PREFIX\|ASSET_SUFFIX' foldmark/updater.py
grep -n 'foldmark-\${VERSION}' .github/workflows/release.yml   # expect 4 hits
```

Expected: `ASSET_PREFIX = "foldmark-"`, `ASSET_SUFFIX = "-source.zip"`, and the workflow
building `foldmark-${VERSION}-source.zip`. The constant and the workflow must agree — the
workflow produces the filename the constant expects.

Then confirm the updater's own tests still pass, since they assert on asset names:

```bash
.venv/bin/python -m unittest tests.test_updater 2>&1 | tail -3
```

- [ ] **Step 3: Confirm attribution survived the doc rewrite**

```bash
grep -c "Microsoft MarkItDown" THIRD-PARTY-NOTICES.md README.md
grep -n "github.com/microsoft/markitdown" THIRD-PARTY-NOTICES.md
```

Expected: both files still carry the phrase, and the Microsoft URL is intact in the notices. If THIRD-PARTY-NOTICES lost its MarkItDown entry, stop — that is a licence problem, not a formatting one.

- [ ] **Step 4: Read the README top to bottom and fix what sed cannot**

The blanket replaces handle the phrase and the URLs. What they cannot judge is the bare word
"MarkItDown", which is ambiguous: it could mean the product or the dependency.

**In this README it always means the dependency.** Every bare occurrence — the `.doc`/`.ppt`
format limits, the OCR paragraph, `convert_local()`, the requirements discussion, the security
note — is about Microsoft's library. **Leave every one of them alone.** Renaming them would
make the document claim things about Foldmark that are true of MarkItDown.

Confirm the result reads correctly:

```bash
head -6 README.md
grep -n "Foldmark" README.md | head
grep -c "Microsoft MarkItDown" README.md
```

Expected: the title is `# Foldmark`; the opening still describes it as an app for the
open-source Microsoft MarkItDown library; `Foldmark` appears wherever the product is named;
the attribution count is unchanged from before the rename.

Read the whole file once and fix any sentence left awkward by the substitution — for example
a line that now reads "Foldmark is an open-source Microsoft" would be a mangled dependency
reference, not a product mention.

- [ ] **Step 5: Run the suite and commit**

```bash
.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3
git add -A
git commit -m "docs: rename the product to Foldmark in docs, workflow and launchers"
```

---

### Task 5: Full verification and the audit

**Files:** none modified unless the audit fails.

**Interfaces:**
- Consumes: everything from Tasks 1 to 4.
- Produces: the evidence that the rename is complete and the attribution intact.

- [ ] **Step 1: Full suite**

```bash
.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3
```

Expected: `Ran 122 tests` / `OK`.

- [ ] **Step 2: The suite as CI runs it — a bare interpreter**

```bash
python3 -m venv /tmp/foldmark-bare
/tmp/foldmark-bare/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3
```

Expected: `Ran 122 tests` / `OK (skipped=7)`.

- [ ] **Step 3: The grep audit**

```bash
AUDIT=(--exclude-dir=.git --exclude-dir=.venv --exclude-dir=node_modules
       --exclude-dir=build --exclude-dir=specs --exclude-dir=plans)
grep -ril "${AUDIT[@]}" -e markitdown_desktop -e "MarkItDown Desktop" -e microsoftmarkitdown .
grep -rio "${AUDIT[@]}" "Microsoft MarkItDown" . | wc -l
```

Expected: the first command prints hits in exactly four files — `app.py`,
`foldmark/converter.py`, `foldmark/cli.py` and `tests/test_ocr.py` — and nothing else; the
second prints **28**.

**Those four hits are not failures.** Case-insensitively, `microsoftmarkitdown` also matches
`MicrosoftMarkItDownConverter`, the class wrapping Microsoft's library. It is correctly named
and must not be renamed, on the same principle as `markitdown_version()`. To separate real
leftovers from it, re-run the first grep case-sensitively:

```bash
grep -rn "${AUDIT[@]}" -e markitdown_desktop -e "MarkItDown Desktop" -e microsoftmarkitdown \
     -e 'MicrosoftMarkItDown"' .    # this must print nothing
```

Keep the case-insensitive pass despite the noise: it is what caught
`obsidian-plugin/src/python.ts` hardcoding the old working-copy folder name as a checkout
search path, a functional break that every case-sensitive sweep missed and that would only
have surfaced after Task 6 moved the folder.

A number other than 28 means the rename ate attribution. Find the last commit before this
work with `git log --oneline` and diff from there:

```bash
git diff <commit-before-task-1> -- THIRD-PARTY-NOTICES.md README.md claude-plugin/ obsidian-plugin/
```

Restore any dropped occurrence of the phrase. Do not "fix" the count by adding the phrase
somewhere new — the point is that the original notices survived, not that a number matches.

- [ ] **Step 4: GUI check**

```bash
.venv/bin/python -c "
import subprocess, sys
p = subprocess.Popen([sys.executable, 'app.py'], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print('launched pid', p.pid)"
```

Ask the user to confirm the window title reads **Foldmark** and that About names Foldmark while still crediting Microsoft MarkItDown. Screenshots are blocked on this machine, so this check cannot be automated.

- [ ] **Step 5: Commit if anything needed fixing**

```bash
git add -A && git commit -m "fix: restore attribution missed by the rename" || echo "nothing to fix"
```

---

### Task 6: Move the working copy and repoint the remote

**Files:** the repository itself.

**Interfaces:**
- Consumes: a fully renamed, committed, pushed repository.
- Produces: the working copy at `~/Claude/Projects/Foldmark` with `origin` at `github.com/bjaysingh/foldmark`.

- [ ] **Step 1: Push everything first**

```bash
git status --porcelain   # expect empty
git push origin main
```

Pushing before the move means the work is safe on the remote if anything about the move goes wrong.

- [ ] **Step 2: Repoint the remote and verify it resolves**

```bash
git remote set-url origin https://github.com/bjaysingh/foldmark.git
git ls-remote --exit-code origin HEAD >/dev/null && echo "remote resolves"
```

- [ ] **Step 3: Move the working copy**

```bash
cd ~ && mv ~/Claude/Projects/MicrosoftMarkItDown ~/Claude/Projects/Foldmark
cd ~/Claude/Projects/Foldmark && git status --porcelain && git log --oneline -1
```

The session's working directory moves here. Every later command uses the new path.

- [ ] **Step 4: Confirm the venv survived the move**

A venv stores absolute paths in its scripts, so a moved venv can break.

```bash
.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3
```

Expected: `Ran 122 tests` / `OK`. If the interpreter fails to start, rebuild with `./Setup-macOS.command` and re-run.

---

### Task 7: Release 2.0.0

**Files:**
- Modify: `foldmark/__init__.py`, `obsidian-plugin/manifest.json`, `obsidian-plugin/package.json`, `obsidian-plugin/versions.json`, `claude-plugin/.claude-plugin/plugin.json`

**Interfaces:**
- Consumes: the renamed, relocated repository.
- Produces: published release v2.0.0 with `foldmark-2.0.0-source.zip`.

- [ ] **Step 1: Bump all five version declarations**

`release.yml` refuses a tag that disagrees with `__version__`, so all five must read 2.0.0.

```bash
sed -i '' 's/"1.0.3"/"2.0.0"/' foldmark/__init__.py
sed -i '' 's/"version": "1.0.3"/"version": "2.0.0"/' \
  obsidian-plugin/manifest.json obsidian-plugin/package.json \
  claude-plugin/.claude-plugin/plugin.json
python3 -c "
import json, pathlib
p = pathlib.Path('obsidian-plugin/versions.json')
d = json.loads(p.read_text()); d['2.0.0'] = d['1.0.3']
p.write_text(json.dumps(d, indent=2) + '\n')"
```

- [ ] **Step 2: Confirm every declaration agrees**

```bash
grep __version__ foldmark/__init__.py
grep -h '"version"' obsidian-plugin/manifest.json obsidian-plugin/package.json \
  claude-plugin/.claude-plugin/plugin.json
```

Expected: 2.0.0 four times.

- [ ] **Step 3: Full checks before tagging**

```bash
.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3
cd obsidian-plugin && npm run build && cd ..
claude plugin validate ./claude-plugin
```

- [ ] **Step 4: Commit, tag and push**

```bash
git add -A
git commit -m "chore: release 2.0.0"
git tag v2.0.0
git push origin main --tags
```

- [ ] **Step 5: Verify the release published**

```bash
until [ "$(gh run list --workflow=Release --limit 1 --json status --jq '.[0].status')" = "completed" ]; do sleep 15; done
gh run list --workflow=Release --limit 1
gh release view v2.0.0 --json name,assets --jq '{name, assets:[.assets[].name]}'
```

Expected: the run succeeded and the assets include `foldmark-2.0.0-source.zip` and `SHA256SUMS.txt`.

- [ ] **Step 6: Tell the user what they must do by hand**

Neither can be fixed from inside the repository:

- Delete `~/Desktop/MarkItDown-Desktop-v1.0.0-demo/` and reinstall from the 2.0.0 release.
- Delete `~/Claude/Projects/.obsidian/plugins/markitdown/`, install the new build as `foldmark`, and re-enable it in Obsidian.

---

### Task 8: Retire the releases published under the old name

**Files:** none. This task acts on GitHub, not the repository.

**Interfaces:**
- Consumes: a published v2.0.0 from Task 7.
- Produces: a releases page listing only Foldmark.

**This task is irreversible.** Deleting a release destroys its source archive and
`SHA256SUMS.txt`; they cannot be restored. It runs only after v2.0.0 is confirmed published,
so the repository is never left without a release for the updater to find.

**Scope, decided with the user:** delete the three releases and their tags. Git history is
**not** rewritten — the old name remains visible in commit subjects and in the eight commits
that touch `markitdown_desktop/` paths, and the spec and plan under `docs/superpowers/`
deliberately name both sides of the rename. The user chose this knowing it leaves those
traces; erasing them would mean a force-pushed history rewrite that invalidates every clone.

- [ ] **Step 1: Confirm v2.0.0 is published before deleting anything**

```bash
gh release view v2.0.0 --json name,isDraft --jq '{name, isDraft}'
```

Expected: the v2.0.0 release exists and `isDraft` is `false`. If it does not, **stop** — do not
delete the old releases while they are the only ones available.

- [ ] **Step 2: Record what is about to be destroyed**

```bash
gh release list
git tag | grep '^v1\.'
```

Expected: releases v1.0.1, v1.0.2, v1.0.3 and the matching tags.

- [ ] **Step 3: Delete the three releases and their tags**

`--cleanup-tag` removes the tag along with the release, and `--yes` skips the interactive
prompt, which cannot be answered in this environment.

```bash
for v in v1.0.1 v1.0.2 v1.0.3; do
  gh release delete "$v" --cleanup-tag --yes
done
```

- [ ] **Step 4: Delete any local tag that survived, and prune**

```bash
git tag -d v1.0.1 v1.0.2 v1.0.3 2>/dev/null
git fetch --prune --prune-tags origin
git tag | tr '\n' ' '
```

Expected: only `v2.0.0` remains.

- [ ] **Step 5: Verify the releases page shows only Foldmark**

```bash
gh release list
```

Expected: exactly one row, `Foldmark 2.0.0`, tagged `v2.0.0`.
