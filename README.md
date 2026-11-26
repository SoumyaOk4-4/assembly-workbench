# Assembly Workbench

A lightweight desktop editor for assembling, running, and debugging Linux
assembly under QEMU/GDB.

## Requirements

- Python 3 with Tkinter
- `gdb-multiarch`
- QEMU user-mode emulators for the targets you use
- Target assemblers/linkers:
  - AArch64: `aarch64-linux-gnu-as` and `aarch64-linux-gnu-ld`
  - ARM 32-bit: `arm-linux-gnueabihf-as` and `arm-linux-gnueabihf-ld`
  - x86 and x86_64: GNU `as` and `ld`
- Bash for the embedded Terminal tab

On Debian/Ubuntu, the packages commonly needed are `binutils-aarch64-linux-gnu`,
`binutils-arm-linux-gnueabihf`, `binutils`, `gdb-multiarch`, and `qemu-user`.

## Start

```sh
./app
```

The launcher returns to the terminal immediately; the workbench keeps running
if you close the terminal.

Without a remembered source file, the workbench opens the bundled `template.s`.

Or open a source file directly:

```sh
./app path/to/program.s
```

The target selector supports **AArch64**, **ARM 32-bit**, **x86 (32-bit)**, and
**x86_64**. It remembers your target selection. Choose assembly syntax and
system calls appropriate to the selected target.

## Build, run, and debug

- **New** starts an empty source file. **Open** chooses a source file, and
  **Save** writes the current file (asking for a filename if it is untitled).
- **Build** assembles and links the source; messages appear in the **Build**
  tab. **Run** builds and executes it under QEMU, with output in **Program**.
- **Build + Debug** builds and starts a QEMU/GDB debugging session. Click the
  editor gutter to set or remove a source breakpoint; **Step** advances one
  machine instruction while debugging.
- **Find** opens the find-and-replace dialog. **Find next** selects the next
  case-insensitive match, **Replace** replaces the selected match, and
  **Replace all** replaces every case-insensitive match.
- **Recent** lists recently opened files; choose one and click **Open**.
  **Settings** opens theme and font controls; click **Apply** to use them.
- **Target** selects the assembly architecture. **Go to line** moves the
  editor cursor to a specified line, and **Comment** toggles `//` comments on
  the current line or selected lines. **Tab spaces** sets the indentation
  width inserted by Tab and automatic indentation.
- The **Memory inspector** works during **Build + Debug** (Build and Run do not
  attach GDB). It automatically reads 128 bytes from the stack pointer when
  execution stops. To inspect another location, enter a register, `&symbol`,
  or numeric address and click **Read**. A register such as `$x0` is treated as
  an address: its current value must be a mapped, readable pointer. An integer
  like `9` is not a valid memory address just because it is in a register.
  Choose bytes, 32-bit words, or 64-bit words; word displays are little-endian.
- The **Stack** view below the Memory inspector automatically shows the first
  32 32-bit words from the current stack pointer whenever execution stops.
- The **Disassembly** tab shows the full function containing the current
  instruction when execution stops, including GDB's current-instruction marker.
- Register views include hexadecimal, unsigned, signed, and binary formats.
  The register filter accepts comma-separated names (for example, `x0, sp,
  lr`); `lr` also matches `x30` on AArch64 and `r14` on ARM. Leave it empty to
  show all registers. Filter names are remembered between launches. Changed
  registers are highlighted, and condition flags are displayed.
- Assembler errors are highlighted in the **Build** tab; click one to jump to
  its source line.

## Editor and preferences

The editor includes line numbers, assembly syntax colors, auto-indent,
configurable Tab spaces, comment/uncomment, go-to-line, find/replace, undo/redo,
and an unsaved-changes indicator. Saved files autosave after a short pause.
Closing with unsaved changes offers **Save and Close**, **Close Without
Saving**, or **Cancel**. Cancel leaves the workbench open.

The app restores the last file, target, theme, font, indentation width, and
window size between sessions. Preferences are stored in
`$XDG_CONFIG_HOME/aarch64-assembly-workbench/settings.json` (normally
`~/.config/aarch64-assembly-workbench/settings.json`).

## Updating

Click **Check Updates** to check the latest stable GitHub release. When an
update is available, the app downloads the release's `app.py` and icon, verifies
their SHA-256 checksums, installs them, and restarts. The app folder must be
writable.

To publish an update, change `APP_VERSION` in `app.py` and push a matching
version tag such as `v0.2.0`. GitHub Actions publishes the app and checksum
assets used by the updater.

Shortcuts: Ctrl+S save, Ctrl+O open, Ctrl+N new, Ctrl+F find/replace, Ctrl+G go
to line, Ctrl+/ comment/uncomment, Ctrl+Z undo, and Ctrl+Y redo.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
