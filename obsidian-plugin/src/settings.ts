import { App, PluginSettingTab, Setting, Notice } from "obsidian";
import type MarkItDownPlugin from "./main";
import { probeConverter } from "./python";

export interface MarkItDownSettings {
  /** Explicit interpreter path. Empty means auto-detect. */
  pythonPath: string;
  /** Checkout of bjaysingh/microsoftmarkitdown providing foldmark.cli. */
  projectRoot: string;
  /** Vault-relative folder that receives converted notes. */
  outputFolder: string;
  /** Open the first converted note when a conversion finishes. */
  openAfterConvert: boolean;
  /** Timeout for a single conversion batch, in seconds. */
  timeoutSeconds: number;
}

export const DEFAULT_SETTINGS: MarkItDownSettings = {
  pythonPath: "",
  projectRoot: "",
  outputFolder: "MarkItDown",
  openAfterConvert: true,
  timeoutSeconds: 300,
};

export class MarkItDownSettingTab extends PluginSettingTab {
  constructor(app: App, private plugin: MarkItDownPlugin) {
    super(app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    const intro = containerEl.createEl("p");
    intro.appendText("Conversion is performed locally by ");
    intro.createEl("a", {
      text: "Microsoft MarkItDown",
      href: "https://github.com/microsoft/markitdown",
    });
    intro.appendText(
      ", an open-source MIT-licensed Microsoft project. This plugin is an independent " +
        "frontend and is not endorsed or sponsored by Microsoft."
    );

    new Setting(containerEl)
      .setName("Converter location")
      .setDesc(
        "Folder containing foldmark/. Leave empty to search the usual locations. " +
          "This is a checkout of github.com/bjaysingh/microsoftmarkitdown with its setup script run."
      )
      .addText((text) =>
        text
          .setPlaceholder("/path/to/microsoftmarkitdown")
          .setValue(this.plugin.settings.projectRoot)
          .onChange(async (value) => {
            this.plugin.settings.projectRoot = value.trim();
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Python interpreter")
      .setDesc(
        "Leave empty to use the converter's own .venv, then python3 or py -3 from PATH."
      )
      .addText((text) =>
        text
          .setPlaceholder("auto-detect")
          .setValue(this.plugin.settings.pythonPath)
          .onChange(async (value) => {
            this.plugin.settings.pythonPath = value.trim();
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Output folder")
      .setDesc("Vault-relative folder for converted notes. It is created if missing.")
      .addText((text) =>
        text
          .setPlaceholder("MarkItDown")
          .setValue(this.plugin.settings.outputFolder)
          .onChange(async (value) => {
            this.plugin.settings.outputFolder = value.trim() || DEFAULT_SETTINGS.outputFolder;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Open the note after converting")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.openAfterConvert).onChange(async (value) => {
          this.plugin.settings.openAfterConvert = value;
          await this.plugin.saveSettings();
        })
      );

    new Setting(containerEl)
      .setName("Conversion timeout")
      .setDesc("Seconds to wait for a batch before giving up.")
      .addText((text) =>
        text.setValue(String(this.plugin.settings.timeoutSeconds)).onChange(async (value) => {
          const parsed = Number.parseInt(value, 10);
          this.plugin.settings.timeoutSeconds =
            Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_SETTINGS.timeoutSeconds;
          await this.plugin.saveSettings();
        })
      );

    // A misconfigured interpreter should fail here, loudly, rather than silently
    // at the moment someone tries to convert a document.
    const status = containerEl.createEl("p", { cls: "setting-item-description" });
    new Setting(containerEl)
      .setName("Test setup")
      .setDesc("Check that Python and Microsoft MarkItDown can be reached.")
      .addButton((button) =>
        button
          .setButtonText("Test")
          .setCta()
          .onClick(async () => {
            status.setText("Checking…");
            const result = await probeConverter(this.plugin.settings);
            if (result.ok) {
              status.setText(
                `Ready. Python ${result.python}, MarkItDown ${result.markitdownVersion}, ` +
                  `using ${result.interpreter}`
              );
              new Notice("MarkItDown is ready.");
            } else {
              status.setText(`Not working: ${result.message}`);
              new Notice(`MarkItDown setup problem: ${result.message}`, 8000);
            }
          })
      );
  }
}
