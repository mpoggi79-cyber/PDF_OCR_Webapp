from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import fitz
from fastapi import HTTPException, UploadFile

from backend.config import (
    CURRENTLY_SUPPORTED_EXTENSIONS,
    DEFAULT_PAGE_IMAGE_EXTENSION,
    PDF_EXTENSIONS,
    RASTER_IMAGE_EXTENSIONS,
    UPLOAD_DIR,
    get_available_prompt_profiles,
    normalize_prompt_profile,
)
from backend.state import ocr_status


def get_doc_dir(doc_id: str) -> Path:
    return UPLOAD_DIR / doc_id


def get_metadata_path(doc_id: str) -> Path:
    return get_doc_dir(doc_id) / "metadata.json"


def build_page_image_path(
    doc_id: str,
    page_num: int,
    *,
    extension: str = DEFAULT_PAGE_IMAGE_EXTENSION,
) -> Path:
    return get_doc_dir(doc_id) / "pages" / f"page_{page_num}{extension}"


def _get_page_image_extension(doc_id: str) -> str:
    meta_path = get_metadata_path(doc_id)
    if not meta_path.exists():
        return DEFAULT_PAGE_IMAGE_EXTENSION

    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_PAGE_IMAGE_EXTENSION

    return metadata.get("page_image_extension", DEFAULT_PAGE_IMAGE_EXTENSION)


def get_page_image_path(doc_id: str, page_num: int) -> Path:
    return build_page_image_path(doc_id, page_num, extension=_get_page_image_extension(doc_id))


def get_page_ocr_path(doc_id: str, page_num: int) -> Path:
    return get_doc_dir(doc_id) / "ocr" / f"page_{page_num}.md"


def get_page_ocr_sidecar_path(doc_id: str, page_num: int) -> Path:
    return get_doc_dir(doc_id) / "ocr" / f"page_{page_num}.json"


def _get_extension(filename: str | None) -> str:
    return Path(filename or "").suffix.lower()


def ensure_supported_upload(filename: str | None) -> str:
    extension = _get_extension(filename)
    if extension not in CURRENTLY_SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Formato non supportato. Usa PDF, PNG, JPG o JPEG.",
        )
    return extension


async def save_uploaded_document(
    file: UploadFile,
    *,
    batch_id: str | None = None,
    prompt_profile: str | None = None,
) -> dict:
    normalized_prompt_profile = normalize_prompt_profile(prompt_profile)
    extension = ensure_supported_upload(file.filename)
    if extension in PDF_EXTENSIONS:
        return await _save_uploaded_pdf(
            file,
            extension=extension,
            batch_id=batch_id,
            prompt_profile=normalized_prompt_profile,
        )
    if extension in RASTER_IMAGE_EXTENSIONS:
        return await _save_uploaded_image(
            file,
            extension=extension,
            batch_id=batch_id,
            prompt_profile=normalized_prompt_profile,
        )

    raise HTTPException(status_code=400, detail="Formato non supportato.")


async def _save_uploaded_pdf(
    file: UploadFile,
    *,
    extension: str,
    batch_id: str | None = None,
    prompt_profile: str,
) -> dict:
    doc_id = str(uuid.uuid4())
    doc_dir = get_doc_dir(doc_id)
    doc_dir.mkdir(parents=True)
    (doc_dir / "pages").mkdir()
    (doc_dir / "ocr").mkdir()

    pdf_path = doc_dir / "document.pdf"
    pdf_path.write_bytes(await file.read())

    try:
        pdf_doc = fitz.open(str(pdf_path))
        page_count = len(pdf_doc)

        if page_count == 0:
            raise ValueError("Il PDF non contiene pagine.")

        for page_num in range(page_count):
            page = pdf_doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            pix.save(str(build_page_image_path(doc_id, page_num)))

        pdf_doc.close()
    except Exception as exc:
        shutil.rmtree(doc_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Conversione documento fallita: {exc}")

    metadata = {
        "doc_id": doc_id,
        "filename": file.filename,
        "page_count": page_count,
        "source_type": "pdf",
        "original_extension": extension,
        "page_image_extension": DEFAULT_PAGE_IMAGE_EXTENSION,
        "prompt_profile": prompt_profile,
    }
    if batch_id is not None:
        metadata["batch_id"] = batch_id

    get_metadata_path(doc_id).write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )

    ocr_status[doc_id] = {page_num: "pending" for page_num in range(page_count)}
    return metadata


async def _save_uploaded_image(
    file: UploadFile,
    *,
    extension: str,
    batch_id: str | None = None,
    prompt_profile: str,
) -> dict:
    doc_id = str(uuid.uuid4())
    doc_dir = get_doc_dir(doc_id)
    doc_dir.mkdir(parents=True)
    (doc_dir / "pages").mkdir()
    (doc_dir / "ocr").mkdir()

    image_bytes = await file.read()
    image_path = build_page_image_path(doc_id, 0, extension=extension)
    image_path.write_bytes(image_bytes)

    metadata = {
        "doc_id": doc_id,
        "filename": file.filename,
        "page_count": 1,
        "source_type": "image",
        "original_extension": extension,
        "page_image_extension": extension,
        "prompt_profile": prompt_profile,
    }
    if batch_id is not None:
        metadata["batch_id"] = batch_id

    get_metadata_path(doc_id).write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )

    ocr_status[doc_id] = {0: "pending"}
    return metadata


def read_document_metadata(doc_id: str) -> dict:
    meta_path = get_metadata_path(doc_id)
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Documento non trovato.")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata["prompt_profile"] = normalize_prompt_profile(metadata.get("prompt_profile"))
    return metadata


def update_document_prompt_profile(doc_id: str, prompt_profile: str | None) -> dict:
    metadata = read_document_metadata(doc_id)
    metadata["prompt_profile"] = normalize_prompt_profile(prompt_profile)
    get_metadata_path(doc_id).write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )
    return metadata


def get_document_payload(doc_id: str) -> dict:
    metadata = read_document_metadata(doc_id)
    metadata["ocr_status"] = {str(k): v for k, v in ocr_status.get(doc_id, {}).items()}
    metadata["available_prompt_profiles"] = get_available_prompt_profiles()
    return metadata


def build_document_markdown(doc_id: str, page_count: int) -> str:
    parts: list[str] = []
    for page_num in range(page_count):
        ocr_path = get_page_ocr_path(doc_id, page_num)
        if not ocr_path.exists():
            continue
        parts.append(
            f"<!-- Pagina {page_num + 1} -->\n\n"
            + ocr_path.read_text(encoding="utf-8").strip()
            + "\n\n---\n"
        )
    return "\n".join(parts) if parts else "_Nessun risultato OCR disponibile._"


def get_document_export_payload(doc_id: str) -> dict:
    metadata = read_document_metadata(doc_id)
    stem = Path(metadata["filename"]).stem
    return {
        "filename": f"{stem}.md",
        "content": build_document_markdown(doc_id, metadata["page_count"]),
    }
