"""
PDF OCR Webapp — Backend FastAPI
Converte pagine PDF in immagini e le invia al modello glm-ocr su Ollama
per ottenere Markdown pulito.
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List

import fitz  # PyMuPDF
import httpx
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── Configurazione ────────────────────────────────────────────────────────────

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

OLLAMA_URL  = "http://localhost:11434/api/generate"
MODEL_NAME  = "glm-ocr:latest"
OCR_TIMEOUT = 240.0  # secondi — il modello può essere lento su CPU

OCR_PROMPT = (
    "Extract all text, tables, and structure from this document image. "
    "Output the result in clean Markdown format. "
    "Preserve headings, lists, tables (as Markdown tables), and any visible structure. "
    "Do not add commentary — only output the Markdown."
)

# Stato OCR in memoria: {doc_id: {page_num: "pending"|"processing"|"done"|"error"}}
ocr_status: dict[str, dict[int, str]] = {}

# Registro batch: {batch_id: [{"doc_id", "filename", "page_count"}]}
batch_registry: dict[str, list[dict]] = {}

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="PDF OCR Webapp")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _rebuild_status() -> None:
    """Ricostruisce lo stato OCR dai file su disco al riavvio del server."""
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
            pass


# ── Endpoint: salute sistema ──────────────────────────────────────────────────

@app.get("/api/health")
async def health() -> JSONResponse:
    """Verifica che Ollama sia raggiungibile e che glm-ocr sia installato."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.get("http://localhost:11434/api/tags")
            res.raise_for_status()
            models = [m.get("name", "") for m in res.json().get("models", [])]
            glm_ok = any(m.startswith("glm-ocr") for m in models)
        return JSONResponse({
            "ollama": "ok",
            "glm_ocr": "available" if glm_ok else "not_found",
            "models": models,
        })
    except Exception as exc:
        return JSONResponse({"ollama": "error", "detail": str(exc)}, status_code=503)


# ── Endpoint: caricamento PDF ─────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)) -> JSONResponse:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo file PDF sono supportati.")

    doc_id  = str(uuid.uuid4())
    doc_dir = UPLOAD_DIR / doc_id
    doc_dir.mkdir(parents=True)
    (doc_dir / "pages").mkdir()
    (doc_dir / "ocr").mkdir()

    pdf_path = doc_dir / "document.pdf"
    pdf_path.write_bytes(await file.read())

    try:
        pdf_doc    = fitz.open(str(pdf_path))
        page_count = len(pdf_doc)

        if page_count == 0:
            raise ValueError("Il PDF non contiene pagine.")

        for i in range(page_count):
            page = pdf_doc[i]
            # Matrice 2× → ~144 DPI: buon compromesso qualità/dimensione
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            pix.save(str(doc_dir / "pages" / f"page_{i}.png"))

        pdf_doc.close()
    except Exception as exc:
        shutil.rmtree(doc_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Conversione PDF fallita: {exc}")

    metadata = {
        "doc_id":     doc_id,
        "filename":   file.filename,
        "page_count": page_count,
    }
    (doc_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )

    ocr_status[doc_id] = {i: "pending" for i in range(page_count)}
    return JSONResponse(metadata)


# ── Endpoint: metadati documento ──────────────────────────────────────────────

@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: str) -> JSONResponse:
    meta_path = UPLOAD_DIR / doc_id / "metadata.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Documento non trovato.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["ocr_status"] = {str(k): v for k, v in ocr_status.get(doc_id, {}).items()}
    return JSONResponse(meta)


# ── Endpoint: immagine pagina ─────────────────────────────────────────────────

@app.get("/api/page/{doc_id}/{page_num}")
async def get_page_image(doc_id: str, page_num: int) -> FileResponse:
    img_path = UPLOAD_DIR / doc_id / "pages" / f"page_{page_num}.png"
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Pagina non trovata.")
    return FileResponse(str(img_path), media_type="image/png")


# ── Endpoint: risultato OCR (lettura) ─────────────────────────────────────────

@app.get("/api/ocr/{doc_id}/{page_num}")
async def get_ocr(doc_id: str, page_num: int) -> JSONResponse:
    ocr_path = UPLOAD_DIR / doc_id / "ocr" / f"page_{page_num}.md"
    if ocr_path.exists():
        return JSONResponse({
            "status":   "done",
            "markdown": ocr_path.read_text(encoding="utf-8"),
        })
    status = (ocr_status.get(doc_id) or {}).get(page_num, "pending")
    return JSONResponse({"status": status, "markdown": None})


# ── Endpoint: avvio OCR (scrittura) ───────────────────────────────────────────

@app.post("/api/ocr/{doc_id}/{page_num}")
async def start_ocr(
    doc_id: str,
    page_num: int,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    img_path = UPLOAD_DIR / doc_id / "pages" / f"page_{page_num}.png"
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Pagina non trovata.")

    ocr_path = UPLOAD_DIR / doc_id / "ocr" / f"page_{page_num}.md"

    # Già completato
    if ocr_path.exists():
        return JSONResponse({
            "status":   "done",
            "markdown": ocr_path.read_text(encoding="utf-8"),
        })

    # Già in elaborazione
    status = (ocr_status.get(doc_id) or {}).get(page_num, "pending")
    if status == "processing":
        return JSONResponse({"status": "processing", "markdown": None})

    # Avvia elaborazione
    if doc_id not in ocr_status:
        ocr_status[doc_id] = {}
    ocr_status[doc_id][page_num] = "processing"

    background_tasks.add_task(_run_ocr, doc_id, page_num, img_path, ocr_path)
    return JSONResponse({"status": "processing", "markdown": None})


# ── Endpoint: export Markdown combinato ──────────────────────────────────────

@app.get("/api/export/{doc_id}")
async def export_markdown(doc_id: str) -> JSONResponse:
    meta_path = UPLOAD_DIR / doc_id / "metadata.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Documento non trovato.")

    meta       = json.loads(meta_path.read_text(encoding="utf-8"))
    page_count = meta["page_count"]
    stem       = Path(meta["filename"]).stem

    parts: list[str] = []
    for i in range(page_count):
        ocr_path = UPLOAD_DIR / doc_id / "ocr" / f"page_{i}.md"
        if ocr_path.exists():
            parts.append(
                f"<!-- Pagina {i + 1} -->\n\n"
                + ocr_path.read_text(encoding="utf-8").strip()
                + "\n\n---\n"
            )

    content = "\n".join(parts) if parts else "_Nessun risultato OCR disponibile._"
    return JSONResponse({"filename": f"{stem}.md", "content": content})


# ── Task background: chiamata a Ollama ───────────────────────────────────────

async def _run_ocr(
    doc_id:   str,
    page_num: int,
    img_path: Path,
    ocr_path: Path,
) -> None:
    try:
        img_b64 = base64.b64encode(img_path.read_bytes()).decode("utf-8")
        payload = {
            "model":  MODEL_NAME,
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
        # Salva il messaggio di errore nel file in modo che il client possa vederlo
        try:
            ocr_path.write_text(
                f"> **Errore OCR (pagina {page_num + 1}):**\n> `{exc}`",
                encoding="utf-8",
            )
            # Segna comunque come done così il client smette di fare polling
            ocr_status[doc_id][page_num] = "done"
        except Exception:
            pass


# ── Endpoint batch: caricamento multiplo PDF ─────────────────────────────────

@app.post("/api/batch")
async def batch_upload(files: List[UploadFile] = File(...)) -> JSONResponse:
    """Carica più PDF, converte in pagine PNG, restituisce batch_id e lista documenti."""
    batch_id = str(uuid.uuid4())
    docs: list[dict] = []
    errors: list[dict] = []

    for file in files:
        if not (file.filename or "").lower().endswith(".pdf"):
            errors.append({"filename": file.filename, "error": "Non è un file PDF."})
            continue

        doc_id  = str(uuid.uuid4())
        doc_dir = UPLOAD_DIR / doc_id
        doc_dir.mkdir(parents=True)
        (doc_dir / "pages").mkdir()
        (doc_dir / "ocr").mkdir()

        pdf_path = doc_dir / "document.pdf"
        pdf_path.write_bytes(await file.read())

        try:
            pdf_doc    = fitz.open(str(pdf_path))
            page_count = len(pdf_doc)
            if page_count == 0:
                raise ValueError("Il PDF non contiene pagine.")
            for i in range(page_count):
                pix = pdf_doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                pix.save(str(doc_dir / "pages" / f"page_{i}.png"))
            pdf_doc.close()
        except Exception as exc:
            shutil.rmtree(doc_dir, ignore_errors=True)
            errors.append({"filename": file.filename, "error": str(exc)})
            continue

        metadata = {
            "doc_id":     doc_id,
            "filename":   file.filename,
            "page_count": page_count,
            "batch_id":   batch_id,
        }
        (doc_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
        ocr_status[doc_id] = {i: "pending" for i in range(page_count)}
        docs.append({"doc_id": doc_id, "filename": file.filename, "page_count": page_count})

    batch_registry[batch_id] = docs
    return JSONResponse({"batch_id": batch_id, "docs": docs, "errors": errors})


# ── Endpoint batch: avvio OCR su tutti i file ────────────────────────────────

@app.post("/api/batch/{batch_id}/start")
async def batch_start_ocr(
    batch_id: str,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Avvia l'OCR in background su tutte le pagine di tutti i documenti del batch."""
    docs = batch_registry.get(batch_id)
    if docs is None:
        raise HTTPException(status_code=404, detail="Batch non trovato.")

    pages_queued = 0
    for doc in docs:
        doc_id     = doc["doc_id"]
        page_count = doc["page_count"]
        for page_num in range(page_count):
            img_path = UPLOAD_DIR / doc_id / "pages" / f"page_{page_num}.png"
            ocr_path = UPLOAD_DIR / doc_id / "ocr"   / f"page_{page_num}.md"
            if ocr_path.exists():
                continue
            current = (ocr_status.get(doc_id) or {}).get(page_num, "pending")
            if current == "processing":
                continue
            if doc_id not in ocr_status:
                ocr_status[doc_id] = {}
            ocr_status[doc_id][page_num] = "processing"
            background_tasks.add_task(_run_ocr, doc_id, page_num, img_path, ocr_path)
            pages_queued += 1

    return JSONResponse({"batch_id": batch_id, "pages_queued": pages_queued})


# ── Endpoint batch: stato avanzamento ────────────────────────────────────────

@app.get("/api/batch/{batch_id}")
async def get_batch_status(batch_id: str) -> JSONResponse:
    """Restituisce lo stato corrente di ogni documento nel batch."""
    docs = batch_registry.get(batch_id)
    if docs is None:
        raise HTTPException(status_code=404, detail="Batch non trovato.")

    result: list[dict] = []
    for doc in docs:
        doc_id     = doc["doc_id"]
        page_count = doc["page_count"]
        page_st    = ocr_status.get(doc_id, {})

        pages_done       = sum(1 for i in range(page_count) if page_st.get(i) == "done")
        pages_error      = sum(1 for i in range(page_count) if page_st.get(i) == "error")
        pages_processing = sum(1 for i in range(page_count) if page_st.get(i) == "processing")

        if pages_done == page_count:
            status = "done"
        elif pages_processing > 0 or (pages_done > 0 and pages_done < page_count):
            status = "processing"
        elif pages_error == page_count:
            status = "error"
        elif pages_error > 0 and pages_done + pages_error == page_count:
            status = "partial"
        else:
            status = "pending"

        result.append({
            "doc_id":      doc_id,
            "filename":    doc["filename"],
            "page_count":  page_count,
            "pages_done":  pages_done,
            "pages_error": pages_error,
            "status":      status,
        })

    return JSONResponse({"batch_id": batch_id, "docs": result})


# ── Endpoint batch: report Markdown ──────────────────────────────────────────

@app.get("/api/batch/{batch_id}/report")
async def get_batch_report(batch_id: str) -> JSONResponse:
    """Genera un report Markdown del batch con riepilogo e dettaglio per file."""
    docs = batch_registry.get(batch_id)
    if docs is None:
        raise HTTPException(status_code=404, detail="Batch non trovato.")

    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(docs)
    n_done = n_partial = n_error = n_pending = 0
    rows: list[tuple] = []

    for doc in docs:
        doc_id     = doc["doc_id"]
        page_count = doc["page_count"]
        page_st    = ocr_status.get(doc_id, {})
        pages_done  = sum(1 for i in range(page_count) if page_st.get(i) == "done")
        pages_error = sum(1 for i in range(page_count) if page_st.get(i) == "error")

        if pages_done == page_count:
            status_label = "✓ Completato"; n_done += 1
        elif pages_error > 0 and pages_done == 0:
            status_label = "✗ Errore"; n_error += 1
        elif pages_done > 0:
            status_label = "⚠ Parziale"; n_partial += 1
        else:
            status_label = "○ Non elaborato"; n_pending += 1

        rows.append((doc["filename"], page_count, pages_done, pages_error, status_label))

    lines = [
        "# Report Conversione Batch OCR",
        "",
        f"- **Data:** {now}",
        f"- **Batch ID:** `{batch_id}`",
        "",
        "## Sommario",
        "",
        f"| Totale | Completati | Parziali | Errori | Non elaborati |",
        f"|--------|------------|----------|--------|---------------|",
        f"| {total} | {n_done} | {n_partial} | {n_error} | {n_pending} |",
        "",
        "## Dettaglio File",
        "",
        "| # | File | Pagine Tot. | Elaborate | Errori | Stato |",
        "|---|------|-------------|-----------|--------|-------|",
    ]
    for idx, (fn, pc, pd, pe, sl) in enumerate(rows, 1):
        lines.append(f"| {idx} | {fn} | {pc} | {pd} | {pe} | {sl} |")

    lines += [
        "",
        "---",
        f"_Report generato automaticamente da PDF OCR Webapp_",
    ]

    report_md = "\n".join(lines)
    filename  = f"report_batch_{batch_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    return JSONResponse({"report": report_md, "filename": filename})


# ── Endpoint batch: export ZIP ────────────────────────────────────────────────

@app.get("/api/batch/{batch_id}/export")
async def export_batch_zip(batch_id: str) -> StreamingResponse:
    """Restituisce uno ZIP con tutti i file Markdown prodotti dal batch."""
    docs = batch_registry.get(batch_id)
    if docs is None:
        raise HTTPException(status_code=404, detail="Batch non trovato.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            doc_id     = doc["doc_id"]
            page_count = doc["page_count"]
            stem       = Path(doc["filename"]).stem
            parts: list[str] = []
            for i in range(page_count):
                ocr_path = UPLOAD_DIR / doc_id / "ocr" / f"page_{i}.md"
                if ocr_path.exists():
                    parts.append(
                        f"<!-- Pagina {i + 1} -->\n\n"
                        + ocr_path.read_text(encoding="utf-8").strip()
                        + "\n\n---\n"
                    )
            if parts:
                zf.writestr(f"{stem}.md", "\n".join(parts))

        # Aggiungi il log/report dentro lo ZIP
        report_lines = [
            "# Log Conversione Batch",
            f"Generato: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Batch ID: {batch_id}",
            "",
        ]
        for doc in docs:
            doc_id = doc["doc_id"]
            pc     = doc["page_count"]
            pg_st  = ocr_status.get(doc_id, {})
            pd     = sum(1 for i in range(pc) if pg_st.get(i) == "done")
            pe     = sum(1 for i in range(pc) if pg_st.get(i) == "error")
            report_lines.append(f"- {doc['filename']}: {pd}/{pc} pagine OK, {pe} errori")
        zf.writestr("_report.md", "\n".join(report_lines))

    buf.seek(0)
    zip_name = f"batch_{batch_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


# ── File statici e root ───────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse("static/index.html")
