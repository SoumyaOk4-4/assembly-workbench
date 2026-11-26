import unittest

from app import AssemblyWorkbench, parse_version


class ParseVersionTests(unittest.TestCase):
    def test_parses_optional_v_prefix(self) -> None:
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))

    def test_compares_numeric_components(self) -> None:
        self.assertLess(parse_version("v0.9.9"), parse_version("v0.10.0"))

    def test_rejects_non_release_versions(self) -> None:
        with self.assertRaises(ValueError):
            parse_version("main")


class StackReadTests(unittest.TestCase):
    def test_reads_fixed_range_from_current_stack_pointer(self) -> None:
        workbench = AssemblyWorkbench.__new__(AssemblyWorkbench)
        workbench.gdb = object()
        workbench.target_name = "AArch64"
        workbench.stack_view = object()
        commands = []
        messages = []
        workbench._send_gdb = lambda command, action=None: commands.append(
            (command, action)
        ) or "token"
        workbench._set_text = lambda _widget, text: messages.append(text)

        workbench._read_stack()

        self.assertEqual(
            commands,
            [("-data-read-memory-bytes $sp 128", ("stack", "$sp"))],
        )
        self.assertIn("32 32-bit words", messages[0])


if __name__ == "__main__":
    unittest.main()
