#!/usr/bin/env python3
"""A small editor and AArch64 assemble/link/GDB workbench."""

from __future__ import annotations

import codecs
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk


AUTOSAVE_DELAY_MS = 800
RECENT_FILE_LIMIT = 10
FONT_FAMILIES = ("monospace", "DejaVu Sans Mono", "Liberation Mono", "Courier New")
THEME_COLORS = {
    "Light": {
        "background": "#f0f0f0",
        "panel": "#ffffff",
        "foreground": "#202020",
        "muted": "#777777",
        "editor": "#ffffff",
        "gutter": "#f2f2f2",
        "selection": "#b7d7f0",
        "instruction": "#7952a3",
        "register": "#005cc5",
        "directive": "#a31515",
        "number": "#098658",
        "label": "#795e26",
        "string": "#a31515",
        "comment": "#008000",
        "execution": "#fff2a8",
        "changed": "#fff2a8",
        "breakpoint": "#cc3333",
    },
    "Dark": {
        "background": "#1e1e1e",
        "panel": "#252526",
        "foreground": "#d4d4d4",
        "muted": "#858585",
        "editor": "#1e1e1e",
        "gutter": "#252526",
        "selection": "#264f78",
        "instruction": "#c586c0",
        "register": "#9cdcfe",
        "directive": "#dcdcaa",
        "number": "#b5cea8",
        "label": "#dcdcaa",
        "string": "#ce9178",
        "comment": "#6a9955",
        "execution": "#51461a",
        "changed": "#3b3a23",
        "breakpoint": "#f14c4c",
    },
}
TARGETS = {
    "AArch64": {
        "assembler": "aarch64-linux-gnu-as",
        "assembler_args": (),
        "linker": "aarch64-linux-gnu-ld",
        "linker_args": (),
        "qemu": "qemu-aarch64",
        "stack_pointer": "$sp",
    },
    "ARM 32-bit": {
        "assembler": "arm-linux-gnueabihf-as",
        "assembler_args": (),
        "linker": "arm-linux-gnueabihf-ld",
        "linker_args": (),
        "qemu": "qemu-arm",
        "stack_pointer": "$sp",
    },
    "x86 (32-bit)": {
        "assembler": "as",
        "assembler_args": ("--32",),
        "linker": "ld",
        "linker_args": ("-m", "elf_i386"),
        "qemu": "qemu-i386",
        "stack_pointer": "$esp",
    },
    "x86_64": {
        "assembler": "as",
        "assembler_args": ("--64",),
        "linker": "ld",
        "linker_args": ("-m", "elf_x86_64"),
        "qemu": "qemu-x86_64",
        "stack_pointer": "$rsp",
    },
}


def settings_file_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "aarch64-assembly-workbench" / "settings.json"


def read_settings(path: Path) -> tuple[dict, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"Could not read settings: {exc}"
    if not isinstance(value, dict):
        return {}, "Could not read settings: settings file must contain a JSON object"
    return value, None


class AssemblyWorkbench:
    def __init__(
        self, root: tk.Tk, source: Path, preferences_path: Path | None = None
    ) -> None:
        self.root = root
        self.preferences_path = preferences_path or settings_file_path()
        preferences, self.preferences_warning = read_settings(self.preferences_path)
        self.theme = preferences.get("theme", "Dark")
        if self.theme not in ("Light", "Dark"):
            self.theme = "Dark"
        self.colors = THEME_COLORS[self.theme]
        self.font_family = preferences.get("font_family", "monospace")
        if self.font_family not in FONT_FAMILIES:
            self.font_family = "monospace"
        self.font_size = preferences.get("font_size", 12)
        if not isinstance(self.font_size, int) or not 8 <= self.font_size <= 32:
            self.font_size = 12
        self.indent_setting = str(preferences.get("indent_width", 4))
        if self.indent_setting not in ("2", "4", "8"):
            self.indent_setting = "4"
        recent_files = preferences.get("recent_files", [])
        self.recent_files = (
            [item for item in recent_files if isinstance(item, str)][:RECENT_FILE_LIMIT]
            if isinstance(recent_files, list)
            else []
        )
        self.last_file = preferences.get("last_file")
        self.target_name = preferences.get("target", "AArch64")
        if not isinstance(self.target_name, str) or self.target_name not in TARGETS:
            self.target_name = "AArch64"
        self.window_geometry = preferences.get("window_geometry", "1280x820")
        if (
            not isinstance(self.window_geometry, str)
            or not re.fullmatch(r"\d+x\d+(?:[+-]\d+){0,2}", self.window_geometry)
        ):
            self.window_geometry = "1280x820"
        self.settings = preferences
        self.register_filter_value = preferences.get("register_filter", "")
        if not isinstance(self.register_filter_value, str):
            self.register_filter_value = ""
        self.source_path: Path | None = source
        self.binary_path: Path | None = None
        self.autosave_id: str | None = None
        self.events: queue.Queue[tuple] = queue.Queue()
        self.gdb: subprocess.Popen[str] | None = None
        self.qemu: subprocess.Popen[str] | None = None
        self.runner: subprocess.Popen[bytes] | None = None
        self.register_names: list[str] = []
        self.register_raw_values: dict[str, str] = {}
        self.changed_registers: set[str] = set()
        self.current_source_line: int | None = None
        self.breakpoints: set[int] = set()
        self.installed_breakpoints: dict[int, str] = {}
        self.pending_breakpoint_lines: set[int] = set()
        self.pending_gdb_actions: dict[str, tuple] = {}
        self.gdb_token = 0
        self.continue_mode = False
        self.pause_requested = False
        self.is_dirty = False
        self.highlight_id: str | None = None
        self.closed = False

        self.root.title("AArch64 Assembly Workbench")
        self.root.geometry(self.window_geometry)
        self.root.minsize(900, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()
        self._set_text(
            self.stack,
            "Memory inspection needs a Build + Debug session.\n"
            "Memory is read automatically from the stack pointer when execution stops.\n"
            "Enter a register or address and click Read. A register is treated as a pointer;\n"
            "its value must point to readable memory.",
        )
        self._apply_theme()
        self._apply_font()
        self._load_source(source)
        self._bind_shortcuts()
        if self.preferences_warning:
            self.status.configure(text=self.preferences_warning)
        self.root.after(50, self._drain_events)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(8, 6))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        for label, command in (
            ("New", self.new_file),
            ("Open", self.open_file),
            ("Save", self.save_file),
            ("Build", self.build),
            ("Build + Debug", self.build_and_debug),
            ("Run", self.run),
            ("Step", self._step_instruction),
            ("Find", self.find_replace),
            ("Recent", self.show_recent_files),
            ("Settings", self.show_settings),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Label(toolbar, text="Target").pack(side=tk.LEFT, padx=(8, 3))
        self.target_var = tk.StringVar(value=self.target_name)
        target_picker = ttk.Combobox(
            toolbar,
            textvariable=self.target_var,
            values=tuple(TARGETS),
            width=13,
            state="readonly",
        )
        target_picker.pack(side=tk.LEFT, padx=(0, 5))
        target_picker.bind("<<ComboboxSelected>>", self._change_target)
        self.path_label = ttk.Label(toolbar, text="", anchor=tk.W)
        self.path_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        main = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        editor_frame = ttk.Frame(main)
        editor_header = ttk.Frame(editor_frame, padding=(4, 3))
        editor_header.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(editor_header, text="Assembly source").pack(side=tk.LEFT)
        ttk.Button(editor_header, text="Comment", command=self._toggle_comment).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(editor_header, text="Go to line", command=self._go_to_line).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Label(editor_header, text="Tab spaces").pack(side=tk.RIGHT, padx=(4, 2))
        self.indent_width = tk.StringVar(value=self.indent_setting)
        ttk.Combobox(
            editor_header,
            textvariable=self.indent_width,
            values=("2", "4", "8"),
            width=3,
            state="readonly",
        ).pack(side=tk.RIGHT)
        editor_body = ttk.Frame(editor_frame)
        editor_body.pack(fill=tk.BOTH, expand=True)
        self.line_numbers = tk.Canvas(
            editor_body,
            width=58,
            highlightthickness=0,
            background="#f2f2f2",
        )
        self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)
        editor_scroll = ttk.Scrollbar(editor_body, orient=tk.VERTICAL)
        editor_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.editor = tk.Text(
            editor_body,
            wrap=tk.NONE,
            undo=True,
            maxundo=-1,
            autoseparators=True,
            font=("monospace", 12),
            yscrollcommand=self._editor_yview,
            padx=8,
            pady=6,
        )
        self.editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.editor_scroll = editor_scroll
        editor_scroll.configure(command=self.editor.yview)
        self.editor.bind("<<Modified>>", self._on_edit)
        self.editor.bind("<KeyRelease>", self._on_editor_key_release)
        self.editor.bind("<Return>", self._insert_newline_with_indent)
        self.editor.bind("<Tab>", self._insert_indent)
        self.editor.bind("<Shift-Tab>", self._outdent_selection)
        self.editor.bind("<Configure>", lambda _event: self._draw_line_numbers())
        self.line_numbers.bind("<Configure>", lambda _event: self._draw_line_numbers())
        self.line_numbers.bind("<Button-1>", self._toggle_breakpoint)
        self.editor.bind("<Control-slash>", lambda _event: self._toggle_comment())
        self.editor.bind("<Control-g>", lambda _event: self._go_to_line())
        self._configure_syntax_tags()

        right = ttk.Panedwindow(main, orient=tk.VERTICAL)
        state_frame = ttk.Frame(right)

        state_top = ttk.Panedwindow(state_frame, orient=tk.HORIZONTAL)
        registers_frame = ttk.LabelFrame(
            state_top, text="Registers — Xn: 64-bit, Wn: low 32 bits"
        )
        register_controls = ttk.Frame(registers_frame)
        register_controls.pack(side=tk.TOP, fill=tk.X, padx=4, pady=3)
        ttk.Label(register_controls, text="Format").pack(side=tk.LEFT)
        self.register_format = tk.StringVar(value="Hex")
        register_format_picker = ttk.Combobox(
            register_controls,
            textvariable=self.register_format,
            values=("Hex", "Unsigned", "Signed", "Binary"),
            width=9,
            state="readonly",
        )
        register_format_picker.pack(side=tk.LEFT, padx=4)
        register_format_picker.bind("<<ComboboxSelected>>", lambda _event: self._render_registers())
        ttk.Label(register_controls, text="Filter").pack(side=tk.LEFT, padx=(8, 2))
        self.register_filter = tk.StringVar(value=self.register_filter_value)
        register_filter_entry = ttk.Entry(
            register_controls, textvariable=self.register_filter, width=12
        )
        register_filter_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.register_filter.trace_add("write", lambda *_args: self._render_registers())
        register_scroll = ttk.Scrollbar(registers_frame, orient=tk.VERTICAL)
        register_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.registers = ttk.Treeview(
            registers_frame,
            columns=("name", "value"),
            show="headings",
            yscrollcommand=register_scroll.set,
            height=15,
        )
        self.registers.heading("name", text="Register")
        self.registers.heading("value", text="Value")
        self.registers.column("name", width=85, stretch=False)
        self.registers.column("value", width=190, anchor=tk.W)
        self.registers.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        register_scroll.configure(command=self.registers.yview)
        self.registers.tag_configure("changed", background="#fff2a8")
        self.flags_label = ttk.Label(registers_frame, text="NZCV: N=? Z=? C=? V=?", padding=(4, 3))
        self.flags_label.pack(side=tk.BOTTOM, fill=tk.X)
        state_top.add(registers_frame, weight=1)

        stack_frame = ttk.LabelFrame(state_top, text="Memory inspector")
        memory_controls = ttk.Frame(stack_frame)
        memory_controls.pack(side=tk.TOP, fill=tk.X, padx=4, pady=3)
        ttk.Label(memory_controls, text="Address").pack(side=tk.LEFT)
        self.memory_address = tk.StringVar(
            value=str(TARGETS[self.target_name]["stack_pointer"])
        )
        ttk.Entry(memory_controls, textvariable=self.memory_address, width=12).pack(
            side=tk.LEFT, padx=3
        )
        self.memory_format = tk.StringVar(value="Bytes")
        ttk.Combobox(
            memory_controls,
            textvariable=self.memory_format,
            values=("Bytes", "32-bit", "64-bit"),
            width=7,
            state="readonly",
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(memory_controls, text="Read", command=self._read_memory).pack(side=tk.LEFT)
        stack_scroll = ttk.Scrollbar(stack_frame, orient=tk.VERTICAL)
        stack_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        memory_horizontal_scroll = ttk.Scrollbar(
            stack_frame, orient=tk.HORIZONTAL
        )
        memory_horizontal_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.stack = tk.Text(
            stack_frame,
            wrap=tk.NONE,
            height=15,
            font=("monospace", 10),
            state=tk.DISABLED,
            yscrollcommand=stack_scroll.set,
            xscrollcommand=memory_horizontal_scroll.set,
        )
        self.stack.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        stack_scroll.configure(command=self.stack.yview)
        memory_horizontal_scroll.configure(command=self.stack.xview)
        state_top.add(stack_frame, weight=1)

        state_top.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        right.add(state_frame, weight=3)

        output_frame = ttk.Frame(right)
        self.output_tabs = ttk.Notebook(output_frame)
        self.build_output = self._add_output_tab("Build")
        self.program_output = self._add_output_tab("Program")
        self.debug_output = self._add_output_tab("Debugger")
        self.disassembly_output = self._add_output_tab("Disassembly")
        self.output_tabs.pack(fill=tk.BOTH, expand=True)
        right.add(output_frame, weight=2)

        main.add(editor_frame, weight=3)
        main.add(right, weight=2)

        self.status = ttk.Label(self.root, text="Ready", anchor=tk.W, padding=(8, 4))
        self.status.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(
            self.root,
            text="made with love by moshi",
            anchor=tk.CENTER,
            padding=(8, 2),
        ).pack(side=tk.BOTTOM, fill=tk.X)

    def _add_output_tab(self, title: str) -> tk.Text:
        frame = ttk.Frame(self.output_tabs)
        text = tk.Text(frame, wrap=tk.WORD, height=9, font=("monospace", 10), state=tk.DISABLED)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.output_tabs.add(frame, text=title)
        if title == "Build":
            text.tag_configure("source_error", foreground="#d00000", underline=True)
            text.tag_bind("source_error", "<Button-1>", self._jump_to_build_error)
        return text

    def _apply_theme(self) -> None:
        self.colors = THEME_COLORS[self.theme]
        self.root.configure(background=self.colors["background"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=self.colors["background"])
        style.configure("TLabel", background=self.colors["background"], foreground=self.colors["foreground"])
        style.configure(
            "TButton",
            background=self.colors["panel"],
            foreground=self.colors["foreground"],
            bordercolor=self.colors["panel"],
            padding=(8, 5),
            relief="flat",
        )
        style.map(
            "TButton",
            background=[
                ("disabled", self.colors["panel"]),
                ("pressed", self.colors["selection"]),
                ("active", self.colors["selection"]),
            ],
            foreground=[("disabled", self.colors["muted"])],
            bordercolor=[("focus", self.colors["register"])],
        )
        style.configure(
            "TEntry",
            fieldbackground=self.colors["editor"],
            foreground=self.colors["foreground"],
            insertcolor=self.colors["foreground"],
            bordercolor=self.colors["panel"],
            padding=4,
        )
        style.configure(
            "TCombobox",
            fieldbackground=self.colors["editor"],
            foreground=self.colors["foreground"],
            background=self.colors["panel"],
            bordercolor=self.colors["panel"],
            arrowcolor=self.colors["foreground"],
            padding=3,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.colors["editor"])],
            foreground=[("readonly", self.colors["foreground"])],
            bordercolor=[("focus", self.colors["register"])],
        )
        self.root.option_add("*TCombobox*Listbox.background", self.colors["editor"])
        self.root.option_add("*TCombobox*Listbox.foreground", self.colors["foreground"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.colors["selection"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", self.colors["foreground"])
        style.configure("TPanedwindow", background=self.colors["background"])
        style.configure("TSeparator", background=self.colors["panel"])
        style.configure(
            "TScrollbar",
            background=self.colors["panel"],
            troughcolor=self.colors["editor"],
            bordercolor=self.colors["background"],
            arrowcolor=self.colors["foreground"],
            lightcolor=self.colors["panel"],
            darkcolor=self.colors["panel"],
            relief="flat",
        )
        style.map(
            "TScrollbar",
            background=[("active", self.colors["selection"]), ("pressed", self.colors["selection"])],
        )
        style.configure(
            "TNotebook",
            background=self.colors["background"],
            bordercolor=self.colors["background"],
        )
        style.configure(
            "TNotebook.Tab",
            background=self.colors["panel"],
            foreground=self.colors["foreground"],
            padding=(10, 6),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[
                ("selected", self.colors["editor"]),
                ("active", self.colors["selection"]),
            ],
            foreground=[("selected", self.colors["foreground"])],
        )
        style.configure(
            "TLabelframe",
            background=self.colors["background"],
            foreground=self.colors["foreground"],
            bordercolor=self.colors["panel"],
        )
        style.configure(
            "TLabelframe.Label",
            background=self.colors["background"],
            foreground=self.colors["foreground"],
        )
        style.configure(
            "Treeview",
            background=self.colors["editor"],
            fieldbackground=self.colors["editor"],
            foreground=self.colors["foreground"],
            font=(self.font_family, max(8, self.font_size - 2)),
            rowheight=max(20, self.font_size + 8),
            bordercolor=self.colors["panel"],
        )
        style.configure(
            "Treeview.Heading",
            background=self.colors["panel"],
            foreground=self.colors["foreground"],
            padding=(6, 5),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", self.colors["selection"])],
        )
        style.map(
            "Treeview",
            background=[("selected", self.colors["selection"])],
            foreground=[("selected", self.colors["foreground"])],
        )

        self.editor.configure(
            background=self.colors["editor"],
            foreground=self.colors["foreground"],
            insertbackground=self.colors["foreground"],
            selectbackground=self.colors["selection"],
            highlightthickness=1,
            highlightbackground=self.colors["panel"],
            highlightcolor=self.colors["register"],
            borderwidth=0,
        )
        for widget in (
            self.stack,
            self.build_output,
            self.program_output,
            self.debug_output,
            self.disassembly_output,
        ):
            widget.configure(
                background=self.colors["editor"],
                foreground=self.colors["foreground"],
                insertbackground=self.colors["foreground"],
                selectbackground=self.colors["selection"],
                highlightthickness=1,
                highlightbackground=self.colors["panel"],
                highlightcolor=self.colors["register"],
                borderwidth=0,
            )
        self.line_numbers.configure(
            background=self.colors["gutter"],
            highlightbackground=self.colors["gutter"],
        )
        self.registers.tag_configure("changed", background=self.colors["changed"])
        self.build_output.tag_configure(
            "source_error",
            foreground="#ff6b68" if self.theme == "Dark" else "#d00000",
            underline=True,
        )
        self._configure_syntax_tags()
        self._draw_line_numbers()

    def _apply_font(self) -> None:
        editor_font = (self.font_family, self.font_size)
        output_font = (self.font_family, max(8, self.font_size - 2))
        self.editor.configure(font=editor_font)
        for widget in (
            self.stack,
            self.build_output,
            self.program_output,
            self.debug_output,
            self.disassembly_output,
        ):
            widget.configure(font=output_font)
        self._draw_line_numbers()

    def _change_target(self, _event: tk.Event | None = None) -> None:
        selected = self.target_var.get()
        if selected == self.target_name:
            return
        old_stack_pointer = TARGETS[self.target_name]["stack_pointer"]
        self.stop_execution()
        self.target_name = selected
        if self.memory_address.get() == old_stack_pointer:
            self.memory_address.set(str(TARGETS[selected]["stack_pointer"]))
        self.register_raw_values.clear()
        self._render_registers()
        self._set_text(self.disassembly_output, "")
        self._save_preferences()
        self._update_path_label()
        self.status.configure(text=f"Target set to {self.target_name}")

    def _save_preferences(self) -> bool:
        self.settings.update(
            theme=self.theme,
            font_family=self.font_family,
            font_size=self.font_size,
            indent_width=int(self.indent_width.get()),
            target=self.target_name,
            register_filter=self.register_filter.get(),
            recent_files=self.recent_files[:RECENT_FILE_LIMIT],
            last_file=str(self.source_path) if self.source_path else self.last_file,
            window_geometry=self.root.geometry(),
        )
        try:
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
            self.preferences_path.write_text(
                json.dumps(self.settings, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            self.status.configure(text=f"Could not save settings: {exc}")
            return False
        return True

    def _highlight_build_errors(self) -> None:
        self.build_output.tag_remove("source_error", "1.0", tk.END)
        content = self.build_output.get("1.0", "end-1c")
        offset = 0
        pattern = re.compile(r"^(.+?):(\d+):(?:\d+:)? (?:fatal )?Error:", re.IGNORECASE)
        for line_text in content.splitlines(keepends=True):
            if pattern.match(line_text):
                start = f"1.0+{offset}c"
                end = f"1.0+{offset + len(line_text.rstrip())}c"
                self.build_output.tag_add("source_error", start, end)
            offset += len(line_text)

    def _jump_to_build_error(self, event: tk.Event) -> None:
        index = self.build_output.index(f"@{event.x},{event.y}")
        line_text = self.build_output.get(f"{index} linestart", f"{index} lineend")
        match = re.match(r"^(.+?):(\d+):(?:\d+:)? (?:fatal )?Error:", line_text, re.IGNORECASE)
        if match is None or self.source_path is None:
            return
        error_file = Path(match.group(1))
        try:
            same_file = error_file.resolve() == self.source_path.resolve()
        except OSError:
            same_file = error_file.name == self.source_path.name
        if not same_file and error_file.name != self.source_path.name:
            return
        self._set_current_source_line(int(match.group(2)))
        self.editor.mark_set(tk.INSERT, f"{match.group(2)}.0")
        self.editor.focus_set()

    def _remember_file(self, path: Path) -> None:
        resolved = str(path.resolve())
        self.recent_files = [item for item in self.recent_files if item != resolved]
        self.recent_files.insert(0, resolved)
        self.recent_files = self.recent_files[:RECENT_FILE_LIMIT]
        self.last_file = resolved
        self._save_preferences()

    def show_recent_files(self) -> None:
        existing = [path for path in self.recent_files if Path(path).is_file()]
        if not existing:
            messagebox.showinfo("Recent files", "No recent source files found.", parent=self.root)
            return
        window = tk.Toplevel(self.root)
        window.title("Recent files")
        window.transient(self.root)
        window.geometry("640x300")
        window.configure(background=self.colors["background"])
        listing = tk.Listbox(
            window,
            background=self.colors["editor"],
            foreground=self.colors["foreground"],
            selectbackground=self.colors["selection"],
            selectforeground=self.colors["foreground"],
            highlightthickness=1,
            highlightbackground=self.colors["panel"],
        )
        listing.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        for path in existing:
            listing.insert(tk.END, path)

        def open_selected(_event: tk.Event | None = None) -> None:
            selection = listing.curselection()
            if selection:
                if not self._may_discard_or_save():
                    return
                self._cancel_autosave()
                self._load_source(Path(existing[selection[0]]))
                window.destroy()

        listing.bind("<Double-Button-1>", open_selected)
        ttk.Button(window, text="Open", command=open_selected).pack(pady=(0, 8))

    def show_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Settings")
        window.transient(self.root)
        window.resizable(False, False)
        window.configure(background=self.colors["background"])
        theme_value = tk.StringVar(value=self.theme)
        font_value = tk.StringVar(value=self.font_family)
        size_value = tk.IntVar(value=self.font_size)
        indent_value = tk.StringVar(value=self.indent_width.get())
        fields = (
            ("Theme", ttk.Combobox(window, textvariable=theme_value, values=("Light", "Dark"), state="readonly")),
            ("Font", ttk.Combobox(window, textvariable=font_value, values=FONT_FAMILIES, state="readonly")),
            ("Font size", ttk.Spinbox(window, from_=8, to=32, textvariable=size_value, width=8)),
            ("Tab spaces", ttk.Combobox(window, textvariable=indent_value, values=("2", "4", "8"), state="readonly")),
        )
        for row, (label, control) in enumerate(fields):
            ttk.Label(window, text=label).grid(row=row, column=0, padx=8, pady=5, sticky=tk.W)
            control.grid(row=row, column=1, padx=8, pady=5, sticky=tk.EW)
        window.columnconfigure(1, weight=1)

        def apply() -> None:
            try:
                size = int(size_value.get())
            except (ValueError, tk.TclError):
                messagebox.showerror("Invalid font size", "Choose a font size from 8 to 32.", parent=window)
                return
            if not 8 <= size <= 32:
                messagebox.showerror("Invalid font size", "Choose a font size from 8 to 32.", parent=window)
                return
            self.theme = theme_value.get()
            self.font_family = font_value.get()
            self.font_size = size
            self.indent_width.set(indent_value.get())
            self._apply_theme()
            self._apply_font()
            self._save_preferences()
            window.destroy()

        ttk.Button(window, text="Apply", command=apply).grid(
            row=len(fields), column=0, columnspan=2, padx=8, pady=10, sticky=tk.E
        )

    def _configure_syntax_tags(self) -> None:
        for tag in ("instruction", "register", "directive", "number", "label", "string", "comment"):
            self.editor.tag_configure(tag, foreground=self.colors[tag])
        self.editor.tag_configure(
            "current_execution", background=self.colors["execution"]
        )

    def _editor_yview(self, first: str, last: str) -> None:
        self.editor_scroll.set(first, last)
        self._draw_line_numbers()

    def _draw_line_numbers(self) -> None:
        self.line_numbers.delete("all")
        if not self.editor.winfo_exists():
            return
        try:
            line = int(self.editor.index("@0,0").split(".")[0])
            bottom = self.editor.winfo_height()
            while True:
                info = self.editor.dlineinfo(f"{line}.0")
                if info is None or info[1] > bottom:
                    break
                self.line_numbers.create_text(
                    48,
                    info[1],
                    anchor=tk.NE,
                    text=str(line),
                    fill=self.colors["muted"],
                    font=(self.font_family, self.font_size),
                )
                if line in self.breakpoints:
                    self.line_numbers.create_oval(
                        3,
                        info[1] + 3,
                        11,
                        info[1] + 11,
                        fill=self.colors["breakpoint"],
                        outline="",
                    )
                if line == self.current_source_line:
                    self.line_numbers.create_text(
                        21,
                        info[1],
                        anchor=tk.NE,
                        text=">",
                        fill=self.colors["register"],
                        font=(self.font_family, self.font_size, "bold"),
                    )
                line += 1
        except tk.TclError:
            return

    def _on_editor_key_release(self, _event: tk.Event) -> None:
        self._update_cursor_status()
        self._draw_line_numbers()

    def _insert_newline_with_indent(self, _event: tk.Event) -> str:
        line_start = self.editor.index(f"{tk.INSERT} linestart")
        before_cursor = self.editor.get(line_start, tk.INSERT)
        indent_match = re.match(r"[ \t]*", before_cursor)
        indent = indent_match.group(0) if indent_match else ""
        if before_cursor.rstrip().endswith(":"):
            indent += " " * int(self.indent_width.get())
        if self.editor.tag_ranges(tk.SEL):
            self.editor.delete(tk.SEL_FIRST, tk.SEL_LAST)
        self.editor.insert(tk.INSERT, "\n" + indent)
        return "break"

    def _insert_indent(self, _event: tk.Event) -> str:
        if self.editor.tag_ranges(tk.SEL):
            self.editor.delete(tk.SEL_FIRST, tk.SEL_LAST)
        self.editor.insert(tk.INSERT, " " * int(self.indent_width.get()))
        return "break"

    def _outdent_selection(self, _event: tk.Event) -> str:
        if not self.editor.tag_ranges(tk.SEL):
            return "break"
        first = int(self.editor.index(tk.SEL_FIRST).split(".")[0])
        last = int(self.editor.index(f"{tk.SEL_LAST}-1c").split(".")[0])
        width = int(self.indent_width.get())
        for line in range(last, first - 1, -1):
            content = self.editor.get(f"{line}.0", f"{line}.end")
            removed = len(content) - len(content.lstrip(" "))
            if removed:
                self.editor.delete(f"{line}.0", f"{line}.{min(width, removed)}")
            elif content.startswith("\t"):
                self.editor.delete(f"{line}.0", f"{line}.1")
        return "break"

    def _toggle_comment(self) -> str:
        if self.editor.tag_ranges(tk.SEL):
            first = int(self.editor.index(tk.SEL_FIRST).split(".")[0])
            last = int(self.editor.index(f"{tk.SEL_LAST}-1c").split(".")[0])
        else:
            first = last = int(self.editor.index(tk.INSERT).split(".")[0])
        lines = [
            self.editor.get(f"{line}.0", f"{line}.end")
            for line in range(first, last + 1)
        ]
        uncomment = all(not text.strip() or re.match(r"^\s*//", text) for text in lines)
        for line in range(last, first - 1, -1):
            text = self.editor.get(f"{line}.0", f"{line}.end")
            indent = len(text) - len(text.lstrip(" \t"))
            if uncomment:
                match = re.match(r"(// ?)", text[indent:])
                if match:
                    self.editor.delete(
                        f"{line}.{indent}",
                        f"{line}.{indent + len(match.group(1))}",
                    )
            elif text.strip():
                self.editor.insert(f"{line}.{indent}", "// ")
        return "break"

    def _go_to_line(self) -> None:
        last_line = int(self.editor.index("end-1c").split(".")[0])
        line = simpledialog.askinteger(
            "Go to line",
            f"Line number (1–{last_line})",
            parent=self.root,
            minvalue=1,
            maxvalue=last_line,
        )
        if line is not None:
            self.editor.mark_set(tk.INSERT, f"{line}.0")
            self.editor.see(tk.INSERT)
            self.editor.focus_set()

    def _toggle_breakpoint(self, event: tk.Event) -> None:
        line = int(self.editor.index(f"@0,{event.y}").split(".")[0])
        if line in self.breakpoints:
            self.breakpoints.remove(line)
            number = self.installed_breakpoints.pop(line, None)
            if number is not None:
                self._send_gdb(f"-break-delete {number}")
        else:
            self.breakpoints.add(line)
            self._insert_breakpoint(line)
        self._draw_line_numbers()

    def _insert_breakpoint(self, line: int) -> None:
        if (
            self.source_path is None
            or line in self.installed_breakpoints
            or line in self.pending_breakpoint_lines
            or self.gdb is None
        ):
            return
        location = f"{self.source_path.resolve()}:{line}"
        self.pending_breakpoint_lines.add(line)
        if self._send_gdb(
            f"-break-insert {self._mi_quote(location)}",
            action=("break_insert", line),
        ) is None:
            self.pending_breakpoint_lines.discard(line)

    def _sync_breakpoints(self) -> None:
        for line in sorted(self.breakpoints):
            self._insert_breakpoint(line)

    def _clear_breakpoints(self) -> None:
        for number in tuple(self.installed_breakpoints.values()):
            self._send_gdb(f"-break-delete {number}")
        self.breakpoints.clear()
        self.installed_breakpoints.clear()
        self.pending_breakpoint_lines.clear()
        self._draw_line_numbers()

    def _set_current_source_line(self, line: int | None) -> None:
        self.editor.tag_remove("current_execution", "1.0", tk.END)
        if line is not None and 1 <= line <= int(self.editor.index("end-1c").split(".")[0]):
            self.current_source_line = line
            self.editor.tag_add("current_execution", f"{line}.0", f"{line}.end")
            self.editor.see(f"{line}.0")
        else:
            self.current_source_line = None
        self.editor.tag_raise("current_execution")
        self._draw_line_numbers()

    def _schedule_highlighting(self) -> None:
        if self.highlight_id is not None:
            self.root.after_cancel(self.highlight_id)
        self.highlight_id = self.root.after_idle(self._highlight_syntax)

    def _highlight_syntax(self) -> None:
        self.highlight_id = None
        source = self.editor.get("1.0", "end-1c")
        tags = {
            "instruction": r"(?m)^[ \t]*(?:(?:[A-Za-z_.$][\w.$]*):[ \t]*)?([A-Za-z][A-Za-z0-9_.]*)\b",
            "register": r"\b(?:[xw]\d+|[xw]zr|[vqbhsdzp]\d+|r(?:\d+|ax|bx|cx|dx|si|di|bp|sp|ip|flags|(?:8|9|1[0-5])d?)|e(?:ax|bx|cx|dx|si|di|bp|sp|ip|flags)|(?:ax|bx|cx|dx|si|di|bp|sp|ip|rflags)|sp|wsp|fp|lr|nzcv|cpsr)\b",
            "directive": r"(?m)^[ \t]*\.[A-Za-z_][\w.]*",
            "number": r"(?<![A-Za-z0-9_])#?-?(?:0[xX][0-9A-Fa-f]+|0[bB][01]+|\d+)\b",
            "label": r"(?m)^[ \t]*[A-Za-z_.$][\w.$]*(?=:)",
            "string": r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
            "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        }
        for tag, pattern in tags.items():
            self.editor.tag_remove(tag, "1.0", tk.END)
            for match in re.finditer(pattern, source, re.IGNORECASE):
                start = match.start(1) if tag == "instruction" else match.start()
                end = match.end(1) if tag == "instruction" else match.end()
                self.editor.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")
        self.editor.tag_raise("comment")

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-s>", lambda _event: self.save_file())
        self.root.bind("<Control-o>", lambda _event: self.open_file())
        self.root.bind("<Control-n>", lambda _event: self.new_file())
        self.root.bind("<Control-f>", lambda _event: self.find_replace())
        self.root.bind("<Control-z>", lambda _event: self._undo())
        self.root.bind("<Control-y>", lambda _event: self._redo())
        self.root.bind("<Control-Shift-Z>", lambda _event: self._redo())

    def _load_source(self, path: Path) -> None:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.status.configure(text=f"Open failed: {exc}")
            return
        self._clear_breakpoints()
        self._set_current_source_line(None)
        self.source_path = path
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", content)
        self.editor.edit_modified(False)
        self.is_dirty = False
        self._highlight_syntax()
        self._draw_line_numbers()
        self._update_path_label()
        self.status.configure(text="Ready — changes are autosaved")
        self._remember_file(path)

    def _may_discard_or_save(self) -> bool:
        if not self.is_dirty:
            return True
        if self.source_path is not None:
            return self.save_file()
        answer = messagebox.askyesnocancel(
            "Unsaved changes",
            "Save this untitled document before continuing?",
            parent=self.root,
        )
        if answer is None:
            return False
        return self.save_file() if answer else True

    def _update_path_label(self) -> None:
        shown = str(self.source_path) if self.source_path else "Untitled"
        self.path_label.configure(text=shown)
        dirty_marker = " *" if self.is_dirty else ""
        self.root.title(f"Assembly Workbench [{self.target_name}] — {shown}{dirty_marker}")

    def new_file(self) -> None:
        if not self._may_discard_or_save():
            return
        self._cancel_autosave()
        self._clear_breakpoints()
        self._set_current_source_line(None)
        self.source_path = None
        self.editor.delete("1.0", tk.END)
        self.editor.edit_modified(False)
        self.is_dirty = False
        self._highlight_syntax()
        self._draw_line_numbers()
        self._update_path_label()
        self.status.configure(text="Untitled — save once to enable autosave")

    def open_file(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self.root,
            filetypes=(("AArch64 assembly", "*.s *.S *.asm"), ("All files", "*")),
        )
        if filename:
            if not self._may_discard_or_save():
                return
            self._cancel_autosave()
            self._load_source(Path(filename).resolve())

    def save_file(self) -> bool:
        if self.source_path is None:
            filename = filedialog.asksaveasfilename(
                parent=self.root,
                defaultextension=".s",
                filetypes=(("AArch64 assembly", "*.s"), ("All files", "*")),
            )
            if not filename:
                return False
            self.source_path = Path(filename).resolve()
            self._update_path_label()
        try:
            self.source_path.write_text(self.editor.get("1.0", "end-1c"), encoding="utf-8")
        except OSError as exc:
            self.status.configure(text=f"Save failed: {exc}")
            self._append(self.build_output, f"Save failed: {exc}\n")
            return False
        self.editor.edit_modified(False)
        self.is_dirty = False
        self._update_path_label()
        if self.source_path is not None:
            self._remember_file(self.source_path)
        self.status.configure(text=f"Saved {self.source_path}")
        return True

    def _on_edit(self, _event: tk.Event) -> None:
        if not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        self.is_dirty = True
        self._update_path_label()
        if self.current_source_line is not None:
            self._set_current_source_line(None)
        if self.breakpoints:
            self._clear_breakpoints()
            self._append(
                self.debug_output,
                "Breakpoints cleared because the source changed; set them again after rebuilding.\n",
            )
        self._update_cursor_status()
        self._schedule_highlighting()
        self._draw_line_numbers()
        self._cancel_autosave()
        if self.source_path is not None:
            self.autosave_id = self.root.after(AUTOSAVE_DELAY_MS, self._autosave)

    def _autosave(self) -> None:
        self.autosave_id = None
        if self.source_path is None:
            return
        try:
            self.source_path.write_text(self.editor.get("1.0", "end-1c"), encoding="utf-8")
        except OSError as exc:
            self.status.configure(text=f"Autosave failed: {exc}")
            self._append(self.build_output, f"Autosave failed: {exc}\n")
            return
        self.is_dirty = False
        self._update_path_label()
        self.status.configure(text=f"Autosaved {self.source_path}")

    def _cancel_autosave(self) -> None:
        if self.autosave_id is not None:
            self.root.after_cancel(self.autosave_id)
            self.autosave_id = None

    def _update_cursor_status(self, _event: tk.Event | None = None) -> None:
        row, column = self.editor.index(tk.INSERT).split(".")
        self.status.configure(text=f"Line {row}, column {int(column) + 1}")

    def _undo(self) -> None:
        try:
            self.editor.edit_undo()
        except tk.TclError:
            pass

    def _redo(self) -> None:
        try:
            self.editor.edit_redo()
        except tk.TclError:
            pass

    def find_replace(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Find and replace")
        window.transient(self.root)
        window.resizable(False, False)
        window.configure(background=self.colors["background"])
        ttk.Label(window, text="Find").grid(row=0, column=0, padx=8, pady=6, sticky=tk.W)
        find_entry = ttk.Entry(window, width=36)
        find_entry.grid(row=0, column=1, padx=8, pady=6)
        ttk.Label(window, text="Replace with").grid(
            row=1, column=0, padx=8, pady=6, sticky=tk.W
        )
        replace_entry = ttk.Entry(window, width=36)
        replace_entry.grid(row=1, column=1, padx=8, pady=6)

        def find_next() -> None:
            needle = find_entry.get()
            if not needle:
                return
            start = self.editor.index(tk.INSERT)
            match = self.editor.search(needle, start, stopindex=tk.END, nocase=True)
            if not match:
                match = self.editor.search(needle, "1.0", stopindex=start, nocase=True)
            if match:
                end = f"{match}+{len(needle)}c"
                self.editor.tag_remove(tk.SEL, "1.0", tk.END)
                self.editor.tag_add(tk.SEL, match, end)
                self.editor.mark_set(tk.INSERT, end)
                self.editor.see(match)
                self.editor.focus_set()

        def replace_one() -> None:
            if self.editor.tag_ranges(tk.SEL):
                selected = self.editor.get(tk.SEL_FIRST, tk.SEL_LAST)
                if selected.casefold() == find_entry.get().casefold():
                    self.editor.delete(tk.SEL_FIRST, tk.SEL_LAST)
                    self.editor.insert(tk.INSERT, replace_entry.get())
            find_next()

        def replace_all() -> None:
            needle = find_entry.get()
            if not needle:
                return
            content = self.editor.get("1.0", "end-1c")
            updated = re.sub(re.escape(needle), lambda _match: replace_entry.get(), content, flags=re.I)
            if updated != content:
                self.editor.delete("1.0", tk.END)
                self.editor.insert("1.0", updated)
            window.destroy()

        buttons = ttk.Frame(window)
        buttons.grid(row=2, column=0, columnspan=2, padx=8, pady=8, sticky=tk.E)
        ttk.Button(buttons, text="Find next", command=find_next).pack(side=tk.LEFT, padx=3)
        ttk.Button(buttons, text="Replace", command=replace_one).pack(side=tk.LEFT, padx=3)
        ttk.Button(buttons, text="Replace all", command=replace_all).pack(side=tk.LEFT, padx=3)
        find_entry.focus_set()

    def build(self) -> None:
        self._build_source(debug_after=False, run_after=False)

    def build_and_debug(self) -> None:
        self._build_source(debug_after=True, run_after=False)

    def run(self) -> None:
        self._build_source(debug_after=False, run_after=True)

    def _build_source(self, debug_after: bool, run_after: bool) -> None:
        if not self.save_file():
            return
        assert self.source_path is not None
        source = self.source_path
        obj = source.with_suffix(".o")
        binary = (
            source.with_suffix("")
            if source.suffix
            else source.with_name(source.name + ".out")
        )
        self.binary_path = binary
        target_name = self.target_name
        target = TARGETS[target_name]
        self._append(
            self.build_output,
            f"$ {target['assembler']} {' '.join(target['assembler_args'])} -g {source.name} -o {obj.name}\n",
        )
        self.status.configure(text="Assembling and linking…" if not run_after else "Building before run…")
        threading.Thread(
            target=self._build_worker,
            args=(source, obj, binary, debug_after, run_after, target_name, target),
            daemon=True,
        ).start()

    def _build_worker(
        self,
        source: Path,
        obj: Path,
        binary: Path,
        debug_after: bool,
        run_after: bool,
        target_name: str,
        target: dict[str, str | tuple[str, ...]],
    ) -> None:
        output: list[str] = []
        try:
            assembler = str(target["assembler"])
            assembler_args = tuple(target["assembler_args"])
            linker = str(target["linker"])
            linker_args = tuple(target["linker_args"])
            assemble = subprocess.run(
                [assembler, *assembler_args, "-g", str(source), "-o", str(obj)],
                cwd=source.parent,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            output.extend(part for part in (assemble.stdout, assemble.stderr) if part)
            if assemble.returncode:
                self.events.put(
                    ("build_done", False, "".join(output), debug_after, run_after, None, target_name)
                )
                return

            output.append(f"$ {linker} {' '.join(linker_args)} {obj.name} -o {binary.name}\n")
            link = subprocess.run(
                [linker, *linker_args, str(obj), "-o", str(binary)],
                cwd=source.parent,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            output.extend(part for part in (link.stdout, link.stderr) if part)
            self.events.put(
                (
                    "build_done",
                    link.returncode == 0,
                    "".join(output),
                    debug_after,
                    run_after,
                    binary,
                    target_name,
                )
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.events.put(
                ("build_done", False, f"{exc}\n", debug_after, run_after, None, target_name)
            )

    def _start_debugger(self, binary: Path, target_name: str) -> None:
        self._stop_runner()
        self.stop_debugger()
        self.continue_mode = False
        self.pause_requested = False
        self.installed_breakpoints.clear()
        self.pending_breakpoint_lines.clear()
        self.pending_gdb_actions.clear()
        self.register_raw_values.clear()
        self.changed_registers.clear()
        self._render_registers()
        self._set_current_source_line(None)
        port = self._free_port()
        self.register_names = []
        self._set_text(
            self.stack,
            "Waiting for GDB to stop.\n"
            "The inspector will read 128 bytes from the stack pointer automatically.",
        )
        self._set_text(self.disassembly_output, "")
        self._append(
            self.debug_output,
            f"$ {TARGETS[target_name]['qemu']} -g {port} {binary}\n",
        )

        def launch() -> None:
            qemu: subprocess.Popen[str] | None = None
            gdb: subprocess.Popen[str] | None = None
            try:
                qemu = subprocess.Popen(
                    [TARGETS[target_name]["qemu"], "-g", str(port), str(binary)],
                    cwd=binary.parent,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                gdb = subprocess.Popen(
                    ["gdb-multiarch", "--quiet", "--nx", "--interpreter=mi2"],
                    cwd=binary.parent,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                if self.closed:
                    gdb.terminate()
                    qemu.terminate()
                    return
                self.events.put(("debug_started", qemu, gdb, binary, port, target_name, None))
            except OSError as exc:
                for proc in (gdb, qemu):
                    if proc is not None:
                        proc.terminate()
                self.events.put(("debug_started", qemu, gdb, binary, port, target_name, str(exc)))

        threading.Thread(target=launch, daemon=True).start()
        self.status.configure(text="Starting QEMU and GDB…")

    def _start_run(self, binary: Path, target_name: str) -> None:
        self.stop_debugger()
        self._stop_runner()
        self._set_text(self.program_output, "")
        self._set_text(
            self.stack,
            "Run mode does not attach GDB.\n"
            "Use Build + Debug to inspect memory.",
        )
        self.output_tabs.select(self.program_output.master)
        emulator = str(TARGETS[target_name]["qemu"])
        self._append(self.program_output, f"$ {emulator} {binary}\n")
        try:
            process = subprocess.Popen(
                [emulator, str(binary)],
                cwd=binary.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )
        except OSError as exc:
            self._append(self.program_output, f"Could not start program: {exc}\n")
            self.status.configure(text="Program failed to start")
            return

        self.runner = process
        threading.Thread(target=self._read_program_output, args=(process,), daemon=True).start()
        self.status.configure(text=f"Running {binary.name}")

    def _read_program_output(self, process: subprocess.Popen[bytes]) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        if process.stdout is not None:
            try:
                while True:
                    chunk = process.stdout.read(4096)
                    if not chunk:
                        break
                    text = decoder.decode(chunk)
                    if text:
                        self.events.put(("run_output", process, text))
            except OSError as exc:
                self.events.put(("run_output", process, f"\nOutput reader failed: {exc}\n"))
            finally:
                process.stdout.close()
        remaining = decoder.decode(b"", final=True)
        if remaining:
            self.events.put(("run_output", process, remaining))
        return_code = process.wait()
        self.events.put(("run_done", process, return_code))

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def _send_gdb(self, command: str, action: tuple | None = None) -> str | None:
        if self.gdb is None or self.gdb.poll() is not None or self.gdb.stdin is None:
            if action is None:
                self.status.configure(text="Debugger is not running")
            return None
        self.gdb_token += 1
        token = str(self.gdb_token)
        if action is not None:
            self.pending_gdb_actions[token] = action
        try:
            self.gdb.stdin.write(token + command + "\n")
            self.gdb.stdin.flush()
        except OSError as exc:
            self.pending_gdb_actions.pop(token, None)
            self._append(self.debug_output, f"GDB command failed: {exc}\n")
            return None
        return token

    def _gdb_command(self, command: str) -> None:
        if self._send_gdb(command) is None:
            return
        if command == "-exec-step-instruction":
            self.status.configure(text="Stepping one instruction…")

    def _step_instruction(self) -> None:
        self.continue_mode = False
        self.pause_requested = False
        self._gdb_command("-exec-step-instruction")

    def _continue_debugging(self) -> None:
        if self.gdb is None or self.gdb.poll() is not None:
            self.status.configure(text="Debugger is not running")
            return
        if self.continue_mode:
            return
        self.continue_mode = True
        self.pause_requested = False
        self.status.configure(text="Running under GDB — Pause stops after the current instruction")
        if self._send_gdb("-exec-step-instruction") is None:
            self.continue_mode = False

    def _pause_debugging(self) -> None:
        if not self.continue_mode:
            self.status.configure(text="Debugger is not running continuously")
            return
        self.continue_mode = False
        self.pause_requested = True
        self.status.configure(text="Pausing after the current instruction…")

    def _read_memory(self, automatic: bool = False) -> None:
        address = self.memory_address.get().strip()
        register_expression = (
            r"\$?(?:sp|wsp|rsp|esp|pc|rip|eip|lr|x\d+|w\d+|r\d+|rax|rbx|rcx|rdx|rsi|rdi|rbp|"
            r"eax|ebx|ecx|edx|esi|edi|ebp|ax|bx|cx|dx|si|di|bp)"
        )
        if not re.fullmatch(
            rf"(?:{register_expression}|0[xX][0-9a-fA-F]+|[0-9]+|&[A-Za-z_.$][\w.$]*)",
            address,
            re.IGNORECASE,
        ):
            message = (
                "Use a register such as $sp or $x0, &label, or a numeric address. "
                "Register values are treated as pointers and must point to readable memory."
            )
            self._set_text(self.stack, f"Invalid address.\n{message}")
            self.status.configure(text=message)
            return
        if not address.startswith("$") and re.fullmatch(
            register_expression, address, re.IGNORECASE
        ):
            address = "$" + address
        if self.gdb is None:
            if not automatic:
                message = "Memory inspection needs Build + Debug; Build and Run do not attach GDB."
                self._set_text(self.stack, message)
                self.status.configure(text=message)
            return
        mode = self.memory_format.get()
        token = self._send_gdb(
            f"-data-read-memory-bytes {address} 128",
            action=("memory", address, mode),
        )
        if token is not None:
            self._set_text(self.stack, f"Reading 128 bytes from {address}…")
            self.status.configure(text=f"Reading memory at {address}…")

    def stop_debugger(self) -> None:
        for proc in (self.gdb, self.qemu):
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError as exc:
                    self._append(self.debug_output, f"Could not stop process: {exc}\n")
        self.gdb = None
        self.qemu = None
        self.pending_gdb_actions.clear()
        self.pending_breakpoint_lines.clear()
        self.installed_breakpoints.clear()

    def _stop_runner(self) -> None:
        if self.runner is not None and self.runner.poll() is None:
            try:
                self.runner.terminate()
            except OSError as exc:
                self._append(self.program_output, f"Could not stop program: {exc}\n")

    def stop_execution(self) -> None:
        self.continue_mode = False
        self.pause_requested = False
        had_debugger = self.gdb is not None or self.qemu is not None
        had_runner = self.runner is not None and self.runner.poll() is None
        self.stop_debugger()
        self._stop_runner()
        if had_runner:
            self.status.configure(text="Stopping program…")
        elif had_debugger:
            self.status.configure(text="Debugger stopped")
        else:
            self.status.configure(text="No program is running")

    def _drain_events(self) -> None:
        if self.closed:
            return
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "build_done":
                _, succeeded, output, debug_after, run_after, binary, target_name = event
                self._append(self.build_output, output or ("Build succeeded.\n" if succeeded else "Build failed.\n"))
                self._highlight_build_errors()
                if succeeded and binary is not None:
                    self.status.configure(text=f"Built {binary}")
                    if debug_after:
                        self._start_debugger(binary, target_name)
                    elif run_after:
                        self._start_run(binary, target_name)
                else:
                    self.status.configure(text="Build failed — see Build output")
            elif kind == "debug_started":
                _, qemu, gdb, binary, port, target_name, error = event
                if error:
                    self._append(self.debug_output, f"Could not start debugger: {error}\n")
                    self.status.configure(text="Debugger failed to start")
                    continue
                self.qemu, self.gdb = qemu, gdb
                self._start_reader(qemu, "qemu")
                self._start_reader(gdb, "gdb")
                self._send_gdb("-gdb-set mi-async on")
                self._send_gdb(f"-file-exec-and-symbols {self._mi_quote(str(binary))}")
                self._send_gdb(f"-target-select remote localhost:{port}")
                self._send_gdb("-data-list-register-names")
                self.status.configure(text=f"Connected to {target_name} — use Step")
            elif kind == "process_line":
                _, process_name, line = event
                if process_name == "gdb":
                    self._handle_gdb_line(line)
                elif line:
                    self._append(self.debug_output, f"QEMU: {line}")
            elif kind == "run_output":
                _, process, text = event
                if process is self.runner:
                    self._append(self.program_output, text)
            elif kind == "run_done":
                _, process, return_code = event
                if process is self.runner:
                    self.runner = None
                    self._append(self.program_output, f"\nProgram exited with status {return_code}\n")
                    self.status.configure(text=f"Program exited with status {return_code}")
        self.root.after(50, self._drain_events)

    def _start_reader(self, proc: subprocess.Popen[str], name: str) -> None:
        if proc.stdout is None:
            return

        def read_output() -> None:
            try:
                for line in proc.stdout:
                    self.events.put(("process_line", name, line))
            except OSError as exc:
                self.events.put(("process_line", name, f"Output reader failed: {exc}\n"))

        threading.Thread(target=read_output, daemon=True).start()

    def _handle_gdb_line(self, line: str) -> None:
        stripped = line.rstrip("\r\n")
        if stripped.startswith('~"') or stripped.startswith('@"') or stripped.startswith('&"'):
            try:
                readable = json.loads(stripped[1:])
            except json.JSONDecodeError:
                readable = stripped
            if not self.continue_mode:
                self._append(self.debug_output, readable)
        elif (
            stripped
            and not stripped.startswith(("*stopped", "*running"))
            and not re.match(r"^(?:\d+)?\^(?:done|error|running|connected|exit)(?:,|$)", stripped)
        ):
            self._append(self.debug_output, stripped + "\n")

        if "*stopped" in stripped:
            reason = re.search(r'reason="([^"]+)"', stripped)
            stop_reason = reason.group(1) if reason else ""
            terminal_reasons = {
                "breakpoint-hit",
                "exited",
                "exited-normally",
                "exited-signalled",
                "signal-received",
                "watchpoint-trigger",
                "location-reached",
            }
            if self.continue_mode and stop_reason not in terminal_reasons:
                self._send_gdb("-exec-step-instruction")
                return
            self.continue_mode = False
            was_pause_requested = self.pause_requested
            self.pause_requested = False
            if stop_reason.startswith("exited"):
                self.status.configure(text=f"Program {stop_reason.replace('-', ' ')}")
                return
            self.status.configure(
                text="Paused after instruction"
                if was_pause_requested
                else f"Debugger stopped: {stop_reason.replace('-', ' ')}"
                if reason
                else "Debugger stopped"
            )
            self._send_gdb("-data-list-register-values x")
            self._read_memory(automatic=True)
            self._send_gdb('-data-disassemble -s $pc -e "$pc+64" -- 0')
            self._send_gdb("-stack-info-frame")
            self._sync_breakpoints()

        result_match = re.match(
            r"^(?:(\d+))?\^(done|error|running|connected|exit)(?:,(.*))?$",
            stripped,
        )
        if result_match is None:
            return
        token, result_class, result = result_match.groups()
        result = result or ""
        action = self.pending_gdb_actions.pop(token, None) if token else None
        if result_class == "error":
            self._append(self.debug_output, f"GDB error: {result}\n")
            if action and action[0] == "break_insert":
                self.pending_breakpoint_lines.discard(action[1])
            if action and action[0] == "memory":
                self._append(self.debug_output, f"Memory read failed: {result}\n")
                self._set_text(
                    self.stack,
                    f"Could not read memory at {action[1]}.\n"
                    "If this is a register, its current value is used as the address; "
                    "it must point to mapped, readable memory.\n"
                    f"GDB details: {result}",
                )
                self.status.configure(
                    text=f"Memory read failed at {action[1]} — check that it is a valid pointer"
                )
            else:
                self.status.configure(text="GDB reported an error — see Debugger output")
            return
        if action:
            self._handle_gdb_action(action, result)
        if result_class != "done":
            return

        names_match = re.search(r"register-names=(\[[\s\S]*?\])(?:,|$)", result)
        if names_match:
            try:
                self.register_names = json.loads(names_match.group(1))
            except json.JSONDecodeError:
                self.register_names = []
        values_match = re.search(r"register-values=(\[[\s\S]*\])$", result)
        if values_match:
            try:
                self._show_registers(self._parse_mi_array(values_match.group(1)))
            except json.JSONDecodeError:
                self._append(self.debug_output, "Could not parse register values from GDB.\n")
        asm_match = re.search(r"asm_insns=(\[[\s\S]*\])$", result)
        if asm_match:
            try:
                self._show_disassembly(self._parse_mi_array(asm_match.group(1)))
            except json.JSONDecodeError:
                self._append(self.debug_output, "Could not parse disassembly from GDB.\n")
        frame_match = re.search(r"frame=\{([\s\S]*)\}$", result)
        if frame_match:
            frame = frame_match.group(1)
            source_line = re.search(r'(?:^|,)line="(\d+)"', frame)
            source_file = re.search(r'(?:^|,)(?:fullname|file)="((?:\\.|[^"])*)"', frame)
            if source_line:
                filename = self.source_path.name if source_file is None or self.source_path is None else source_file.group(1)
                try:
                    filename = json.loads(f'"{filename}"')
                except json.JSONDecodeError:
                    pass
                if self.source_path is None or Path(filename).name == self.source_path.name:
                    self._set_current_source_line(int(source_line.group(1)))
                else:
                    self._set_current_source_line(None)

    def _handle_gdb_action(self, action: tuple, result: str) -> None:
        if action[0] == "memory":
            memory_match = re.search(r"memory=(\[[\s\S]*\])$", result)
            if memory_match:
                try:
                    memory = self._parse_mi_array(memory_match.group(1))
                    self._show_memory(memory, action[2])
                    if memory:
                        self.status.configure(
                            text=f"Memory read complete — {action[2]} from {action[1]}"
                        )
                    else:
                        self.status.configure(text="GDB returned no readable memory")
                except (json.JSONDecodeError, ValueError) as exc:
                    self._append(self.debug_output, f"Could not parse memory from GDB: {exc}\n")
                    self._set_text(self.stack, f"Could not parse memory returned by GDB.\n{exc}")
                    self.status.configure(text="Could not parse memory — see Debugger output")
            else:
                message = "GDB returned no memory data. Make sure the debug session is stopped."
                self._append(self.debug_output, message + "\n")
                self._set_text(self.stack, message)
                self.status.configure(text=message)
            return
        if action[0] == "break_insert":
            line = action[1]
            self.pending_breakpoint_lines.discard(line)
            breakpoint = re.search(r'bkpt=\{number="([^"]+)"', result)
            if breakpoint is None:
                self._append(self.debug_output, f"Could not install breakpoint at line {line}.\n")
                return
            number = breakpoint.group(1)
            if line in self.breakpoints:
                self.installed_breakpoints[line] = number
            else:
                self._send_gdb(f"-break-delete {number}")
            self._draw_line_numbers()

    @staticmethod
    def _parse_mi_array(value: str) -> list:
        normalized = re.sub(
            r"([{,])([A-Za-z][A-Za-z0-9_-]*)=",
            r'\1"\2":',
            value,
        )
        return json.loads(normalized)

    def _show_registers(self, values: list[dict[str, str]]) -> None:
        previous = self.register_raw_values
        current: dict[str, str] = {}
        for item in values:
            try:
                index = int(item["number"])
                name = self.register_names[index]
            except (KeyError, ValueError, IndexError):
                continue
            if name:
                current[name] = item.get("value", "")
        self.changed_registers = {
            name for name, value in current.items()
            if name in previous and previous[name] != value
        }
        self.register_raw_values = current
        self._render_registers()

    def _render_registers(self) -> None:
        self.registers.delete(*self.registers.get_children())
        filter_names = {
            name.strip().removeprefix("$").casefold()
            for name in self.register_filter.get().split(",")
            if name.strip()
        }
        for name, raw_value in self.register_raw_values.items():
            if filter_names and name.casefold() not in filter_names:
                continue
            display_value = self._format_register_value(name, raw_value, self.register_format.get())
            tags = ("changed",) if name in self.changed_registers else ()
            self.registers.insert("", tk.END, values=(name, display_value), tags=tags)
        flags = self.register_raw_values.get("cpsr")
        flags_name = "NZCV"
        flag_bits = (("N", 31), ("Z", 30), ("C", 29), ("V", 28))
        if self.target_name.startswith("x86"):
            flags = self.register_raw_values.get("eflags", self.register_raw_values.get("rflags"))
            flags_name = "Flags"
            flag_bits = (("CF", 0), ("PF", 2), ("ZF", 6), ("SF", 7), ("OF", 11))
        match = re.fullmatch(r"(?:0[xX])?([0-9a-fA-F]+)", flags or "")
        if match:
            flag_value = int(match.group(1), 16)
            rendered_flags = " ".join(
                f"{name}={(flag_value >> bit) & 1}" for name, bit in flag_bits
            )
            self.flags_label.configure(text=f"{flags_name}: {rendered_flags}")
        else:
            self.flags_label.configure(text=f"{flags_name}: unavailable")

    def _format_register_value(self, name: str, value: str, mode: str = "Hex") -> str:
        if self.target_name == "AArch64":
            if re.fullmatch(r"(?:x\d+|xzr|sp|pc)", name):
                bits = 64
            elif re.fullmatch(r"(?:w\d+|wzr|wsp|cpsr)", name):
                bits = 32
            else:
                return value
        elif self.target_name == "ARM 32-bit":
            if re.fullmatch(r"(?:r\d+|sp|lr|pc|cpsr)", name):
                bits = 32
            else:
                return value
        elif self.target_name == "x86 (32-bit)":
            if re.fullmatch(r"(?:e(?:ax|bx|cx|dx|si|di|bp|sp|ip|flags))", name):
                bits = 32
            elif re.fullmatch(r"(?:ax|bx|cx|dx|si|di|bp|sp|ip)", name):
                bits = 16
            elif re.fullmatch(r"(?:al|ah|bl|bh|cl|ch|dl|dh)", name):
                bits = 8
            else:
                return value
        elif self.target_name == "x86_64":
            if re.fullmatch(r"(?:r(?:ax|bx|cx|dx|si|di|bp|sp|ip|flags)|r(?:8|9|1[0-5]))", name):
                bits = 64
            elif re.fullmatch(r"(?:e(?:ax|bx|cx|dx|si|di|bp|sp|ip|flags)|r(?:8|9|1[0-5])d)", name):
                bits = 32
            elif re.fullmatch(r"(?:ax|bx|cx|dx|si|di|bp|sp|ip)", name):
                bits = 16
            elif re.fullmatch(r"(?:al|ah|bl|bh|cl|ch|dl|dh)", name):
                bits = 8
            else:
                return value
        else:
            return value

        match = re.fullmatch(r"(?:0[xX])?([0-9a-fA-F]+)", value)
        if not match:
            return value
        integer = int(match.group(1), 16)
        if mode == "Unsigned":
            return str(integer)
        if mode == "Signed":
            signed = integer - (1 << bits) if integer & (1 << (bits - 1)) else integer
            return str(signed)
        if mode == "Binary":
            return f"0b{integer:0{bits}b}"
        return f"0x{integer:0{bits // 4}x}"

    def _show_memory(self, memory: list[dict[str, str]], mode: str) -> None:
        rows: list[str] = []
        for block in memory:
            address = int(block.get("begin", "0"), 16)
            contents = bytes.fromhex(block.get("contents", ""))
            for offset in range(0, len(contents), 16):
                chunk = contents[offset : offset + 16]
                if mode == "Bytes":
                    hex_bytes = " ".join(f"{byte:02x}" for byte in chunk)
                    ascii_bytes = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in chunk)
                    rows.append(f"0x{address + offset:016x}  {hex_bytes:<47}  {ascii_bytes}")
                    continue
                width = 4 if mode == "32-bit" else 8
                values = []
                for position in range(0, len(chunk) - width + 1, width):
                    word = int.from_bytes(chunk[position : position + width], "little")
                    values.append(f"0x{word:0{width * 2}x}")
                rows.append(f"0x{address + offset:016x}  {' '.join(values)}")
        output = f"{mode} — little-endian, 128 bytes\n"
        output += "\n".join(rows) if rows else "No readable bytes were returned."
        self._set_text(self.stack, output + ("\n" if rows else ""))

    def _show_disassembly(self, instructions: list[dict[str, str]]) -> None:
        rows = []
        for item in instructions:
            address = item.get("address", "")
            function = item.get("func-name")
            if function:
                rows.append(f"<{function}>:")
            rows.append(f"{address:>18}  {item.get('inst', '')}")
        self._set_text(self.disassembly_output, "\n".join(rows) + ("\n" if rows else ""))

    @staticmethod
    def _mi_quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state=tk.DISABLED)

    @staticmethod
    def _append(widget: tk.Text, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, value)
        widget.see(tk.END)
        widget.configure(state=tk.DISABLED)

    def _confirm_close(self) -> str:
        window = tk.Toplevel(self.root)
        window.title("Unsaved changes")
        window.transient(self.root)
        window.resizable(False, False)
        window.configure(background=self.colors["background"])
        window.protocol("WM_DELETE_WINDOW", window.destroy)

        content = ttk.Frame(window, padding=16)
        content.pack(fill=tk.BOTH, expand=True)
        ttk.Label(content, text="Save your changes before closing?").pack(
            anchor=tk.W, pady=(0, 14)
        )

        result = ["cancel"]

        def choose(choice: str) -> None:
            result[0] = choice
            window.destroy()

        buttons = ttk.Frame(content)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Cancel", command=lambda: choose("cancel")).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(
            buttons,
            text="Close Without Saving",
            command=lambda: choose("discard"),
        ).pack(side=tk.RIGHT, padx=(6, 0))
        save_button = ttk.Button(
            buttons,
            text="Save and Close",
            command=lambda: choose("save"),
        )
        save_button.pack(side=tk.RIGHT)

        window.bind("<Escape>", lambda _event: choose("cancel"))
        window.grab_set()
        save_button.focus_set()
        window.wait_window()
        return result[0]

    def close(self) -> None:
        if self.is_dirty:
            choice = self._confirm_close()
            if choice == "cancel":
                return
            if choice == "save" and not self.save_file():
                return
        self._cancel_autosave()
        if self.highlight_id is not None:
            self.root.after_cancel(self.highlight_id)
            self.highlight_id = None
        self.closed = True
        self.stop_execution()
        self._save_preferences()
        self.root.destroy()


def main() -> None:
    if not os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
        print("A graphical display is required to run the workbench.", file=sys.stderr)
        raise SystemExit(1)

    root = tk.Tk()
    if len(sys.argv) > 1:
        source = Path(sys.argv[1]).expanduser().resolve()
    else:
        preferences, _warning = read_settings(settings_file_path())
        last_file = preferences.get("last_file")
        previous = Path(last_file).expanduser() if isinstance(last_file, str) else None
        source = (
            previous.resolve()
            if previous is not None and previous.is_file()
            else Path(__file__).with_name("template.s").resolve()
        )
    AssemblyWorkbench(root, source)
    root.mainloop()


if __name__ == "__main__":
    main()
