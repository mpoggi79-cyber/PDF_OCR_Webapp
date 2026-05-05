from __future__ import annotations

import base64
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, HTTPException

from backend.config import MODEL_NAME, OCR_PROMPT, OCR_TIMEOUT, OLLAMA_URL
from backend.documents import get_page_image_path, get_page_ocr_path
from backend.state import ocr_status


def get_ocr_payload(doc_id: str, page_num: int) -> dict:
    ocr_path = get_page_ocr_path(doc_id, page_num)
    if ocr_path.exists():
        return {
            "status": "done",
            "markdown": ocr_path.read_text(encoding="utf-8"),
        }

    status = (ocr_status.get(doc_id) or {}).get(page_num, "pending")
    return {"status": status, "markdown": None}


def start_ocr_payload(
    background_tasks: BackgroundTasks,
    doc_id: str,
    page_num: int,
) -> dict:
    img_path = get_page_image_path(doc_id, page_num)
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Pagina non trovata.")

    ocr_path = get_page_ocr_path(doc_id, page_num)
    if ocr_path.exists():
        return {
            "status": "done",
            "markdown": ocr_path.read_text(encoding="utf-8"),
        }

    status = (ocr_status.get(doc_id) or {}).get(page_num, "pending")
    if status == "processing":
        return {"status": "processing", "markdown": None}

    ocr_status.setdefault(doc_id, {})[page_num] = "processing"
    background_tasks.add_task(run_ocr, doc_id, page_num, img_path, ocr_path)
    return {"status": "processing", "markdown": None}


def queue_ocr_page(
    background_tasks: BackgroundTasks,
    doc_id: str,
    page_num: int,
) -> bool:
    img_path = get_page_image_path(doc_id, page_num)
    if not img_path.exists():
        return False

    ocr_path = get_page_ocr_path(doc_id, page_num)
    if ocr_path.exists():
        return False

    current_status = (ocr_status.get(doc_id) or {}).get(page_num, "pending")
    if current_status == "processing":
        return False

    ocr_status.setdefault(doc_id, {})[page_num] = "processing"
    background_tasks.add_task(run_ocr, doc_id, page_num, img_path, ocr_path)
    return True


async def run_ocr(
    doc_id: str,
    page_num: int,
    img_path: Path,
    ocr_path: Path,
) -> None:
    try:
        img_b64 = base64.b64encode(img_path.read_bytes()).decode("utf-8")
        payload = {
            "model": MODEL_NAME,
            "prompt": OCR_PROMPT,
            "images": [img_b64],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=OCR_TIMEOUT) as client:
            response = await client.post(OLLAMA_URL, json=payload)
            response.raise_for_status()
            result = response.json()

        markdown = result.get("response", "")
        ocr_path.write_text(markdown, encoding="utf-8")
        ocr_status[doc_id][page_num] = "done"
    except Exception as exc:
        ocr_status[doc_id][page_num] = "error"
        try:
            ocr_path.write_text(
                f"> **Errore OCR (pagina {page_num + 1}):**\n> `{exc}`",
                encoding="utf-8",
            )
            ocr_status[doc_id][page_num] = "done"
        except Exception:
            pass
