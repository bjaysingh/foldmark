import {
  Notice,
  Plugin,
  TAbstractFile,
  TFile,
  TFolder,
  normalizePath,
} from "obsidian";
import * as fs from "fs";
import * as path from "path";
import {
  DEFAULT_SETTINGS,
  MarkItDownSettingTab,
  type MarkItDownSettings,
} from "./settings";
import { cleanupTempDir, convertToTempDir, type ConversionRecord } from "./python";

export default class MarkItDownPlugin extends Plugin {
  settings: MarkItDownSettings = DEFAULT_SETTINGS;

  async onload(): Promise<void> {
    await this.loadSettings();
    this.addSettingTab(new MarkItDownSettingTab(this.app, this));

    this.addRibbonIcon("file-text", "Convert to Markdown with Foldmark", () => {
      void this.convertActiveFile();
    });

    this.addCommand({
      id: "convert-active-file",
      name: "Convert the current file to Markdown",
      callback: () => void this.convertActiveFile(),
    });

    this.addCommand({
      id: "convert-vault-folder",
      name: "Convert every supported file in a folder",
      callback: () => void this.convertActiveFolder(),
    });

    this.registerEvent(
      this.app.workspace.on("file-menu", (menu, file: TAbstractFile) => {
        const isFolder = file instanceof TFolder;
        if (!isFolder && !(file instanceof TFile)) return;
        menu.addItem((item) =>
          item
            .setTitle(isFolder ? "Convert folder with Foldmark" : "Convert with Foldmark")
            .setIcon("file-text")
            .onClick(() => void this.convertVaultPaths([file])),
        );
      }),
    );
  }

  async loadSettings(): Promise<void> {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  /** Absolute on-disk path for a vault item, or null on a non-filesystem vault. */
  private absolutePath(file: TAbstractFile): string | null {
    const adapter = this.app.vault.adapter as { getBasePath?: () => string };
    if (typeof adapter.getBasePath !== "function") return null;
    return path.join(adapter.getBasePath(), file.path);
  }

  private async convertActiveFile(): Promise<void> {
    const active = this.app.workspace.getActiveFile();
    if (!active) {
      new Notice("Open a file to convert, or use the file menu.");
      return;
    }
    await this.convertVaultPaths([active]);
  }

  private async convertActiveFolder(): Promise<void> {
    const active = this.app.workspace.getActiveFile();
    const folder = active?.parent;
    if (!folder) {
      new Notice("Open a file inside the folder you want to convert.");
      return;
    }
    await this.convertVaultPaths([folder]);
  }

  private async convertVaultPaths(files: TAbstractFile[]): Promise<void> {
    const sources = files
      .map((file) => this.absolutePath(file))
      .filter((value): value is string => value !== null);
    if (sources.length === 0) {
      new Notice("This vault is not stored on disk, so Foldmark cannot read its files.");
      return;
    }

    const notice = new Notice("Foldmark: converting…", 0);
    const { records, skipped, tempDir, error } = await convertToTempDir(this.settings, sources);
    try {
      if (error) {
        notice.hide();
        new Notice(`Foldmark: ${error}`, 10000);
        return;
      }
      const created = await this.importResults(records);
      notice.hide();
      this.report(records, skipped, created);
    } finally {
      cleanupTempDir(tempDir);
    }
  }

  /**
   * Move converted Markdown into the vault through the vault API.
   *
   * Writing straight to disk would work but leaves Obsidian to notice the files
   * on its own; creating them through the vault indexes and links them at once.
   */
  private async importResults(records: ConversionRecord[]): Promise<TFile[]> {
    const folder = normalizePath(this.settings.outputFolder || DEFAULT_SETTINGS.outputFolder);
    if (!this.app.vault.getAbstractFileByPath(folder)) {
      await this.app.vault.createFolder(folder).catch(() => undefined);
    }

    const created: TFile[] = [];
    for (const record of records) {
      if (!record.ok || !record.output) continue;
      let markdown: string;
      try {
        markdown = fs.readFileSync(record.output, "utf8");
      } catch {
        continue;
      }
      const base = path.basename(record.output, ".md");
      const target = this.availablePath(folder, base);
      try {
        created.push(await this.app.vault.create(target, markdown));
      } catch {
        // Another process may have taken the name between the check and the write.
      }
    }

    if (created.length > 0 && this.settings.openAfterConvert) {
      await this.app.workspace.getLeaf(false).openFile(created[0]);
    }
    return created;
  }

  /** Mirrors the desktop app's rule: never overwrite, add -2, -3, and so on. */
  private availablePath(folder: string, base: string): string {
    let candidate = normalizePath(`${folder}/${base}.md`);
    let counter = 2;
    while (this.app.vault.getAbstractFileByPath(candidate)) {
      candidate = normalizePath(`${folder}/${base}-${counter}.md`);
      counter += 1;
    }
    return candidate;
  }

  private report(records: ConversionRecord[], skipped: string[], created: TFile[]): void {
    const failed = records.filter((record) => !record.ok);
    if (records.length === 0) {
      new Notice("Foldmark: no supported files were found.", 6000);
      return;
    }
    const parts = [`${created.length} note${created.length === 1 ? "" : "s"} created`];
    if (failed.length > 0) parts.push(`${failed.length} failed`);
    if (skipped.length > 0) parts.push(`${skipped.length} unsupported skipped`);
    new Notice(`Foldmark: ${parts.join(" · ")}`, failed.length > 0 ? 10000 : 5000);

    if (failed.length > 0) {
      const detail = failed
        .slice(0, 5)
        .map((record) => `${path.basename(record.source)}: ${record.message}`)
        .join("\n");
      new Notice(detail, 12000);
    }
  }
}
