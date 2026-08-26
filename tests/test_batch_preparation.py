"""Test del flusso incrementale di preparazione dei batch."""

from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks, HTTPException, UploadFile

import backend.state as state
from backend.batch import (
    complete_batch_preparation,
    initialize_batch,
    prepare_batch_file,
    start_batch_ocr,
)


def _upload(filename: str) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(b"pdf"))


class BatchPreparationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.upload_root = Path(self.temp_dir.name)
        self.upload_dir_patch = patch.object(state, "UPLOAD_DIR", self.upload_root)
        self.upload_dir_patch.start()
        state.batch_registry.clear()

    def tearDown(self) -> None:
        state.batch_registry.clear()
        self.upload_dir_patch.stop()
        self.temp_dir.cleanup()

    async def test_prepares_files_one_at_a_time_and_finalizes(self) -> None:
        batch = initialize_batch(["uno.pdf", "due.pdf"], [10, 20])
        batch_id = batch["batch_id"]
        save_document = AsyncMock(
            side_effect=[
                {"doc_id": "doc-1", "filename": "uno.pdf", "page_count": 2},
                {"doc_id": "doc-2", "filename": "due.pdf", "page_count": 3},
            ]
        )

        with patch("backend.batch.save_uploaded_document", save_document):
            first = await prepare_batch_file(batch_id, 0, _upload("uno.pdf"))
            self.assertEqual(first["preparation"]["prepared_files"], 1)
            self.assertEqual(first["preparation"]["failed_files"], 0)
            self.assertEqual(len(first["prepared_files"]), 1)

            second = await prepare_batch_file(batch_id, 1, _upload("due.pdf"))
            self.assertEqual(second["preparation"]["prepared_files"], 2)
            self.assertEqual(len(second["prepared_files"]), 2)

        completed = complete_batch_preparation(batch_id)
        self.assertEqual(completed["preparation"]["status"], "ready")
        self.assertEqual(save_document.await_count, 2)

    async def test_keeps_partial_errors_and_does_not_start_before_complete(self) -> None:
        batch = initialize_batch(["bad.pdf", "good.pdf"])
        batch_id = batch["batch_id"]
        save_document = AsyncMock(
            side_effect=[
                HTTPException(status_code=400, detail="PDF non valido"),
                {"doc_id": "doc-2", "filename": "good.pdf", "page_count": 1},
            ]
        )

        with patch("backend.batch.save_uploaded_document", save_document):
            failed = await prepare_batch_file(batch_id, 0, _upload("bad.pdf"))
            self.assertEqual(failed["preparation"]["failed_files"], 1)
            self.assertEqual(len(failed["errors"]), 1)

            prepared = await prepare_batch_file(batch_id, 1, _upload("good.pdf"))
            self.assertEqual(prepared["preparation"]["prepared_files"], 1)
            self.assertEqual(len(prepared["errors"]), 1)

        with self.assertRaises(HTTPException) as context:
            start_batch_ocr(BackgroundTasks(), batch_id)
        self.assertEqual(context.exception.status_code, 409)

        completed = complete_batch_preparation(batch_id)
        self.assertEqual(completed["preparation"]["status"], "ready")
        self.assertEqual(len(completed["prepared_files"]), 1)
        self.assertEqual(len(completed["errors"]), 1)


if __name__ == "__main__":
    unittest.main()