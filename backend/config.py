from pathlib import Path

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "glm-ocr:latest"
OCR_TIMEOUT = 240.0
OCR_BLOCK_SIZE = 10

OCR_PROMPT = (
    "Extract all text, tables, and structure from this document image. "
    "Output the result in clean Markdown format. "
    "Preserve headings, lists, tables (as Markdown tables), and any visible structure. "
    "Do not add commentary - only output the Markdown."
)

PDF_EXTENSIONS = {".pdf"}
RASTER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
DEFAULT_PAGE_IMAGE_EXTENSION = ".png"
CURRENTLY_SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | RASTER_IMAGE_EXTENSIONS
