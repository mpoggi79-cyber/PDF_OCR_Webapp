from __future__ import annotations

import io
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException, UploadFile

from backend.config import OCR_BLOCK_SIZE
from backend.documents import build_document_markdown, save_uploaded_document
from backend.ocr import queue_document_ocr
from backend.state import (
    batch_registry,
    get_or_load_batch_docs,
    ocr_jobs,
    ocr_status,
    read_batch_state,
    save_batch_state,
)


def _get_batch_docs_or_404(batch_id: str) -> list[dict]:
    docs = get_or_load_batch_docs(batch_id)
    if docs is None:
        raise HTTPException(status_code=404, detail="Batch non trovato.")
    return docs


def _persist_batch_snapshot(batch_id: str, docs: list[dict], status: str) -> None:
    persisted = read_batch_state(batch_id) or {}
    save_batch_state(
        batch_id,
        docs,
        created_at=persisted.get("created_at"),
        status=status,
    )


def initialize_batch(
    filenames: list[str],
    sizes: list[int] | None = None,
) -> dict:
    if not filenames:
        raise HTTPException(status_code=400, detail="Seleziona almeno un file PDF.")

    batch_id = str(uuid.uuid4())
    normalized_sizes = sizes or []
    files = [
        {
            "index": index,
            "filename": filename,
            "size": normalized_sizes[index] if index < len(normalized_sizes) else None,
            "status": "pending",
        }
        for index, filename in enumerate(filenames)
    ]
    preparation = {
        "status": "preparing",
        "total_files": len(files),
        "prepared_files": 0,
        "failed_files": 0,
        "current_filename": None,
        "files": files,
    }
    save_batch_state(batch_id, [], status="preparing", preparation=preparation, errors=[])
    return {"batch_id": batch_id, "preparation": preparation, "docs": [], "errors": []}


def _get_preparation(batch_id: str) -> tuple[list[dict], dict]:
    persisted = read_batch_state(batch_id)
    if persisted is None:
        raise HTTPException(status_code=404, detail="Batch non trovato.")
    preparation = persisted.get("preparation")
    if not isinstance(preparation, dict):
        raise HTTPException(status_code=409, detail="Il batch non supporta la preparazione incrementale.")
    docs = persisted.get("docs") or []
    return docs, preparation


async def prepare_batch_file(
    batch_id: str,
    index: int,
    file: UploadFile,
    *,
    prompt_profile: str | None = None,
) -> dict:
    docs, preparation = _get_preparation(batch_id)
    files = preparation.get("files")
    if not isinstance(files, list) or index < 0 or index >= len(files):
        raise HTTPException(status_code=400, detail="Indice file non valido.")

    entry = files[index]
    if entry.get("status") in {"prepared", "error"}:
        return get_batch_preparation_payload(batch_id)

    errors = list((read_batch_state(batch_id) or {}).get("errors") or [])
    preparation["current_filename"] = entry.get("filename") or file.filename
    entry["status"] = "processing"
    _persist_preparation_snapshot(batch_id, docs, preparation, errors)

    try:
        metadata = await save_uploaded_document(file, batch_id=batch_id, prompt_profile=prompt_profile)
    except HTTPException as exc:
        error = {"index": index, "filename": file.filename, "error": exc.detail}
        errors.append(error)
        entry["status"] = "error"
        entry["error"] = str(exc.detail)
        preparation["failed_files"] = int(preparation.get("failed_files") or 0) + 1
    except Exception as exc:
        error = {"index": index, "filename": file.filename, "error": str(exc)}
        errors.append(error)
        entry["status"] = "error"
        entry["error"] = str(exc)
        preparation["failed_files"] = int(preparation.get("failed_files") or 0) + 1
    else:
        docs.append(
            {
                "doc_id": metadata["doc_id"],
                "filename": metadata["filename"],
                "page_count": metadata["page_count"],
            }
        )
        entry["status"] = "prepared"
        entry["doc_id"] = metadata["doc_id"]
        preparation["prepared_files"] = int(preparation.get("prepared_files") or 0) + 1

    preparation["current_filename"] = None
    _persist_preparation_snapshot(batch_id, docs, preparation, errors)
    return get_batch_preparation_payload(batch_id)


def _persist_preparation_snapshot(
    batch_id: str,
    docs: list[dict],
    preparation: dict,
    errors: list[dict],
    *,
    status: str = "preparing",
) -> None:
    persisted = read_batch_state(batch_id) or {}
    save_batch_state(
        batch_id,
        docs,
        created_at=persisted.get("created_at"),
        status=status,
        preparation=preparation,
        errors=errors,
    )


def get_batch_preparation_payload(batch_id: str) -> dict:
    docs, preparation = _get_preparation(batch_id)
    persisted = read_batch_state(batch_id) or {}
    return {
        "batch_id": batch_id,
        "preparation": preparation,
        "prepared_files": docs,
        "errors": persisted.get("errors") or [],
    }


def complete_batch_preparation(batch_id: str) -> dict:
    docs, preparation = _get_preparation(batch_id)
    files = preparation.get("files") or []
    if any(entry.get("status") == "pending" or entry.get("status") == "processing" for entry in files):
        raise HTTPException(status_code=409, detail="La preparazione batch non e' ancora terminata.")

    preparation["status"] = "ready"
    preparation["current_filename"] = None
    errors = list((read_batch_state(batch_id) or {}).get("errors") or [])
    _persist_preparation_snapshot(batch_id, docs, preparation, errors, status="pending")
    return get_batch_preparation_payload(batch_id)
async def upload_batch(files: list[UploadFile], *, prompt_profile: str | None = None) -> dict:
    batch_id = str(uuid.uuid4())
    docs: list[dict] = []
    errors: list[dict] = []

    for file in files:
        try:
            metadata = await save_uploaded_document(file, batch_id=batch_id, prompt_profile=prompt_profile)
        except HTTPException as exc:
            errors.append({"filename": file.filename, "error": exc.detail})
            continue
        except Exception as exc:
            errors.append({"filename": file.filename, "error": str(exc)})
            continue

        docs.append(
            {
                "doc_id": metadata["doc_id"],
                "filename": metadata["filename"],
                "page_count": metadata["page_count"],
            }
        )

    batch_registry[batch_id] = docs
    _persist_batch_snapshot(batch_id, docs, status="pending")
    return {"batch_id": batch_id, "docs": docs, "errors": errors}
def start_batch_ocr(
    background_tasks: BackgroundTasks,
    batch_id: str,
    *,
    prompt_profile: str | None = None,
) -> dict:
    docs = _get_batch_docs_or_404(batch_id)
    persisted = read_batch_state(batch_id) or {}
    preparation = persisted.get("preparation")
    if isinstance(preparation, dict) and preparation.get("status") != "ready":
        raise HTTPException(status_code=409, detail="Completa prima la preparazione dei file batch.")

    jobs_started = 0
    pages_queued = 0
    for doc in docs:
        job = queue_document_ocr(
            background_tasks,
            doc["doc_id"],
            batch_id=batch_id,
            prompt_profile=prompt_profile,
        )
        pages_queued += job.get("pending_pages", 0)
        if job.get("scheduled"):
            jobs_started += 1

    snapshot_status = "processing" if pages_queued > 0 else "pending"
    _persist_batch_snapshot(batch_id, docs, status=snapshot_status)

    return {
        "batch_id": batch_id,
        "pages_queued": pages_queued,
        "jobs_started": jobs_started,
        "block_size": OCR_BLOCK_SIZE,
    }


def _get_page_counts(doc_id: str, page_count: int) -> tuple[int, int, int]:
    page_status = ocr_status.get(doc_id, {})
    pages_done = sum(1 for i in range(page_count) if page_status.get(i) == "done")
    pages_error = sum(1 for i in range(page_count) if page_status.get(i) == "error")
    pages_processing = sum(1 for i in range(page_count) if page_status.get(i) == "processing")
    return pages_done, pages_error, pages_processing


def _resolve_doc_status(
    page_count: int,
    pages_done: int,
    pages_error: int,
    pages_processing: int,
) -> str:
    if pages_done == page_count:
        return "done"
    if pages_processing > 0:
        return "processing"
    if pages_error == page_count:
        return "error"
    if pages_error > 0 and pages_done + pages_error == page_count:
        return "partial"
    return "pending"


def _resolve_batch_status(docs: list[dict]) -> str:
    if not docs:
        return "pending"

    statuses = [doc["status"] for doc in docs]
    if all(status == "done" for status in statuses):
        return "done"
    if any(status == "processing" for status in statuses):
        return "processing"
    if all(status == "error" for status in statuses):
        return "error"
    if any(status == "pending" for status in statuses):
        return "pending"
    if any(status == "partial" for status in statuses):
        return "partial"
    if any(status == "error" for status in statuses):
        return "partial"
    return "pending"


def get_batch_status_payload(batch_id: str) -> dict:
    docs = _get_batch_docs_or_404(batch_id)
    persisted = read_batch_state(batch_id) or {}

    result: list[dict] = []
    for doc in docs:
        pages_done, pages_error, pages_processing = _get_page_counts(
            doc["doc_id"],
            doc["page_count"],
        )
        job_status = (ocr_jobs.get(doc["doc_id"]) or {}).get("status")
        status = _resolve_doc_status(
            doc["page_count"],
            pages_done,
            pages_error,
            pages_processing,
        )
        if job_status in {"queued", "processing"} and status == "pending":
            status = "processing"

        result.append(
            {
                "doc_id": doc["doc_id"],
                "filename": doc["filename"],
                "page_count": doc["page_count"],
                "pages_done": pages_done,
                "pages_error": pages_error,
                "status": status,
            }
        )

    preparation = persisted.get("preparation")
    if isinstance(preparation, dict) and preparation.get("status") == "preparing":
        batch_status = "preparing"
    else:
        batch_status = _resolve_batch_status(result)
    _persist_batch_snapshot(batch_id, docs, status=batch_status)
    return {
        "batch_id": batch_id,
        "status": batch_status,
        "docs": result,
        "preparation": preparation if isinstance(preparation, dict) else None,
        "errors": persisted.get("errors") or [],
    }


def get_batch_report_payload(batch_id: str) -> dict:
    docs = _get_batch_docs_or_404(batch_id)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(docs)
    n_done = 0
    n_partial = 0
    n_error = 0
    n_pending = 0
    rows: list[tuple[str, int, int, int, str]] = []

    for doc in docs:
        pages_done, pages_error, pages_processing = _get_page_counts(
            doc["doc_id"],
            doc["page_count"],
        )

        if pages_done == doc["page_count"]:
            status_label = "✓ Completato"
            n_done += 1
        elif pages_error > 0 and pages_done == 0:
            status_label = "✗ Errore"
            n_error += 1
        elif pages_done > 0:
            status_label = "⚠ Parziale"
            n_partial += 1
        else:
            status_label = "○ Non elaborato"
            n_pending += 1

        rows.append((doc["filename"], doc["page_count"], pages_done, pages_error, status_label))

    lines = [
        "# Report Conversione Batch OCR",
        "",
        f"- **Data:** {now}",
        f"- **Batch ID:** `{batch_id}`",
        "",
        "## Sommario",
        "",
        "| Totale | Completati | Parziali | Errori | Non elaborati |",
        "|--------|------------|----------|--------|---------------|",
        f"| {total} | {n_done} | {n_partial} | {n_error} | {n_pending} |",
        "",
        "## Dettaglio File",
        "",
        "| # | File | Pagine Tot. | Elaborate | Errori | Stato |",
        "|---|------|-------------|-----------|--------|-------|",
    ]
    for index, (filename, page_count, pages_done, pages_error, status_label) in enumerate(rows, 1):
        lines.append(f"| {index} | {filename} | {page_count} | {pages_done} | {pages_error} | {status_label} |")

    lines += [
        "",
        "---",
        "_Report generato automaticamente da PDF OCR Webapp_",
    ]

    report_md = "\n".join(lines)
    filename = f"report_batch_{batch_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    return {"report": report_md, "filename": filename}


def export_batch_zip_payload(batch_id: str) -> tuple[io.BytesIO, str]:
    docs = _get_batch_docs_or_404(batch_id)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for doc in docs:
            content = build_document_markdown(doc["doc_id"], doc["page_count"])
            if content == "_Nessun risultato OCR disponibile._":
                continue
            stem = Path(doc["filename"]).stem
            archive.writestr(f"{stem}.md", content)

        report_lines = [
            "# Log Conversione Batch",
            f"Generato: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Batch ID: {batch_id}",
            "",
        ]
        for doc in docs:
            pages_done, pages_error, _ = _get_page_counts(doc["doc_id"], doc["page_count"])
            report_lines.append(
                f"- {doc['filename']}: {pages_done}/{doc['page_count']} pagine OK, {pages_error} errori"
            )
        archive.writestr("_report.md", "\n".join(report_lines))

    buffer.seek(0)
    zip_name = f"batch_{batch_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return buffer, zip_name
