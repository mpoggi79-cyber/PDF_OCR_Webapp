from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import OCR_BLOCK_SIZE, UPLOAD_DIR

ocr_status: dict[str, dict[int, str]] = {}
ocr_jobs: dict[str, dict] = {}
batch_registry: dict[str, list[dict]] = {}

JOB_STATE_FILENAME = "job_state.json"
BATCH_DIRNAME = "_batches"
TERMINAL_JOB_STATUSES = {"done", "error", "partial"}
ERROR_METADATA_PREFIX = "<!-- OCR_ERROR "


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count_page_statuses(page_status: dict[int, str], page_count: int) -> tuple[int, int, int]:
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


def _resolve_rebuilt_job_status(
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


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _coerce_duration_ms(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(round(value))
    return None


def _normalize_pages_duration_ms(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None

    normalized: dict[str, int] = {}
    for page_num, duration_ms in value.items():
        coerced = _coerce_duration_ms(duration_ms)
        if coerced is not None:
            normalized[str(page_num)] = coerced

    return normalized or None


def _collect_job_timing_from_dir(doc_dir: Path, page_count: int) -> dict[str, Any]:
    total_duration_ms = 0
    pages_duration_ms: dict[str, int] = {}
    started_at: str | None = None
    finished_at: str | None = None
    has_duration = False

    for page_num in range(page_count):
        sidecar = _read_json(doc_dir / "ocr" / f"page_{page_num}.json")
        if sidecar is None:
            continue

        duration_ms = _coerce_duration_ms(sidecar.get("duration_ms"))
        if duration_ms is not None:
            pages_duration_ms[str(page_num)] = duration_ms
            total_duration_ms += duration_ms
            has_duration = True

        page_started_at = sidecar.get("started_at")
        if isinstance(page_started_at, str) and page_started_at:
            if started_at is None or page_started_at < started_at:
                started_at = page_started_at

        page_finished_at = sidecar.get("finished_at")
        if isinstance(page_finished_at, str) and page_finished_at:
            if finished_at is None or page_finished_at > finished_at:
                finished_at = page_finished_at

    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "total_duration_ms": total_duration_ms if has_duration else None,
        "pages_duration_ms": pages_duration_ms or None,
    }


def collect_job_timing_from_sidecars(doc_id: str, page_count: int) -> dict[str, Any]:
    return _collect_job_timing_from_dir(UPLOAD_DIR / doc_id, page_count)


def get_job_state_path(doc_id: str) -> Path:
    return UPLOAD_DIR / doc_id / JOB_STATE_FILENAME


def get_batch_dir() -> Path:
    batch_dir = UPLOAD_DIR / BATCH_DIRNAME
    batch_dir.mkdir(parents=True, exist_ok=True)
    return batch_dir


def get_batch_state_path(batch_id: str) -> Path:
    return get_batch_dir() / f"{batch_id}.json"


def read_job_state(doc_id: str) -> dict[str, Any] | None:
    return _read_json(get_job_state_path(doc_id))


def save_job_state(doc_id: str, job: dict[str, Any]) -> dict[str, Any]:
    pages_duration_ms = _normalize_pages_duration_ms(job.get("pages_duration_ms"))
    payload = {
        "doc_id": doc_id,
        "batch_id": job.get("batch_id"),
        "status": job.get("status", "pending"),
        "block_size": int(job.get("block_size") or OCR_BLOCK_SIZE),
        "current_block": job.get("current_block"),
        "total_pages": int(job.get("total_pages") or 0),
        "done_pages": int(job.get("done_pages") or 0),
        "error_pages": int(job.get("error_pages") or 0),
        "processing_pages": int(job.get("processing_pages") or 0),
        "pending_pages": int(job.get("pending_pages") or 0),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "total_duration_ms": _coerce_duration_ms(job.get("total_duration_ms")),
        "pages_duration_ms": pages_duration_ms,
        "updated_at": job.get("updated_at") or _utc_now_iso(),
        "interrupted": bool(job.get("interrupted")),
        "resumable": bool(job.get("resumable")),
    }
    _write_json(get_job_state_path(doc_id), payload)
    return payload


def read_batch_state(batch_id: str) -> dict[str, Any] | None:
    return _read_json(get_batch_state_path(batch_id))


def save_batch_state(
    batch_id: str,
    docs: list[dict[str, Any]],
    *,
    created_at: str | None = None,
    status: str = "pending",
    preparation: dict[str, Any] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_docs = [
        {
            "doc_id": doc.get("doc_id"),
            "filename": doc.get("filename"),
            "page_count": int(doc.get("page_count") or 0),
        }
        for doc in docs
        if doc.get("doc_id")
    ]

    previous = read_batch_state(batch_id) or {}
    if preparation is None:
        preparation = previous.get("preparation")
    if errors is None:
        errors = previous.get("errors")

    payload = {
        "batch_id": batch_id,
        "created_at": created_at or _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "status": status,
        "docs": normalized_docs,
    }
    if isinstance(preparation, dict):
        payload["preparation"] = preparation
    if isinstance(errors, list) and errors:
        payload["errors"] = errors
    _write_json(get_batch_state_path(batch_id), payload)
    batch_registry[batch_id] = normalized_docs
    return payload


def _doc_summary_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": metadata.get("doc_id"),
        "filename": metadata.get("filename"),
        "page_count": int(metadata.get("page_count") or 0),
    }


def discover_batch_docs(batch_id: str | None = None) -> dict[str, list[dict[str, Any]]] | list[dict[str, Any]]:
    discovered: dict[str, list[dict[str, Any]]] = {}

    for doc_dir in UPLOAD_DIR.iterdir():
        if not doc_dir.is_dir() or doc_dir.name == BATCH_DIRNAME:
            continue

        metadata = _read_json(doc_dir / "metadata.json")
        if metadata is None:
            continue

        current_batch_id = metadata.get("batch_id")
        if not current_batch_id:
            continue

        discovered.setdefault(str(current_batch_id), []).append(_doc_summary_from_metadata(metadata))

    if batch_id is not None:
        return discovered.get(batch_id, [])
    return discovered


def get_or_load_batch_docs(batch_id: str) -> list[dict[str, Any]] | None:
    docs = batch_registry.get(batch_id)
    if docs is not None:
        return docs

    persisted = read_batch_state(batch_id)
    if persisted is not None:
        docs = persisted.get("docs") or discover_batch_docs(batch_id)
        batch_registry[batch_id] = docs
        return docs

    discovered = discover_batch_docs(batch_id)
    if discovered:
        save_batch_state(batch_id, discovered)
        return batch_registry.get(batch_id)

    return None


def _build_recovered_job(
    doc_id: str,
    page_count: int,
    page_status: dict[int, str],
    *,
    metadata: dict[str, Any],
    persisted_job: dict[str, Any] | None,
) -> dict[str, Any]:
    pages_done, pages_error, pages_processing = _count_page_statuses(page_status, page_count)
    pending_pages = max(page_count - pages_done - pages_error - pages_processing, 0)
    timing_summary = collect_job_timing_from_sidecars(doc_id, page_count)

    persisted_status = (persisted_job or {}).get("status")
    was_interrupted = bool((persisted_job or {}).get("interrupted")) or persisted_status in {
        "queued",
        "processing",
    }

    status = _resolve_rebuilt_job_status(page_count, pages_done, pages_error, pages_processing)
    resumable = pending_pages > 0 and status not in TERMINAL_JOB_STATUSES
    interrupted = was_interrupted and resumable

    if status in TERMINAL_JOB_STATUSES:
        interrupted = False
        resumable = False

    return {
        "doc_id": doc_id,
        "batch_id": (persisted_job or {}).get("batch_id") or metadata.get("batch_id"),
        "status": status,
        "block_size": int((persisted_job or {}).get("block_size") or OCR_BLOCK_SIZE),
        "current_block": None,
        "total_pages": page_count,
        "done_pages": pages_done,
        "error_pages": pages_error,
        "processing_pages": pages_processing,
        "pending_pages": pending_pages,
        "updated_at": _utc_now_iso(),
        "interrupted": interrupted,
        "resumable": resumable,
        **timing_summary,
    }


def _read_ocr_file_status(ocr_path) -> str:
    if not ocr_path.exists():
        return "pending"

    try:
        content = ocr_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return "done"

    normalized = content.lstrip()
    if normalized.startswith(ERROR_METADATA_PREFIX) or normalized.startswith("> **Errore OCR"):
        return "error"
    return "done"


def rebuild_ocr_status() -> None:
    """Ricostruisce lo stato OCR dai file su disco al riavvio del server."""
    ocr_status.clear()
    ocr_jobs.clear()
    batch_registry.clear()

    discovered_batches = discover_batch_docs()

    for doc_dir in UPLOAD_DIR.iterdir():
        if not doc_dir.is_dir() or doc_dir.name == BATCH_DIRNAME:
            continue
        meta_path = doc_dir / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            doc_id = meta["doc_id"]
            page_count = int(meta["page_count"])
            page_status = {
                i: _read_ocr_file_status(doc_dir / "ocr" / f"page_{i}.md")
                for i in range(page_count)
            }
            ocr_status[doc_id] = page_status

            persisted_job = read_job_state(doc_id)
            if persisted_job is not None:
                recovered_job = _build_recovered_job(
                    doc_id,
                    page_count,
                    page_status,
                    metadata=meta,
                    persisted_job=persisted_job,
                )
                ocr_jobs[doc_id] = recovered_job
                save_job_state(doc_id, recovered_job)
        except Exception:
            continue

    batch_dir = get_batch_dir()
    for batch_file in batch_dir.glob("*.json"):
        persisted = _read_json(batch_file)
        if persisted is None:
            continue

        batch_id = str(persisted.get("batch_id") or batch_file.stem)
        docs = persisted.get("docs") or discovered_batches.get(batch_id, [])
        save_batch_state(
            batch_id,
            docs,
            created_at=persisted.get("created_at"),
            status=str(persisted.get("status") or "pending"),
        )

    for batch_id, docs in discovered_batches.items():
        if batch_id not in batch_registry:
            save_batch_state(batch_id, docs)
