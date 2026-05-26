"""PDF OCR Webapp — Backend FastAPI."""

from __future__ import annotations

import os
import time
from typing import List

import httpx
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.batch import (
    export_batch_zip_payload,
    get_batch_report_payload,
    get_batch_status_payload,
    start_batch_ocr,
    upload_batch,
)
from backend.documents import (
    get_document_export_payload,
    get_document_payload,
    get_page_image_path,
    save_uploaded_document,
)
from backend.ocr import get_document_job_payload, get_ocr_payload, queue_document_ocr, start_ocr_payload
from backend.state import rebuild_ocr_status

app = FastAPI(title="PDF OCR Webapp")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _rebuild_status() -> None:
    rebuild_ocr_status()


@app.get("/api/health")
async def health() -> JSONResponse:
    """Verifica che Ollama sia raggiungibile e che glm-ocr sia installato."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.get("http://localhost:11434/api/tags")
            response.raise_for_status()
            models = [model.get("name", "") for model in response.json().get("models", [])]
            glm_ok = any(model.startswith("glm-ocr") for model in models)
        return JSONResponse(
            {
                "ollama": "ok",
                "glm_ocr": "available" if glm_ok else "not_found",
                "models": models,
            }
        )
    except Exception as exc:
        return JSONResponse({"ollama": "error", "detail": str(exc)}, status_code=503)


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)) -> JSONResponse:
    return JSONResponse(await save_uploaded_document(file))


@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: str) -> JSONResponse:
    return JSONResponse(get_document_payload(doc_id))


@app.get("/api/page/{doc_id}/{page_num}")
async def get_page_image(doc_id: str, page_num: int) -> FileResponse:
    img_path = get_page_image_path(doc_id, page_num)
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Pagina non trovata.")
    return FileResponse(str(img_path))


@app.get("/api/ocr/{doc_id}/{page_num}")
async def get_ocr(doc_id: str, page_num: int) -> JSONResponse:
    return JSONResponse(get_ocr_payload(doc_id, page_num))


@app.get("/api/ocr-job/{doc_id}")
async def get_document_ocr_job(doc_id: str) -> JSONResponse:
    return JSONResponse(get_document_job_payload(doc_id))


@app.post("/api/ocr-job/{doc_id}")
async def start_document_ocr_job(doc_id: str, background_tasks: BackgroundTasks) -> JSONResponse:
    return JSONResponse(queue_document_ocr(background_tasks, doc_id))


@app.post("/api/ocr/{doc_id}/{page_num}")
async def start_ocr(
    doc_id: str,
    page_num: int,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    return JSONResponse(start_ocr_payload(background_tasks, doc_id, page_num))


@app.get("/api/export/{doc_id}")
async def export_markdown(doc_id: str) -> JSONResponse:
    return JSONResponse(get_document_export_payload(doc_id))


@app.post("/api/batch")
async def batch_upload(files: List[UploadFile] = File(...)) -> JSONResponse:
    return JSONResponse(await upload_batch(files))


@app.post("/api/batch/{batch_id}/start")
async def batch_start(batch_id: str, background_tasks: BackgroundTasks) -> JSONResponse:
    return JSONResponse(start_batch_ocr(background_tasks, batch_id))


@app.get("/api/batch/{batch_id}")
async def get_batch_status(batch_id: str) -> JSONResponse:
    return JSONResponse(get_batch_status_payload(batch_id))


@app.get("/api/batch/{batch_id}/report")
async def get_batch_report(batch_id: str) -> JSONResponse:
    return JSONResponse(get_batch_report_payload(batch_id))


@app.get("/api/batch/{batch_id}/export")
async def export_batch_zip(batch_id: str) -> StreamingResponse:
    buffer, zip_name = export_batch_zip_payload(batch_id)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@app.post("/api/shutdown")
async def shutdown(background_tasks: BackgroundTasks) -> JSONResponse:
    """Chiude il server locale dopo aver inviato la risposta al client."""

    def _shutdown() -> None:
        time.sleep(0.5)
        os._exit(0)

    background_tasks.add_task(_shutdown)
    return JSONResponse({"detail": "shutting down"})


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse("static/index.html")
