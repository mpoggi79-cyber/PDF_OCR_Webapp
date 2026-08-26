"""Test unitari per classificazione errori e output strutturato OCR."""

from __future__ import annotations

import unittest

from backend.ocr import (
    _build_retry_delay,
    _build_glmocr_kwargs,
    _classify_error_detail,
    _normalize_ollama_response,
)
from backend.config import get_glmocr_task_prompt_mapping


class OcrCoreTests(unittest.TestCase):
    def test_glmocr_uses_official_specialized_task_prompts(self) -> None:
        prompts = get_glmocr_task_prompt_mapping()

        self.assertEqual(prompts["text"], "Text Recognition:")
        self.assertEqual(prompts["table"], "Table Recognition:")
        self.assertEqual(prompts["formula"], "Formula Recognition:")

        kwargs = _build_glmocr_kwargs(
            "glm-ocr:latest",
            {"text": "prompt pagina", "table": "prompt tabella locale"},
        )
        task_prompts = kwargs["_dotted"]["pipeline.page_loader.task_prompt_mapping"]
        self.assertEqual(task_prompts["text"], "Text Recognition:")
        self.assertEqual(task_prompts["table"], "Table Recognition:")
        self.assertEqual(task_prompts["formula"], "Formula Recognition:")

    def test_classifies_timeout_as_retryable(self) -> None:
        error = _classify_error_detail("request timed out while waiting for Ollama")

        self.assertEqual(error["type"], "timeout")
        self.assertTrue(error["retryable"])

    def test_classifies_runtime_assert_as_non_retryable(self) -> None:
        error = _classify_error_detail("GGML_ASSERT(ctx->model != nullptr) failed")

        self.assertEqual(error["type"], "model_runtime_assert")
        self.assertFalse(error["retryable"])

    def test_retry_delay_grows_exponentially(self) -> None:
        self.assertEqual(_build_retry_delay(1), 0.5)
        self.assertEqual(_build_retry_delay(2), 1.0)
        self.assertEqual(_build_retry_delay(3), 2.0)

    def test_normalizes_ollama_regions_and_metadata(self) -> None:
        markdown, structured = _normalize_ollama_response(
            {
                "response": "# Fattura\n\n<table></table>",
                "layout_details": [
                    [
                        {"label": "table", "bbox_2d": [1, 2, 3, 4], "content": "Totale"},
                        {"type": "formula", "bbox": [5, 6, 7, 8]},
                    ]
                ],
                "confidence": 0.91,
            },
            "glm-ocr:latest",
            page_num=2,
        )

        self.assertIn("# Fattura", markdown)
        self.assertIsNotNone(structured)
        assert structured is not None
        self.assertEqual(structured["model"], "glm-ocr:latest")
        self.assertEqual(structured["confidence"], 0.91)
        self.assertEqual(len(structured["table_regions"]), 1)
        self.assertEqual(len(structured["formula_regions"]), 1)
        self.assertTrue(structured["capabilities"]["structured_regions"])
        self.assertTrue(structured["capabilities"]["table_regions"])
        self.assertTrue(structured["capabilities"]["formula_regions"])
        self.assertFalse(structured["capabilities"]["layout_visualization"])
        self.assertEqual(structured["structure_metadata"]["regions"][0]["page"], 2)
        self.assertEqual(structured["structure_metadata"]["regions"][0]["bbox"], [1, 2, 3, 4])

    def test_rejects_ollama_response_without_markdown(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing string response field"):
            _normalize_ollama_response({"response": None}, "glm-ocr:latest")


if __name__ == "__main__":
    unittest.main()