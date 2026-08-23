"""Test del confronto tra risultati actual ed expected del runner ufficiale."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.run_official_tests import compare_actual_with_expected


class OfficialRunnerTests(unittest.TestCase):
    def test_reports_match_when_markdown_is_equal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual = root / "actual.md"
            expected = root / "expected.md"
            actual.write_text("# Documento\n", encoding="utf-8")
            expected.write_text("# Documento\n", encoding="utf-8")

            comparison = compare_actual_with_expected(actual, expected)

        self.assertEqual(comparison["status"], "match")
        self.assertIsNone(comparison["warning"])

    def test_reports_warning_when_markdown_is_different(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual = root / "actual.md"
            expected = root / "expected.md"
            actual.write_text("# Actual\n", encoding="utf-8")
            expected.write_text("# Expected\n", encoding="utf-8")

            comparison = compare_actual_with_expected(actual, expected)

        self.assertEqual(comparison["status"], "different")
        self.assertIn("ATTENZIONE", comparison["warning"] or "")

    def test_does_not_warn_when_expected_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            actual = Path(directory) / "actual.md"
            actual.write_text("# Documento\n", encoding="utf-8")

            comparison = compare_actual_with_expected(actual, None)

        self.assertEqual(comparison["status"], "not_available")
        self.assertIsNone(comparison["warning"])


if __name__ == "__main__":
    unittest.main()