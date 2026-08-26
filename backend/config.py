from pathlib import Path

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
MODEL_NAME = "glm-ocr:latest"
MODEL_FALLBACK_NAMES = ("glm-ocr:v0.1.5",)
OCR_PROVIDER = "glmocr"
OCR_TIMEOUT = 240.0
OCR_BLOCK_SIZE = 10
OCR_RETRY_MAX_ATTEMPTS = 2
OCR_RETRY_BACKOFF_BASE_SECONDS = 0.5
PDF_RENDER_SCALE = 2.0

OCR_ENABLE_STRUCTURED_OUTPUT = True
OCR_ENABLE_LAYOUT_VISUALIZATION = True
OCR_RETURN_CROP_IMAGES = False
OCR_INCLUDE_RAW_PROVIDER_PAYLOAD = False

GLMOCR_MODE = "selfhosted"
GLMOCR_LAYOUT_DEVICE = "cpu"
GLMOCR_OCR_API_URL = OLLAMA_URL
GLMOCR_OCR_API_MODE = "ollama_generate"
GLMOCR_SAVE_LAYOUT_VISUALIZATION = False
GLMOCR_OFFICIAL_TASK_PROMPTS = {
    "text": "Text Recognition:",
    "table": "Table Recognition:",
    "formula": "Formula Recognition:",
}

DEFAULT_OCR_PROMPT_PROFILE = "structured_document_no_html"

OCR_PROMPT_PROFILES = {
    "default": {
        "text": (
            "Extract all text, tables, and structure from this document image. "
            "Output the result in clean Markdown format. "
            "Preserve headings, lists, tables (as Markdown tables), and any visible structure. "
            "Do not add commentary - only output the Markdown."
        ),
        "table": (
            "Extract the table from this region and output it cleanly in Markdown or HTML. "
            "Preserve headers, row order, and cell values exactly when possible."
        ),
        "formula": "Extract only the formula from this region and output it cleanly, preferably in LaTeX when possible.",
    },
    "structured_document": {
        "text": (
            "Extract all text and document structure from this image and output the result in clean Markdown. "
            "For structured, form-like, banking, invoice, receipt, or tabular documents, preserve the exact field/value structure, row order, headings, dates, amounts, codes, and visible grouping. "
            "When a table is visually boxed or grid-based, prefer HTML table output if that preserves the structure more faithfully than a Markdown table, and use thead/tbody when a true header row is evident. "
            "Preserve empty fields as empty cells when they are part of the real document structure. "
            "Do not invent spacer rows, filler text, or commentary. Output only the document content."
        ),
        "table": (
            "Extract only the real table or structured field/value block from this region. "
            "Output a clean HTML or Markdown table, preferring HTML when it preserves merged headers, section titles, or form-like rows more faithfully. "
            "Use thead/tbody when appropriate, keep exact row order and cell values, and do not insert empty spacer rows unless they are real data rows."
        ),
        "formula": "Extract only the formula from this region and output it cleanly, preferably in LaTeX when possible.",
    },
    "structured_document_no_html": {
        "text": (
            "Extract all text and document structure from this image and output the result in clean Markdown only. "
            "Never output HTML tags. For every table or structured field/value block, use a pipe-delimited Markdown table. "
            "Preserve the exact field/value structure, row order, headings, dates, amounts, codes, and visible grouping. "
            "Always transcribe all text in the page header and margins, including date, sender, company details, recipient, address, and tax code; do not skip the top area even when it is faint or separated from the main body. "
            "Preserve empty fields as empty cells when they are part of the real document structure. "
            "Do not invent spacer rows, filler text, or commentary. Output only the document content."
        ),
        "table": (
            "Extract only the real table or structured field/value block from this region. "
            "Output a clean pipe-delimited Markdown table only; never use HTML tags. "
            "Keep exact row order and cell values, and do not insert empty spacer rows unless they are real data rows."
        ),
        "formula": "Extract only the formula from this region and output it cleanly, preferably in LaTeX when possible.",
    },
    "web_article": {
        "text": (
            "Extract the main document content from this page image and output it in clean Markdown format. "
            "Preserve headings, paragraphs, lists, tables, formulas, and meaningful section structure. "
            "When the page is a printed web page or web article, keep the main article body and genuine content sections, "
            "but ignore obvious website chrome and boilerplate that are not part of the core document content, including "
            "navigation menus, site headers, breadcrumbs, ads, promo banners, cookie or privacy notices, pagination controls, "
            "subscribe or comment prompts, related-article lists, rankings widgets, product cards, repeated footer links, and legal footer blocks. "
            "Preserve real content tables, specifications, and links that belong to the main document. "
            "Do not add commentary - only output the Markdown."
        ),
        "table": (
            "Extract only the real content table or specification data from this document region. "
            "Output the table in clean Markdown or HTML. "
            "Ignore ads, promo cards, rankings widgets, navigation, and other website boilerplate that are not part of the main content."
        ),
        "formula": "Extract only the formula from this region and output it cleanly, preferably in LaTeX when possible.",
    },
}

OCR_PROMPT = OCR_PROMPT_PROFILES[DEFAULT_OCR_PROMPT_PROFILE]["text"]
GLMOCR_TASK_PROMPT_MAPPING = OCR_PROMPT_PROFILES[DEFAULT_OCR_PROMPT_PROFILE]


def get_available_prompt_profiles() -> list[str]:
    return sorted(OCR_PROMPT_PROFILES)


def normalize_prompt_profile(prompt_profile: str | None) -> str:
    normalized = (prompt_profile or DEFAULT_OCR_PROMPT_PROFILE).strip().lower()
    if normalized not in OCR_PROMPT_PROFILES:
        available = ", ".join(get_available_prompt_profiles())
        raise ValueError(f"Profilo prompt OCR non supportato: {normalized}. Disponibili: {available}.")
    return normalized


def get_prompt_profile_mapping(prompt_profile: str | None) -> dict[str, str]:
    return dict(OCR_PROMPT_PROFILES[normalize_prompt_profile(prompt_profile)])


def get_glmocr_task_prompt_mapping() -> dict[str, str]:
    return dict(GLMOCR_OFFICIAL_TASK_PROMPTS)

PDF_EXTENSIONS = {".pdf"}
RASTER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
DEFAULT_PAGE_IMAGE_EXTENSION = ".png"
CURRENTLY_SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | RASTER_IMAGE_EXTENSIONS
