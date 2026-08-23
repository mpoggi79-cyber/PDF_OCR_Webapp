"""Test sintetici per la pulizia del markdown OCR persistito dal backend."""

from __future__ import annotations

import unittest

from backend.ocr import _post_process_markdown


class MarkdownCleanupTests(unittest.TestCase):
    def test_keeps_existing_blank_line_and_crop_cleanup(self) -> None:
        source = "Riga uno\n\n![crop](imgs/cropped_1.png)\n\n\nRiga due\n"

        cleaned = _post_process_markdown(source)

        self.assertEqual(cleaned, "Riga uno\n\nRiga due")

    def test_unwraps_simple_html_fence_block(self) -> None:
        source = "```html\n\nVia Santarcangiolese, 27\n\nP.IVA 03956190403\n\n```"

        cleaned = _post_process_markdown(source)

        self.assertEqual(cleaned, "Via Santarcangiolese, 27\n\nP.IVA 03956190403")

    def test_promotes_contaminated_heading_block(self) -> None:
        source = "## ```html\n\nI dati della sua fornitura\n\n```\n\nLa fornitura e' a Rimini"

        cleaned = _post_process_markdown(source)

        self.assertEqual(cleaned, "## I dati della sua fornitura\n\nLa fornitura e' a Rimini")

    def test_unwraps_markdown_fence_with_plain_prose(self) -> None:
        source = "```markdown\n\nControl remotely and print with just one click.\n\n```"

        cleaned = _post_process_markdown(source)

        self.assertEqual(cleaned, "Control remotely and print with just one click.")

    def test_preserves_literal_code_block(self) -> None:
        source = "```text\npip install glmocr\npython -m uvicorn app:app --reload\n```"

        cleaned = _post_process_markdown(source)

        self.assertEqual(cleaned, source)

    def test_preserves_raw_html_table(self) -> None:
        source = "<table border=\"1\">\n<tr><td>Codice</td><td>0249</td></tr>\n</table>"

        cleaned = _post_process_markdown(source)

        self.assertEqual(cleaned, source)

    def test_converts_html_table_when_no_html_is_forced(self) -> None:
        source = "<table><tr><th>Codice</th><th>Importo</th></tr><tr><td>MANODOP</td><td>3.891,00 €</td></tr></table>"

        cleaned = _post_process_markdown(source, force_no_html=True)

        self.assertEqual(
            cleaned,
            "| Codice | Importo |\n| --- | --- |\n| MANODOP | 3.891,00 € |",
        )


if __name__ == "__main__":
    unittest.main()