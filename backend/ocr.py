from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from fastapi import BackgroundTasks, HTTPException

from backend.config import (
    DEFAULT_OCR_PROMPT_PROFILE,
    GLMOCR_LAYOUT_DEVICE,
    GLMOCR_MODE,
    GLMOCR_OCR_API_MODE,
    GLMOCR_OCR_API_URL,
    GLMOCR_SAVE_LAYOUT_VISUALIZATION,
    MODEL_NAME,
    MODEL_FALLBACK_NAMES,
    OCR_BLOCK_SIZE,
    OCR_ENABLE_LAYOUT_VISUALIZATION,
    OCR_ENABLE_STRUCTURED_OUTPUT,
    OCR_INCLUDE_RAW_PROVIDER_PAYLOAD,
    OCR_PROVIDER,
    OCR_RETURN_CROP_IMAGES,
    OCR_RETRY_BACKOFF_BASE_SECONDS,
    OCR_RETRY_MAX_ATTEMPTS,
    OCR_TIMEOUT,
    OLLAMA_URL,
    get_glmocr_task_prompt_mapping,
    get_prompt_profile_mapping,
)
from backend.documents import (
    get_page_image_path,
    get_page_ocr_path,
    get_page_ocr_sidecar_path,
    read_document_metadata,
    update_document_prompt_profile,
)
from backend.state import TERMINAL_JOB_STATUSES, ocr_jobs, ocr_status, save_job_state
from backend.state import collect_job_timing_from_sidecars

_ocr_lock: asyncio.Lock | None = None
ERROR_METADATA_PREFIX = "<!-- OCR_ERROR "
logger = logging.getLogger(__name__)
_CROPPED_IMAGE_LINE_RE = re.compile(r"^!\[[^\]]*\]\(imgs/cropped_[^)]+\)\s*$")
_LABELED_FENCE_LINE_RE = re.compile(r"^\s*```(?P<language>[A-Za-z0-9_+-]+)\s*$")
_CONTAMINATED_HEADING_FENCE_RE = re.compile(r"^(?P<prefix>\s{0,3}#{1,6}\s*)```(?P<language>[A-Za-z0-9_+-]+)\s*$")
_BARE_FENCE_LINE_RE = re.compile(r"^\s*```\s*$")
_INLINE_HTML_TAG_RE = re.compile(r"</?[A-Za-z][\w:-]*(?:\s+[^>]*)?>")
_SIMPLE_TEXT_FENCE_LANGUAGES = {"html", "markdown", "md", "text", "plaintext"}


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

    if "429" in lowered or "too many requests" in lowered:
        return _build_error_info(
            source="ollama",
            error_type="rate_limited",
            label="Servizio OCR temporaneamente sovraccarico",
            interpretation=(
                "Ollama ha rifiutato temporaneamente la richiesta per sovraccarico o rate limiting. "
                "Il documento non e' necessariamente problematico e una nuova prova puo' riuscire."
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
            error_type="ollama_unreachable",
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

    if (
        "502" in lowered
        or "503" in lowered
        or "504" in lowered
        or "bad gateway" in lowered
        or "service unavailable" in lowered
        or "gateway timeout" in lowered
    ):
        return _build_error_info(
            source="ollama",
            error_type="service_unavailable",
            label="Servizio OCR temporaneamente non disponibile",
            interpretation=(
                "Ollama ha risposto con un errore temporaneo lato servizio o gateway. "
                "Il problema sembra transitorio e una nuova prova puo' riuscire."
            ),
            detail=detail,
            retryable=True,
        )

    if "500 internal server error" in lowered:
        return _build_error_info(
            source="ollama",
            error_type="model_runtime_error",
            label="Errore interno di Ollama o del modello",
            interpretation=(
                "Ollama ha accettato la richiesta ma il runtime del modello ha restituito un errore interno. "
                "Se l'errore non contiene un crash esplicito del modello, una nuova prova puo' riuscire."
            ),
            detail=detail,
            retryable=True,
        )

    if (
        "malformed ocr response" in lowered
        or "invalid json" in lowered
        or "expecting value" in lowered
        or "response field" in lowered
    ):
        return _build_error_info(
            source="ollama",
            error_type="api_error",
            label="Risposta OCR malformata",
            interpretation=(
                "Il backend ha raggiunto Ollama ma la risposta JSON non e' risultata nel formato atteso. "
                "Questo segnala un problema transitorio di protocollo o di compatibilita' del servizio."
            ),
            detail=detail,
            retryable=True,
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


def _is_retryable_error(error_info: dict) -> bool:
    return bool(error_info.get("retryable"))


def _build_retry_delay(attempt: int) -> float:
    return OCR_RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))


def _get_candidate_models() -> list[str]:
    models: list[str] = []
    for model_name in (MODEL_NAME, *MODEL_FALLBACK_NAMES):
        if model_name and model_name not in models:
            models.append(model_name)
    return models


def _get_candidate_providers() -> list[str]:
    providers: list[str] = []
    for provider_name in (OCR_PROVIDER, "ollama_http"):
        normalized = (provider_name or "").strip().lower()
        if normalized and normalized not in providers:
            providers.append(normalized)
    return providers


def _format_detail_for_markdown(detail: str) -> str:
    return " ".join(detail.strip().split()).replace("`", "'")


def _extract_structured_regions(raw_regions: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_regions, list):
        return []

    normalized: list[dict[str, Any]] = []
    for page_index, page_regions in enumerate(raw_regions):
        if not isinstance(page_regions, list):
            continue
        for region_index, region in enumerate(page_regions):
            if not isinstance(region, dict):
                continue
            label = str(region.get("label") or region.get("type") or "text")
            normalized.append(
                {
                    "page": int(region.get("page", page_index)),
                    "index": int(region.get("index", region_index)),
                    "label": label,
                    "bbox": region.get("bbox") or region.get("bbox_2d"),
                    "content": region.get("content"),
                }
            )
    return normalized


def _filter_regions_by_labels(regions: list[dict[str, Any]], labels: set[str]) -> list[dict[str, Any]]:
    return [region for region in regions if str(region.get("label", "")).lower() in labels]


def _prune_none_values(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_sidecar_timing(
    payload: dict[str, Any] | None,
    *,
    started_at: str,
    finished_at: str,
    duration_ms: int,
) -> dict[str, Any]:
    merged = dict(payload or {})
    merged["started_at"] = started_at
    merged["finished_at"] = finished_at
    merged["duration_ms"] = duration_ms
    return _prune_none_values(merged)


def _encode_image_like(value: Any) -> str | None:
    save = getattr(value, "save", None)
    if not callable(save):
        return None

    try:
        buffer = BytesIO()
        save(buffer, format="PNG")
    except Exception:
        return None

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _make_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")

    image_data = _encode_image_like(value)
    if image_data is not None:
        return image_data

    if isinstance(value, dict):
        return {
            str(key): _make_json_safe(item)
            for key, item in value.items()
            if item is not None
        }

    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(item) for item in value]

    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return _make_json_safe(tolist())
        except Exception:
            pass

    return str(value)


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._current_cell_span = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "tr":
            self._current_row = []
        elif normalized_tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            attributes = dict(attrs)
            try:
                self._current_cell_span = max(int(attributes.get("colspan") or "1"), 1)
            except ValueError:
                self._current_cell_span = 1
        elif normalized_tag == "br" and self._current_cell is not None:
            self._current_cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            value = " ".join("".join(self._current_cell).split())
            self._current_row.append(value)
            self._current_row.extend("" for _ in range(self._current_cell_span - 1))
            self._current_cell = None
            self._current_cell_span = 1
        elif normalized_tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None


class _HtmlTableExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.output: list[str] = []
        self._table_markup: list[str] | None = None
        self._table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raw_tag = self.get_starttag_text() or f"<{tag}>"
        if self._table_depth:
            self._table_markup.append(raw_tag)
            if tag.lower() == "table":
                self._table_depth += 1
        elif tag.lower() == "table":
            self._table_markup = [raw_tag]
            self._table_depth = 1
        else:
            self.output.append(raw_tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raw_tag = self.get_starttag_text() or f"<{tag}/>"
        if self._table_depth:
            self._table_markup.append(raw_tag)
        else:
            self.output.append(raw_tag)

    def handle_endtag(self, tag: str) -> None:
        raw_tag = f"</{tag}>"
        if not self._table_depth:
            self.output.append(raw_tag)
            return

        self._table_markup.append(raw_tag)
        if tag.lower() != "table":
            return

        self._table_depth -= 1
        if self._table_depth:
            return

        table_markup = "".join(self._table_markup)
        self.output.append(_render_html_table_as_markdown(table_markup))
        self._table_markup = None

    def handle_data(self, data: str) -> None:
        if self._table_depth:
            self._table_markup.append(data)
        else:
            self.output.append(data)

    def handle_entityref(self, name: str) -> None:
        self._append_raw(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append_raw(f"&#{name};")

    def _append_raw(self, value: str) -> None:
        if self._table_depth:
            self._table_markup.append(value)
        else:
            self.output.append(value)


def _render_html_table_as_markdown(table_markup: str) -> str:
    parser = _HtmlTableParser()
    parser.feed(table_markup)
    parser.close()
    if not parser.rows:
        return ""

    column_count = max(len(row) for row in parser.rows)
    rows = [row + [""] * (column_count - len(row)) for row in parser.rows]

    def format_cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ").strip()

    header = rows[0]
    separator = ["---"] * column_count
    rendered = [
        "| " + " | ".join(format_cell(value) for value in header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    rendered.extend(
        "| " + " | ".join(format_cell(value) for value in row) + " |"
        for row in rows[1:]
    )
    return "\n".join(rendered)


def _convert_html_tables_to_markdown(markdown: str) -> str:
    parser = _HtmlTableExtractor()
    parser.feed(markdown)
    parser.close()
    return "".join(parser.output)


def _post_process_markdown(markdown: str, *, force_no_html: bool = False) -> str:
    if force_no_html:
        markdown = _convert_html_tables_to_markdown(markdown)

    lines = _rewrite_spurious_fence_blocks(markdown.splitlines())
    cleaned_lines: list[str] = []
    previous_blank = False

    for line in lines:
        if _CROPPED_IMAGE_LINE_RE.match(line.strip()):
            continue

        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue

        cleaned_lines.append(line.rstrip())
        previous_blank = is_blank

    return "\n".join(cleaned_lines).strip()


def _rewrite_spurious_fence_blocks(lines: list[str]) -> list[str]:
    rewritten_lines: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        contaminated_heading_match = _CONTAMINATED_HEADING_FENCE_RE.match(line)
        labeled_fence_match = _LABELED_FENCE_LINE_RE.match(line)

        if contaminated_heading_match or labeled_fence_match:
            opening_match = contaminated_heading_match or labeled_fence_match
            language = (opening_match.group("language") or "").lower()
            closing_index = _find_simple_fence_block_end(lines, index + 1)

            if language in _SIMPLE_TEXT_FENCE_LANGUAGES and closing_index is not None:
                block_lines = lines[index + 1 : closing_index]
                if _is_simple_text_fence_block(block_lines):
                    heading_prefix = (
                        contaminated_heading_match.group("prefix")
                        if contaminated_heading_match is not None
                        else None
                    )
                    rewritten_lines.extend(
                        _unwrap_simple_fence_block(block_lines, heading_prefix=heading_prefix)
                    )
                    index = closing_index + 1
                    continue

        if _is_spurious_standalone_fence(lines, index):
            index += 1
            continue

        rewritten_lines.append(line)
        index += 1

    return rewritten_lines


def _find_simple_fence_block_end(lines: list[str], start_index: int) -> int | None:
    for index in range(start_index, len(lines)):
        if _BARE_FENCE_LINE_RE.match(lines[index]):
            return index
    return None


def _is_simple_text_fence_block(block_lines: list[str]) -> bool:
    meaningful_lines = [line.strip() for line in block_lines if line.strip()]
    if not meaningful_lines:
        return True

    return all(not _looks_like_literal_code_line(line) for line in meaningful_lines)


def _looks_like_literal_code_line(line: str) -> bool:
    if line.startswith(("$", ">>>", "pip ", "python ", "curl ", "npm ", "git ")):
        return True

    if _INLINE_HTML_TAG_RE.search(line):
        return True

    if any(token in line for token in ("</", "/>", "=>", "::", "{", "}", ";")):
        return True

    if line.startswith(("def ", "class ", "import ", "from ", "SELECT ", "INSERT ", "UPDATE ")):
        return True

    return False


def _unwrap_simple_fence_block(
    block_lines: list[str],
    *,
    heading_prefix: str | None,
) -> list[str]:
    trimmed_lines = _trim_blank_edges(block_lines)
    if not trimmed_lines:
        return []

    if heading_prefix:
        meaningful_lines = [line.strip() for line in trimmed_lines if line.strip()]
        if not meaningful_lines:
            return []

        unwrapped_lines = [f"{heading_prefix}{meaningful_lines[0]}"]
        if len(meaningful_lines) > 1:
            unwrapped_lines.append("")
            unwrapped_lines.extend(meaningful_lines[1:])
        return unwrapped_lines

    return [line.rstrip() for line in trimmed_lines]


def _trim_blank_edges(lines: list[str]) -> list[str]:
    start_index = 0
    end_index = len(lines)

    while start_index < end_index and not lines[start_index].strip():
        start_index += 1

    while end_index > start_index and not lines[end_index - 1].strip():
        end_index -= 1

    return lines[start_index:end_index]


def _is_spurious_standalone_fence(lines: list[str], index: int) -> bool:
    line = lines[index]
    if not _BARE_FENCE_LINE_RE.match(line):
        return False

    previous_line = lines[index - 1].strip() if index > 0 else ""
    next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""

    if _looks_like_literal_code_line(previous_line) or _looks_like_literal_code_line(next_line):
        return False

    if _INLINE_HTML_TAG_RE.search(previous_line) or _INLINE_HTML_TAG_RE.search(next_line):
        return False

    if not previous_line and not next_line:
        return True

    if not previous_line:
        return True

    if not next_line:
        return True

    return True


def _has_meaningful_structured_payload(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False

    for key, value in payload.items():
        if key in {"provider", "model", "raw_provider_payload"}:
            continue
        if value not in (None, [], {}, ""):
            return True
    return False


def _build_structured_payload(
    *,
    provider: str,
    model_name: str,
    layout_visualization: Any = None,
    crop_regions: Any = None,
    structured_regions: list[dict[str, Any]] | None = None,
    confidence: Any = None,
    structure_metadata: dict[str, Any] | None = None,
    raw_provider_payload: Any = None,
) -> dict[str, Any] | None:
    if not OCR_ENABLE_STRUCTURED_OUTPUT:
        return None

    regions = structured_regions or []
    table_regions = _filter_regions_by_labels(regions, {"table"})
    formula_regions = _filter_regions_by_labels(
        regions,
        {"formula", "display_formula", "inline_formula"},
    )
    payload = _make_json_safe(
        _prune_none_values(
                {
                    "provider": provider,
                    "model": model_name,
                    "layout_visualization": layout_visualization,
                    "crop_regions": crop_regions,
                    "table_regions": table_regions or None,
                    "formula_regions": formula_regions or None,
                    "confidence": confidence,
                    "capabilities": {
                        "layout_visualization": layout_visualization is not None,
                        "crop_regions": crop_regions not in (None, [], {}),
                        "structured_regions": bool(regions),
                        "table_regions": bool(table_regions),
                        "formula_regions": bool(formula_regions),
                        "confidence": confidence is not None,
                    },
                    "structure_metadata": structure_metadata,
                    "raw_provider_payload": raw_provider_payload if OCR_INCLUDE_RAW_PROVIDER_PAYLOAD else None,
                }
            )
    )
    if not isinstance(payload, dict):
        return None
    return payload if _has_meaningful_structured_payload(payload) else None


def _read_structured_sidecar(doc_id: str, page_num: int) -> dict[str, Any] | None:
    sidecar_path = get_page_ocr_sidecar_path(doc_id, page_num)
    if not sidecar_path.exists():
        return None

    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    return payload if isinstance(payload, dict) else None


def _write_structured_sidecar(doc_id: str, page_num: int, payload: dict[str, Any] | None) -> None:
    sidecar_path = get_page_ocr_sidecar_path(doc_id, page_num)
    if not _has_meaningful_structured_payload(payload):
        if sidecar_path.exists():
            sidecar_path.unlink()
        return

    sidecar_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_ollama_response(result: dict[str, Any], model_name: str) -> tuple[str, dict[str, Any] | None]:
    markdown = result.get("response") or result.get("md_results")
    if not isinstance(markdown, str):
        raise ValueError("Malformed OCR response: missing string response field")

    raw_regions = result.get("layout_details")
    if raw_regions is None:
        raw_regions = result.get("regions")

    structured_regions = _extract_structured_regions(raw_regions)
    structure_metadata = {
        "regions": structured_regions,
        "page_count": len(raw_regions) if isinstance(raw_regions, list) else None,
        "data_info": result.get("data_info"),
        "usage": result.get("usage"),
    }
    structure_metadata = _prune_none_values(structure_metadata)

    structured_payload = _build_structured_payload(
        provider="ollama_http",
        model_name=model_name,
        layout_visualization=result.get("layout_visualization"),
        crop_regions=result.get("crop_regions"),
        structured_regions=structured_regions,
        confidence=result.get("confidence"),
        structure_metadata=structure_metadata or None,
        raw_provider_payload=result,
    )
    return markdown, structured_payload


def _normalize_glmocr_result(result: Any, model_name: str) -> tuple[str, dict[str, Any] | None]:
    markdown = getattr(result, "markdown_result", None)
    if not isinstance(markdown, str):
        raise ValueError("Malformed glmocr result: missing markdown_result")

    json_result = getattr(result, "json_result", None)
    structured_regions = _extract_structured_regions(json_result)
    layout_visualization = getattr(result, "layout_visualization", None)
    if layout_visualization is None:
        layout_visualization = getattr(result, "_layout_visualization", None)

    raw_provider_payload = None
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        maybe_payload = to_dict()
        if isinstance(maybe_payload, dict):
            raw_provider_payload = maybe_payload

    structure_metadata = {
        "regions": structured_regions,
        "page_count": len(json_result) if isinstance(json_result, list) else None,
        "image_files": getattr(result, "image_files", None),
    }
    structure_metadata = _prune_none_values(structure_metadata)

    structured_payload = _build_structured_payload(
        provider="glmocr",
        model_name=model_name,
        layout_visualization=layout_visualization,
        crop_regions=getattr(result, "image_files", None),
        structured_regions=structured_regions,
        confidence=None,
        structure_metadata=structure_metadata or None,
        raw_provider_payload=raw_provider_payload,
    )
    return markdown, structured_payload


def _build_glmocr_kwargs(model_name: str, prompt_mapping: dict[str, str]) -> dict[str, Any]:
    task_prompt_mapping = dict(prompt_mapping)
    task_prompt_mapping.update(get_glmocr_task_prompt_mapping())
    kwargs: dict[str, Any] = {
        "mode": GLMOCR_MODE,
        "model": model_name,
        "timeout": int(OCR_TIMEOUT),
        "_dotted": {
            "pipeline.ocr_api.api_url": GLMOCR_OCR_API_URL,
            "pipeline.ocr_api.api_mode": GLMOCR_OCR_API_MODE,
            "pipeline.ocr_api.model": model_name,
            "pipeline.page_loader.task_prompt_mapping": task_prompt_mapping,
        },
    }
    if GLMOCR_LAYOUT_DEVICE:
        kwargs["layout_device"] = GLMOCR_LAYOUT_DEVICE
    return kwargs


def _run_glmocr_sync(
    img_path: Path,
    model_name: str,
    prompt_mapping: dict[str, str],
) -> tuple[str, dict[str, Any] | None]:
    from glmocr import GlmOcr

    parse_kwargs: dict[str, Any] = {
        "save_layout_visualization": GLMOCR_SAVE_LAYOUT_VISUALIZATION,
    }
    if OCR_ENABLE_LAYOUT_VISUALIZATION:
        parse_kwargs["need_layout_visualization"] = True
    if OCR_RETURN_CROP_IMAGES:
        parse_kwargs["return_crop_images"] = True

    with GlmOcr(**_build_glmocr_kwargs(model_name, prompt_mapping)) as parser:
        result = parser.parse(img_path, **parse_kwargs)
    return _normalize_glmocr_result(result, model_name)


async def _run_ocr_with_glmocr(
    img_path: Path,
    model_name: str,
    prompt_mapping: dict[str, str],
) -> tuple[str, dict[str, Any] | None]:
    return await asyncio.to_thread(_run_glmocr_sync, img_path, model_name, prompt_mapping)


async def _run_ocr_with_ollama_http(
    img_b64: str,
    model_name: str,
    prompt_mapping: dict[str, str],
) -> tuple[str, dict[str, Any] | None]:
    payload: dict[str, Any] = {
        "model": model_name,
        "prompt": prompt_mapping.get("text") or get_prompt_profile_mapping(DEFAULT_OCR_PROMPT_PROFILE)["text"],
        "images": [img_b64],
        "stream": False,
    }
    if OCR_ENABLE_LAYOUT_VISUALIZATION:
        payload["need_layout_visualization"] = True
    if OCR_RETURN_CROP_IMAGES:
        payload["return_crop_images"] = True

    async with httpx.AsyncClient(timeout=OCR_TIMEOUT) as client:
        response = await client.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        result = response.json()
    if not isinstance(result, dict):
        raise ValueError("Malformed OCR response: expected JSON object")
    return _normalize_ollama_response(result, model_name)


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
    timing_summary = collect_job_timing_from_sidecars(doc_id, page_count)
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
            **timing_summary,
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
        content = ocr_path.read_text(encoding="utf-8", errors="ignore").lstrip()
        return content.startswith(ERROR_METADATA_PREFIX) or content.startswith("> **Errore OCR")
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
    prompt_profile: str | None = None,
) -> dict:
    if prompt_profile is not None:
        metadata = update_document_prompt_profile(doc_id, prompt_profile)
    else:
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
    structured_payload = _read_structured_sidecar(doc_id, page_num)

    if status == "processing":
        return {"status": "processing", "markdown": None, "error": None}
    if status == "error":
        markdown = ocr_path.read_text(encoding="utf-8") if ocr_path.exists() else None
        payload = {
            "status": "error",
            "markdown": markdown,
            "error": _extract_error_info_from_markdown(markdown),
        }
        if structured_payload:
            payload.update(structured_payload)
        return payload
    if ocr_path.exists():
        payload = {
            "status": "done",
            "markdown": ocr_path.read_text(encoding="utf-8"),
            "error": None,
        }
        if structured_payload:
            payload.update(structured_payload)
        return payload

    return {"status": status, "markdown": None, "error": None}


def start_ocr_payload(
    background_tasks: BackgroundTasks,
    doc_id: str,
    page_num: int,
    *,
    prompt_profile: str | None = None,
) -> dict:
    img_path = get_page_image_path(doc_id, page_num)
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Pagina non trovata.")

    if prompt_profile is not None:
        update_document_prompt_profile(doc_id, prompt_profile)

    status = (ocr_status.get(doc_id) or {}).get(page_num, "pending")
    if status == "processing":
        return {"status": "processing", "markdown": None}

    ocr_path = get_page_ocr_path(doc_id, page_num)
    if ocr_path.exists() and status != "error":
        return get_ocr_payload(doc_id, page_num)

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
    started_at = _utc_now_iso()
    started_at_perf = time.perf_counter()
    try:
        metadata = read_document_metadata(doc_id)
        prompt_profile = metadata.get("prompt_profile") or DEFAULT_OCR_PROMPT_PROFILE
        prompt_mapping = get_prompt_profile_mapping(prompt_profile)
        img_b64 = base64.b64encode(img_path.read_bytes()).decode("utf-8")
        last_error: Exception | None = None
        provider_result: tuple[str, dict[str, Any] | None] | None = None
        providers = _get_candidate_providers()
        models = _get_candidate_models()

        for provider_index, provider_name in enumerate(providers, start=1):
            provider_failed = False
            for model_index, model_name in enumerate(models, start=1):
                for attempt in range(1, OCR_RETRY_MAX_ATTEMPTS + 1):
                    try:
                        if provider_name == "glmocr":
                            provider_result = await _run_ocr_with_glmocr(img_path, model_name, prompt_mapping)
                        else:
                            provider_result = await _run_ocr_with_ollama_http(img_b64, model_name, prompt_mapping)

                        markdown, structured_payload = provider_result
                        markdown = _post_process_markdown(
                            markdown,
                            force_no_html=prompt_profile == "structured_document_no_html",
                        )
                        if model_index > 1 or provider_index > 1:
                            logger.info(
                                "OCR succeeded for doc=%s page=%s using fallback provider=%s model=%s",
                                doc_id,
                                page_num,
                                provider_name,
                                model_name,
                            )
                        ocr_path.write_text(markdown, encoding="utf-8")
                        finished_at = _utc_now_iso()
                        duration_ms = max(int((time.perf_counter() - started_at_perf) * 1000), 0)
                        _write_structured_sidecar(
                            doc_id,
                            page_num,
                            _merge_sidecar_timing(
                                structured_payload,
                                started_at=started_at,
                                finished_at=finished_at,
                                duration_ms=duration_ms,
                            ),
                        )
                        ocr_status[doc_id][page_num] = "done"
                        return
                    except Exception as exc:
                        last_error = exc
                        error_info = _classify_ocr_exception(exc)
                        retryable = _is_retryable_error(error_info)
                        is_last_attempt = attempt >= OCR_RETRY_MAX_ATTEMPTS
                        has_fallback_model = model_index < len(models)
                        has_fallback_provider = provider_index < len(providers)

                        logger.warning(
                            "OCR attempt failed for doc=%s page=%s provider=%s model=%s attempt=%s/%s type=%s retryable=%s detail=%s",
                            doc_id,
                            page_num,
                            provider_name,
                            model_name,
                            attempt,
                            OCR_RETRY_MAX_ATTEMPTS,
                            error_info.get("type", "unexpected_error"),
                            retryable,
                            error_info.get("detail", ""),
                        )

                        if provider_name == "glmocr" and not retryable and has_fallback_provider:
                            provider_failed = True
                            logger.info(
                                "Falling back to next OCR provider for doc=%s page=%s after provider=%s failed with type=%s",
                                doc_id,
                                page_num,
                                provider_name,
                                error_info.get("type", "unexpected_error"),
                            )
                            break

                        if error_info.get("type") == "model_not_found" and has_fallback_model:
                            logger.info(
                                "Falling back to next OCR model for doc=%s page=%s provider=%s after missing model=%s",
                                doc_id,
                                page_num,
                                provider_name,
                                model_name,
                            )
                            break

                        if not retryable or is_last_attempt:
                            raise

                        delay = _build_retry_delay(attempt)
                        logger.info(
                            "Retrying OCR for doc=%s page=%s model=%s in %.2fs after attempt %s",
                            doc_id,
                            page_num,
                            model_name,
                            delay,
                            attempt,
                        )
                        await asyncio.sleep(delay)

                if provider_failed:
                    break

            if provider_failed:
                continue

        if provider_result is None:
            raise RuntimeError("OCR response missing after retry loop") from last_error
    except Exception as exc:
        ocr_status[doc_id][page_num] = "error"
        try:
            finished_at = _utc_now_iso()
            duration_ms = max(int((time.perf_counter() - started_at_perf) * 1000), 0)
            _write_structured_sidecar(
                doc_id,
                page_num,
                _merge_sidecar_timing(
                    None,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                ),
            )
            error_info = _classify_ocr_exception(exc)
            ocr_path.write_text(_build_error_markdown(page_num, error_info), encoding="utf-8")
        except Exception:
            pass
