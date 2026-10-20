"""PDF validation and text extraction (SRS FR-020, FR-021). Bytes stay in memory; nothing is written to disk."""
from __future__ import annotations

import io
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import pdfplumber
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect

from app.core.config import get_settings
from app.core.errors import AppError

MIN_TEXT_CHARS = 300
MAX_TEXT_CHARS = 30_000
EXTRACT_TIMEOUT_S = 20

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdf")


class PdfError(AppError):
    status_code = 422


def sanitise_filename(name: str | None) -> str | None:
    if not name:
        return None
    base = name.replace("\\", "/").split("/")[-1]
    clean = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")[:100]
    return clean or None


def validate_upload(data: bytes, filename: str | None, content_type: str | None) -> None:
    s = get_settings()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise PdfError(f"The file is larger than {s.max_upload_mb} MB.", code="FILE_TOO_LARGE", status_code=413)
    name = (filename or "").lower()
    if not name.endswith(".pdf") or (content_type and content_type not in ("application/pdf", "application/x-pdf",
                                                                           "application/octet-stream")):
        raise PdfError("Upload a PDF file.", code="UNSUPPORTED_FILE_TYPE", status_code=415)
    if not data.startswith(b"%PDF-"):
        raise PdfError("Upload a PDF file. This file's contents are not a PDF.", code="UNSUPPORTED_FILE_TYPE",
                       status_code=415)


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract(data: bytes, max_pages: int) -> str:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > max_pages:
                raise PdfError(f"The PDF has more than {max_pages} pages. Upload a resume of {max_pages} pages or "
                               "fewer.", code="PDF_TOO_MANY_PAGES")
            pages = [(page.extract_text(x_tolerance=1.5, y_tolerance=3) or "") for page in pdf.pages]
    except PdfError:
        raise
    except (PDFPasswordIncorrect, PDFEncryptionError) as exc:
        raise PdfError("This PDF is password-protected. Remove the password or re-export the PDF.",
                       code="PDF_UNREADABLE") from exc
    except Exception as exc:
        raise PdfError("We couldn't open this PDF. It may be damaged — try re-exporting it.",
                       code="PDF_UNREADABLE") from exc
    return "\n\n".join(pages)


def extract_text(data: bytes) -> tuple[str, list[str]]:
    """Returns (clean_text, warnings). Raises PdfError for unreadable / scanned PDFs."""
    future = _pool.submit(_extract, data, get_settings().max_pdf_pages)
    try:
        raw = future.result(timeout=EXTRACT_TIMEOUT_S)
    except FutureTimeout as exc:
        raise PdfError("Reading this PDF took too long. Try a simpler export or paste the text instead.",
                       code="PDF_TIMEOUT", status_code=504) from exc
    text = _clean(raw)
    if len(text) < MIN_TEXT_CHARS:
        raise PdfError(
            "We couldn't read text from this PDF — it may be a scanned image. Scanned-PDF OCR isn't part of this "
            "version, so nothing was analysed. Paste your resume text or build it from scratch instead.",
            code="PDF_NO_TEXT", details={"options": ["paste_text", "build_from_scratch"]})
    warnings = []
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        warnings.append("TEXT_TRUNCATED")
    return text, warnings
