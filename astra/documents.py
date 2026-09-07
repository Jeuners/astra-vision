"""Local document ingestion: PDF text extraction. No network access, no persistence."""

from io import BytesIO

from pypdf import PdfReader


def extract_pdf_text(data: bytes, max_chars: int = 8000) -> str:
    """Extract and concatenate text from every page of a PDF, capped to max_chars."""
    reader = PdfReader(BytesIO(data))
    pages = (page.extract_text() or "" for page in reader.pages)
    text = "\n\n".join(page.strip() for page in pages if page.strip())
    return text[:max_chars]
