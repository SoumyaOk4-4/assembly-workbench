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

- **Build** assembles and links the current source.
- **Run** builds and executes normally under QEMU; program output appears in
  the **Program** tab.
- **Build + Debug** builds and connects `gdb-multiarch` to QEMU.
- Click the editor gutter to set or remove a source breakpoint. **Step**
  advances one instruction during a debugging session.
- The **Memory inspector** works during **Build + Debug** (Build and Run do not
  attach GDB). It automatically reads 128 bytes from the stack pointer when
  execution stops; enter a register, `&symbol`, or numeric address and click
  **Read** to inspect another location. A register such as `$x0` is treated as
  an address: its current value must be a mapped, readable pointer. An integer
  like `9` is not a valid memory address just because it is in a register.
  Choose bytes, 32-bit words, or 64-bit words; word displays are little-endian.
- Register views include hexadecimal, unsigned, signed, and binary formats.
  Changed registers are highlighted, and condition flags are displayed.
- Assembler errors are highlighted in the **Build** tab; click one to jump to
  its source line.

Continue is debugger-controlled instruction stepping so it can pause
responsively; use **Run** for normal, faster execution.

## Editor and preferences

The editor includes line numbers, assembly syntax colors, auto-indent,
configurable Tab spaces, comment/uncomment, go-to-line, find/replace, undo/redo,
and an unsaved-changes indicator. Saved files autosave after a short pause.

**Recent** lists recently opened files. The app restores the last file, target,
theme, font, indentation width, and window size between sessions. **Settings**
offers light/dark themes and font controls. Preferences are stored in
`$XDG_CONFIG_HOME/aarch64-assembly-workbench/settings.json` (normally
`~/.config/aarch64-assembly-workbench/settings.json`).

Shortcuts: Ctrl+S save, Ctrl+O open, Ctrl+N new, Ctrl+F find/replace, Ctrl+G go
to line, Ctrl+/ comment/uncomment, Ctrl+Z undo, and Ctrl+Y redo.
