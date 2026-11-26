<p align="center">
  <img src="assets/app-icon.png" alt="Assembly Workbench dragon logo" width="144">
</p>

<h1 align="center">Assembly Workbench</h1>

<p align="center">
  A lightweight desktop workbench for writing, building, running, and debugging
  Linux assembly.
</p>

<p align="center">
  <a href="https://github.com/SoumyaOk4-4/assembly-workbench/releases/latest">
    <img alt="Latest release" src="https://img.shields.io/github/v/release/SoumyaOk4-4/assembly-workbench?display_name=tag&color=35d985">
  </a>
  <a href="https://github.com/SoumyaOk4-4/assembly-workbench/actions/workflows/publish-release.yml">
    <img alt="Release workflow" src="https://img.shields.io/github/actions/workflow/status/SoumyaOk4-4/assembly-workbench/publish-release.yml?branch=main&label=release%20workflow">
  </a>
  <a href="LICENSE">
    <img alt="MIT License" src="https://img.shields.io/github/license/SoumyaOk4-4/assembly-workbench">
  </a>
</p>

---

## What it does

- **Edit** assembly in a syntax-highlighted editor with line numbers,
  auto-indent, find and replace, and comment toggling.
- **Build and run** programs for AArch64, ARM 32-bit, x86, and x86_64 using
  GNU assemblers/linkers and QEMU.
- **Debug** with GDB: step through instructions, set source breakpoints, and
  inspect registers, memory, stack words, and disassembly.
- **Customize** the editor with Light, Dark, Yellow, and Pink themes, plus
  adjustable fonts and tab width.
- **Update** from the app with **Check Updates**.

## Get started

### Requirements

- Python 3 with Tkinter
- `gdb-multiarch`
- QEMU user-mode emulators (`qemu-user`)
- GNU assemblers and linkers: `binutils`, `binutils-aarch64-linux-gnu`, and
  `binutils-arm-linux-gnueabihf` for the targets you use
- Bash for the embedded Terminal tab

On Debian or Ubuntu, install the common dependencies with:

```sh
sudo apt install python3 python3-tk binutils binutils-aarch64-linux-gnu \
  binutils-arm-linux-gnueabihf gdb-multiarch qemu-user
```

### Launch

Download and extract the [latest release](https://github.com/SoumyaOk4-4/assembly-workbench/releases/latest), then run:

```sh
./app
```

Open a source file directly:

```sh
./app path/to/program.s
```

The launcher starts the workbench in the background. On first launch, it opens
the bundled `template.s`; later launches restore your last source file and
preferences.

## Build, run, and debug

| Action | What it does |
| --- | --- |
| **Build** | Assembles and links the current source; diagnostics appear in Build. |
| **Run** | Builds and executes the program under QEMU. |
| **Build + Debug** | Starts QEMU and GDB for instruction-level debugging. |
| **Step** | Advances one machine instruction. |

Click the editor gutter to toggle source breakpoints. While debugging, the
register panel shows values and condition flags; the Memory inspector reads
memory from a register, label, or address; and the Stack view shows 32
32-bit words from the current stack pointer.

Supported targets are **AArch64**, **ARM 32-bit**, **x86 (32-bit)**, and
**x86_64**. Use assembly syntax and system calls appropriate to the selected
target.

## Editor and preferences

The editor includes syntax coloring, line numbers, auto-indent, configurable
tab spaces, comment/uncomment, go-to-line, find/replace, undo/redo, and
autosave. When closing with unsaved edits, you can save, discard, or cancel.

Choose **Settings** to select a theme, font, font size, and indentation width.
Preferences and recent files are stored in:

```text
$XDG_CONFIG_HOME/aarch64-assembly-workbench/settings.json
```

If `XDG_CONFIG_HOME` is not set, the default location is
`~/.config/aarch64-assembly-workbench/settings.json`.

### Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+S | Save |
| Ctrl+O | Open |
| Ctrl+N | New file |
| Ctrl+F | Find and replace |
| Ctrl+G | Go to line |
| Ctrl+/ | Comment or uncomment |
| Ctrl+Z / Ctrl+Y | Undo / redo |

## Updates and releases

Click **Check Updates** to look for the latest stable release. When one is
available, the app verifies and installs the updated program and icon, then
restarts. The app directory must be writable.

To publish a release, update `APP_VERSION` in `app.py` and push a matching tag
(for example, `v0.2.0`). GitHub Actions creates the release with the ZIP
package as its only downloadable asset.

## License

Released under the [MIT License](LICENSE).
