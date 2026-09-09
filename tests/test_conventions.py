from __future__ import annotations

import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def effective_line_count(
    path: pathlib.Path, import_stack: tuple[pathlib.Path, ...] = ()
) -> int:
    path = path.resolve()
    if path in import_stack:
        raise ValueError(f"recursive instruction import: {path}")
    lines = path.read_text().splitlines()
    imported = (
        path.parent / line.removeprefix("@").strip()
        for line in lines
        if line.startswith("@")
    )
    return len(lines) + sum(
        effective_line_count(candidate, (*import_stack, path))
        for candidate in imported
    )


class ConventionsTest(unittest.TestCase):
    def test_effective_line_count_includes_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            imported = root / "imported.md"
            imported.write_text("imported one\nimported two\n")
            entry = root / "AGENTS.md"
            entry.write_text("entry\n@imported.md\n")

            self.assertEqual(effective_line_count(entry), 4)

    def test_portable_conventions_stay_below_harness_line_ceiling(self) -> None:
        line_count = effective_line_count(ROOT / "conventions" / "AGENTS.md")

        self.assertLess(line_count, 200)
