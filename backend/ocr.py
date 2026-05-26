from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, HTTPException

from backend.config import MODEL_NAME, OCR_BLOCK_SIZE, OCR_PROMPT, OCR_TIMEOUT, OLLAMA_URL
from backend.documents import get_page_image_path, get_page_ocr_path, read_document_metadata
from backend.state import TERMINAL_JOB_STATUSES, ocr_jobs, ocr_status, save_job_state

_ocr_lock: asyncio.Lock | None = None
ERROR_METADATA_PREFIX = "<!-- OCR_ERROR "


def _get_ocr_lock() -> asyncio.Lock:
    global _ocr_lock
    if _ocr_lock is None:
        _ocr_lock = asyncio.Lock()
    return _ocr_lock


def _build_error_info(
    *,
    source: str,
    error_type: str,
    label: str,
    interpretation: str,
    detail: str,
    retryable: bool,
) -> dict:
    return {
        "source": source,
        "type": error_type,
        "label": label,
        "interpretation": interpretation,
        "detail": detail.strip() or "Errore non specificato.",
        "retryable": retryable,
    }


def _classify_error_detail(detail: str) -> dict:
    detail = detail.strip() or "Errore non specificato."
    lowered = detail.lower()

    if "GGML_ASSERT" in detail.upper():
        return _build_error_info(
            source="ollama",
            error_type="model_runtime_assert",
            label="Crash runtime del modello",
            interpretation=(
                "Il runtime GGML del modello ha generato un'asserzione interna su questo input. "
                "Il backend ha raggiunto Ollama correttamente, ma il modello locale non ha completato l'elaborazione dell'immagine."
            ),
            detail=detail,
            retryable=False,
        )

    if "timeout" in lowered or "timed out" in lowered:
        return _build_error_info(
            source="ollama",
            error_type="timeout",
            label="Timeout del modello",
            interpretation=(
                "Ollama o il modello non hanno risposto entro il tempo massimo configurato. "
                "Il problema sembra di latenza o saturazione, non di parsing locale del documento."
            ),
            detail=detail,
            retryable=True,
        )

    if (
        "connection refused" in lowered
        or "connecterror" in lowered
        or "failed to establish a new connection" in lowered
        or "all connection attempts failed" in lowered
    ):
        return _build_error_info(
            source="ollama",
            error_type="service_unreachable",
            label="Servizio Ollama non raggiungibile",
            interpretation=(
                "Il backend non riesce a collegarsi all'istanza Ollama locale. "
                "Il modello non è stato eseguito, quindi il problema è infrastrutturale e non del documento."
            ),
            detail=detail,
            retryable=True,
        )

    if "404" in lowered and "model" in lowered:
        return _build_error_info(
            source="ollama",
            error_type="model_not_found",
            label="Modello OCR non disponibile",
            interpretation=(
                "Ollama è raggiungibile ma il modello richiesto non risulta disponibile con il nome configurato."
            ),
            detail=detail,
            retryable=False,
        )

    if "500 internal server error" in lowered or '"error":' in lowered:
        return _build_error_info(
            source="ollama",
            error_type="model_runtime_error",
            label="Errore interno di Ollama o del modello",
            interpretation=(
                "Ollama ha accettato la richiesta ma il modello ha fallito durante l'esecuzione. "
                "Questo indica una difficoltà del runtime o del modello sull'input corrente."
            ),
            detail=detail,
            retryable=False,
        )

    if "no such file" in lowered or "cannot identify image file" in lowered:
        return _build_error_info(
            source="backend",
            error_type="input_read_error",
            label="Input immagine non leggibile",
            interpretation=(
                "Il backend non è riuscito a leggere o interpretare il file immagine della pagina prima di chiamare il modello."
            ),
            detail=detail,
            retryable=False,
        )

    return _build_error_info(
        source="backend",
        error_type="unexpected_error",
        label="Errore applicativo non classificato",
        interpretation=(
            "Si è verificata un'eccezione non classificata nel backend OCR. "
            "Serve leggere il dettaglio tecnico per capire se sia un problema locale o della libreria HTTP."
        ),
        detail=detail,
        retryable=True,
    )


def _classify_ocr_exception(exc: Exception) -> dict:
    detail = str(exc).strip() or exc.__class__.__name__

    if isinstance(exc, httpx.HTTPStatusError):
        response_body = ""
        try:
            response_body = exc.response.text.strip()
        except Exception:
            response_body = ""

        status_detail = response_body or detail
        error_info = _classify_error_detail(status_detail)
        error_info["http_status"] = exc.response.status_code
        return error_info

    if isinstance(exc, httpx.TimeoutException):
        return _classify_error_detail(detail)

    if isinstance(exc, httpx.ConnectError):
        return _classify_error_detail(detail)

    if isinstance(exc, OSError):
        return _build_error_info(
            source="backend",
            error_type="file_io_error",
            label="Errore di I/O locale",
            interpretation=(
                "Il backend ha fallito nel leggere l'immagine o nel salvare il risultato OCR sul filesystem locale."
            ),
            detail=detail,
            retryable=False,
        )

    return _classify_error_detail(detail)


def _format_detail_for_markdown(detail: str) -> str:
    return " ".join(detail.strip().split()).replace("`", "'")


def _build_error_markdown(page_num: int, error_info: dict) -> str:
    metadata = json.dumps(error_info, ensure_ascii=False)
    retry_label = "sì" if error_info.get("retryable") else "no"
    detail = _format_detail_for_markdown(str(error_info.get("detail", "")))
    return "\n".join(
        [
            f"{ERROR_METADATA_PREFIX}{metadata} -->",
            f"> **Errore OCR (pagina {page_num + 1}):**",
            f"> **Fonte:** `{error_info.get('source', 'backend')}`",
            f"> **Tipo:** `{error_info.get('type', 'unexpected_error')}`",
            f"> **Diagnosi:** {error_info.get('label', 'Errore OCR')}",
            f"> **Interpretazione:** {error_info.get('interpretation', 'Nessuna interpretazione disponibile.')}",
            f"> **Riprova consigliata:** {retry_label}",
            f"> **Dettaglio tecnico:** `{detail}`",
        ]
    )


def _extract_error_info_from_markdown(markdown: str | None) -> dict | None:
    if not markdown:
        return None

    first_line, *_ = markdown.splitlines() or [""]
    if first_line.startswith(ERROR_METADATA_PREFIX) and first_line.endswith("-->"):
        raw_payload = first_line[len(ERROR_METADATA_PREFIX) : -3].strip()
        try:
            payload = json.loads(raw_payload)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass

    detail = None
    marker = "**Dettaglio tecnico:**"
    for line in markdown.splitlines():
        if marker in line:
            detail = line.split(marker, 1)[1].strip().strip("`")
            break

    if detail is None and "`" in markdown:
        first_tick = markdown.find("`")
        second_tick = markdown.find("`", first_tick + 1)
        if first_tick != -1 and second_tick != -1:
            detail = markdown[first_tick + 1 : second_tick]

    if detail is None:
        detail = markdown

    return _classify_error_detail(detail)


def _count_pages(doc_id: str, page_count: int) -> tuple[int, int, int]:
    page_status = ocr_status.get(doc_id, {})
    pages_done = 0
    pages_error = 0
    pages_processing = 0

    for page_num in range(page_count):
        status = page_status.get(page_num, "pending")
        if status == "done":
            pages_done += 1
        elif status == "error":
            pages_error += 1
        elif status == "processing":
            pages_processing += 1

    return pages_done, pages_error, pages_processing


def _resolve_job_status(
    page_count: int,
    pages_done: int,
    pages_error: int,
    pages_processing: int,
) -> str:
    if page_count == 0:
        return "pending"
    if pages_done == page_count:
        return "done"
    if pages_error == page_count:
        return "error"
    if pages_done + pages_error == page_count and pages_error > 0:
        return "partial"
    if pages_processing > 0:
        return "processing"
    return "pending"


def _update_job(doc_id: str, page_count: int, **updates) -> dict:
    pages_done, pages_error, pages_processing = _count_pages(doc_id, page_count)
    pending_pages = max(page_count - pages_done - pages_error - pages_processing, 0)
    existing = ocr_jobs.setdefault(
        doc_id,
        {
            "doc_id": doc_id,
            "block_size": OCR_BLOCK_SIZE,
            "interrupted": False,
            "resumable": pending_pages > 0,
        },
    )
    current_block = updates.get("current_block", existing.get("current_block"))
    status = updates.get(
        "status",
        _resolve_job_status(page_count, pages_done, pages_error, pages_processing),
    )

    batch_id = existing.get("batch_id")
    if "batch_id" in updates and updates["batch_id"] is not None:
        batch_id = updates["batch_id"]

    interrupted = updates.get("interrupted", existing.get("interrupted", False))
    resumable = updates.get(
        "resumable",
        pending_pages > 0 and status not in TERMINAL_JOB_STATUSES,
    )

    if status in {"queued", "processing"}:
        interrupted = False
    if status in TERMINAL_JOB_STATUSES or pending_pages == 0:
        resumable = False
    if status in TERMINAL_JOB_STATUSES:
        interrupted = False

    existing.update(
        {
            "doc_id": doc_id,
            "total_pages": page_count,
            "done_pages": pages_done,
            "error_pages": pages_error,
            "processing_pages": pages_processing,
            "pending_pages": pending_pages,
            "block_size": existing.get("block_size", OCR_BLOCK_SIZE),
            "status": status,
            "current_block": current_block,
            "batch_id": batch_id,
            "interrupted": interrupted,
            "resumable": resumable,
        }
    )
    for key, value in updates.items():
        if key == "batch_id" and value is None:
            continue
        existing[key] = value

    if existing["status"] in {"queued", "processing"}:
        existing["interrupted"] = False
    if existing["status"] in TERMINAL_JOB_STATUSES:
        existing["interrupted"] = False
        existing["resumable"] = False
    elif existing["pending_pages"] == 0:
        existing["resumable"] = False

    persisted = save_job_state(doc_id, existing)
    existing["updated_at"] = persisted["updated_at"]
    return dict(existing)


def _is_error_markdown(ocr_path: Path) -> bool:
    if not ocr_path.exists():
        return False
    try:
        return ocr_path.read_text(encoding="utf-8", errors="ignore").lstrip().startswith(
            "> **Errore OCR"
        )
    except Exception:
        return False


def _get_next_block_pages(doc_id: str, page_count: int) -> list[int]:
    page_status = ocr_status.setdefault(doc_id, {})
    pages: list[int] = []

    for page_num in range(page_count):
        status = page_status.get(page_num, "pending")
        ocr_path = get_page_ocr_path(doc_id, page_num)

        if ocr_path.exists() and status not in {"error", "processing"}:
            page_status[page_num] = "error" if _is_error_markdown(ocr_path) else "done"
            status = page_status[page_num]

        if status in {"done", "error", "processing"}:
            continue

        pages.append(page_num)
        if len(pages) >= OCR_BLOCK_SIZE:
            break

    return pages


def get_document_job_payload(doc_id: str) -> dict:
    metadata = read_document_metadata(doc_id)
    page_count = metadata["page_count"]
    if doc_id not in ocr_jobs:
        pages_done, pages_error, pages_processing = _count_pages(doc_id, page_count)
        status = _resolve_job_status(page_count, pages_done, pages_error, pages_processing)
        return _update_job(
            doc_id,
            page_count,
            status=status,
            current_block=None,
            batch_id=metadata.get("batch_id"),
        )
    return _update_job(doc_id, page_count)


def queue_document_ocr(
    background_tasks: BackgroundTasks,
    doc_id: str,
    *,
    batch_id: str | None = None,
) -> dict:
    metadata = read_document_metadata(doc_id)
    page_count = metadata["page_count"]
    job = get_document_job_payload(doc_id)
    effective_batch_id = batch_id or job.get("batch_id") or metadata.get("batch_id")

    if job["status"] in {"queued", "processing"}:
        job["scheduled"] = False
        return job

    if not _get_next_block_pages(doc_id, page_count):
        update_kwargs = {"current_block": None, "interrupted": False}
        if effective_batch_id is not None:
            update_kwargs["batch_id"] = effective_batch_id
        job = _update_job(doc_id, page_count, **update_kwargs)
        job["scheduled"] = False
        return job

    update_kwargs = {
        "status": "queued",
        "current_block": None,
        "interrupted": False,
        "resumable": True,
    }
    if effective_batch_id is not None:
        update_kwargs["batch_id"] = effective_batch_id
    job = _update_job(doc_id, page_count, **update_kwargs)
    job["scheduled"] = True
    background_tasks.add_task(run_document_ocr_job, doc_id, page_count)
    return job


def get_ocr_payload(doc_id: str, page_num: int) -> dict:
    ocr_path = get_page_ocr_path(doc_id, page_num)
    status = (ocr_status.get(doc_id) or {}).get(page_num, "pending")

    if status == "processing":
        return {"status": "processing", "markdown": None, "error": None}
    if status == "error":
        markdown = ocr_path.read_text(encoding="utf-8") if ocr_path.exists() else None
        return {
            "status": "error",
            "markdown": markdown,
            "error": _extract_error_info_from_markdown(markdown),
        }
    if ocr_path.exists():
        return {
            "status": "done",
            "markdown": ocr_path.read_text(encoding="utf-8"),
            "error": None,
        }

    return {"status": status, "markdown": None, "error": None}


def start_ocr_payload(
    background_tasks: BackgroundTasks,
    doc_id: str,
    page_num: int,
) -> dict:
    img_path = get_page_image_path(doc_id, page_num)
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Pagina non trovata.")

    status = (ocr_status.get(doc_id) or {}).get(page_num, "pending")
    if status == "processing":
        return {"status": "processing", "markdown": None}

    ocr_path = get_page_ocr_path(doc_id, page_num)
    if ocr_path.exists() and status != "error":
        return {
            "status": "done",
            "markdown": ocr_path.read_text(encoding="utf-8"),
        }

    ocr_status.setdefault(doc_id, {})[page_num] = "processing"
    background_tasks.add_task(run_page_ocr_task, doc_id, page_num)
    return {"status": "processing", "markdown": None}


def queue_ocr_page(
    background_tasks: BackgroundTasks,
    doc_id: str,
    page_num: int,
) -> bool:
    img_path = get_page_image_path(doc_id, page_num)
    if not img_path.exists():
        return False

    current_status = (ocr_status.get(doc_id) or {}).get(page_num, "pending")
    if current_status == "processing":
        return False

    ocr_path = get_page_ocr_path(doc_id, page_num)
    if ocr_path.exists() and current_status != "error":
        return False

    ocr_status.setdefault(doc_id, {})[page_num] = "processing"
    background_tasks.add_task(run_page_ocr_task, doc_id, page_num)
    return True


async def run_page_ocr_task(doc_id: str, page_num: int) -> None:
    img_path = get_page_image_path(doc_id, page_num)
    ocr_path = get_page_ocr_path(doc_id, page_num)
    metadata = read_document_metadata(doc_id)
    page_count = metadata["page_count"]

    async with _get_ocr_lock():
        current_status = (ocr_status.get(doc_id) or {}).get(page_num, "pending")
        if ocr_path.exists() and current_status not in {"error", "processing"}:
            ocr_status.setdefault(doc_id, {})[page_num] = "done"
            _update_job(doc_id, page_count, current_block=None)
            return

        ocr_status.setdefault(doc_id, {})[page_num] = "processing"
        _update_job(
            doc_id,
            page_count,
            status="processing",
            current_block={
                "start_page": page_num + 1,
                "end_page": page_num + 1,
                "size": 1,
                "completed_in_block": 0,
            },
            batch_id=metadata.get("batch_id"),
            interrupted=False,
            resumable=True,
        )
        await run_ocr(doc_id, page_num, img_path, ocr_path)

    final_job = _update_job(doc_id, page_count, current_block=None)
    final_status = _resolve_job_status(
        page_count,
        final_job["done_pages"],
        final_job["error_pages"],
        final_job["processing_pages"],
    )
    _update_job(
        doc_id,
        page_count,
        status=final_status,
        current_block=None,
        batch_id=metadata.get("batch_id"),
        interrupted=False,
    )


async def run_document_ocr_job(doc_id: str, page_count: int) -> None:
    metadata = read_document_metadata(doc_id)

    while True:
        block_pages = _get_next_block_pages(doc_id, page_count)
        if not block_pages:
            break

        _update_job(
            doc_id,
            page_count,
            status="processing",
            current_block={
                "start_page": block_pages[0] + 1,
                "end_page": block_pages[-1] + 1,
                "size": len(block_pages),
                "completed_in_block": 0,
            },
            batch_id=metadata.get("batch_id"),
            interrupted=False,
            resumable=True,
        )

        async with _get_ocr_lock():
            for index, page_num in enumerate(block_pages, start=1):
                page_status = ocr_status.setdefault(doc_id, {})
                current_status = page_status.get(page_num, "pending")
                ocr_path = get_page_ocr_path(doc_id, page_num)

                if current_status not in {"done", "error"} and not ocr_path.exists():
                    page_status[page_num] = "processing"
                    _update_job(
                        doc_id,
                        page_count,
                        status="processing",
                        current_block={
                            "start_page": block_pages[0] + 1,
                            "end_page": block_pages[-1] + 1,
                            "size": len(block_pages),
                            "completed_in_block": index - 1,
                        },
                        batch_id=metadata.get("batch_id"),
                        interrupted=False,
                        resumable=True,
                    )
                    await run_ocr(doc_id, page_num, get_page_image_path(doc_id, page_num), ocr_path)
                elif ocr_path.exists() and current_status != "error":
                    page_status[page_num] = "error" if _is_error_markdown(ocr_path) else "done"

                _update_job(
                    doc_id,
                    page_count,
                    status="processing",
                    current_block={
                        "start_page": block_pages[0] + 1,
                        "end_page": block_pages[-1] + 1,
                        "size": len(block_pages),
                        "completed_in_block": index,
                    },
                    batch_id=metadata.get("batch_id"),
                    interrupted=False,
                    resumable=True,
                )

        await asyncio.sleep(0)

    final_job = _update_job(
        doc_id,
        page_count,
        current_block=None,
        batch_id=metadata.get("batch_id"),
        interrupted=False,
    )
    final_status = _resolve_job_status(
        page_count,
        final_job["done_pages"],
        final_job["error_pages"],
        final_job["processing_pages"],
    )
    _update_job(
        doc_id,
        page_count,
        status=final_status,
        current_block=None,
        batch_id=metadata.get("batch_id"),
        interrupted=False,
    )


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
            error_info = _classify_ocr_exception(exc)
            ocr_path.write_text(_build_error_markdown(page_num, error_info), encoding="utf-8")
        except Exception:
            pass
