from __future__ import annotations

import json

from backend.config import UPLOAD_DIR

ocr_status: dict[str, dict[int, str]] = {}
batch_registry: dict[str, list[dict]] = {}


def rebuild_ocr_status() -> None:
    """Ricostruisce lo stato OCR dai file su disco al riavvio del server."""
    ocr_status.clear()
    for doc_dir in UPLOAD_DIR.iterdir():
        if not doc_dir.is_dir():
            continue
        meta_path = doc_dir / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            doc_id = meta["doc_id"]
            ocr_status[doc_id] = {
                i: ("done" if (doc_dir / "ocr" / f"page_{i}.md").exists() else "pending")
                for i in range(meta["page_count"])
            }
        except Exception:
            continue
