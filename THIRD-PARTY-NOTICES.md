# Third-party notices

This project is licensed under the MIT License; see [LICENSE](LICENSE). The notices below
cover software it depends on, not this project itself.

This application installs and uses the following open-source packages:

- **MarkItDown** by Microsoft contributors — MIT License — https://github.com/microsoft/markitdown
- **TkinterDnD2** and bundled TkDnD components — MIT-style licenses — https://github.com/Eliav2/tkinterdnd2

The Obsidian plugin in `obsidian-plugin/` additionally uses, at build time only:

- **esbuild** — MIT License — https://github.com/evanw/esbuild
- **TypeScript** — Apache-2.0 License — https://github.com/microsoft/TypeScript
- **obsidian** API typings — MIT License — https://github.com/obsidianmd/obsidian-api

None of these build-time packages are redistributed in the plugin bundle; only the plugin's own
compiled code ships in `main.js`.

Their dependencies may include additional open-source software. Review the installed package
metadata and upstream repositories before redistributing a built executable.

“Microsoft” and related marks belong to Microsoft Corporation. This independent frontend is not
endorsed or sponsored by Microsoft.
